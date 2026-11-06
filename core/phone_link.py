"""Phone link: talk to JARVIS from anywhere and get its alerts, through a private Telegram bot.

Why Telegram: it reaches the phone on any network with no port forwarding, no
public server and no app to build, and the user owns the bot.

Security model
    * The user creates the bot in Telegram (@BotFather) and gives JARVIS its token,
      typed into JARVIS (never spoken aloud, never committed — config/phone-link.json
      is git-ignored and owner-only readable).
    * Pairing: JARVIS shows a one-time 6-digit code; the user sends "/pair <code>"
      from their phone. Only that chat is accepted afterwards; everyone else is ignored.
    * Messages from the phone are the user's own requests; JARVIS's existing
      confirmation rules for sending, buying or deleting still apply.

What it does
    * Text or voice notes from the phone → handled by JARVIS like typed commands;
      the spoken answer is sent back as text.
    * Alerts JARVIS raises itself (finished research, security, break reminders,
      trading alerts) are pushed to the phone, with quiet hours.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / 'config' / 'phone-link.json'
API = 'https://api.telegram.org/bot{token}/{method}'
FILE = 'https://api.telegram.org/file/bot{token}/{path}'
DEFAULTS = {'token': '', 'chat_id': None, 'enabled': True, 'alerts': True, 'remote': True, 'quiet_start': 23, 'quiet_end': 7,
            'alert_kinds': ['research', 'security', 'wellbeing', 'trading', 'reminder']}


def load() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(cfg, f)
    os.replace(tmp, CONFIG)
    os.chmod(CONFIG, 0o600)


def _call(token, method, timeout=20, timeout_s=None, **params):
    if timeout_s is not None:
        params['timeout'] = timeout_s      # Telegram's own long-poll parameter
    r = requests.post(API.format(token=token, method=method), json=params, timeout=timeout)
    data = r.json()
    if not data.get('ok'):
        raise RuntimeError(data.get('description') or f'Telegram {method} failed')
    return data['result']


def _upload(token, method, field, filename, data, timeout=120, **params):
    """Multipart upload (photos, documents): Telegram does not take files as JSON."""
    r = requests.post(API.format(token=token, method=method), data={k: str(v) for k, v in params.items()},
                      files={field: (filename, data)}, timeout=timeout)
    out = r.json()
    if not out.get('ok'):
        raise RuntimeError(out.get('description') or f'Telegram {method} failed')
    return out['result']


class PhoneLink:
    """Long-polls Telegram on a background thread. on_text(text, reply) is called for paired messages."""

    def __init__(self, on_text=None):
        self.on_text = on_text
        self.cfg = load()
        self.pair_code: str | None = None
        self.pair_expires = 0.0
        self.offset = 0
        self.bot_name = ''
        self.running = False
        self.last_error = ''
        self._stt = None
        self._thread: threading.Thread | None = None
        self._file_choices: list[dict] = []

    # ── setup ───────────────────────────────────────────────────────────────
    def set_token(self, token: str) -> dict:
        token = str(token or '').strip()
        if ':' not in token or len(token) < 30:
            raise ValueError('That does not look like a Telegram bot token (it looks like 123456:ABC...).')
        me = _call(token, 'getMe')
        self.cfg.update(token=token, chat_id=None)
        save(self.cfg)
        self.bot_name = me.get('username', '')
        self.start()
        return self.begin_pairing()

    def begin_pairing(self) -> dict:
        if not self.cfg.get('token'):
            raise ValueError('No bot token yet. Create a bot with @BotFather in Telegram, then type: /phonelink token <token>')
        self.pair_code = f'{random.SystemRandom().randint(0, 999999):06d}'
        self.pair_expires = time.time() + 600
        self.start()
        return {'bot': '@' + (self.bot_name or self._username()), 'pair_code': self.pair_code, 'expires_in_minutes': 10,
                'instructions': f'On your phone, open the bot in Telegram and send: /pair {self.pair_code}'}

    def unpair(self) -> dict:
        self.cfg['chat_id'] = None
        save(self.cfg)
        return {'paired': False}

    def _username(self):
        try:
            self.bot_name = _call(self.cfg['token'], 'getMe').get('username', '')
        except Exception:
            pass
        return self.bot_name

    def status(self) -> dict:
        return {'configured': bool(self.cfg.get('token')), 'paired': bool(self.cfg.get('chat_id')),
                'bot': ('@' + self.bot_name) if self.bot_name else None, 'running': self.running,
                'alerts': self.cfg.get('alerts'), 'remote_commands': self.cfg.get('remote', True), 'quiet_hours': [self.cfg['quiet_start'], self.cfg['quiet_end']],
                'pairing_open': bool(self.pair_code and time.time() < self.pair_expires), 'last_error': self.last_error or None}

    def configure(self, **changes) -> dict:
        for k in ('enabled', 'alerts', 'remote'):
            if changes.get(k) is not None:
                self.cfg[k] = bool(changes[k])
        for k in ('quiet_start', 'quiet_end'):
            if changes.get(k) is not None:
                self.cfg[k] = max(0, min(23, int(changes[k])))
        save(self.cfg)
        return self.status()

    # ── sending ─────────────────────────────────────────────────────────────
    def send(self, text: str) -> bool:
        if not (self.cfg.get('token') and self.cfg.get('chat_id') and self.cfg.get('enabled')):
            return False
        text = str(text or '').strip()
        if not text:
            return False
        for i in range(0, len(text), 3900):
            _call(self.cfg['token'], 'sendMessage', chat_id=self.cfg['chat_id'], text=text[i:i + 3900],
                  disable_web_page_preview=True)
        return True

    def _paired(self) -> bool:
        return bool(self.cfg.get('token') and self.cfg.get('chat_id') and self.cfg.get('enabled'))

    def send_photo(self, data: bytes, caption: str = '', chat_id=None) -> bool:
        if not (chat_id or self._paired()) or not data:
            return False
        _upload(self.cfg['token'], 'sendPhoto', 'photo', 'jarvis.jpg', data,
                chat_id=chat_id or self.cfg['chat_id'], caption=caption[:1000])
        return True

    def send_document(self, path, caption: str = '', chat_id=None) -> bool:
        """Send a file from this Mac; the never-send list and size limit are enforced here."""
        from core.remote_armour import allowed_path
        p = allowed_path(path)
        if not (chat_id or self._paired()):
            return False
        _upload(self.cfg['token'], 'sendDocument', 'document', p.name, p.read_bytes(),
                chat_id=chat_id or self.cfg['chat_id'], caption=caption[:1000])
        return True

    def _quiet(self) -> bool:
        h, a, b = datetime.now().hour, self.cfg['quiet_start'], self.cfg['quiet_end']
        return (a <= h or h < b) if a > b else (a <= h < b)

    def alert(self, kind: str, text: str, urgent: bool = False) -> bool:
        if not self.cfg.get('alerts') or kind not in self.cfg.get('alert_kinds', []):
            return False
        if self._quiet() and not urgent:
            return False
        try:
            return self.send(('🔴 ' if urgent else '🔔 ') + text)
        except Exception as exc:
            self.last_error = str(exc)[:200]
            return False

    # ── receiving ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self.running or not self.cfg.get('token'):
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name='jarvis-phone-link')
        self._thread.start()

    def stop(self) -> None:
        self.running = False

    def _loop(self):
        backoff = 2
        while self.running and self.cfg.get('token'):
            try:
                # Long poll: Telegram holds the request up to 25 s until a message arrives.
                updates = _call(self.cfg['token'], 'getUpdates', timeout=35, offset=self.offset, timeout_s=25,
                                allowed_updates=['message', 'edited_message'])
                backoff = 2
                self.last_error = ''
                for u in updates:
                    self.offset = max(self.offset, u['update_id'] + 1)
                    try:
                        if u.get('edited_message', {}).get('location'):
                            self._location(u['edited_message'], live_update=True)   # live location moving
                        else:
                            self._handle(u.get('message') or {})
                    except Exception as exc:
                        print(f'[PhoneLink] message failed: {exc}')
            except Exception as exc:
                self.last_error = str(exc)[:200]
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _reply(self, chat_id, text):
        try:
            _call(self.cfg['token'], 'sendMessage', chat_id=chat_id, text=str(text)[:3900])
        except Exception as exc:
            self.last_error = str(exc)[:200]

    def _handle(self, msg: dict):
        chat = (msg.get('chat') or {}).get('id')
        if chat is None or (msg.get('chat') or {}).get('type') != 'private':
            return
        text = (msg.get('text') or '').strip()
        if text.startswith('/pair'):
            code = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ''
            if self.pair_code and time.time() < self.pair_expires and code == self.pair_code:
                self.cfg['chat_id'] = chat
                save(self.cfg)
                self.pair_code = None
                self._reply(chat, 'Paired with JARVIS. Send me a message or a voice note any time.')
                from core import notify
                notify.send('phone', 'Your phone is now paired with JARVIS.', speak=True)
            else:
                self._reply(chat, 'That pairing code is wrong or expired. Ask JARVIS for a new one.')
            return
        if chat != self.cfg.get('chat_id'):
            self._reply(chat, 'This JARVIS is private.')
            return
        if text in ('/start', '/help'):
            self._reply(chat, 'Talk to JARVIS here: type, or send a voice note. /status shows the link, /alerts on|off, '
                              '/armour lists the remote commands.')
            return
        from core import remote_armour
        if remote_armour.is_command(text):
            self._remote(chat, text)
            return
        if msg.get('photo') or msg.get('document'):
            self._incoming(chat, msg)
            if not (msg.get('caption') or '').strip():
                return
            text = msg['caption'].strip()
        if text.startswith('/alerts'):
            on = 'off' not in text
            self.configure(alerts=on)
            self._reply(chat, 'Alerts ' + ('on.' if on else 'off.'))
            return
        if text == '/status':
            self._reply(chat, json.dumps(self.status(), indent=1))
            return
        if msg.get('location'):
            self._location(msg)
            return
        if msg.get('voice') or msg.get('audio'):
            text = self._transcribe(msg.get('voice') or msg.get('audio'))
            if not text:
                self._reply(chat, "I couldn't make out that voice note.")
                return
            self._reply(chat, f'🎙 "{text}"')
        if not text:
            return
        if self.on_text:
            self.on_text(text, lambda answer: self._reply(chat, answer))
        else:
            self._reply(chat, 'JARVIS is not listening right now.')

    # ── virtual armour ──────────────────────────────────────────────────────
    def _remote(self, chat, text: str):
        """A fixed menu of remote commands from the paired chat. Never a shell."""
        from core import notify, remote_armour as ra
        word, _, arg = text.partition(' ')
        word, arg = word.lower(), arg.strip()
        if word == '/armour':
            self._reply(chat, ra.help_text() + ('' if self.cfg.get('remote', True) else '\n\n⛔ Remote commands are OFF. '
                                                'Turn them back on from the Mac ("JARVIS, enable remote commands").'))
            return
        if word == '/remote':
            if arg.lower() == 'off':
                self.configure(remote=False)
                self._reply(chat, '⛔ Remote commands off. Only the Mac can turn them back on.')
                notify.send('remote', 'Remote phone commands were switched off from your phone.', speak=False)
            else:
                self._reply(chat, 'Remote commands are ' + ('ON' if self.cfg.get('remote', True) else 'OFF')
                            + '. Send /remote off to disable; re-enabling is only possible on the Mac.')
            return
        if not self.cfg.get('remote', True):
            self._reply(chat, '⛔ Remote commands are off. Turn them on from the Mac.')
            return
        try:
            if word == '/screen':
                self.send_photo(ra.screenshot(), '🖥 Screen ' + time.strftime('%H:%M:%S'), chat_id=chat)
                notify.send('remote', 'Your phone took a screenshot of this Mac.', speak=False)
            elif word == '/cam':
                self.send_photo(ra.camera(), '📷 Camera ' + time.strftime('%H:%M:%S'), chat_id=chat)
                notify.send('remote', 'Your phone took a camera photo on this Mac.', speak=False)
            elif word == '/file':
                if arg.isdigit() and self._file_choices:
                    i = int(arg) - 1
                    if not 0 <= i < len(self._file_choices):
                        raise ValueError(f'Pick 1–{len(self._file_choices)}.')
                    chosen = self._file_choices[i]
                    self.send_document(chosen['path'], '📄 ' + chosen['name'], chat_id=chat)
                    notify.send('remote', f"Sent {chosen['name']} to your phone.", speak=False)
                    return
                found = ra.find_files(arg)
                self._file_choices = found
                if not found:
                    self._reply(chat, f'No sendable file matched "{arg}".')
                elif len(found) == 1:
                    self.send_document(found[0]['path'], '📄 ' + found[0]['name'], chat_id=chat)
                    notify.send('remote', f"Sent {found[0]['name']} to your phone.", speak=False)
                else:
                    self._reply(chat, 'Which one? Send /file <number>:\n' + '\n'.join(
                        f"{n}. {f['name']} · {f['size_mb']} MB · {f['modified']}" for n, f in enumerate(found, 1)))
            elif word == '/clip':
                if arg:
                    ra.clipboard_set(arg)
                    self._reply(chat, '📋 Copied to the Mac clipboard.')
                else:
                    clip = ra.clipboard_get()
                    self._reply(chat, '📋 ' + (clip[:3800] if clip.strip() else '(clipboard is empty or not text)'))
            elif word == '/lock':
                self._reply(chat, '🔒 ' + ra.lock())
            elif word == '/sys':
                self._reply(chat, ra.system_report())
            elif word == '/home':
                from core import home_bridge
                parts = arg.split()
                if parts and parts[0].lower() in ('on', 'off') and len(parts) == 2:
                    r = home_bridge.control(parts[1], parts[0].lower() == 'on')
                    self._reply(chat, f"🏠 {r['entity']}: asked {r['requested']}, now {r['observed']}"
                                + (' ✅' if r['verified'] else ' (not confirmed)'))
                else:
                    data = home_bridge.states()
                    if not data.get('configured'):
                        self._reply(chat, '🏠 ' + data.get('note', 'Home Assistant is not set up.'))
                    else:
                        self._reply(chat, '🏠\n' + ('\n'.join(f"{r['name']} ({r['entity']}): {r['state']}"
                                                              for r in data['states']) or 'No allowed devices.')
                                    + '\n\n/home on|off <entity>')
        except Exception as exc:
            self._reply(chat, f'⚠️ {word[1:]} failed: {str(exc)[:300]}')

    def _incoming(self, chat, msg: dict):
        """A photo or file sent from the phone lands in ~/Downloads/From Phone."""
        from core import remote_armour as ra
        if msg.get('photo'):
            media, name = msg['photo'][-1], f"photo-{time.strftime('%Y%m%d-%H%M%S')}.jpg"   # largest size
        else:
            media, name = msg['document'], msg['document'].get('file_name') or 'file'
        if (media.get('file_size') or 0) > 20_000_000:
            self._reply(chat, 'Telegram only lets bots download files up to 20 MB.')
            return
        try:
            info = _call(self.cfg['token'], 'getFile', file_id=media['file_id'])
            data = requests.get(FILE.format(token=self.cfg['token'], path=info['file_path']), timeout=60).content
            dest = ra.save_incoming(name, data)
            self._reply(chat, f'📥 Saved to Downloads/From Phone/{dest.name}')
            from core import notify
            notify.send('phone', f'Your phone sent {dest.name}; it is in Downloads, From Phone.', speak=True)
        except Exception as exc:
            self._reply(chat, f'⚠️ Could not save that: {str(exc)[:200]}')

    def _location(self, msg: dict, live_update: bool = False):
        """A location (or live-location update) shared from the paired phone: GPS-accurate position for JARVIS."""
        if (msg.get('chat') or {}).get('id') != self.cfg.get('chat_id'):
            return
        loc = msg['location']
        from core import location
        location.set_phone_fix(loc['latitude'], loc['longitude'], loc.get('horizontal_accuracy'),
                               live=bool(loc.get('live_period')) or live_update)
        if not live_update:
            self._reply(msg['chat']['id'], '📍 Got your location. JARVIS will use it for "where am I", weather and nearby '
                                           'places for the next 15 minutes' + (' (live updates keep it fresh).' if loc.get('live_period') else '.'))

    def _transcribe(self, media: dict) -> str:
        try:
            info = _call(self.cfg['token'], 'getFile', file_id=media['file_id'])
            data = requests.get(FILE.format(token=self.cfg['token'], path=info['file_path']), timeout=30).content
            if len(data) > 20_000_000:
                return ''
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as f:
                f.write(data)
                path = f.name
            try:
                if self._stt is None:
                    from faster_whisper import WhisperModel
                    self._stt = WhisperModel('base', device='cpu', compute_type='int8',
                                             download_root=str(BASE / 'models' / 'whisper'))
                segments, _ = self._stt.transcribe(path, vad_filter=True)
                return ' '.join(s.text.strip() for s in segments).strip()
            finally:
                os.unlink(path)
        except Exception as exc:
            self.last_error = 'voice note: ' + str(exc)[:160]
            return ''


_instance: PhoneLink | None = None


def instance(on_text=None) -> PhoneLink:
    global _instance
    if _instance is None:
        _instance = PhoneLink(on_text)
    elif on_text is not None:
        _instance.on_text = on_text
    return _instance
