"""Virtual armour: drive this Mac from the paired phone over the Telegram link.

Commands are only accepted from the paired private chat (core/phone_link.py
checks that before anything here runs). They are deliberately a fixed menu —
there is no remote shell — and every one says what it actually observed.

    /screen          screenshot of the main display
    /cam             one webcam frame (camera light comes on)
    /file <words>    Spotlight search in your home folder; /file 2 sends result 2
    /clip            what is on the Mac's clipboard;  /clip <text> puts text there
    /lock            lock the Mac now
    /sys             battery, CPU, memory, disk, uptime, front app
    /home            Home Assistant lights/switches;  /home on|off <entity>
    /remote off      kill switch: stop all remote commands (re-enable on the Mac)

Files and photos sent from the phone are saved to ~/Downloads/From Phone.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
INBOX = HOME / 'Downloads' / 'From Phone'
MAX_SEND = 49 * 1024 * 1024          # Telegram bot uploads stop at 50 MB

# Never leaves the Mac, whatever the request says: keys, credentials, browser and
# app data, and this assistant's own secrets.
_DENY = re.compile(
    r'(^|/)(\.ssh|\.gnupg|\.aws|\.kube|\.docker|\.config/gh|Library|\.Trash|Keychains)(/|$)'
    r'|(^|/)\.env(\.|$)|(^|/)\.netrc$|(^|/)\.git-credentials$'
    r'|(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$|\.(pem|key|p12|pfx|keychain|kdbx|ovpn)$'
    r'|(^|/)(api_keys\.json|phone-link\.json|home-assistant-private\.json|owner-guard\.json)$'
    r'|(^|/)[^/]*(password|passwd|secret|credential|token|api[_-]?key|private[_-]?key)[^/]*$',
    re.IGNORECASE)

COMMANDS = ('/screen', '/cam', '/file', '/clip', '/lock', '/sys', '/home', '/remote', '/armour')


def help_text() -> str:
    return ('🛡 Virtual armour — remote commands:\n'
            '/screen  screenshot\n/cam  webcam photo\n/file <words>  find & send a file (then /file 2 …)\n'
            '/clip  read clipboard · /clip <text>  set it\n/lock  lock the Mac\n/sys  system status\n'
            '/home  smart-home states · /home on|off <entity>\n/remote off  disable remote commands\n'
            'Send a photo or file to drop it into Downloads/From Phone. Anything else goes to JARVIS.')


def is_command(text: str) -> bool:
    word = (text or '').split(maxsplit=1)[0].lower() if text else ''
    return word in COMMANDS


# ── files ───────────────────────────────────────────────────────────────────
def allowed_path(path: str | os.PathLike) -> Path:
    """The resolved path if it may be sent to the phone; ValueError otherwise."""
    p = Path(os.path.expanduser(str(path))).resolve()
    try:
        rel = p.relative_to(HOME)
    except ValueError:
        raise ValueError('Only files inside your home folder can be sent.') from None
    if _DENY.search(str(rel)) or _DENY.search(p.name):
        raise ValueError('That file is on the never-send list (keys, credentials or app data).')
    if not p.is_file():
        raise ValueError('That is not a file (folders are not sent).')
    if p.stat().st_size > MAX_SEND:
        raise ValueError(f'That file is {p.stat().st_size / 1048576:.0f} MB; Telegram bots can send up to 50 MB.')
    return p


def find_files(query: str, limit: int = 8) -> list[dict]:
    """Newest matching files under home that are allowed to be sent."""
    query = str(query or '').strip()
    if not query:
        raise ValueError('Say what to look for, e.g. /file resume')
    rows = []
    if platform.system() == 'Darwin':
        from core.mac_find import find
        rows = find(query, folder=str(HOME), content=False, limit=30).get('results', [])
        paths = [r['path'] for r in rows]
    else:
        words = query.lower().split()
        paths = []
        for root, dirs, files in os.walk(HOME):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'Library']
            paths += [os.path.join(root, f) for f in files if all(w in f.lower() for w in words)]
            if len(paths) > 200:
                break
        paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    out = []
    for raw in paths:
        try:
            p = allowed_path(raw)
        except (ValueError, OSError):
            continue
        st = p.stat()
        out.append({'path': str(p), 'name': p.name, 'size_mb': round(st.st_size / 1048576, 2),
                    'modified': datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M')})
        if len(out) >= limit:
            break
    return out


def save_incoming(name: str, data: bytes) -> Path:
    """Store a file sent from the phone without overwriting anything."""
    INBOX.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[^\w.\- ]+', '_', os.path.basename(name or '')).strip(' .') or f'phone-{int(time.time())}'
    dest = INBOX / safe
    stem, suffix, n = dest.stem, dest.suffix, 1
    while dest.exists():
        dest = INBOX / f'{stem} ({n}){suffix}'
        n += 1
    dest.write_bytes(data)
    return dest


# ── captures ────────────────────────────────────────────────────────────────
def screenshot() -> bytes:
    from actions.screen_processor import _capture_screen
    data, _mime = _capture_screen()
    return data


def camera() -> bytes:
    from actions.screen_processor import _capture_camera
    data, _mime = _capture_camera()
    return data


# ── control ─────────────────────────────────────────────────────────────────
def lock() -> str:
    system = platform.system()
    if system == 'Darwin':
        # Ctrl+Cmd+Q, the system lock shortcut. Falls back to sleeping the display,
        # which locks when "require password after sleep" is on.
        r = subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "q" using '
                            '{control down, command down}'], capture_output=True, timeout=8)
        if r.returncode != 0:
            subprocess.run(['pmset', 'displaysleepnow'], capture_output=True, timeout=8)
            return 'Display put to sleep (it locks if your Mac asks for the password after sleep).'
        return 'Lock requested. If the Mac did not lock, give Mark LVI Accessibility permission.'
    if system == 'Windows':
        subprocess.run(['rundll32.exe', 'user32.dll,LockWorkStation'], timeout=8)
        return 'Lock requested.'
    for cmd in (['loginctl', 'lock-session'], ['xdg-screensaver', 'lock']):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, timeout=8)
            return 'Lock requested.'
    raise RuntimeError('No screen locker found on this system.')


def clipboard_get() -> str:
    if platform.system() == 'Darwin':
        return subprocess.run(['pbpaste'], capture_output=True, text=True, timeout=5).stdout
    import pyperclip
    return pyperclip.paste()


def clipboard_set(text: str) -> None:
    if platform.system() == 'Darwin':
        subprocess.run(['pbcopy'], input=text, text=True, timeout=5, check=True)
        return
    import pyperclip
    pyperclip.copy(text)


def system_report() -> str:
    import psutil
    lines = [f'🖥 {platform.node()} · {platform.system()} {platform.release()}']
    bat = psutil.sensors_battery() if hasattr(psutil, 'sensors_battery') else None
    if bat:
        lines.append(f"🔋 {bat.percent:.0f}% {'charging' if bat.power_plugged else 'on battery'}")
    lines.append(f'⚙️ CPU {psutil.cpu_percent(interval=.5):.0f}% · RAM {psutil.virtual_memory().percent:.0f}%')
    du = psutil.disk_usage(str(HOME))
    lines.append(f'💾 Disk {du.percent:.0f}% used · {du.free / 1e9:.0f} GB free')
    up = time.time() - psutil.boot_time()
    lines.append(f'⏱ Up {int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m')
    if platform.system() == 'Darwin':
        try:
            front = subprocess.run(['osascript', '-e', 'tell application "System Events" to get name of first '
                                    'application process whose frontmost is true'], capture_output=True, text=True,
                                   timeout=5).stdout.strip()
            if front:
                lines.append(f'🪟 Front app: {front}')
        except Exception:
            pass
    return '\n'.join(lines)
