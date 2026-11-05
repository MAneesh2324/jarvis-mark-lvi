"""Voice tools: find files, downloads, everyday Mac control, and the autonomous browser agent."""
import json

from core import outcome


def _out(name, data):
    return outcome.untrusted(name, json.dumps(data, ensure_ascii=False, default=str))


def find_files(parameters, **kwargs):
    p = dict(parameters or {})
    try:
        from core.mac_find import find
        return _out('find-files', find(p.get('text', ''), p.get('kind', ''), p.get('days'), p.get('folder', ''),
                                       bool(p.get('downloaded')), p.get('content', True), p.get('limit', 15)))
    except Exception as exc:
        return outcome.failed('find_files', str(exc)[:300])


def downloads(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'download')
    try:
        from core import downloads as dl
        if action == 'download':
            data = dl.start(p.get('url', ''), p.get('filename', ''), p.get('folder', ''))
            state = data['download']['state']
            if state == 'failed':
                return outcome.failed('downloads', data['download'].get('error') or 'download failed')
            return (outcome.done if state == 'done' else outcome.started)('downloads', **data['download'])
        if action == 'status':
            return _out('downloads', dl.status(p.get('id', '')))
        if action == 'cancel':
            return outcome.done('downloads', **dl.cancel(p['id']))
        if action == 'recent':
            return _out('downloads', dl.recent(p.get('limit', 10), p.get('folder', '')))
        raise ValueError('Unknown downloads action.')
    except Exception as exc:
        return outcome.failed('downloads', str(exc)[:300])


def mac_system(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'battery')
    try:
        from core import mac_system as ms
        table = {
            'clipboard_get': lambda: ms.clipboard_get(),
            'clipboard_set': lambda: ms.clipboard_set(p.get('text', '')),
            'running_apps': lambda: ms.running_apps(),
            'top_processes': lambda: ms.top_processes(p.get('by', 'cpu'), p.get('limit', 8)),
            'quit_app': lambda: ms.quit_app(p.get('name', ''), bool(p.get('force')), bool(p.get('confirm'))),
            'battery': lambda: ms.battery(),
            'network': lambda: ms.network(),
            'storage': lambda: ms.storage(),
            'open': lambda: ms.open_item(p.get('target', ''), p.get('app', '')),
            'reveal': lambda: ms.reveal(p.get('target', '')),
            'shortcuts_list': lambda: ms.shortcuts_list(),
            'shortcut_run': lambda: ms.shortcut_run(p.get('name', ''), p.get('text', '')),
            'notify': lambda: ms.notify_mac(p.get('name', 'JARVIS'), p.get('text', '')),
        }
        if action not in table:
            raise ValueError('Unknown mac_system action.')
        return _out('mac-system', table[action]())
    except Exception as exc:
        return outcome.failed('mac_system', str(exc)[:300])


def browser_agent(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'start')
    try:
        from core import browser_agent as ba
        if action == 'start':
            return outcome.started('browser_agent', **ba.start(p.get('goal', '')))
        if action == 'status':
            return _out('browser-agent', ba.status(p.get('id', '')))
        if action == 'reply':
            return outcome.done('browser_agent', **ba.reply(p.get('id', ''), bool(p.get('approve')), p.get('text', '')))
        if action == 'stop':
            return outcome.done('browser_agent', **ba.stop(p.get('id', '')))
        raise ValueError('Unknown browser_agent action.')
    except Exception as exc:
        return outcome.failed('browser_agent', str(exc)[:300])


