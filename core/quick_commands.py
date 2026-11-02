"""Read-only local keyboard commands. No provider requests or speech synthesis."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo

COMMANDS = {'/help', '/time', '/recall', '/history', '/perf'}


def recognizes(text):
    words = str(text).strip().split(maxsplit=1)
    return bool(words) and words[0].casefold() in COMMANDS


def run(text):
    words = str(text).strip().split(maxsplit=1)
    command = words[0].casefold()
    arg = words[1].strip() if len(words) > 1 else ''
    if command == '/time':
        now = datetime.now(ZoneInfo(arg)) if arg else datetime.now().astimezone()
        return 'LOCAL TIME', now.strftime('%A, %d %B %Y · %I:%M:%S %p %Z (UTC%z)')
    if command == '/recall':
        from memory.memory_manager import search_memory
        return 'LOCAL MEMORY', search_memory(arg, limit=12)
    if command == '/history':
        from memory.conversation_journal import search
        rows = search(arg, limit=8)
        return 'LOCAL CONVERSATION HISTORY', '\n\n'.join(f"{r['created']} · {r['role']}\n{r['text'][:2500]}" for r in reversed(rows)) or 'No matching saved conversations.'
    if command == '/perf':
        from core.performance import snapshot
        data = snapshot()
        lines = [f"{r['name']}: last {r['last_ms']:.0f} ms · median {r['median_ms']:.0f} ms · {r['samples']} samples" for r in data['timings']]
        return 'PERFORMANCE', ('\n'.join(lines) or 'No timing samples yet. Send a typed request or run a tool, then check again.') + '\n\n' + data['measurement']
    return 'INSTANT LOCAL COMMANDS', ('/time — current system-local time\n/time Asia/Kolkata — time in a named timezone\n/recall favorite person — search personal facts\n/history project — search saved conversations\n/perf — measured response and tool timings\n/missions — mission dashboard; /briefing — personal briefing; /earth — Earth globe\n/map — street map\n/satellite — satellite imagery\n/location — ask to use device location\n/help — this list\n/project — project workspace status\n/project NAME — activate a saved project\n/routine NAME — run a saved routine\n/local COMMAND — run a supported local command\n/localvoice on or off — local-only speech commands\n/screen permission — macOS capture setup\n/screen diagnose or check — screen troubleshooting\n/screen highlights — summarize the latest recording\n\nThese commands work without a model connection and display text without speaking. Ordinary messages still go to your conversation provider.')
