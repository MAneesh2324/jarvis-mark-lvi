"""Background learning while the app is open.

Every cycle (30 minutes by default) it:
  * refreshes multi-outlet news for the core categories and for the topics the
    user follows or keeps asking about, so answers start from warm, corroborated data;
  * refreshes ECB forex reference data and CISA known-exploited vulnerabilities;
  * forward-tests trading setups on watched markets (core.setup_tracker), so the
    analyser learns which setup types actually reach their targets;
  * writes a compact brief that is injected into each new voice session.

This is retrieval and outcome bookkeeping, not model training, and it never
acts on anything it reads.
"""
from pathlib import Path
from datetime import datetime, timezone
import json, threading, time

from core.mission_store import write_file

CONFIG = Path(__file__).resolve().parent.parent / 'config' / 'auto-learning.json'
STATE = Path(__file__).resolve().parent.parent / 'memory' / 'auto-learning-state.json'
BRIEF = Path(__file__).resolve().parent.parent / 'memory' / 'knowledge-brief.json'
DEFAULTS = {'enabled': False, 'interval_minutes': 30,
            'news_categories': ['forex', 'central_banks', 'world', 'business'],
            'trading_learning': True}
_lock = threading.Lock(); _running = False; _next = 0.0


def settings():
    try:
        data = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **data}


def configure(enabled=None, **changes):
    current = settings()
    if enabled is not None:
        current['enabled'] = bool(enabled)
    if 'interval_minutes' in changes and changes['interval_minutes'] is not None:
        current['interval_minutes'] = max(10, min(int(changes['interval_minutes']), 360))
    if changes.get('news_categories'):
        from core.news_engine import CATEGORIES
        current['news_categories'] = [c for c in changes['news_categories'] if c in CATEGORIES] or DEFAULTS['news_categories']
    if 'trading_learning' in changes and changes['trading_learning'] is not None:
        current['trading_learning'] = bool(changes['trading_learning'])
    CONFIG.parent.mkdir(exist_ok=True)
    write_file(CONFIG, json.dumps({k: current[k] for k in DEFAULTS}))
    return settings()


def state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {'state': 'not yet refreshed', 'note': 'No sources refreshed yet.'}


def headlines(topic='world', refresh=False):
    """Kept for knowledge_workspace: corroborated stories in the old item shape."""
    from core.news_engine import headlines as news
    data = news(topic, limit=10, refresh=refresh)
    return {'topic': topic, 'fetched_at': data['checked_at'],
            'items': [{'title': s['headline'], 'url': s['links'][0]['url'], 'published': s['latest_update'],
                       'outlets': s['outlets']} for s in data['stories']],
            'note': 'Attributed headlines grouped across outlets, not independently verified facts.'}


def _story_brief(stories, n):
    return [{'headline': s['headline'], 'outlets': s['outlet_count'], 'updated': s['latest_update']} for s in stories[:n]]


