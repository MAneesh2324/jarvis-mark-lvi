"""Everyday Mac control: clipboard, apps and processes, battery, network, storage,
opening and revealing files, Shortcuts, and notifications.

Quitting asks the app politely (it can save work); force-quit needs confirm=True.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import psutil


def _run(cmd, timeout=15, input_text=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or 'command failed').strip()[:300])
    return r.stdout


def clipboard_get() -> dict:
    text = _run(['pbpaste'])
    return {'text': text[:4000], 'characters': len(text), 'truncated': len(text) > 4000}


def clipboard_set(text: str) -> dict:
    _run(['pbcopy'], input_text=str(text))
    return {'copied_characters': len(str(text))}


def running_apps() -> dict:
    from AppKit import NSWorkspace
    apps = []
    for a in NSWorkspace.sharedWorkspace().runningApplications():
        if a.activationPolicy() == 0:          # regular apps with a Dock icon
            apps.append({'name': str(a.localizedName()), 'pid': int(a.processIdentifier()), 'active': bool(a.isActive())})
    return {'apps': sorted(apps, key=lambda x: x['name'].lower())}


def top_processes(by: str = 'cpu', limit: int = 8) -> dict:
    procs = list(psutil.process_iter(['pid', 'name', 'memory_info']))
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(0.6)
    rows = []
    for p in procs:
        try:
            rows.append({'name': p.info['name'], 'pid': p.info['pid'], 'cpu_percent': round(p.cpu_percent(None), 1),
                         'memory_mb': round(p.info['memory_info'].rss / 1048576)})
        except (psutil.Error, AttributeError, TypeError):
            continue
    rows.sort(key=lambda r: r['cpu_percent' if by == 'cpu' else 'memory_mb'], reverse=True)
    vm = psutil.virtual_memory()
    return {'by': by, 'processes': rows[:max(1, min(int(limit), 25))], 'cpu_total_percent': psutil.cpu_percent(0.2),
            'memory_used_percent': vm.percent}


def quit_app(name: str, force: bool = False, confirm: bool = False) -> dict:
    from AppKit import NSWorkspace
    name_l = str(name or '').strip().lower()
    if not name_l:
        raise ValueError('Name the app to quit.')
    matches = [a for a in NSWorkspace.sharedWorkspace().runningApplications()
               if a.localizedName() and name_l in str(a.localizedName()).lower() and a.activationPolicy() == 0]
    if not matches:
        return {'quit': False, 'note': f'No running app matches "{name}".'}
    if force and not confirm:
        return {'quit': False, 'needs_confirmation': True,
                'note': 'Force quit loses unsaved work. Ask the user to confirm, then call again with confirm=true.'}
    names = []
    for a in matches:
        (a.forceTerminate() if force else a.terminate())
        names.append(str(a.localizedName()))
    time.sleep(1.5)
    still = [str(a.localizedName()) for a in matches if not a.isTerminated()]
    return {'asked_to_quit': names, 'still_running': still,
            'note': 'Some apps ask to save first; check the screen.' if still and not force else ''}


def battery() -> dict:
    b = psutil.sensors_battery()
    if b is None:
        return {'battery': 'No battery (desktop Mac).'}
    mins = None if b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else round(b.secsleft / 60)
    return {'percent': round(b.percent), 'charging': bool(b.power_plugged), 'minutes_left': mins}


def network() -> dict:
    info = {}
    try:
        out = _run(['ipconfig', 'getsummary', 'en0'], timeout=5)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith('SSID :'):
                info['wifi'] = line.split(':', 1)[1].strip()
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('1.1.1.1', 80))
        info['local_ip'] = s.getsockname()[0]
        s.close()
        info['online'] = True
    except OSError:
        info['online'] = False
    counters = psutil.net_io_counters()
    info['sent_mb'], info['received_mb'] = round(counters.bytes_sent / 1048576), round(counters.bytes_recv / 1048576)
    return info


def storage() -> dict:
    u = shutil.disk_usage('/')
    return {'total_gb': round(u.total / 1e9), 'free_gb': round(u.free / 1e9), 'used_percent': round(100 * u.used / u.total, 1)}


def open_item(target: str, app: str = '') -> dict:
    target = str(target or '').strip()
    if not target:
        raise ValueError('Say what to open.')
    if not target.startswith(('http://', 'https://')):
        from core import paths
        p = paths.resolve(target)
        if not p.exists():
            raise ValueError(f'Not found: {p}')
        target = str(p)
    _run(['open'] + (['-a', app] if app else []) + [target])
    return {'opened': target, 'with': app or 'default app'}


def reveal(path: str) -> dict:
    from core import paths
    p = paths.resolve(path)
    if not p.exists():
        raise ValueError(f'Not found: {p}')
    _run(['open', '-R', str(p)])
    return {'revealed': str(p)}


def shortcuts_list() -> dict:
    names = [n for n in _run(['shortcuts', 'list'], timeout=20).splitlines() if n.strip()]
    return {'shortcuts': names[:200], 'count': len(names)}


def shortcut_run(name: str, text_input: str = '') -> dict:
    available = shortcuts_list()['shortcuts']
    match = next((n for n in available if n.lower() == str(name).lower()), None) or \
        next((n for n in available if str(name).lower() in n.lower()), None)
    if not match:
        return {'ran': False, 'note': f'No shortcut named "{name}".', 'available': available[:30]}
    out = _run(['shortcuts', 'run', match] + (['--input-path', '-'] if text_input else []), timeout=120,
               input_text=text_input or None)
    return {'ran': match, 'output': out.strip()[:2000]}


def notify_mac(title: str, text: str) -> dict:
    esc = lambda s: str(s).replace('\\', '\\\\').replace('"', '\\"')[:200]
    _run(['osascript', '-e', f'display notification "{esc(text)}" with title "{esc(title or "JARVIS")}"'])
    return {'shown': True}
