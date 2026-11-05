"""Full system diagnostic for the Mac: everything that matters, checked in parallel, rated, explained.

Sections: system, CPU, memory, storage, disk health, battery, network, security,
background software, and JARVIS itself. Each check returns ok / warn / critical
with a plain fix, an overall health score is computed, and a Markdown report is
saved to Desktop/JARVIS Reports. Read-only: nothing is changed or deleted.

Depth: quick (~3 s) · standard (~10 s, default) · full (adds an internet speed
test and a software-update check, ~40-90 s).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import psutil

HOME = Path.home()
BASE = Path(__file__).resolve().parent.parent
REPORTS = HOME / 'Desktop' / 'JARVIS Reports'
LAST = BASE / 'memory' / 'last-diagnostic.md'


def _sh(cmd, timeout=10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or '') + (r.stderr or '')
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ''


def _gb(n) -> float:
    return round(n / 1e9, 1)


def _gib(n) -> float:
    """Memory is sold in binary units: a 16 GB Mac has 16 GiB."""
    return round(n / 1024 ** 3, 1)


def _human(n) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit in ('B', 'KB') else f'{n:.1f} {unit}'
        n /= 1000


def _check(name, status, detail, fix=''):
    return {'check': name, 'status': status, 'detail': detail, **({'fix': fix} if fix and status != 'ok' else {})}


# ── sections ────────────────────────────────────────────────────────────────

def system_info():
    checks, info = [], {}
    info['model'] = _sh(['sysctl', '-n', 'hw.model']).strip()
    info['chip'] = _sh(['sysctl', '-n', 'machdep.cpu.brand_string']).strip()
    info['macos'] = platform.mac_ver()[0]
    info['cores'] = psutil.cpu_count()
    info['memory_gb'] = _gib(psutil.virtual_memory().total)
    up = time.time() - psutil.boot_time()
    days = up / 86400
    info['uptime'] = f'{int(days)}d {int(up % 86400 // 3600)}h'
    checks.append(_check('Uptime', 'warn' if days > 14 else 'ok', f'Running for {info["uptime"]} since the last restart.',
                         'Restart the Mac: it clears memory leaks and finishes pending updates.'))
    try:
        from Foundation import NSProcessInfo
        state = int(NSProcessInfo.processInfo().thermalState())
        label = ['normal', 'fair', 'serious', 'critical'][state]
        checks.append(_check('Temperature', 'ok' if state <= 1 else 'warn' if state == 2 else 'critical',
                             f'Thermal state is {label}.',
                             'The Mac is hot and slowing itself down: close heavy apps, keep vents clear, use a hard surface.'))
    except Exception:
        pass
    return {'section': 'System', 'info': info, 'checks': checks}


def cpu():
    total = psutil.cpu_percent(interval=1.0)
    cores = psutil.cpu_count() or 1
    load1, load5, load15 = os.getloadavg()
    procs = []
    for p in psutil.process_iter(['name', 'pid']):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except psutil.Error:
            pass
    time.sleep(0.8)
    tops = []
    for p in procs:
        try:
            tops.append((p.cpu_percent(None), p.info['name'], p.info['pid']))
        except psutil.Error:
            pass
    tops.sort(reverse=True)
    top = [{'name': n, 'pid': pid, 'cpu_percent': round(c, 1)} for c, n, pid in tops[:5] if c > 0.5]
    status = 'critical' if load5 > cores * 1.5 else 'warn' if load5 > cores * 0.9 or total > 85 else 'ok'
    hog = next((t for t in top if t['cpu_percent'] > 80), None)
    checks = [_check('CPU load', status, f'{total:.0f}% busy now; load average {load1:.1f} / {load5:.1f} / {load15:.1f} '
                                         f'on {cores} cores.', 'Quit or restart the busiest apps listed below.')]
    if hog:
        checks.append(_check('CPU hog', 'warn', f'{hog["name"]} is using {hog["cpu_percent"]:.0f}% of a core.',
                             f'If you are not using {hog["name"]} heavily right now, quit and reopen it.'))
    return {'section': 'CPU', 'info': {'percent': total, 'load_avg': [round(load1, 2), round(load5, 2), round(load15, 2)],
                                       'top_processes': top}, 'checks': checks}


def memory():
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    free_pct = None
    m = re.search(r'free percentage:\s*(\d+)%', _sh(['memory_pressure', '-Q'], 8))
    if m:
        free_pct = int(m.group(1))
    procs = []
    for p in psutil.process_iter(['name', 'memory_info']):
        try:
            procs.append((p.info['memory_info'].rss, p.info['name']))
        except (psutil.Error, AttributeError, TypeError):
            pass
    procs.sort(reverse=True)
    top = [{'name': n, 'memory': _human(r)} for r, n in procs[:5]]
    pressure = 'critical' if free_pct is not None and free_pct < 10 else 'warn' if free_pct is not None and free_pct < 25 else 'ok'
    checks = [_check('Memory pressure', pressure,
                     f'{vm.percent:.0f}% of {_gib(vm.total):g} GB in use' + (f'; {free_pct}% free by macOS\'s own measure.' if free_pct is not None else '.'),
                     'Close apps and browser tabs you are not using; the top memory users are listed.')]
    swap_gb = _gib(sw.used)
    checks.append(_check('Swap', 'warn' if swap_gb > 4 else 'ok', f'{swap_gb} GB of memory has spilled to disk (swap).',
                         'Heavy swap slows everything down; a restart clears it, fewer open apps prevents it.'))
    return {'section': 'Memory', 'info': {'used_percent': vm.percent, 'total_gb': _gib(vm.total), 'available_gb': _gib(vm.available),
                                          'swap_gb': swap_gb, 'free_percent_pressure': free_pct, 'top_processes': top},
            'checks': checks}


def _du(path: Path, timeout=20):
    if not path.exists():
        return None
    out = _sh(['du', '-sk', str(path)], timeout)
    m = re.match(r'(\d+)', out.strip())
    return int(m.group(1)) * 1024 if m else None


def storage():
    checks, volumes = [], []
    seen = set()
    for part in psutil.disk_partitions(all=False):
        mp = part.mountpoint
        if mp.startswith('/System/Volumes/') and mp not in ('/System/Volumes/Data',) or mp in seen:
            continue
        try:
            u = shutil.disk_usage(mp)
        except OSError:
            continue
        key = (u.total, u.used)
        if key in seen:
            continue
        seen.add(key)
        seen.add(mp)
        name = 'Macintosh HD' if mp in ('/', '/System/Volumes/Data') else Path(mp).name
        free_pct = 100 * u.free / u.total
        volumes.append({'volume': name, 'mount': mp, 'total_gb': _gb(u.total), 'free_gb': _gb(u.free),
                        'free_percent': round(free_pct, 1)})
        status = 'critical' if free_pct < 5 or u.free < 5e9 else 'warn' if free_pct < 15 or u.free < 20e9 else 'ok'
        checks.append(_check(f'Free space on {name}', status, f'{_gb(u.free)} GB free of {_gb(u.total)} GB ({free_pct:.0f}%).',
                             'Empty the Trash and clear the large folders listed; macOS needs 15-20% free to run well.'))
    places = {'Trash': HOME / '.Trash', 'Downloads': HOME / 'Downloads', 'App caches': HOME / 'Library' / 'Caches',
              'iPhone backups': HOME / 'Library' / 'Application Support' / 'MobileSync' / 'Backup',
              'Xcode build data': HOME / 'Library' / 'Developer' / 'Xcode' / 'DerivedData',
              'JARVIS recordings': BASE / 'recordings'}
    sizes = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_du, p): name for name, p in places.items()}
        for f in as_completed(futs):
            try:
                v = f.result()
            except Exception:
                v = None
            if v:
                sizes[futs[f]] = v
    reclaim = sorted(((v, k) for k, v in sizes.items()), reverse=True)
    if sizes.get('Trash', 0) > 1e9:
        checks.append(_check('Trash', 'warn', f'The Trash holds {_human(sizes["Trash"])}.',
                             'Empty the Trash yourself in Finder to free that space (JARVIS never empties it).'))
    if sizes.get('Downloads', 0) > 10e9:
        checks.append(_check('Downloads folder', 'warn', f'Downloads holds {_human(sizes["Downloads"])}.',
                             'Old installers (.dmg) and archives there are usually safe to remove once installed.'))
    return {'section': 'Storage', 'info': {'volumes': volumes, 'space_used_by': [{'place': k, 'size': _human(v)} for v, k in reclaim]},
            'checks': checks}


def disk_health():
    out = _sh(['diskutil', 'info', 'disk0'], 10)
    m = re.search(r'SMART Status:\s*(.+)', out)
    smart = m.group(1).strip() if m else 'Unknown'
    status = 'ok' if smart.lower().startswith('verified') else 'critical' if 'fail' in smart.lower() else 'ok'
    media = (re.search(r'Device / Media Name:\s*(.+)', out) or re.search(r'Media Name:\s*(.+)', out))
    return {'section': 'Disk health', 'info': {'smart_status': smart, 'drive': media.group(1).strip() if media else ''},
            'checks': [_check('Drive health (SMART)', status, f'Internal drive reports: {smart}.',
                              'Back up immediately and contact Apple: the drive reports a failure.')]}


def battery():
    b = psutil.sensors_battery()
    if b is None:
        return {'section': 'Battery', 'info': {'present': False}, 'checks': []}
    prof = _sh(['system_profiler', 'SPPowerDataType'], 15)
    cycles = re.search(r'Cycle Count:\s*(\d+)', prof)
    cond = re.search(r'Condition:\s*(.+)', prof)
    maxcap = re.search(r'Maximum Capacity:\s*(\d+)%', prof)
    info = {'percent': round(b.percent), 'charging': bool(b.power_plugged), 'cycle_count': int(cycles.group(1)) if cycles else None,
            'condition': cond.group(1).strip() if cond else None, 'max_capacity_percent': int(maxcap.group(1)) if maxcap else None}
    checks = []
    if info['max_capacity_percent'] is not None:
        cap = info['max_capacity_percent']
        checks.append(_check('Battery health', 'ok' if cap >= 80 else 'warn' if cap >= 70 else 'critical',
                             f'Holds {cap}% of its original charge after {info["cycle_count"]} cycles '
                             f'(condition: {info["condition"] or "unknown"}).',
                             'Below 80% Apple recommends a battery service; check System Settings > Battery.'))
    elif info['condition']:
        checks.append(_check('Battery health', 'ok' if info['condition'].lower() == 'normal' else 'warn',
                             f'Condition: {info["condition"]}.', 'Have the battery checked by Apple.'))
    if not b.power_plugged and b.percent < 20:
        checks.append(_check('Charge', 'warn', f'Battery at {round(b.percent)}% and not charging.', 'Plug in the charger.'))
    return {'section': 'Battery', 'info': info, 'checks': checks}


def _ping(host, count=4):
    out = _sh(['ping', '-c', str(count), '-i', '0.2', '-t', '5', host], 8)
    loss = re.search(r'([\d.]+)% packet loss', out)
    avg = re.search(r'= [\d.]+/([\d.]+)/', out)
    return (float(loss.group(1)) if loss else 100.0), (float(avg.group(1)) if avg else None)


def network(speed_test=False):
    info, checks = {}, []
    gw = re.search(r'gateway:\s*(\S+)', _sh(['route', '-n', 'get', 'default'], 5))
    info['gateway'] = gw.group(1) if gw else None
    summary = _sh(['ipconfig', 'getsummary', 'en0'], 5)
    ssid = re.search(r'^\s*SSID : (.+)$', summary, re.M)
    info['wifi'] = ssid.group(1).strip() if ssid else None
    air = _sh(['system_profiler', 'SPAirPortDataType'], 20)
    sig = re.search(r'Current Network Information:.*?Signal / Noise:\s*(-?\d+) dBm / (-?\d+) dBm', air, re.S)
    if sig:
        rssi, noise = int(sig.group(1)), int(sig.group(2))
        info['wifi_signal_dbm'], info['wifi_noise_dbm'] = rssi, noise
        checks.append(_check('Wi-Fi signal', 'ok' if rssi >= -67 else 'warn' if rssi >= -75 else 'critical',
                             f'Signal {rssi} dBm (noise {noise} dBm): ' + ('strong' if rssi >= -60 else 'good' if rssi >= -67 else
                                                                         'weak' if rssi >= -75 else 'very weak') + '.',
                             'Move closer to the router or remove obstacles; weak signal causes dropouts and slow voice replies.'))
    if info['gateway']:
        loss, avg = _ping(info['gateway'])
        avg = round(avg) if avg is not None else None
        info['router_ping_ms'], info['router_loss_percent'] = avg, loss
        # Wi-Fi replies jitter; only a consistently slow or lossy router is worth flagging.
        checks.append(_check('Router connection', 'ok' if loss == 0 and (avg or 0) < 60 else 'warn' if loss < 25 else 'critical',
                             f'Router replies in {avg} ms with {loss:.0f}% loss.' if avg else 'Router did not answer pings.',
                             'Restart the router; check for interference or a loose cable.'))
    loss, avg = _ping('1.1.1.1')
    avg = round(avg) if avg is not None else None
    info['internet_ping_ms'], info['internet_loss_percent'] = avg, loss
    online = avg is not None
    checks.append(_check('Internet', 'critical' if not online else 'ok' if loss == 0 and avg < 80 else 'warn',
                         f'Internet replies in {avg} ms with {loss:.0f}% loss.' if online else 'No internet connection.',
                         'Check the router and your provider; high delay or loss makes JARVIS slow to answer.'))
    t = time.monotonic()
    try:
        socket.getaddrinfo('www.google.com', 443)
        dns_ms = round((time.monotonic() - t) * 1000)
        info['dns_ms'] = dns_ms
        checks.append(_check('DNS', 'ok' if dns_ms < 150 else 'warn', f'Name lookup took {dns_ms} ms.',
                             'Slow DNS: consider 1.1.1.1 or 8.8.8.8 in System Settings > Network > DNS.'))
    except OSError:
        checks.append(_check('DNS', 'critical', 'Name lookup failed.', 'Check your network or DNS settings.'))
    if speed_test and online:
        out = _sh(['networkQuality', '-s', '-c'], 70)
        try:
            import json as _j
            d = _j.loads(out[out.find('{'):out.rfind('}') + 1])
            down = round(d.get('dl_throughput', 0) / 1e6, 1)
            up = round(d.get('ul_throughput', 0) / 1e6, 1)
            info['download_mbps'], info['upload_mbps'] = down, up
            resp = d.get('responsiveness') or d.get('dl_responsiveness')
            if resp:
                info['responsiveness_rpm'] = round(resp)
            checks.append(_check('Internet speed', 'ok' if down >= 25 else 'warn' if down >= 5 else 'critical',
                                 f'Download {down} Mbps, upload {up} Mbps.',
                                 'Slow line: check other devices using bandwidth, or your plan with the provider.'))
        except Exception:
            checks.append(_check('Internet speed', 'warn', 'The speed test did not complete.', 'Try again later.'))
    io = psutil.net_io_counters()
    info['since_boot'] = {'sent': _human(io.bytes_sent), 'received': _human(io.bytes_recv)}
    return {'section': 'Network', 'info': info, 'checks': checks}


def security(check_updates=False):
    checks, info = [], {}
    fv = _sh(['fdesetup', 'status'], 5)
    info['filevault'] = 'on' if 'is On' in fv else 'off' if 'is Off' in fv else 'unknown'
    if info['filevault'] != 'unknown':
        checks.append(_check('FileVault disk encryption', 'ok' if info['filevault'] == 'on' else 'warn',
                             f'FileVault is {info["filevault"]}.',
                             'Turn on FileVault in System Settings > Privacy & Security so a lost Mac cannot be read.'))
    fw = _sh(['/usr/libexec/ApplicationFirewall/socketfilterfw', '--getglobalstate'], 5)
    info['firewall'] = 'on' if 'enabled' in fw.lower() else 'off' if 'disabled' in fw.lower() else 'unknown'
    if info['firewall'] != 'unknown':
        checks.append(_check('Firewall', 'ok' if info['firewall'] == 'on' else 'warn', f'The firewall is {info["firewall"]}.',
                             'Turn it on in System Settings > Network > Firewall.'))
    sip = _sh(['csrutil', 'status'], 5)
    info['system_integrity_protection'] = 'on' if 'enabled' in sip.lower() else 'off' if 'disabled' in sip.lower() else 'unknown'
    if info['system_integrity_protection'] == 'off':
        checks.append(_check('System Integrity Protection', 'critical', 'SIP is disabled.',
                             'Re-enable it from Recovery mode (csrutil enable) unless you disabled it on purpose.'))
    gk = _sh(['spctl', '--status'], 5)
    info['gatekeeper'] = 'on' if 'enabled' in gk else 'off' if 'disabled' in gk else 'unknown'
    if info['gatekeeper'] == 'off':
        checks.append(_check('Gatekeeper', 'warn', 'Gatekeeper app checking is off.',
                             'Turn it back on: sudo spctl --master-enable (you run it; JARVIS will not).'))
    tm = _sh(['tmutil', 'latestbackup'], 8).strip()
    m = re.search(r'(\d{4}-\d{2}-\d{2})-(\d{6})', tm)
    if m:
        when = datetime.strptime(m.group(1), '%Y-%m-%d')
        age = (datetime.now() - when).days
        info['last_backup'] = m.group(1)
        checks.append(_check('Time Machine backup', 'ok' if age <= 7 else 'warn', f'Last backup {age} days ago ({m.group(1)}).',
                             'Connect the backup drive; a week-old backup can lose a week of work.'))
    elif 'No machine directory' in tm or not tm or 'requires' in tm.lower() or 'error' in tm.lower():
        info['last_backup'] = 'none found or not readable'
        checks.append(_check('Time Machine backup', 'warn', 'No Time Machine backup was found (or macOS did not allow reading it).',
                             'Set up Time Machine or another backup: a disk failure would lose everything not backed up.'))
    if check_updates:
        out = _sh(['softwareupdate', '-l'], 90)
        pending = re.findall(r'\* Label:\s*(.+)', out)
        info['pending_updates'] = pending
        checks.append(_check('macOS updates', 'warn' if pending else 'ok',
                             (f'{len(pending)} update(s) waiting: ' + ', '.join(pending[:3])) if pending else 'macOS is up to date.',
                             'Install them in System Settings > General > Software Update.'))
    return {'section': 'Security', 'info': info, 'checks': checks}


def background_software():
    names = []
    for d in (HOME / 'Library' / 'LaunchAgents', Path('/Library/LaunchAgents'), Path('/Library/LaunchDaemons')):
        if d.exists():
            for p in d.glob('*.plist'):
                if not p.name.startswith('com.apple.'):
                    names.append(p.stem)
    names = sorted(set(names))
    checks = [_check('Background helpers', 'ok' if len(names) <= 15 else 'warn',
                     f'{len(names)} third-party background helpers start automatically.',
                     'Review them in System Settings > General > Login Items & Extensions and turn off ones you do not need.')]
    return {'section': 'Background software', 'info': {'count': len(names), 'items': names[:40]}, 'checks': checks}


def jarvis_health():
    info, checks = {}, []
    for p in psutil.process_iter(['name', 'memory_info', 'cmdline']):
        try:
            if 'MarkLVI' in (p.info['name'] or '') or any('Mark LVI.app' in c for c in (p.info['cmdline'] or [])):
                info['app_memory'] = _human(p.info['memory_info'].rss)
                break
        except (psutil.Error, TypeError):
            continue
    log = BASE / 'native-startup.log'
    if log.exists():
        info['log_size'] = _human(log.stat().st_size)
        if log.stat().st_size > 200e6:
            checks.append(_check('JARVIS log', 'warn', f'The JARVIS log is {info["log_size"]}.', 'It can be cleared safely while JARVIS is closed.'))
    try:
        import json as _j
        st = _j.loads((BASE / 'memory' / 'auto-learning-state.json').read_text())
        bad = [k for k, v in st.get('sources', {}).items() if not v.get('ok')]
        info['last_learning_cycle'] = st.get('finished', '')[:16]
        checks.append(_check('Background learning', 'ok' if not bad else 'warn',
                             'Last cycle healthy.' if not bad else 'Failed parts in the last cycle: ' + ', '.join(bad),
                             'Usually a temporary network or quota issue; it retries every 30 minutes.'))
    except Exception:
        pass
    info['running'] = 'app_memory' in info
    return {'section': 'JARVIS', 'info': info, 'checks': checks}


# ── run everything ──────────────────────────────────────────────────────────

SECTIONS = {'system': system_info, 'cpu': cpu, 'memory': memory, 'storage': storage, 'disk': disk_health,
            'battery': battery, 'network': network, 'security': security, 'background': background_software,
            'jarvis': jarvis_health}


def run(depth: str = 'standard', only: list[str] | None = None) -> dict:
    depth = depth if depth in ('quick', 'standard', 'full') else 'standard'
    names = [n for n in (only or SECTIONS) if n in SECTIONS]
    if depth == 'quick' and not only:
        names = ['system', 'cpu', 'memory', 'storage', 'battery', 'network']
    t0 = time.monotonic()
    results = {}
    with ThreadPoolExecutor(max_workers=len(names)) as ex:
        futs = {}
        for n in names:
            fn = SECTIONS[n]
            if n == 'network':
                futs[ex.submit(fn, depth == 'full')] = n
            elif n == 'security':
                futs[ex.submit(fn, depth == 'full')] = n
            else:
                futs[ex.submit(fn)] = n
        for f in as_completed(futs):
            n = futs[f]
            try:
                results[n] = f.result()
            except Exception as exc:
                results[n] = {'section': n.title(), 'info': {}, 'checks': [_check(n.title(), 'warn', f'Check could not run: {exc}')]}
    ordered = [results[n] for n in names if n in results]
    issues = [dict(c, section=s['section']) for s in ordered for c in s['checks'] if c['status'] != 'ok']
    rank = {'critical': 0, 'warn': 1}
    issues.sort(key=lambda c: rank[c['status']])
    crit = sum(1 for c in issues if c['status'] == 'critical')
    warn = len(issues) - crit
    score = max(0, 100 - crit * 20 - warn * 6)
    verdict = 'excellent' if score >= 90 else 'good' if score >= 75 else 'needs attention' if score >= 50 else 'poor'
    summary = (f'Health score {score}/100 ({verdict}). ' +
               (f'{crit} critical and {warn} warning(s). Top issue: {issues[0]["detail"]}' if issues else 'No problems found.'))
    report = {'when': datetime.now().strftime('%Y-%m-%d %H:%M'), 'depth': depth, 'seconds': round(time.monotonic() - t0, 1),
              'score': score, 'verdict': verdict, 'summary': summary, 'issues': issues, 'sections': ordered}
    report['report_path'] = _save(report)
    return report


def _save(r) -> str:
    icon = {'ok': '✅', 'warn': '⚠️', 'critical': '🛑'}
    lines = [f'# System diagnostic — {r["when"]}', '', f'**Health score: {r["score"]}/100 ({r["verdict"]})** · '
             f'{r["depth"]} check in {r["seconds"]} s', '']
    if r['issues']:
        lines += ['## What needs attention', '']
        for c in r['issues']:
            lines.append(f'- {icon[c["status"]]} **{c["section"]} — {c["check"]}:** {c["detail"]}' + (f' _Fix:_ {c["fix"]}' if c.get('fix') else ''))
        lines.append('')
    for s in r['sections']:
        lines += [f'## {s["section"]}', '']
        for c in s['checks']:
            lines.append(f'- {icon[c["status"]]} {c["check"]}: {c["detail"]}')
        for k, v in s['info'].items():
            if isinstance(v, list):
                if v and isinstance(v[0], dict):
                    lines.append(f'- {k.replace("_", " ")}: ' + '; '.join(', '.join(f'{a}={b}' for a, b in d.items()) for d in v[:8]))
                elif v:
                    lines.append(f'- {k.replace("_", " ")}: ' + ', '.join(map(str, v[:15])))
            elif isinstance(v, dict):
                lines.append(f'- {k.replace("_", " ")}: ' + ', '.join(f'{a} {b}' for a, b in v.items()))
            elif v not in (None, ''):
                lines.append(f'- {k.replace("_", " ")}: {v}')
        lines.append('')
    lines.append('_Read-only check by JARVIS: nothing was changed or deleted._')
    text = '\n'.join(lines)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f'system-diagnostic-{datetime.now():%Y-%m-%d-%H%M}.md'
    path.write_text(text, encoding='utf-8')
    LAST.parent.mkdir(parents=True, exist_ok=True)
    LAST.write_text(text, encoding='utf-8')
    return str(path)