TOOLS = [
    {'name': 'find_files',
     'description': ('Find files, folders and apps anywhere on this Mac instantly with Spotlight: by words in the name or '
                     'contents (text), kind (pdf, image, video, audio, document, word, spreadsheet, presentation, text, '
                     'code, archive, installer, app, folder), modified within the last N days, inside a folder, or only '
                     'downloaded files (downloaded=true; days then means downloaded within N days). Newest first. Use for '
                     '"find the PDF I downloaded yesterday", "where is my resume", "photos from this week". Then use '
                     'mac_system open/reveal to open one or show it in Finder.'),
     'brief': 'Spotlight search across the Mac.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'text': {'type': 'STRING'}, 'kind': {'type': 'STRING', 'enum': ['pdf', 'image', 'photo', 'video', 'audio', 'music',
                  'document', 'word', 'spreadsheet', 'presentation', 'text', 'code', 'archive', 'installer', 'app', 'folder']},
         'days': {'type': 'NUMBER'}, 'folder': {'type': 'STRING'}, 'downloaded': {'type': 'BOOLEAN'},
         'content': {'type': 'BOOLEAN', 'description': 'Also search inside files (default true)'},
         'limit': {'type': 'INTEGER'}}},
     'handler': find_files, 'tier': 'core'},
    {'name': 'downloads',
     'description': ('Download a file from a direct link into ~/Downloads (or a folder), in the background for big files, '
                     'with the macOS quarantine flag so Gatekeeper checks installers. It never opens or runs the file; '
                     'open it only if the user asks (mac_system open). For downloads that need clicking on a website, use '
                     'browser_agent. recent: latest files in Downloads. status/cancel by id. Local-network links are refused.'),
     'brief': 'Download files; list recent downloads.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'action': {'type': 'STRING', 'enum': ['download', 'status', 'cancel', 'recent']},
         'url': {'type': 'STRING'}, 'filename': {'type': 'STRING'}, 'folder': {'type': 'STRING'},
         'id': {'type': 'STRING'}, 'limit': {'type': 'INTEGER'}}, 'required': ['action']},
     'handler': downloads, 'tier': 'core'},
    {'name': 'mac_system',
     'description': ('Everyday Mac control. clipboard_get / clipboard_set (text); running_apps; top_processes (by cpu or '
                     'memory) for "what is slowing my Mac"; quit_app (name; asks the app to quit so it can save — force '
                     'quit only with force=true AND confirm=true after the user agrees); battery; network (Wi-Fi name, '
                     'online); storage; open (target = file path or URL, optional app); reveal (show a file in Finder); '
                     'shortcuts_list / shortcut_run (the user\'s Shortcuts app automations; name, optional text input); '
                     'notify (a Mac notification: name=title, text). Volume, brightness, dark mode and windows are in '
                     'computer_settings.'),
     'brief': 'Clipboard, apps, processes, battery, network, open/reveal, Shortcuts.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'action': {'type': 'STRING', 'enum': ['clipboard_get', 'clipboard_set', 'running_apps', 'top_processes', 'quit_app',
                                               'battery', 'network', 'storage', 'open', 'reveal', 'shortcuts_list',
                                               'shortcut_run', 'notify']},
         'text': {'type': 'STRING'}, 'name': {'type': 'STRING'}, 'target': {'type': 'STRING'}, 'app': {'type': 'STRING'},
         'by': {'type': 'STRING', 'enum': ['cpu', 'memory']}, 'limit': {'type': 'INTEGER'},
         'force': {'type': 'BOOLEAN'}, 'confirm': {'type': 'BOOLEAN'}}, 'required': ['action']},
     'handler': mac_system, 'tier': 'core'},
    {'name': 'browser_agent',
     'description': ('Autonomous browser agent for multi-step web tasks: give it a goal ("find the cheapest flight from '
                     'Delhi to Goa on Friday", "download the latest MT5 installer for Mac", "fill this form with my '
                     'details", "find the support email on example.com") and it navigates, searches, clicks, types, '
                     'scrolls and downloads by itself in JARVIS\'s browser, then reports the answer. Use browser_control '
                     'for single steps the user dictates. It stops and asks before buying, paying, sending, posting, '
                     'deleting, signing up or accepting terms, and never types passwords or card details. start: goal. '
                     'status: progress or the question it is waiting on. reply: answer its question (approve=true to let '
                     'a paused action go ahead, or text), OR while it runs, pass text to change the plan ("laptops instead '
                     'of PCs") — never start a second task for a correction. start while a task runs replaces it. stop: '
                     'cancel. Tell the user it is working; its steps show in the activity log and it announces the result. '
                     'Do not also drive the browser with browser_control or screenshots while it runs.'),
     'brief': 'Autonomous multi-step browser tasks with approval for risky steps.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'action': {'type': 'STRING', 'enum': ['start', 'status', 'reply', 'stop']},
         'goal': {'type': 'STRING'}, 'id': {'type': 'STRING'}, 'approve': {'type': 'BOOLEAN'}, 'text': {'type': 'STRING'}},
         'required': ['action']},
     'handler': browser_agent, 'tier': 'core'},
]
