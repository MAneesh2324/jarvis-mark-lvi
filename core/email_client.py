"""Email for JARVIS: read, search, draft, reply and send through the user's own mailbox.

Works with any provider that speaks IMAP and SMTP: Gmail and Google Workspace, Outlook and
Microsoft 365, iCloud, Zoho, Yahoo, or a custom server. The user signs in with an APP PASSWORD
(made in their account's security page), never their real password, and it is stored in
config/api_keys.json, which is git-ignored. Servers are worked out from the address, including
custom domains, by looking at where the domain's mail is delivered (its MX record).

Safety:
  * Everything read from a mailbox (names, subjects, bodies) is someone else's text. Callers wrap it
    with outcome.untrusted, so instructions inside an email are reported, never obeyed.
  * Nothing is ever sent from here without the on-screen CONFIRM (actions/email.py uses core/confirm).
    Saving a draft is reversible and needs no confirmation.
  * New-mail alerts skip newsletters and bulk mail, so JARVIS only speaks up for real people.
"""
from __future__ import annotations

import html
import imaplib
import re
import smtplib
import ssl
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

NAMESPACE = 'email'

# (imap host, smtp host, smtp port). IMAP is always 993 with TLS.
GMAIL = ('imap.gmail.com', 'smtp.gmail.com', 587)
OFFICE = ('outlook.office365.com', 'smtp.office365.com', 587)
ICLOUD = ('imap.mail.me.com', 'smtp.mail.me.com', 587)
YAHOO = ('imap.mail.yahoo.com', 'smtp.mail.yahoo.com', 465)
ZOHO = ('imap.zoho.com', 'smtp.zoho.com', 465)
ZOHO_IN = ('imap.zoho.in', 'smtp.zoho.in', 465)

KNOWN = {
    'gmail.com': GMAIL, 'googlemail.com': GMAIL,
    'outlook.com': OFFICE, 'hotmail.com': OFFICE, 'live.com': OFFICE, 'msn.com': OFFICE,
    'icloud.com': ICLOUD, 'me.com': ICLOUD, 'mac.com': ICLOUD,
    'yahoo.com': YAHOO, 'yahoo.co.in': YAHOO, 'ymail.com': YAHOO,
    'zoho.com': ZOHO, 'zohomail.com': ZOHO, 'zoho.in': ZOHO_IN, 'zohomail.in': ZOHO_IN,
}
# Where a custom domain's mail is delivered → which provider hosts it.
MX_HINTS = [('google.com', GMAIL), ('googlemail.com', GMAIL), ('outlook.com', OFFICE),
            ('zoho.in', ZOHO_IN), ('zoho.com', ZOHO), ('icloud.com', ICLOUD), ('yahoodns.net', YAHOO)]

# Providers that file a copy of SMTP-sent mail in Sent by themselves.
SAVES_SENT = ('smtp.gmail.com', 'smtp.office365.com')

APP_PASSWORD_HELP = {
    'imap.gmail.com': 'Google account → Security → 2-Step Verification → App passwords',
    'outlook.office365.com': 'Microsoft account → Security → Advanced security options → App passwords',
    'imap.mail.me.com': 'appleid.apple.com → Sign-In and Security → App-Specific Passwords',
    'imap.mail.yahoo.com': 'Yahoo account → Account security → Generate app password',
    'imap.zoho.com': 'Zoho Mail → Settings → Security → App passwords',
    'imap.zoho.in': 'Zoho Mail → Settings → Security → App passwords',
}

HEADER_FIELDS = 'FROM TO CC SUBJECT DATE MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE AUTO-SUBMITTED'
BODY_LIMIT = 4000


# ── servers ─────────────────────────────────────────────────────────────────────