def refresh_all():
    from core import news_engine
    from core.forex_workspace import snapshot
    from core.cyber_workspace import kev
    cfg = settings()
    result = {'started': datetime.now(timezone.utc).isoformat(), 'sources': {}}
    brief = {}

    def run(name, fn):
        if not settings().get('enabled'):
            return None
        t0 = time.monotonic()
        try:
            value = fn()
            result['sources'][name] = {'ok': True, 'seconds': round(time.monotonic() - t0, 2)}
            return value
        except Exception as exc:
            result['sources'][name] = {'ok': False, 'error': str(exc)[:300]}
            return None

    news = {}
    for cat in cfg['news_categories']:
        value = run('news:' + cat, lambda cat=cat: news_engine.headlines(cat, limit=6, refresh=True))
        if value:
            news[cat] = _story_brief(value['stories'], 5 if cat == 'world' else 3)
            result['sources']['news:' + cat].update(stories=len(value['stories']), outlets_failed=value['outlets_failed'])
    if news:
        brief['news'] = news
    followed = {}
    for topic in news_engine.interests(4):
        value = run('topic:' + topic, lambda t=topic: news_engine.search(t, limit=3, within='1d', refresh=True, remember=False))
        if value and value['stories']:
            followed[topic] = _story_brief(value['stories'], 2)
    if followed:
        brief['followed_topics'] = followed
    cal = run('economic_calendar', lambda: news_engine.calendar(None, 'High', hours_ahead=36, refresh=False))
    if cal:
        brief['calendar'] = [f"{e['time_utc']} {e['currency']} {e['event']}" + (f" (f {e['forecast']}, p {e['previous']})"
                             if e.get('forecast') else '') for e in cal['events'] if e['status'] == 'upcoming'][:8]
    fx = run('forex', lambda: snapshot('EUR/USD'))
    if fx:
        brief['forex'] = {'pair': fx['pair'], 'as_of': fx['as_of'], 'latest': fx['analysis']['latest'],
                          'data_type': fx['data_type']}
    cyber = run('cybersecurity', lambda: kev(limit=5))
    if cyber:
        brief['cybersecurity'] = {'catalog_date': cyber.get('catalog_date'),
                                  'items': [f"{i.get('cveID')} {i.get('vendorProject', '')} {i.get('product', '')}".strip()
                                            for i in cyber.get('items', [])[:3]]}
    from core import self_learning
    sl = run('self_review', self_learning.review)
    if sl:
        result['sources']['self_review'].update(reviewed=sl.get('reviewed'), new_rules=len(sl.get('new_rules') or []))
        if sl.get('new_rules'):
            from core import notify
            notify.send('learning', 'I reviewed my recent mistakes and learned: ' + '; '.join(sl['new_rules'][:3]))
    from core import recall
    tl = run('memory_timeline', lambda: recall.extract_new(120))   # small batches keep each cycle short
    if tl:
        result['sources']['memory_timeline'].update(processed=tl.get('processed', 0), added=tl.get('added', 0))
    if cfg['trading_learning']:
        from core import setup_tracker
        tr = run('trading_learning', setup_tracker.cycle)
        if tr:
            result['sources']['trading_learning'].update(markets=len(tr['markets']), errors=tr['errors'])
            line = setup_tracker.context_line()
            if line:
                brief['trading_learning'] = line
    result['finished'] = datetime.now(timezone.utc).isoformat(); result['state'] = 'finished'
    STATE.parent.mkdir(exist_ok=True)
    write_file(STATE, json.dumps(result))
    write_file(BRIEF, json.dumps({'updated': result['finished'], 'sources': brief}, ensure_ascii=False))
    return result


def tick():
    global _running, _next
    cfg = settings()
    if not cfg.get('enabled'):
        return
    with _lock:
        if _running or time.monotonic() < _next:
            return
        _running = True; _next = time.monotonic() + 60 * cfg['interval_minutes']

    def work():
        global _running
        try:
            refresh_all()
        except Exception as exc:
            print(f'[AutoLearning] cycle failed: {exc}')
        finally:
            with _lock:
                _running = False
    threading.Thread(target=work, daemon=True, name='jarvis-public-learning').start()


def current():
    try:
        return json.loads(BRIEF.read_text())
    except (OSError, ValueError):
        return {'note': 'No automatic brief is available yet. Use the news or knowledge tools for current source data.'}


def context():
    """A short text brief for the start of a voice session. Full data stays behind the tools."""
    from core.outcome import untrusted
    data = current()
    src = data.get('sources')
    if not src:
        return ''
    lines = [f"Brief updated {data.get('updated', '')[:16].replace('T', ' ')} UTC."]
    for cat, stories in (src.get('news') or {}).items():
        lines.append(cat.upper() + ': ' + ' | '.join(f"{s['headline']} ({s['outlets']} outlets)" for s in stories))
    if src.get('calendar'):
        lines.append('HIGH-IMPACT EVENTS NEXT 36H: ' + ' | '.join(src['calendar']))
    for topic, stories in (src.get('followed_topics') or {}).items():
        lines.append(f"FOLLOWED '{topic}': " + ' | '.join(s['headline'] for s in stories))
    if src.get('forex'):
        f = src['forex']; lines.append(f"FOREX: {f['pair']} ECB reference {f['latest']} as of {f['as_of']} (daily reference, not live).")
    if src.get('trading_learning'):
        lines.append(src['trading_learning'])
    text = '\n'.join(lines)[:5000]
    return ('[AUTOMATIC BACKGROUND BRIEF — headlines grouped across outlets with outlet counts; not verified facts. '
            'For anything the user asks about, fetch fresh coverage with the news tool before answering.]\n'
            + untrusted('public-knowledge-brief', text))
