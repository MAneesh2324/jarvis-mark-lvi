"""Multi-source news: parallel RSS fetch, story clustering across outlets, search and article reading.

Accuracy comes from corroboration: a story is grouped across outlets by headline
similarity, and every result says how many independent outlets carry it, which
ones, and when. Feed text is untrusted content, never instructions.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

BASE = Path(__file__).resolve().parent.parent
INTERESTS = BASE / 'memory' / 'news-interests.json'
FEED_TTL = 900  # seconds; the background learner keeps this warm

FEEDS = {
    'forex': [
        ('FXStreet', 'https://www.fxstreet.com/rss/news'),
        ('FXStreet Analysis', 'https://www.fxstreet.com/rss/analysis'),
        ('investingLive', 'https://investinglive.com/feed'),
        ('Investing.com Forex', 'https://www.investing.com/rss/news_1.rss'),
        ('Investing.com Fundamentals', 'https://www.investing.com/rss/forex_Fundamental.rss'),
        ('Investing.com Indicators', 'https://www.investing.com/rss/news_95.rss'),
        ('FXEmpire', 'https://www.fxempire.com/api/v1/en/articles/rss/news'),
    ],
    'central_banks': [
        ('Federal Reserve', 'https://www.federalreserve.gov/feeds/press_all.xml'),
        ('ECB', 'https://www.ecb.europa.eu/rss/press.html'),
        ('Bank of England', 'https://www.bankofengland.co.uk/rss/news'),
        ('Bank of Japan', 'https://www.boj.or.jp/en/rss/whatsnew.xml'),
        ('Swiss National Bank', 'https://www.snb.ch/public/en/rss/news'),
        ('Bank of Canada', 'https://www.bankofcanada.ca/content_type/press-releases/feed/'),
        ('RBNZ', 'https://www.rbnz.govt.nz/feeds/news'),
    ],
    'world': [
        ('BBC', 'https://feeds.bbci.co.uk/news/world/rss.xml'),
        ('Al Jazeera', 'https://www.aljazeera.com/xml/rss/all.xml'),
        ('The Guardian', 'https://www.theguardian.com/world/rss'),
        ('NPR', 'https://feeds.npr.org/1004/rss.xml'),
        ('DW', 'https://rss.dw.com/rdf/rss-en-world'),
        ('France 24', 'https://www.france24.com/en/rss'),
        ('New York Times', 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml'),
        ('Sky News', 'https://feeds.skynews.com/feeds/rss/world.xml'),
    ],
    'business': [
        ('BBC', 'https://feeds.bbci.co.uk/news/business/rss.xml'),
        ('CNBC', 'https://www.cnbc.com/id/100727362/device/rss/rss.html'),
        ('The Guardian', 'https://www.theguardian.com/business/rss'),
        ('Economic Times', 'https://economictimes.indiatimes.com/rssfeedstopstories.cms'),
        ('Mint', 'https://www.livemint.com/rss/news'),
    ],
    'markets': [
        ('FXStreet', 'https://www.fxstreet.com/rss/news'),
        ('Investing.com', 'https://www.investing.com/rss/news_1.rss'),
        ('CNBC', 'https://www.cnbc.com/id/100727362/device/rss/rss.html'),
    ],
    'technology': [
        ('BBC', 'https://feeds.bbci.co.uk/news/technology/rss.xml'),
        ('The Verge', 'https://www.theverge.com/rss/index.xml'),
        ('Ars Technica', 'https://feeds.arstechnica.com/arstechnica/index'),
        ('The Guardian', 'https://www.theguardian.com/technology/rss'),
    ],
    'science': [
        ('BBC', 'https://feeds.bbci.co.uk/news/science_and_environment/rss.xml'),
        ('ScienceDaily', 'https://www.sciencedaily.com/rss/top/science.xml'),
        ('NASA', 'https://www.nasa.gov/feed/'),
    ],
    'india': [
        ('The Hindu', 'https://www.thehindu.com/news/national/feeder/default.rss'),
        ('Indian Express', 'https://indianexpress.com/section/india/feed/'),
        ('NDTV', 'https://feeds.feedburner.com/ndtvnews-top-stories'),
        ('Times of India', 'https://timesofindia.indiatimes.com/rssfeedstopstories.cms'),
    ],
}
CATEGORIES = tuple(FEEDS)

_STOP = set('''a an the and or but of to in on at for from by with as is are was were be been being it its this that these
those after before over under into about amid says say said new news live latest update updates more than up out
his her their they he she we you i not no will would could can may might has have had do does did how what why who
when where which there here just also vs v first last year years day days week amid against'''.split())


# ── fetching and parsing ────────────────────────────────────────────────────

def _local(tag):
    return tag.rsplit('}', 1)[-1].lower() if isinstance(tag, str) else ''


def _text(el, *names):
    for child in el:
        if _local(child.tag) in names:
            if _local(child.tag) == 'link' and not (child.text or '').strip():
                href = child.attrib.get('href')
                if href and child.attrib.get('rel', 'alternate') == 'alternate':
                    return href
                continue
            value = ''.join(child.itertext()).strip()
            if value:
                return value
    return ''


def _clean(text, limit):
    text = re.sub(r'<[^>]+>', ' ', html.unescape(text or ''))
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit].rstrip() + ('…' if len(text) > limit else '')


def _when(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(text: str, source: str, limit: int = 40) -> list[dict]:
    """RSS 2.0, RSS 1.0/RDF and Atom, into one article shape."""
    if '<!DOCTYPE' in text[:2000].upper() or '<!ENTITY' in text.upper():
        raise ValueError('Unexpected XML declarations in feed.')
    root = ET.fromstring(text.encode('utf-8') if isinstance(text, str) else text)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ('item', 'entry'):
            continue
        title = _clean(_text(el, 'title'), 300)
        link = _text(el, 'link', 'guid', 'id')
        if not title or not link.startswith('http'):
            continue
        outlet = source
        for child in el:
            if _local(child.tag) == 'source' and (child.text or '').strip():
                outlet = child.text.strip()  # aggregator feeds name the real outlet here
        if outlet != source and title.endswith(' - ' + outlet):
            title = title[: -len(' - ' + outlet)]
        out.append({'title': title, 'url': link.strip(), 'source': outlet,
                    'published': _when(_text(el, 'pubdate', 'published', 'updated', 'date', 'issued')),
                    'summary': _clean(_text(el, 'description', 'summary', 'content', 'encoded'), 320)})
        if len(out) >= limit:
            break
    return out


def _fetch(source, url, ttl=FEED_TTL, refresh=False):
    from core import intelligence_cache as cache
    data = cache.fetch(url, ttl=ttl, force=refresh)
    items = parse_feed(data['text'], source)
    for it in items:
        it['offline'] = bool(data.get('offline_fallback'))
    return items


def fetch_many(pairs, refresh=False, ttl=FEED_TTL, budget=12.0):
    """Fetch feeds in parallel; a slow or broken outlet never holds the rest up."""
    articles, failed = [], []
    pool = ThreadPoolExecutor(max_workers=min(10, max(1, len(pairs))))
    futures = {pool.submit(_fetch, s, u, ttl, refresh): s for s, u in pairs}
    try:
        for fut in as_completed(futures, timeout=budget):
            try:
                articles += fut.result()
            except Exception:
                failed.append(futures[fut])
    except Exception:
        failed += [s for f, s in futures.items() if not f.done()]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return articles, sorted(set(failed))


# ── clustering ──────────────────────────────────────────────────────────────

def _tokens(title):
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", title.lower())
    out = set()
    for w in words:
        w = w.replace("'s", '')
        if w in _STOP or len(w) < 3 and not w.isdigit():
            continue
        # A 6-letter prefix is a crude stem: africa/africans, election/elections, israel/israeli match.
        out.add(w if w.isdigit() else w[:6])
    return out


def _similar(a, b):
    if not a or not b:
        return False
    common = len(a & b)
    return common / len(a | b) >= 0.42 or (common >= 4 and common / min(len(a), len(b)) >= 0.6)


def cluster(articles: list[dict]) -> list[dict]:
    stories: list[dict] = []
    for art in sorted(articles, key=lambda a: a['published'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        tok = _tokens(art['title'])
        for st in stories:
            if _similar(tok, st['tokens']):
                st['articles'].append(art)
                st['tokens'] |= tok if len(st['tokens']) < 30 else set()
                break
        else:
            stories.append({'tokens': set(tok), 'articles': [art]})
    now = datetime.now(timezone.utc)
    out = []
    for st in stories:
        arts = st['articles']
        outlets = sorted({a['source'] for a in arts})
        times = [a['published'] for a in arts if a['published']]
        newest = max(times) if times else None
        age_h = (now - newest).total_seconds() / 3600 if newest else 48.0
        lead = min(arts, key=lambda a: (not a['summary'], len(a['title'])))
        out.append({
            'headline': lead['title'], 'summary': lead['summary'],
            'outlets': outlets, 'outlet_count': len(outlets),
            'corroboration': (f'reported by {len(outlets)} independent outlets' if len(outlets) > 1
                              else 'single source so far; treat details as unconfirmed'),
            'latest_update': newest.strftime('%Y-%m-%d %H:%M UTC') if newest else 'time not given',
            'age_hours': round(max(age_h, 0), 1),
            'links': [{'source': a['source'], 'url': a['url']} for a in arts[:4]],
            'offline_copy': all(a.get('offline') for a in arts),
            '_score': len(outlets) * 3 + max(0.0, 24 - age_h) / 6,
        })
    out.sort(key=lambda s: -s['_score'])
    return out


def _public(stories, limit):
    return [{k: v for k, v in s.items() if not k.startswith('_')} for s in stories[:limit]]


# ── public API ──────────────────────────────────────────────────────────────

def headlines(category='world', limit=8, refresh=False, max_age_hours=None) -> dict:
    category = str(category or 'world').lower()
    if max_age_hours is None:
        max_age_hours = 168 if category == 'central_banks' else 48  # banks publish rarely; a week stays relevant
    if category not in FEEDS:
        raise ValueError('Choose a category: ' + ', '.join(CATEGORIES) + '.')
    limit = max(1, min(int(limit or 8), 20))
    t0 = time.monotonic()
    articles, failed = fetch_many(FEEDS[category], refresh=refresh)
    if not articles:
        raise RuntimeError('No news source answered and nothing is cached yet.')
    fresh = [a for a in articles if not a['published'] or
             (datetime.now(timezone.utc) - a['published']).total_seconds() <= max_age_hours * 3600]
    stories = cluster(fresh or articles)
    return {'category': category, 'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'outlets_checked': len(FEEDS[category]), 'outlets_failed': failed, 'articles_read': len(articles),
            'seconds': round(time.monotonic() - t0, 2), 'stories': _public(stories, limit),
            'note': 'Ranked by how many independent outlets carry a story, then recency. Headlines and summaries are '
                    'the outlets\' own words; read the article for details before relying on them.'}


def search(query, limit=8, within='1d', refresh=False, region='IN', remember=True) -> dict:
    query = str(query or '').strip()
    if not 2 <= len(query) <= 200:
        raise ValueError('Give a search topic of 2 to 200 characters.')
    within = within if within in ('1h', '12h', '1d', '7d', '30d') else '1d'
    limit = max(1, min(int(limit or 8), 20))
    if remember:
        note_interest(query)
    t0 = time.monotonic()
    region = re.sub(r'[^A-Z]', '', str(region or 'IN').upper())[:2] or 'IN'
    gnews = (f'https://news.google.com/rss/search?q={quote_plus(query + " when:" + within)}'
             f'&hl=en-{region}&gl={region}&ceid={region}:en')
    pairs = [('Google News', gnews)]
    articles, failed = fetch_many(pairs, refresh=refresh, ttl=300, budget=10)
    # Our own outlet feeds, filtered to the query: catches stories aggregators have not indexed yet.
    want = _tokens(query) or {query.lower()}
    cached, _ = fetch_many([p for cat in FEEDS.values() for p in cat], ttl=FEED_TTL, budget=8)
    seen = {a['url'] for a in articles}
    for a in cached:
        hay = _tokens(a['title'] + ' ' + a['summary'])
        if a['url'] not in seen and len(want & hay) >= max(1, (len(want) + 1) // 2):
            articles.append(a); seen.add(a['url'])
    if len(articles) < 3:
        articles += _ddg_news(query)
    if not articles:
        return {'query': query, 'stories': [], 'note': 'No recent coverage found. Try a broader query or a longer window.'}
    stories = cluster(articles)
    return {'query': query, 'window': within, 'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'articles_found': len(articles), 'sources_failed': failed, 'seconds': round(time.monotonic() - t0, 2),
            'stories': _public(stories, limit),
            'note': 'Grouped across outlets; prefer stories with several outlets. Single-source claims are unconfirmed.'}


def _ddg_news(query):
    try:
        from ddgs import DDGS
        rows = DDGS().news(query, max_results=10) or []
    except Exception:
        return []
    out = []
    for r in rows:
        if r.get('title') and str(r.get('url', '')).startswith('http'):
            out.append({'title': _clean(r['title'], 300), 'url': r['url'], 'source': r.get('source') or 'web',
                        'published': _when(r.get('date')), 'summary': _clean(r.get('body', ''), 320)})
    return out


def read_article(url: str, max_chars=6000) -> dict:
    """Main text of one article, for detail and fact checks. Content is untrusted."""
    import requests
    from bs4 import BeautifulSoup
    url = str(url or '').strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Give a full http(s) article link.')
    if parsed.hostname.endswith('bing.com') and 'url' in parse_qs(parsed.query):
        url = parse_qs(parsed.query)['url'][0]
    host = urlparse(url).hostname or ''
    if host in ('localhost',) or re.fullmatch(r'(127|10|192\.168|169\.254)\..*', host) or host.endswith('.local'):
        raise ValueError('Only public web articles can be read.')
    resp = requests.get(url, timeout=(5, 15), headers={'User-Agent': 'Mozilla/5.0 (Macintosh) MarkLVI-Reader/1.0'},
                        allow_redirects=True)
    resp.raise_for_status()
    if 'html' not in resp.headers.get('content-type', 'text/html'):
        raise ValueError('That link is not a web page.')
    soup = BeautifulSoup(resp.text[:3_000_000], 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'noscript', 'figure']):
        tag.decompose()
    body = soup.find('article') or soup.find('main') or soup.body or soup
    paras = [p.get_text(' ', strip=True) for p in body.find_all('p')]
    text = '\n'.join(p for p in paras if len(p) > 40)
    title = (soup.title.string or '').strip() if soup.title and soup.title.string else ''
    meta_time = soup.find('meta', attrs={'property': 'article:published_time'})
    if len(text) < 200:
        return {'url': resp.url, 'title': title, 'text': '', 'note': 'The page did not expose readable article text '
                '(paywall, script-only page or aggregator redirect). Use another outlet from the story links.'}
    return {'url': resp.url, 'title': title, 'published': meta_time.get('content') if meta_time else None,
            'characters': len(text), 'text': text[:max_chars], 'truncated': len(text) > max_chars}


# ── economic calendar ───────────────────────────────────────────────────────

CALENDAR_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
FX_CCY = ('USD', 'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD', 'CNY')
IMPACTS = ('High', 'Medium', 'Low', 'Holiday')


def _calendar_rows(refresh=False):
    from core import intelligence_cache as cache
    # The publisher rate-limits; an hour-old copy is fine because the schedule rarely moves.
    data = cache.fetch(CALENDAR_URL, ttl=3600, force=refresh)
    rows = json.loads(data['text'])
    if not isinstance(rows, list):
        raise ValueError('Unexpected calendar format.')
    out = []
    for r in rows:
        when = _when(r.get('date'))
        if not when:
            continue
        out.append({'time_utc': when, 'currency': str(r.get('country', '')).upper(), 'event': _clean(r.get('title', ''), 120),
                    'impact': r.get('impact', ''), 'forecast': r.get('forecast') or None, 'previous': r.get('previous') or None})
    return out, data


def calendar(currencies=None, impact='High', hours_ahead=48, include_past_hours=0, refresh=False) -> dict:
    """Scheduled economic events for this week, e.g. NFP, CPI, rate decisions."""
    wanted = {c.strip().upper() for c in (currencies or []) if str(c).strip()} or set(FX_CCY)
    levels = {'High': ('High',), 'Medium': ('High', 'Medium'), 'Low': ('High', 'Medium', 'Low'),
              'All': IMPACTS}.get(str(impact or 'High').title(), ('High',))
    rows, data = _calendar_rows(refresh)
    now = datetime.now(timezone.utc)
    hours_ahead = max(1, min(int(hours_ahead or 48), 24 * 8))
    past = max(0, min(int(include_past_hours or 0), 24 * 8))
    events = []
    for r in rows:
        delta_h = (r['time_utc'] - now).total_seconds() / 3600
        if r['currency'] in wanted and r['impact'] in levels and -past <= delta_h <= hours_ahead:
            events.append({**r, 'time_utc': r['time_utc'].strftime('%a %Y-%m-%d %H:%M UTC'),
                           'in_hours': round(delta_h, 1), 'status': 'upcoming' if delta_h > 0 else 'released'})
    events.sort(key=lambda e: e['in_hours'])
    return {'source': 'ForexFactory weekly calendar (faireconomy mirror)', 'fetched_at': data.get('fetched_at'),
            'offline_copy': bool(data.get('offline_fallback')), 'currencies': sorted(wanted), 'impact': list(levels),
            'window_hours': [-past, hours_ahead], 'events': events[:60],
            'note': 'Times are UTC. Actual results are not in this feed; use news search right after a release. '
                    'Only this week is covered.'}


def news_risk(pair: str, hours=24) -> dict | None:
    """High-impact events for either currency of a forex pair in the next `hours`."""
    code = re.sub(r'[^A-Z]', '', str(pair).upper().replace('=X', ''))
    if len(code) != 6:
        return None
    ccys = [code[:3], code[3:]]
    try:
        cal = calendar(ccys, 'High', hours_ahead=hours)
    except Exception:
        return None
    ev = [{'event': e['event'], 'currency': e['currency'], 'time_utc': e['time_utc'], 'in_hours': e['in_hours']}
          for e in cal['events'] if e['status'] == 'upcoming']
    return {'high_impact_next_hours': hours, 'events': ev[:6],
            'warning': (f"{len(ev)} high-impact event(s) for {'/'.join(ccys)} within {hours}h; zones can be run through "
                        'on the release, spreads widen.') if ev else f'No high-impact {"/".join(ccys)} events in the next {hours}h.'}


# ── interests: what the user follows ────────────────────────────────────────

_ilock = threading.Lock()


def _load_interests():
    try:
        return json.loads(INTERESTS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'followed': [], 'searches': {}}


def _save_interests(data):
    from core.mission_store import write_file
    INTERESTS.parent.mkdir(parents=True, exist_ok=True)
    write_file(INTERESTS, json.dumps(data, ensure_ascii=False, indent=1))


def note_interest(query):
    key = ' '.join(sorted(_tokens(query)))[:80]
    if not key:
        return
    with _ilock:
        data = _load_interests()
        s = data.setdefault('searches', {})
        entry = s.get(key) or {'query': query[:120], 'count': 0}
        entry['count'] += 1
        entry['last'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        s[key] = entry
        if len(s) > 200:  # keep the most used
            data['searches'] = dict(sorted(s.items(), key=lambda kv: -kv[1]['count'])[:150])
        _save_interests(data)


def follow(topic, on=True):
    topic = re.sub(r'\s+', ' ', str(topic or '')).strip()[:120]
    if len(topic) < 2:
        raise ValueError('Name the topic to follow.')
    with _ilock:
        data = _load_interests()
        followed = [t for t in data.get('followed', []) if t.lower() != topic.lower()]
        if on:
            followed.append(topic)
        data['followed'] = followed[-12:]
        _save_interests(data)
    return {'followed': data['followed']}


def interests(limit=5):
    """Explicitly followed topics first, then topics searched at least twice."""
    data = _load_interests()
    learned = [v['query'] for v in sorted(data.get('searches', {}).values(), key=lambda v: (-v['count'], v.get('last', '')))
               if v['count'] >= 2]
    out = []
    for t in data.get('followed', []) + learned:
        if t.lower() not in (o.lower() for o in out):
            out.append(t)
    return out[:limit]


def interest_status():
    data = _load_interests()
    top = sorted(data.get('searches', {}).values(), key=lambda v: -v['count'])[:10]
    return {'followed': data.get('followed', []), 'most_searched': [{'query': v['query'], 'times': v['count']} for v in top],
            'watched_in_background': interests()}


def topic_counts(stories):
    """Most common words across story headlines: a cheap 'what is the world talking about' signal."""
    c = Counter()
    for s in stories:
        c.update(_tokens(s['headline']))
    return [w for w, n in c.most_common(12) if n > 1]