def _mx(domain: str) -> list[str]:
    try:
        out = subprocess.run(['dig', '+short', '+time=3', '+tries=1', 'MX', domain],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    return [line.split()[-1].rstrip('.').lower() for line in out.splitlines() if line.strip()]


def detect_servers(address: str, mx=_mx) -> tuple[str, str, int]:
    """(imap host, smtp host, smtp port) for an address."""
    domain = address.rsplit('@', 1)[-1].strip().lower()
    if domain in KNOWN:
        return KNOWN[domain]
    for host in mx(domain):
        for hint, servers in MX_HINTS:
            if host.endswith(hint):
                return servers
    return (f'imap.{domain}', f'smtp.{domain}', 587)


def _tls() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# ── text helpers ────────────────────────────────────────────────────────────────

def html_to_text(markup: str) -> str:
    t = re.sub(r'(?is)<(script|style|head)\b.*?</\1>', ' ', markup or '')
    t = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h[1-6])>', '\n', t)
    t = re.sub(r'(?i)<li\b[^>]*>', '• ', t)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = html.unescape(t).replace('\xa0', ' ')
    t = re.sub(r'[ \t\r\f\v]+', ' ', t)
    return re.sub(r'\n\s*\n+', '\n\n', '\n'.join(line.strip() for line in t.splitlines())).strip()


_QUOTE_START = re.compile(r'^(On .{4,200} wrote:|-{2,} ?Original Message ?-{2,}|From: .+|_{8,})\s*$', re.I | re.M)


def strip_quoted(text: str) -> str:
    """The new part of a message, without the reply history quoted under it."""
    m = _QUOTE_START.search(text or '')
    if m and m.start() > 0:
        text = text[:m.start()]
    lines = [l for l in (text or '').splitlines() if not l.lstrip().startswith('>')]
    return '\n'.join(lines).strip()


def when(value: str, now: datetime | None = None) -> str:
    """'today 18:20', 'yesterday 09:05', 'Mon 14:00' or '5 Nov' — easy to say out loud."""
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
    except Exception:
        return ''
    now = now or datetime.now()
    days = (now.date() - dt.date()).days
    if days == 0:
        return dt.strftime('today %H:%M')
    if days == 1:
        return dt.strftime('yesterday %H:%M')
    if 1 < days < 7:
        return dt.strftime('%a %H:%M')
    return f'{dt.day} {dt.strftime("%b")}' + ('' if dt.year == now.year else f' {dt.year}')


def is_bulk(msg) -> bool:
    """Newsletters, promotions and automatic mail: never worth interrupting the user for."""
    if msg.get('List-Unsubscribe') or msg.get('List-Id'):
        return True
    if str(msg.get('Precedence', '')).strip().lower() in ('bulk', 'list', 'junk'):
        return True
    auto = str(msg.get('Auto-Submitted', '')).strip().lower()
    if auto and auto != 'no':
        return True
    sender = parseaddr(str(msg.get('From', '')))[1].lower()
    return bool(re.match(r'(no-?reply|do-?not-?reply|notifications?|mailer-daemon)@', sender))


def _quote(mailbox: str) -> str:
    return '"' + mailbox.replace('\\', '\\\\').replace('"', '\\"') + '"'


_FETCH_HEAD = re.compile(rb'UID (\d+)')
_FLAGS = re.compile(rb'FLAGS \(([^)]*)\)')
_LIST = re.compile(r'\((?P<flags>[^)]*)\) (?:"(?P<d>[^"]*)"|NIL) (?P<name>.+)$')


def parse_fetch(data) -> list[tuple[int, set[str], bytes]]:
    """imaplib FETCH response → [(uid, flags, payload bytes)]."""
    out = []
    for part in data or []:
        if not isinstance(part, tuple) or len(part) < 2:
            continue
        head, payload = part[0], part[1]
        m = _FETCH_HEAD.search(head)
        if not m:
            continue
        f = _FLAGS.search(head)
        flags = set(f.group(1).decode(errors='replace').split()) if f else set()
        out.append((int(m.group(1)), flags, payload))
    return out


