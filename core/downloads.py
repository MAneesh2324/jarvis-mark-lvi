"""Download files for the user: to ~/Downloads, in the background, safely.

* Streams to a .part file and renames only when complete, so a half file never
  looks finished.
* Marks every download with macOS's quarantine flag — what Safari and Chrome do —
  so Gatekeeper checks installers and apps before they first run.
* Never opens or runs what it downloads; opening is a separate, explicit request,
  and installers/scripts are flagged in the result.
* Refuses local-network addresses, so a page cannot use it to reach devices on
  the user's network.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

DOWNLOADS = Path.home() / 'Downloads'
MAX_BYTES = 5 * 1024 ** 3
RISKY = {'.dmg', '.pkg', '.mpkg', '.app', '.command', '.sh', '.zsh', '.bash', '.py', '.jar', '.exe', '.msi', '.scpt',
         '.workflow', '.terminal', '.webloc', '.zip'}
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _public(url: str) -> str:
    u = urlparse(str(url or '').strip())
    if u.scheme not in ('http', 'https') or not u.hostname:
        raise ValueError('Give a full http(s) link to download.')
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror:
        raise ValueError(f'Cannot resolve {u.hostname}.')
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError('Downloads from local-network addresses are blocked.')
    return u.geturl()


def _name_from(resp, url: str, wanted: str = '') -> str:
    if wanted:
        name = wanted
    else:
        cd = resp.headers.get('content-disposition', '')
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
        name = unquote(m.group(1)) if m else unquote(Path(urlparse(resp.url).path).name) or 'download'
    name = re.sub(r'[/\\:\x00-\x1f]', '_', name).strip(' .')[:180] or 'download'
    if '.' not in name:
        ctype = resp.headers.get('content-type', '').split(';')[0]
        ext = {'application/pdf': '.pdf', 'image/jpeg': '.jpg', 'image/png': '.png', 'application/zip': '.zip',
               'text/csv': '.csv', 'video/mp4': '.mp4', 'audio/mpeg': '.mp3', 'text/html': '.html'}.get(ctype, '')
        name += ext
    return name


def unique(folder: Path, name: str) -> Path:
    p = folder / name
    stem, suf, n = p.stem, p.suffix, 2
    while p.exists() or p.with_name(p.name + '.part').exists():
        p = folder / f'{stem} ({n}){suf}'
        n += 1
    return p


def quarantine(path: Path, source: str = '') -> None:
    """Same flag browsers set: Gatekeeper then checks the file before it first opens."""
    value = f'0081;{int(time.time()):x};JARVIS;{uuid.uuid4()}'
    subprocess.run(['xattr', '-w', 'com.apple.quarantine', value, str(path)], capture_output=True)
    if source:
        plist = json.dumps([source])
        subprocess.run(['xattr', '-w', 'com.apple.metadata:kMDItemWhereFroms', plist, str(path)], capture_output=True)


def _human(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def start(url: str, filename: str = '', folder: str = '') -> dict:
    url = _public(url)
    dest = Path(os.path.expanduser(folder)).resolve() if folder else DOWNLOADS
    dest.mkdir(parents=True, exist_ok=True)
    job = {'id': uuid.uuid4().hex[:8], 'url': url, 'state': 'starting', 'received': 0, 'total': None,
           'path': None, 'started': datetime.now().isoformat(timespec='seconds')}
    with _lock:
        _jobs[job['id']] = job
    threading.Thread(target=_run, args=(job, dest, filename), daemon=True, name='jarvis-download').start()
    deadline = time.time() + 6          # small files finish before we answer
    while time.time() < deadline and job['state'] in ('starting', 'downloading'):
        time.sleep(0.1)
    return status(job['id'])


def _run(job, dest: Path, filename: str):
    from core import notify
    part = None
    try:
        with requests.get(job['url'], stream=True, timeout=(10, 60), allow_redirects=True,
                          headers={'User-Agent': 'Mozilla/5.0 (Macintosh) JARVIS-Downloader/1.0'}) as r:
            r.raise_for_status()
            _public(r.url)            # a redirect must not lead into the local network either
            total = int(r.headers.get('content-length') or 0) or None
            if total and total > MAX_BYTES:
                raise ValueError(f'File is {_human(total)}, over the 5 GB limit.')
            path = unique(dest, _name_from(r, job['url'], filename))
            part = path.with_name(path.name + '.part')
            job.update(state='downloading', total=total, path=str(path))
            h = hashlib.sha256()
            with open(part, 'wb') as f:
                for chunk in r.iter_content(1 << 16):
                    if job.get('cancel'):
                        raise InterruptedError('cancelled')
                    f.write(chunk)
                    h.update(chunk)
                    job['received'] += len(chunk)
                    if job['received'] > MAX_BYTES:
                        raise ValueError('Download exceeded the 5 GB limit.')
        os.replace(part, path)
        quarantine(path, job['url'])
        job.update(state='done', sha256=h.hexdigest(), finished=datetime.now().isoformat(timespec='seconds'),
                   risky=path.suffix.lower() in RISKY)
        if job['received'] > 20 * 1024 ** 2:
            notify.send('download', f'Download finished: {path.name} ({_human(job["received"])}) in {path.parent.name}.',
                        speak=True)
    except InterruptedError:
        job['state'] = 'cancelled'
    except Exception as exc:
        job.update(state='failed', error=str(exc)[:200])
    finally:
        if part is not None and part.exists() and job['state'] != 'done':
            part.unlink(missing_ok=True)


def status(job_id: str = '') -> dict:
    if not job_id:
        return {'downloads': [status(j)['download'] for j in list(_jobs)[-10:]]}
    job = _jobs.get(job_id)
    if not job:
        raise ValueError('No download with that id.')
    view = {k: job.get(k) for k in ('id', 'state', 'path', 'url', 'error', 'sha256', 'risky')}
    view['size'] = _human(job['received'])
    if job.get('total'):
        view['progress_percent'] = round(100 * job['received'] / job['total'], 1)
    if job.get('risky') and job['state'] == 'done':
        view['note'] = 'This is an installer, app, script or archive. It was not opened. macOS will check it on first open.'
    return {'download': view}


def cancel(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise ValueError('No download with that id.')
    job['cancel'] = True
    return {'id': job_id, 'state': 'cancelling'}


def recent(limit: int = 10, folder: str = '') -> dict:
    d = Path(os.path.expanduser(folder)).resolve() if folder else DOWNLOADS
    files = sorted((p for p in d.iterdir() if not p.name.startswith('.') and not p.name.endswith('.part')),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:max(1, min(int(limit), 50))]
    return {'folder': str(d), 'files': [{'name': p.name, 'path': str(p), 'size': _human(p.stat().st_size) if p.is_file() else '',
                                         'added': datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')}
                                        for p in files]}
