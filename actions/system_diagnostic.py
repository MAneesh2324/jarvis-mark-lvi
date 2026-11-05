"""Voice tool: full system diagnostic of the Mac."""
import json
import threading

from core import outcome

_running = {'full': False}


def system_diagnostic(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'run')
    try:
        from core import diagnostics as dg
        if action == 'last':
            text = dg.LAST.read_text(encoding='utf-8') if dg.LAST.exists() else ''
            return outcome.untrusted('system-diagnostic', text[:9000] or 'No diagnostic has been run yet.')
        depth = p.get('depth', 'standard')
        sections = p.get('sections') or None
        if depth == 'full' and not sections:
            # The speed test and update check take a minute or more: run in the background and announce.
            if _running['full']:
                return outcome.started('system_diagnostic', note='A full diagnostic is already running.')
            _running['full'] = True

            def work():
                from core import notify
                try:
                    r = dg.run('full')
                    top = '; '.join(f"{c['check']}: {c['detail']}" for c in r['issues'][:3])
                    notify.send('diagnostic', f"Full system diagnostic done. {r['summary']}" + (f' Main points: {top}' if top else '')
                                + ' The full report is in JARVIS Reports on your Desktop.', speak=True)
                except Exception as exc:
                    notify.send('diagnostic', f'The full diagnostic failed: {exc}')
                finally:
                    _running['full'] = False
            threading.Thread(target=work, daemon=True, name='jarvis-diagnostic').start()
            return outcome.started('system_diagnostic', depth='full', eta='about a minute',
                                   note='Includes an internet speed test and update check; I will announce the result.')
        r = dg.run(depth, sections)
        compact = {k: r[k] for k in ('when', 'depth', 'seconds', 'score', 'verdict', 'summary', 'report_path')}
        compact['issues'] = [{k: c.get(k) for k in ('section', 'check', 'status', 'detail', 'fix')} for c in r['issues']]
        compact['key_numbers'] = {s['section']: {k: v for k, v in s['info'].items() if not isinstance(v, (list, dict))}
                                  for s in r['sections']}
        return outcome.untrusted('system-diagnostic', json.dumps(compact, ensure_ascii=False, default=str))
    except Exception as exc:
        return outcome.failed('system_diagnostic', str(exc)[:300])


TOOL = {
    'name': 'system_diagnostic',
    'description': (
        'Full health check of this Mac: system and uptime, temperature, CPU load and hogs, memory pressure and swap, '
        'free space and what is using it (Trash, Downloads, caches, backups), drive SMART health, battery health and '
        'cycles, Wi-Fi signal, router and internet latency and loss, DNS, security (FileVault, firewall, SIP, '
        'Gatekeeper, Time Machine backups), background helpers, and JARVIS itself. Each item is rated ok / warning / '
        'critical with a fix, plus a 0-100 health score and a saved report. depth: quick (~3 s), standard (~6 s, '
        'default), full (adds internet speed test and macOS update check; runs in the background and announces). '
        'sections: run only some (system, cpu, memory, storage, disk, battery, network, security, background, jarvis). '
        'last: the previous report. Read-only: it never changes or deletes anything. Lead with the score and the '
        'issues that matter, in plain words; for live CPU/RAM numbers only, system_status is enough.'
    ),
    'brief': 'Full Mac health check with score, issues, fixes and a report.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['run', 'last']},
            'depth': {'type': 'STRING', 'enum': ['quick', 'standard', 'full']},
            'sections': {'type': 'ARRAY', 'items': {'type': 'STRING', 'enum': ['system', 'cpu', 'memory', 'storage', 'disk',
                                                                                'battery', 'network', 'security',
                                                                                'background', 'jarvis']}},
        },
        'required': ['action'],
    },
    'handler': system_diagnostic,
    'tier': 'core',
}