def parse_list(lines) -> dict[str, str]:
    """LIST response → {'\\Sent': name, '\\Drafts': name, ...} from the special-use flags."""
    found = {}
    for raw in lines or []:
        line = raw.decode(errors='replace') if isinstance(raw, bytes) else str(raw)
        m = _LIST.match(line.strip())
        if not m:
            continue
        name = m.group('name').strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('\\"', '"')
        for flag in m.group('flags').split():
            if flag in ('\\Sent', '\\Drafts', '\\Trash', '\\All', '\\Junk', '\\Archive'):
                found.setdefault(flag, name)
        low = name.lower().rsplit('/', 1)[-1]
        for flag, names in (('\\Sent', ('sent', 'sent items', 'sent mail', 'sent messages')),
                            ('\\Drafts', ('drafts', 'draft'))):
            if low in names:
                found.setdefault(flag, name)
    return found


# ── the account ─────────────────────────────────────────────────────────────────

@dataclass
class Account:
    address: str
    password: str
    imap_host: str
    smtp_host: str
    smtp_port: int
    name: str = ''
    notify_new: bool = True

    @property
    def ready(self) -> bool:
        return bool(self.address and self.password and '@' in self.address)


def load_account(cfg: dict | None = None, mx=_mx) -> Account:
    if cfg is None:
        from memory.config_manager import get_plugin_config
        cfg = get_plugin_config(NAMESPACE)
    address = str(cfg.get('address') or '').strip()
    password = re.sub(r'\s+', '', str(cfg.get('app_password') or ''))   # Google shows it in groups of four
    imap_host, smtp_host, smtp_port = detect_servers(address, mx) if '@' in address else ('', '', 587)
    if str(cfg.get('imap_host') or '').strip():
        imap_host = str(cfg['imap_host']).strip()
    if str(cfg.get('smtp_host') or '').strip():
        host = str(cfg['smtp_host']).strip()
        if ':' in host:
            host, port = host.rsplit(':', 1)
            smtp_port = int(port) if port.isdigit() else smtp_port
        smtp_host = host
    name = str(cfg.get('name') or '').strip()
    if not name:
        try:
            from memory.config_manager import load_api_keys
            name = str(load_api_keys().get('user_name') or '').strip()
        except Exception:
            name = ''
    notify = cfg.get('notify_new', True)
    return Account(address, password, imap_host, smtp_host, int(smtp_port), name,
                   notify not in (False, 'false', 'False', '0', 0))


class EmailError(Exception):
    pass


class Mailbox:
    """One user's mailbox. Thread-safe; keeps one IMAP connection open and reopens it when it drops."""

    def __init__(self, account: Account, imap_factory=None, smtp_factory=None):
        self.account = account
        self._imap_factory = imap_factory or (lambda a: imaplib.IMAP4_SSL(a.imap_host, 993, ssl_context=_tls(),
                                                                          timeout=20))
        self._smtp_factory = smtp_factory or self._smtp_connect
        self._imap = None
        self._lock = threading.RLock()
        self._folders: dict[str, str] | None = None
        self._last: list[int] = []            # UIDs of the last listing, for "read the second one"
        self._watch: tuple[str, int] | None = None   # (uidvalidity, last uid seen) for new-mail alerts

    # connections
    def _connect(self):
        a = self.account
        if not a.ready:
            raise EmailError('Email is not set up. Add the address and an app password in ⚙ PLUGIN SETTINGS → EMAIL.')
        try:
            conn = self._imap_factory(a)
            conn.login(a.address, a.password)
        except imaplib.IMAP4.error as exc:
            hint = APP_PASSWORD_HELP.get(a.imap_host, "your mail account's security settings")
            raise EmailError(f'Sign-in to {a.imap_host} was refused ({str(exc)[:120]}). Use an app password '
                             f'from {hint}, and make sure IMAP is switched on.') from exc
        except OSError as exc:
            raise EmailError(f'Could not reach {a.imap_host}: {exc}') from exc
        return conn

    def _conn(self):
        if self._imap is not None:
            try:
                if self._imap.noop()[0] == 'OK':
                    return self._imap
            except Exception:
                pass
            self.close()
        self._imap = self._connect()
        return self._imap

    def close(self):
        with self._lock:
            conn, self._imap = self._imap, None
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

    def _smtp_connect(self, a: Account):
        if a.smtp_port == 465:
            s = smtplib.SMTP_SSL(a.smtp_host, 465, context=_tls(), timeout=25)
        else:
            s = smtplib.SMTP(a.smtp_host, a.smtp_port, timeout=25)
            s.starttls(context=_tls())
        s.login(a.address, a.password)
        return s

    def _select(self, conn, folder: str = 'INBOX', readonly: bool = True):
        typ, data = conn.select(_quote(folder), readonly=readonly)
        if typ != 'OK':
            raise EmailError(f'Could not open the folder {folder}.')
        return int((data or [b'0'])[0] or 0)

    def folders(self) -> dict[str, str]:
        with self._lock:
            if self._folders is None:
                typ, lines = self._conn().list()
                self._folders = parse_list(lines) if typ == 'OK' else {}
            return self._folders

    def _gmail(self, conn) -> bool:
        return 'X-GM-EXT-1' in getattr(conn, 'capabilities', ())

    # reading
    def _search(self, conn, criteria: list[str]) -> list[int]:
        typ, data = conn.uid('SEARCH', *criteria)
        if typ != 'OK':
            raise EmailError('The mail server refused the search.')
        return [int(x) for x in (data[0] or b'').split()]

    def _headers(self, conn, uids: list[int]) -> list[dict]:
        if not uids:
            return []
        typ, data = conn.uid('FETCH', ','.join(map(str, uids)),
                             f'(UID FLAGS BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])')
        if typ != 'OK':
            raise EmailError('Could not fetch the messages.')
        rows = []
        for uid, flags, payload in parse_fetch(data):
            msg = message_from_bytes(payload or b'', policy=policy.default)
            rows.append(self._summary(uid, flags, msg))
        rows.sort(key=lambda r: r['uid'], reverse=True)
        return rows

    @staticmethod
    def _summary(uid: int, flags: set[str], msg) -> dict:
        name, addr = parseaddr(str(msg.get('From', '')))
        return {'uid': uid, 'from_name': name or addr, 'from': addr, 'subject': str(msg.get('Subject', '') or '(no subject)'),
                'date': str(msg.get('Date', '')), 'when': when(str(msg.get('Date', ''))),
                'unread': '\\Seen' not in flags, 'bulk': is_bulk(msg)}

    def criteria(self, conn, query: str = '', sender: str = '', subject: str = '', since_days: int | None = None,
                 unread_only: bool = False) -> list[str]:
        crit: list[str] = []
        if query and self._gmail(conn):
            return ['X-GM-RAW', _quote(_ascii(query) + (' is:unread' if unread_only else '')
                                       + (f' newer_than:{int(since_days)}d' if since_days else ''))]
        if unread_only:
            crit.append('UNSEEN')
        if since_days:
            crit += ['SINCE', (datetime.now() - timedelta(days=int(since_days))).strftime('%d-%b-%Y')]
        for key, value in (('FROM', sender), ('SUBJECT', subject), ('TEXT', query)):
            if value:
                crit += [key, _quote(_ascii(value))]
        return crit or ['ALL']

    def list(self, folder: str = 'INBOX', limit: int = 8, unread_only: bool = False, query: str = '',
             sender: str = '', subject: str = '', since_days: int | None = None,
             include_bulk: bool = False) -> dict:
        """Newest first. Newsletters are counted, not listed, unless include_bulk."""
        limit = max(1, min(int(limit or 8), 25))
        with self._lock:
            conn = self._conn()
            self._select(conn, folder)
            uids = self._search(conn, self.criteria(conn, query, sender, subject, since_days, unread_only))
            searched = bool(query or sender or subject)
            window = uids[-(limit if include_bulk or searched else limit * 4):]
            rows = self._headers(conn, window)
        bulk = [r for r in rows if r['bulk']]
        keep = rows if include_bulk or searched else [r for r in rows if not r['bulk']]
        keep = keep[:limit]
        self._last = [r['uid'] for r in keep]
        return {'folder': folder, 'matches': len(uids), 'messages': keep,
                'newsletters_skipped': 0 if include_bulk or searched else len(bulk)}

    def resolve_uid(self, uid=None, index=None) -> int:
        if uid not in (None, '', 0):
            return int(uid)
        if index not in (None, '', 0):
            i = int(index)
            if 1 <= i <= len(self._last):
                return self._last[i - 1]
            raise EmailError(f'There is no message number {i} in the last list.')
        if self._last:
            return self._last[0]
        raise EmailError('Say which message: list the inbox first, or give its uid.')

    def _raw(self, conn, uid: int):
        typ, data = conn.uid('FETCH', str(uid), '(UID FLAGS BODY.PEEK[])')
        rows = parse_fetch(data) if typ == 'OK' else []
        if not rows:
            raise EmailError('That message was not found; it may have been moved or deleted.')
        return rows[0][1], message_from_bytes(rows[0][2], policy=policy.default)

    def read(self, uid: int, folder: str = 'INBOX', mark_read: bool = True, full: bool = False) -> dict:
        with self._lock:
            conn = self._conn()
            self._select(conn, folder, readonly=not mark_read)
            flags, msg = self._raw(conn, uid)
            if mark_read and '\\Seen' not in flags:
                conn.uid('STORE', str(uid), '+FLAGS', '(\\Seen)')
        body = msg.get_body(preferencelist=('plain', 'html'))
        text = ''
        if body is not None:
            try:
                content = body.get_content()
            except Exception:
                content = (body.get_payload(decode=True) or b'').decode('utf-8', 'replace')
            text = html_to_text(content) if body.get_content_type() == 'text/html' else str(content)
        if not full:
            text = strip_quoted(text)
        text = re.sub(r'\n{3,}', '\n\n', text.replace('\r', '')).strip()
        cut = len(text) > BODY_LIMIT
        attachments = [p.get_filename() or p.get_content_type() for p in msg.iter_attachments()]
        out = self._summary(uid, flags, msg)
        out.update({'to': str(msg.get('To', '')), 'cc': str(msg.get('Cc', '') or ''),
                    'body': text[:BODY_LIMIT] + (' …[cut]' if cut else ''), 'attachments': attachments})
        return out

    def mark(self, uid: int, read: bool = True, folder: str = 'INBOX') -> None:
        with self._lock:
            conn = self._conn()
            self._select(conn, folder, readonly=False)
            conn.uid('STORE', str(uid), '+FLAGS' if read else '-FLAGS', '(\\Seen)')

    def unread_count(self) -> int:
        with self._lock:
            typ, data = self._conn().status('INBOX', '(UNSEEN)')
        m = re.search(rb'UNSEEN (\d+)', (data or [b''])[0] or b'')
        return int(m.group(1)) if typ == 'OK' and m else 0

    def contacts(self, name: str, limit: int = 5) -> list[tuple[str, str]]:
        """People the user has mailed with whose name or address matches, most frequent first."""
        name = name.strip()
        if '@' in name:
            return [('', name)]
        counts: dict[str, list] = {}
        want = name.lower().split()
        with self._lock:
            conn = self._conn()
            places = [('INBOX', 'FROM', 'From')]
            sent = self.folders().get('\\Sent')
            if sent:
                places.append((sent, 'TO', 'To'))
            for folder, key, header in places:
                try:
                    self._select(conn, folder)
                    uids = self._search(conn, [key, _quote(_ascii(name))])[-40:]
                    if not uids:
                        continue
                    typ, data = conn.uid('FETCH', ','.join(map(str, uids)),
                                         f'(UID BODY.PEEK[HEADER.FIELDS ({header.upper()} CC)])')
                except Exception:
                    continue
                for _, _, payload in parse_fetch(data):
                    msg = message_from_bytes(payload or b'', policy=policy.default)
                    for disp, addr in getaddresses([str(v) for v in msg.get_all(header, []) + msg.get_all('Cc', [])]):
                        hay = f'{disp} {addr}'.lower()
                        if addr and all(w in hay for w in want) and addr.lower() != self.account.address.lower():
                            slot = counts.setdefault(addr.lower(), [disp, addr, 0])
                            slot[0] = slot[0] or disp
                            slot[2] += 1
        ranked = sorted(counts.values(), key=lambda s: -s[2])
        return [(d, a) for d, a, _ in ranked[:limit]]

    # writing
    def compose(self, to: list[str], subject: str, body: str, cc: list[str] | None = None,
                reply_to: dict | None = None) -> EmailMessage:
        a = self.account
        msg = EmailMessage()
        msg['From'] = formataddr((a.name, a.address)) if a.name else a.address
        msg['To'] = ', '.join(to)
        if cc:
            msg['Cc'] = ', '.join(cc)
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid(domain=a.address.rsplit('@', 1)[-1])
        if reply_to and reply_to.get('message_id'):
            msg['In-Reply-To'] = reply_to['message_id']
            msg['References'] = (reply_to.get('references', '') + ' ' + reply_to['message_id']).strip()
        msg.set_content(body.rstrip() + '\n')
        return msg

    def reply_context(self, uid: int, reply_all: bool = False, folder: str = 'INBOX') -> dict:
        """Who a reply goes to, its subject, and the threading headers."""
        with self._lock:
            conn = self._conn()
            self._select(conn, folder)
            _, msg = self._raw(conn, uid)
        me = self.account.address.lower()
        sender = parseaddr(str(msg.get('Reply-To') or msg.get('From', '')))
        to = [formataddr(sender)] if sender[1] else []
        cc = []
        if reply_all:
            for disp, addr in getaddresses([str(v) for v in msg.get_all('To', []) + msg.get_all('Cc', [])]):
                if addr and addr.lower() not in (me, sender[1].lower()):
                    cc.append(formataddr((disp, addr)))
        subject = str(msg.get('Subject', '') or '')
        if not re.match(r'(?i)^\s*re:', subject):
            subject = 'Re: ' + subject
        return {'to': to, 'cc': cc, 'subject': subject, 'message_id': str(msg.get('Message-ID', '') or ''),
                'references': str(msg.get('References', '') or ''), 'from_name': sender[0] or sender[1]}

    def send(self, msg: EmailMessage) -> None:
        a = self.account
        try:
            s = self._smtp_factory(a)
        except smtplib.SMTPAuthenticationError as exc:
            hint = APP_PASSWORD_HELP.get(a.imap_host, "your mail account's security settings")
            raise EmailError(f'{a.smtp_host} refused the sign-in. Use an app password from {hint}.') from exc
        except OSError as exc:
            raise EmailError(f'Could not reach {a.smtp_host}: {exc}') from exc
        try:
            s.send_message(msg)
        finally:
            try:
                s.quit()
            except Exception:
                pass
        if a.smtp_host not in SAVES_SENT:
            try:
                self._append('\\Sent', msg, '(\\Seen)')
            except Exception as exc:
                print(f'[Email] could not file a copy in Sent: {exc}')

    def save_draft(self, msg: EmailMessage) -> str:
        return self._append('\\Drafts', msg, '(\\Draft \\Seen)')

    def _append(self, use: str, msg: EmailMessage, flags: str) -> str:
        with self._lock:
            conn = self._conn()
            folder = self.folders().get(use) or {'\\Drafts': 'Drafts', '\\Sent': 'Sent'}[use]
            typ, data = conn.append(_quote(folder), flags, imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            if typ != 'OK':
                raise EmailError(f'The server did not accept the message into {folder}.')
            return folder

    # new mail
    def new_mail(self) -> list[dict]:
        """Unread mail from real people that arrived since the last call. The first call only sets the mark."""
        with self._lock:
            conn = self._conn()
            typ, data = conn.status('INBOX', '(UIDNEXT UIDVALIDITY)')
            raw = (data or [b''])[0] or b''
            nxt = re.search(rb'UIDNEXT (\d+)', raw)
            val = re.search(rb'UIDVALIDITY (\d+)', raw)
            if typ != 'OK' or not nxt:
                return []
            validity, top = (val.group(1).decode() if val else ''), int(nxt.group(1)) - 1
            if self._watch is None or self._watch[0] != validity:
                self._watch = (validity, top)
                return []
            last = self._watch[1]
            if top <= last:
                return []
            self._select(conn, 'INBOX')
            uids = [u for u in self._search(conn, ['UNSEEN', 'UID', f'{last + 1}:*']) if u > last]
            self._watch = (validity, top)
            rows = self._headers(conn, uids[-10:])
        me = self.account.address.lower()
        return [r for r in rows if not r['bulk'] and r['from'].lower() != me]


def _ascii(text: str) -> str:
    """IMAP SEARCH without a charset only takes ASCII; keep the searchable part."""
    out = text.encode('ascii', 'ignore').decode().strip()
    if not out:
        raise EmailError('Search the mailbox with words in English letters, or use the sender\'s address.')
    return out


# ── module state ────────────────────────────────────────────────────────────────

_box: Mailbox | None = None
_box_key: tuple | None = None
_box_lock = threading.Lock()


def mailbox() -> Mailbox:
    """The configured mailbox, rebuilt when the settings change."""
    global _box, _box_key
    account = load_account()
    key = (account.address, account.password, account.imap_host, account.smtp_host, account.smtp_port, account.name)
    with _box_lock:
        if _box is None or _box_key != key:
            if _box is not None:
                _box.close()
            _box, _box_key = Mailbox(account), key
        else:
            _box.account = account
        return _box


def configured() -> bool:
    try:
        return load_account(mx=lambda d: []).ready
    except Exception:
        return False


def test_connection(values: dict) -> tuple[bool, str]:
    """⚙ settings button: sign in to both servers with what the user typed."""
    account = load_account(values)
    if not account.ready:
        return False, 'Type your email address and an app password first.'
    box = Mailbox(account)
    try:
        unread = box.unread_count()
        s = box._smtp_connect(account)
        s.quit()
    except EmailError as exc:
        return False, str(exc)
    except smtplib.SMTPAuthenticationError:
        return False, f'Reading works, but {account.smtp_host} refused the sign-in for sending.'
    except Exception as exc:
        return False, f'{type(exc).__name__}: {str(exc)[:160]}'
    finally:
        box.close()
    return True, f'Connected ✓  {account.imap_host} · {unread} unread. Ask JARVIS "check my email".'


SETTINGS = {
    'namespace': NAMESPACE,
    'title': '✉  EMAIL',
    'fields': [
        {'key': 'address', 'label': 'Email address', 'type': 'text', 'placeholder': 'you@example.com'},
        {'key': 'app_password', 'label': 'App password (not your normal password)', 'type': 'password',
         'placeholder': 'Gmail: Google account → Security → App passwords'},
        {'key': 'notify_new', 'label': 'Tell me when mail from a real person arrives', 'type': 'toggle', 'default': True},
        {'key': 'imap_host', 'label': 'IMAP server (leave empty to detect)', 'type': 'text', 'placeholder': 'auto'},
        {'key': 'smtp_host', 'label': 'SMTP server[:port] (leave empty to detect)', 'type': 'text', 'placeholder': 'auto'},
    ],
    'action': {'label': 'TEST CONNECTION', 'run': test_connection},
}


def settings_section() -> dict:
    from memory.config_manager import get_plugin_config
    return {'plugin': 'email', **SETTINGS, 'values': get_plugin_config(NAMESPACE)}
