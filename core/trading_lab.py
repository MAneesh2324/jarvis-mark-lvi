"""Trading lab: candle data, chart pattern detection, strategy playbook, backtests
and trading code generation.

Analysis of data the user points at. Nothing here connects to a broker or places
an order. Detection rules are mechanical approximations of discretionary
concepts (order blocks, breakers, FVGs, sweeps); results say what was found and
where, so the user can check them on their own chart.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import string
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).resolve().parent.parent
PLAYBOOK = Path(__file__).with_name('trading_playbook.json')
USER_PLAYBOOK = BASE / 'memory' / 'trading-playbook-user.json'
CODE_DIR = Path.home() / 'Desktop' / 'JARVIS Trading Code'

MIN_CANDLES = 60
MAX_CANDLES = 5000

# ── symbols and data ────────────────────────────────────────────────────────

FX = {'USD', 'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD', 'SEK', 'NOK', 'DKK', 'SGD',
      'HKD', 'ZAR', 'MXN', 'TRY', 'INR', 'CNH', 'CNY', 'PLN', 'HUF', 'CZK'}
CRYPTO = {'BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'ADA', 'DOGE', 'LTC', 'DOT', 'AVAX', 'LINK', 'TRX'}
SYMBOLS = {
    'XAUUSD': 'GC=F', 'GOLD': 'GC=F', 'XAGUSD': 'SI=F', 'SILVER': 'SI=F',
    'USOIL': 'CL=F', 'WTI': 'CL=F', 'OIL': 'CL=F', 'UKOIL': 'BZ=F', 'BRENT': 'BZ=F',
    'US30': '^DJI', 'DJ30': '^DJI', 'DOW': '^DJI', 'NAS100': '^NDX', 'US100': '^NDX',
    'NASDAQ': '^NDX', 'SPX500': '^GSPC', 'US500': '^GSPC', 'SPX': '^GSPC', 'SP500': '^GSPC',
    'GER40': '^GDAXI', 'DAX': '^GDAXI', 'UK100': '^FTSE', 'JP225': '^N225',
    'NIFTY': '^NSEI', 'NIFTY50': '^NSEI', 'BANKNIFTY': '^NSEBANK', 'SENSEX': '^BSESN',
    'DXY': 'DX-Y.NYB',
}
PROXY_NOTES = {
    'GC=F': 'Gold futures (COMEX), a proxy for spot XAUUSD; levels differ slightly from broker spot.',
    'SI=F': 'Silver futures, a proxy for spot XAGUSD.',
    'CL=F': 'WTI crude futures.', 'BZ=F': 'Brent crude futures.',
}
INTERVALS = ('1m', '2m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk', '1mo')
DEFAULT_RANGE = {'1m': '5d', '2m': '1mo', '5m': '1mo', '15m': '1mo', '30m': '1mo',
                 '1h': '3mo', '4h': '6mo', '1d': '2y', '1wk': '5y', '1mo': '10y'}
RANGES = ('1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max')


def normalize_symbol(symbol: str) -> str:
    raw = str(symbol or '').strip().upper()
    compact = re.sub(r'[\s/_]', '', raw)
    if not compact:
        raise ValueError('Name a symbol, such as EURUSD, XAUUSD, BTCUSD or AAPL.')
    if compact in SYMBOLS:
        return SYMBOLS[compact]
    if len(compact) == 6 and compact[:3] in FX and compact[3:] in FX and compact[:3] != compact[3:]:
        return compact + '=X'
    for quote_ccy in ('USDT', 'USD'):
        if compact.endswith(quote_ccy) and compact[:-len(quote_ccy)] in CRYPTO:
            return compact[:-len(quote_ccy)] + '-USD'
    if compact in CRYPTO:
        return compact + '-USD'
    if not re.fullmatch(r'[A-Z0-9^=.\-]{1,20}', compact):
        raise ValueError('That symbol has characters a market data symbol cannot contain.')
    return compact


def _yahoo_url(symbol: str, interval: str, range_: str) -> str:
    return ('https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe='=^.-')
            + '?interval=' + interval + '&range=' + range_ + '&includePrePost=false')


def parse_yahoo(text: str) -> tuple[list[dict], dict]:
    data = json.loads(text)
    chart = data.get('chart') or {}
    result = chart.get('result')
    if not result:
        err = chart.get('error') or {}
        raise ValueError('Market data source returned no candles: ' + str(err.get('description') or 'unknown symbol'))
    r = result[0]
    stamps = r.get('timestamp') or []
    q = ((r.get('indicators') or {}).get('quote') or [{}])[0]
    vols = q.get('volume') or [None] * len(stamps)
    candles = []
    for i, t in enumerate(stamps):
        try:
            o, h, l, c = (q[k][i] for k in ('open', 'high', 'low', 'close'))
        except (KeyError, IndexError, TypeError):
            continue
        if None in (o, h, l, c):
            continue
        o, h, l, c = float(o), float(h), float(l), float(c)
        if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
            continue
        candles.append({'t': int(t), 'o': o, 'h': max(h, o, c), 'l': min(l, o, c), 'c': c,
                        'v': float(vols[i] or 0) if i < len(vols) else 0.0})
    meta = r.get('meta') or {}
    return candles, {'currency': meta.get('currency'), 'exchange_timezone': meta.get('exchangeTimezoneName'),
                     'instrument_type': meta.get('instrumentType')}


def resample(candles: list[dict], seconds: int) -> list[dict]:
    out: list[dict] = []
    for c in candles:
        bucket = c['t'] - c['t'] % seconds
        if out and out[-1]['t'] == bucket:
            b = out[-1]
            b['h'] = max(b['h'], c['h']); b['l'] = min(b['l'], c['l']); b['c'] = c['c']; b['v'] += c['v']
        else:
            out.append({**c, 't': bucket})
    return out


def fetch_candles(symbol: str, interval: str = '1h', range_: str = '', refresh: bool = False) -> dict:
    from core import intelligence_cache as cache
    interval = str(interval or '1h').lower().replace('60m', '1h')
    if interval not in INTERVALS:
        raise ValueError('Choose an interval from ' + ', '.join(INTERVALS) + '.')
    range_ = str(range_ or DEFAULT_RANGE[interval]).lower()
    if range_ not in RANGES:
        raise ValueError('Choose a range from ' + ', '.join(RANGES) + '.')
    sym = normalize_symbol(symbol)
    source_interval = '60m' if interval in ('1h', '4h') else interval
    intraday = interval not in ('1d', '1wk', '1mo')
    data = cache.fetch(_yahoo_url(sym, source_interval, range_), ttl=60 if intraday else 1800, force=refresh)
    candles, meta = parse_yahoo(data['text'])
    if interval == '4h':
        candles = resample(candles, 4 * 3600)
    candles = candles[-MAX_CANDLES:]
    return {'symbol': sym, 'requested': str(symbol), 'interval': interval, 'range': range_,
            'source': 'Yahoo Finance chart data (delayed or indicative; not your broker feed)',
            'proxy_note': PROXY_NOTES.get(sym, ''), **meta, **cache.metadata(data), 'candles': candles}


_TIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y.%m.%d %H:%M', '%Y.%m.%d %H:%M:%S',
                 '%d/%m/%Y %H:%M', '%m/%d/%Y %H:%M', '%d.%m.%Y %H:%M:%S.%f', '%d.%m.%Y %H:%M',
                 '%Y-%m-%d', '%d/%m/%Y', '%Y.%m.%d')


def parse_time(value) -> int:
    text = str(value).strip()
    try:
        num = float(text)
        if math.isfinite(num) and num > 0:
            return int(num / 1000) if num > 1e12 else int(num)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        dt = None
        for fmt in _TIME_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError('Unrecognised time value in CSV: ' + text[:40])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def load_csv(path: str) -> dict:
    """OHLC from a CSV, such as TradingView's 'Export chart data'."""
    p = Path(os.path.expanduser(str(path or ''))).resolve()
    if not p.is_file():
        raise ValueError('CSV file not found: ' + str(p))
    if p.stat().st_size > 30_000_000:
        raise ValueError('CSV is larger than 30 MB; export a shorter range.')
    with p.open(newline='', encoding='utf-8-sig') as f:
        sample = f.read(4096); f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        fields = {(name or '').strip().lower(): name for name in (reader.fieldnames or [])}

        def col(*names):
            for n in names:
                if n in fields:
                    return fields[n]
            return None

        tcol = col('time', 'datetime', 'timestamp', 'date/time', 'date', 'gmt time', 'local time')
        dcol = fields.get('date') if tcol and tcol != fields.get('date') else None
        cols = {k: col(k, k[0]) for k in ('open', 'high', 'low', 'close')}
        vcol = col('volume', 'vol', 'tick volume', 'tickvol')
        if not tcol or None in cols.values():
            raise ValueError('CSV needs time, open, high, low and close columns.')
        candles = []
        for row in reader:
            try:
                stamp = (row[dcol] + ' ' + row[tcol]) if dcol and ':' in str(row[tcol]) and '-' not in str(row[tcol]) else row[tcol]
                o, h, l, c = (float(row[cols[k]]) for k in ('open', 'high', 'low', 'close'))
                v = float(row[vcol]) if vcol and row.get(vcol) not in (None, '', 'NaN') else 0.0
                t = parse_time(stamp)
            except (ValueError, TypeError, KeyError):
                continue
            if all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
                candles.append({'t': t, 'o': o, 'h': max(h, o, c), 'l': min(l, o, c), 'c': c, 'v': v})
    candles = sorted({c['t']: c for c in candles}.values(), key=lambda c: c['t'])[-MAX_CANDLES:]
    return {'symbol': p.stem, 'interval': _guess_interval(candles), 'source': 'CSV file ' + p.name,
            'path': str(p), 'candles': candles}


def _guess_interval(candles):
    if len(candles) < 3:
        return 'unknown'
    gaps = sorted(b['t'] - a['t'] for a, b in zip(candles, candles[1:]))
    g = gaps[len(gaps) // 2]
    for secs, name in ((60, '1m'), (300, '5m'), (900, '15m'), (1800, '30m'), (3600, '1h'),
                       (14400, '4h'), (86400, '1d'), (604800, '1wk')):
        if g <= secs:
            return name
    return '1mo'


def load(params: dict) -> dict:
    if params.get('csv_path'):
        data = load_csv(params['csv_path'])
    else:
        data = fetch_candles(params.get('symbol', ''), params.get('interval', '1h'),
                             params.get('range', ''), bool(params.get('refresh')))
    if len(data['candles']) < MIN_CANDLES:
        raise ValueError(f"Only {len(data['candles'])} candles available; need at least {MIN_CANDLES}. Use a longer range.")
    return data


# ── indicators ──────────────────────────────────────────────────────────────

def ema(values, n):
    out, prev, k = [], None, 2 / (n + 1)
    for i, v in enumerate(values):
        if i < n - 1:
            out.append(None); continue
        prev = sum(values[i - n + 1:i + 1]) / n if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n

    def value(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / l)

    out[n] = value(ag, al)
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = value(ag, al)
    return out


def atr(c, n=14):
    tr = [c[0]['h'] - c[0]['l']] + [max(x['h'] - x['l'], abs(x['h'] - p['c']), abs(x['l'] - p['c']))
                                     for p, x in zip(c, c[1:])]
    out = [None] * len(c)
    if len(c) < n:
        return out
    prev = sum(tr[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(c)):
        prev = (prev * (n - 1) + tr[i]) / n
        out[i] = prev
    return out


def macd(closes, fast=12, slow=26, signal=9):
    f, s = ema(closes, fast), ema(closes, slow)
    line = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig = [None] * start + ema(line[start:], signal) if start < len(line) else [None] * len(line)
    return line, sig


class Series:
    """Candles plus the indicator arrays every detector shares."""

    def __init__(self, candles, k=3):
        self.c = candles
        self.n = len(candles)
        self.k = max(1, min(int(k), 10))
        closes = [x['c'] for x in candles]
        self.atr = atr(candles)
        self.rsi = rsi(closes)
        self.ema20, self.ema50, self.ema200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
        ranges = sorted(x['h'] - x['l'] for x in candles)
        self.median_range = ranges[len(ranges) // 2] or 1e-9

    def a(self, i):
        """ATR at i, falling back to the median candle range early in the series."""
        v = self.atr[min(max(i, 0), self.n - 1)]
        return v if v else self.median_range


# ── detectors ───────────────────────────────────────────────────────────────

def swings(s: Series):
    out, c, k = [], s.c, s.k
    for i in range(k, s.n - k):
        h, l = c[i]['h'], c[i]['l']
        if h > max(x['h'] for x in c[i - k:i]) and h >= max(x['h'] for x in c[i + 1:i + k + 1]):
            out.append({'i': i, 'kind': 'high', 'price': h, 'confirmed': i + k})
        if l < min(x['l'] for x in c[i - k:i]) and l <= min(x['l'] for x in c[i + 1:i + k + 1]):
            out.append({'i': i, 'kind': 'low', 'price': l, 'confirmed': i + k})
    return out


def structure(s: Series, sw):
    last = {'high': None, 'low': None}
    for p in sw:
        prev = last[p['kind']]
        if p['kind'] == 'high':
            p['label'] = 'H' if prev is None else ('HH' if p['price'] > prev['price'] else 'LH')
        else:
            p['label'] = 'L' if prev is None else ('HL' if p['price'] > prev['price'] else 'LL')
        last[p['kind']] = p
    events, trend, ptr = [], None, 0
    active = {'high': None, 'low': None}
    ordered = sorted(sw, key=lambda p: (p['confirmed'], p['i']))
    for j, bar in enumerate(s.c):
        while ptr < len(ordered) and ordered[ptr]['confirmed'] <= j:
            active[ordered[ptr]['kind']] = ordered[ptr]; ptr += 1
        hi, lo = active['high'], active['low']
        if hi and bar['c'] > hi['price']:
            events.append({'type': 'CHoCH' if trend == 'down' else 'BOS', 'direction': 'bullish', 'i': j,
                           'level': hi['price'], 'swing_i': hi['i']})
            trend, active['high'] = 'up', None
        elif lo and bar['c'] < lo['price']:
            events.append({'type': 'CHoCH' if trend == 'up' else 'BOS', 'direction': 'bearish', 'i': j,
                           'level': lo['price'], 'swing_i': lo['i']})
            trend, active['low'] = 'down', None
    return events, trend


def order_blocks(s: Series, events):
    """Order blocks from structure breaks, and the breakers they become when they fail."""
    c, seen, blocks = s.c, set(), []
    for e in events:
        j, start = e['i'], e['swing_i']
        if e['direction'] == 'bullish':
            m = min(range(start, j + 1), key=lambda x: c[x]['l'])
            idx = next((x for x in range(m, max(m - 10, -1), -1) if c[x]['c'] < c[x]['o']), m)
        else:
            m = max(range(start, j + 1), key=lambda x: c[x]['h'])
            idx = next((x for x in range(m, max(m - 10, -1), -1) if c[x]['c'] > c[x]['o']), m)
        if idx in seen:
            continue
        seen.add(idx)
        blocks.append({'direction': e['direction'], 'i': idx, 'formed': j, 'low': c[idx]['l'],
                       'high': c[idx]['h'], 'from': e['type']})
    breakers = []
    for b in blocks:
        b.update(state='fresh', touched=None, broken=None)
        for x in range(b['formed'] + 1, s.n):
            bar = c[x]
            if b['direction'] == 'bullish':
                if bar['c'] < b['low']:
                    b['broken'] = x; break
                if b['touched'] is None and bar['l'] <= b['high']:
                    b['touched'] = x
            else:
                if bar['c'] > b['high']:
                    b['broken'] = x; break
                if b['touched'] is None and bar['h'] >= b['low']:
                    b['touched'] = x
        b['state'] = 'broken' if b['broken'] is not None else ('mitigated' if b['touched'] is not None else 'fresh')
        if b['broken'] is not None:
            breakers.append(_breaker(s, b))
    return blocks, breakers


def _breaker(s: Series, ob):
    c = s.c
    direction = 'bearish' if ob['direction'] == 'bullish' else 'bullish'
    br = {'direction': direction, 'low': ob['low'], 'high': ob['high'], 'ob_i': ob['i'], 'i': ob['broken'],
          'retests': 0, 'first_retest': None, 'first_retest_rejected': None, 'invalidated': None}
    inside = False
    for x in range(ob['broken'] + 1, s.n):
        bar = c[x]
        if direction == 'bearish':
            if bar['c'] > br['high']:
                br['invalidated'] = x; break
            touching = bar['h'] >= br['low']
            rejected = bar['c'] < br['low']
        else:
            if bar['c'] < br['low']:
                br['invalidated'] = x; break
            touching = bar['l'] <= br['high']
            rejected = bar['c'] > br['high']
        if touching and not inside:
            br['retests'] += 1
            if br['first_retest'] is None:
                br['first_retest'], br['first_retest_rejected'] = x, rejected
        inside = touching
    br['status'] = ('invalidated' if br['invalidated'] is not None else
                    'fresh, awaiting first retest' if br['retests'] == 0 else
                    f"retested {br['retests']}x")
    return br


def fvgs(s: Series):
    c, out = s.c, []
    for i in range(2, s.n):
        a, b = c[i - 2], c[i]
        min_size = 0.1 * s.a(i)
        if b['l'] > a['h'] and b['l'] - a['h'] >= min_size:
            out.append({'direction': 'bullish', 'i': i - 1, 'low': a['h'], 'high': b['l']})
        elif b['h'] < a['l'] and a['l'] - b['h'] >= min_size:
            out.append({'direction': 'bearish', 'i': i - 1, 'low': b['h'], 'high': a['l']})
    for g in out:
        g['state'] = 'unfilled'
        for x in range(g['i'] + 2, s.n):
            bar = c[x]
            if g['direction'] == 'bullish':
                if bar['l'] <= g['low']:
                    g['state'] = 'filled'; break
                if bar['l'] <= g['high']:
                    g['state'] = 'partly filled'
            else:
                if bar['h'] >= g['high']:
                    g['state'] = 'filled'; break
                if bar['h'] >= g['low']:
                    g['state'] = 'partly filled'
    return out


def sweeps(s: Series, sw):
    c, out = s.c, []
    for p in sw:
        for x in range(p['i'] + 1, s.n):
            bar = c[x]
            if p['kind'] == 'high' and bar['h'] > p['price']:
                if bar['c'] < p['price']:
                    out.append({'direction': 'bearish', 'i': x, 'level': p['price'], 'swing_i': p['i'],
                                'took': 'buy-side liquidity above swing high'})
                break
            if p['kind'] == 'low' and bar['l'] < p['price']:
                if bar['c'] > p['price']:
                    out.append({'direction': 'bullish', 'i': x, 'level': p['price'], 'swing_i': p['i'],
                                'took': 'sell-side liquidity below swing low'})
                break
    return sorted(out, key=lambda x: x['i'])


def equal_levels(s: Series, sw):
    out = []
    for kind in ('high', 'low'):
        pts = [p for p in sw if p['kind'] == kind]
        for a, b in zip(pts, pts[1:]):
            if abs(a['price'] - b['price']) <= 0.1 * s.a(b['i']):
                level = max(a['price'], b['price']) if kind == 'high' else min(a['price'], b['price'])
                later = s.c[b['i'] + 1:]
                taken = any(x['h'] > level for x in later) if kind == 'high' else any(x['l'] < level for x in later)
                out.append({'kind': 'equal highs' if kind == 'high' else 'equal lows', 'level': level,
                            'i': b['i'], 'taken': taken})
    return out


def key_levels(s: Series, sw, limit=8):
    price, tol = s.c[-1]['c'], 0.3 * s.a(s.n - 1)
    pts = sorted(sw, key=lambda p: p['price'])
    clusters: list[list[dict]] = []
    for p in pts:
        # Anchored to the cluster's first price, so zones cannot chain into one wide band.
        if clusters and p['price'] - clusters[-1][0]['price'] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = []
    for cl in clusters:
        if len(cl) < 2:
            continue
        lo, hi = min(p['price'] for p in cl), max(p['price'] for p in cl)
        last = max(p['i'] for p in cl)
        role = 'resistance' if lo > price else 'support' if hi < price else 'price is at this level'
        levels.append({'low': lo, 'high': hi, 'touches': len(cl), 'last_touch_i': last, 'role': role,
                       'strength': round(len(cl) + last / s.n, 2), 'distance_atr': round(_dist(price, lo, hi) / s.a(s.n - 1), 2)})
    levels.sort(key=lambda z: (z['distance_atr'], -z['strength']))
    return levels[:limit]


def _dist(price, lo, hi):
    return 0.0 if lo <= price <= hi else min(abs(price - lo), abs(price - hi))


def candle_patterns(s: Series, recent=30):
    c, out = s.c, []
    for i in range(max(2, s.n - recent), s.n):
        x, p, pp = c[i], c[i - 1], c[i - 2]
        rng = (x['h'] - x['l']) or 1e-12
        body = abs(x['c'] - x['o'])
        upper, lower = x['h'] - max(x['o'], x['c']), min(x['o'], x['c']) - x['l']
        pbody = abs(p['c'] - p['o'])
        found = []
        if p['c'] < p['o'] and x['c'] > x['o'] and x['c'] >= p['o'] and x['o'] <= p['c'] and body > pbody:
            found.append(('bullish engulfing', 'bullish'))
        if p['c'] > p['o'] and x['c'] < x['o'] and x['c'] <= p['o'] and x['o'] >= p['c'] and body > pbody:
            found.append(('bearish engulfing', 'bearish'))
        if lower >= 2 * body and upper <= 0.25 * rng and rng >= 0.5 * s.a(i):
            found.append(('hammer / bullish pin bar', 'bullish'))
        if upper >= 2 * body and lower <= 0.25 * rng and rng >= 0.5 * s.a(i):
            found.append(('shooting star / bearish pin bar', 'bearish'))
        if body <= 0.1 * rng and not found:
            found.append(('doji', 'neutral'))
        if x['h'] < p['h'] and x['l'] > p['l']:
            found.append(('inside bar', 'neutral'))
        ppbody, pprng = abs(pp['c'] - pp['o']), (pp['h'] - pp['l']) or 1e-12
        mid = (pp['o'] + pp['c']) / 2
        if pp['c'] < pp['o'] and ppbody > 0.5 * pprng and pbody < 0.5 * ppbody and x['c'] > x['o'] and x['c'] > mid:
            found.append(('morning star', 'bullish'))
        if pp['c'] > pp['o'] and ppbody > 0.5 * pprng and pbody < 0.5 * ppbody and x['c'] < x['o'] and x['c'] < mid:
            found.append(('evening star', 'bearish'))
        out += [{'pattern': name, 'bias': bias, 'i': i} for name, bias in found]
    return out


def chart_patterns(s: Series, sw):
    c, out = s.c, []
    highs = [p for p in sw if p['kind'] == 'high']
    lows = [p for p in sw if p['kind'] == 'low']

    def closes_beyond(start, level_at, below):
        for x in range(start, s.n):
            lvl = level_at(x)
            if (c[x]['c'] < lvl) if below else (c[x]['c'] > lvl):
                return x
        return None

    for pts, top in ((highs, True), (lows, False)):
        for a, b in zip(pts, pts[1:]):
            tol = 0.5 * s.a(b['i'])
            if abs(a['price'] - b['price']) > tol or b['i'] - a['i'] < 2 * s.k:
                continue
            between = c[a['i']:b['i'] + 1]
            neck = min(x['l'] for x in between) if top else max(x['h'] for x in between)
            height = abs((a['price'] + b['price']) / 2 - neck)
            if height < s.a(b['i']):
                continue
            hit = closes_beyond(b['i'] + 1, lambda x: neck, top)
            out.append({'pattern': 'double top' if top else 'double bottom', 'bias': 'bearish' if top else 'bullish',
                        'i': b['i'], 'start_i': a['i'], 'neckline': neck,
                        'state': 'confirmed (closed through neckline)' if hit is not None else 'forming (neckline not broken)',
                        'confirmed_i': hit, 'measured_target': neck - height if top else neck + height})
        for a, b, d in zip(pts, pts[1:], pts[2:]):
            head_out = b['price'] > max(a['price'], d['price']) if top else b['price'] < min(a['price'], d['price'])
            if not head_out or abs(a['price'] - d['price']) > s.a(d['i']):
                continue
            if abs(b['price'] - (a['price'] + d['price']) / 2) < 0.5 * s.a(b['i']):
                continue
            seg1, seg2 = c[a['i']:b['i'] + 1], c[b['i']:d['i'] + 1]
            if top:
                n1 = min(range(len(seg1)), key=lambda x: seg1[x]['l']); n2 = min(range(len(seg2)), key=lambda x: seg2[x]['l'])
                p1, v1, p2, v2 = a['i'] + n1, seg1[n1]['l'], b['i'] + n2, seg2[n2]['l']
            else:
                n1 = max(range(len(seg1)), key=lambda x: seg1[x]['h']); n2 = max(range(len(seg2)), key=lambda x: seg2[x]['h'])
                p1, v1, p2, v2 = a['i'] + n1, seg1[n1]['h'], b['i'] + n2, seg2[n2]['h']
            slope = (v2 - v1) / (p2 - p1) if p2 != p1 else 0.0
            level_at = lambda x, v1=v1, p1=p1, slope=slope: v1 + slope * (x - p1)
            hit = closes_beyond(d['i'] + 1, level_at, top)
            height = abs(b['price'] - level_at(b['i']))
            neck_now = level_at(s.n - 1)
            out.append({'pattern': 'head and shoulders' if top else 'inverse head and shoulders',
                        'bias': 'bearish' if top else 'bullish', 'i': d['i'], 'start_i': a['i'],
                        'neckline_now': neck_now,
                        'state': 'confirmed (closed through neckline)' if hit is not None else 'forming (neckline not broken)',
                        'confirmed_i': hit, 'measured_target': neck_now - height if top else neck_now + height})
    tri = _triangle(s, highs, lows)
    if tri:
        out.append(tri)
    return sorted(out, key=lambda p: p['i'])


def _slope(pts):
    xs, ys = [p['i'] for p in pts], [p['price'] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs) or 1
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def _triangle(s: Series, highs, lows):
    hs, ls = highs[-3:], lows[-3:]
    if len(hs) < 3 or len(ls) < 3 or s.n - 1 - max(hs[-1]['i'], ls[-1]['i']) > 40:
        return None
    a = s.a(s.n - 1)
    span = s.n - min(hs[0]['i'], ls[0]['i'])
    dh, dl = _slope(hs) * span, _slope(ls) * span
    flat_h, flat_l = abs(dh) < 0.5 * a, abs(dl) < 0.5 * a
    if flat_h and dl > 0.5 * a:
        name, bias = 'ascending triangle', 'bullish'
    elif flat_l and dh < -0.5 * a:
        name, bias = 'descending triangle', 'bearish'
    elif dh < -0.5 * a and dl > 0.5 * a:
        name, bias = 'symmetrical triangle', 'neutral (breakout direction decides)'
    else:
        return None
    return {'pattern': name, 'bias': bias, 'i': max(hs[-1]['i'], ls[-1]['i']), 'start_i': min(hs[0]['i'], ls[0]['i']),
            'upper_points': [p['price'] for p in hs], 'lower_points': [p['price'] for p in ls],
            'state': 'forming; wait for a close outside the triangle'}


def divergences(s: Series, sw):
    out = []
    for kind in ('high', 'low'):
        pts = [p for p in sw if p['kind'] == kind and s.rsi[p['i']] is not None]
        for a, b in zip(pts, pts[1:]):
            ra, rb = s.rsi[a['i']], s.rsi[b['i']]
            if kind == 'high' and b['price'] > a['price'] and rb < ra - 1:
                out.append({'type': 'regular bearish divergence', 'bias': 'bearish', 'i': b['i'], 'from_i': a['i'],
                            'rsi': [round(ra, 1), round(rb, 1)]})
            if kind == 'low' and b['price'] < a['price'] and rb > ra + 1:
                out.append({'type': 'regular bullish divergence', 'bias': 'bullish', 'i': b['i'], 'from_i': a['i'],
                            'rsi': [round(ra, 1), round(rb, 1)]})
    return sorted(out, key=lambda d: d['i'])


# ── analysis ────────────────────────────────────────────────────────────────

def _decimals(price):
    return max(2, min(6, 5 - int(math.floor(math.log10(abs(price) or 1)))))


def _when(c, i):
    return datetime.fromtimestamp(c[i]['t'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if i is not None else None


def _overlap(lo1, hi1, lo2, hi2, pad=0.0):
    return lo1 - pad <= hi2 and lo2 - pad <= hi1


def detect(candles, k=3):
    """Every detector over one candle list. Raw indexes; analyse() formats them."""
    s = Series(candles, k)
    sw = swings(s)
    events, trend = structure(s, sw)
    obs, brs = order_blocks(s, events)
    return {'series': s, 'swings': sw, 'events': events, 'trend': trend, 'order_blocks': obs,
            'breakers': brs, 'fvgs': fvgs(s), 'sweeps': sweeps(s, sw), 'equal_levels': equal_levels(s, sw),
            'key_levels': key_levels(s, sw), 'candles': candle_patterns(s), 'chart_patterns': chart_patterns(s, sw),
            'divergences': divergences(s, sw)}


def _summary(d):
    s = d['series']; c = s.c; i = s.n - 1; price = c[i]['c']
    highs = [p for p in d['swings'] if p['kind'] == 'high']
    lows = [p for p in d['swings'] if p['kind'] == 'low']
    rng = None
    if highs and lows:
        # The latest swing range, stretched by any price that has traded beyond it since.
        start = min(highs[-1]['i'], lows[-1]['i'])
        hi = max(highs[-1]['price'], max(x['h'] for x in c[start:]))
        lo = min(lows[-1]['price'], min(x['l'] for x in c[start:]))
        if hi > lo:
            pos = (price - lo) / (hi - lo)
            rng = {'swing_high': hi, 'swing_low': lo, 'position_percent': round(100 * pos, 1),
                   'zone': 'premium (upper half, favours sells)' if pos > 0.5 else 'discount (lower half, favours buys)'}
    e50, e200 = s.ema50[i], s.ema200[i]
    ema_bias = None
    if e50 is not None and e200 is not None:
        ema_bias = 'bullish' if price > e50 > e200 else 'bearish' if price < e50 < e200 else 'mixed'
    last_labels = [p['label'] for p in d['swings'][-6:]]
    return {'session': forex_session(c), 'price': price, 'as_of': _when(c, i), 'structure_trend': {'up': 'bullish', 'down': 'bearish'}.get(d['trend'], 'undetermined'),
            'recent_swing_labels': last_labels, 'ema50': e50, 'ema200': e200, 'ema_bias': ema_bias,
            'rsi14': round(s.rsi[i], 1) if s.rsi[i] is not None else None, 'atr14': s.a(i), 'dealing_range': rng}


SESSIONS = (('Sydney', 21, 6), ('Tokyo', 0, 9), ('London', 7, 16), ('New York', 12, 21))  # UTC, approximate (no DST shift)


def forex_session(c):
    """Open sessions at the last candle, and today's Asian range with whether London/NY swept it."""
    if len(c) < 3 or c[-1]['t'] - c[-2]['t'] >= 86400:
        return None
    last = datetime.fromtimestamp(c[-1]['t'], tz=timezone.utc)
    hour = last.hour
    open_now = [n for n, a, b in SESSIONS if (a <= hour < b if a < b else hour >= a or hour < b)]
    day0 = int(last.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    asia = [x for x in c if day0 <= x['t'] < day0 + 7 * 3600]
    out = {'open_sessions': open_now or ['between sessions'],
           'overlap': 'London/New York overlap: highest liquidity' if {'London', 'New York'} <= set(open_now) else None}
    if asia:
        hi, lo = max(x['h'] for x in asia), min(x['l'] for x in asia)
        after = [x for x in c if x['t'] >= day0 + 7 * 3600]
        out['asian_range'] = {'high': hi, 'low': lo,
                              'high_swept': any(x['h'] > hi for x in after) if after else None,
                              'low_swept': any(x['l'] < lo for x in after) if after else None,
                              'note': 'Asian session 00:00-07:00 UTC today; a London sweep of one side often precedes the move the other way.'}
    return out


def _setups(d, bias='both'):
    s = d['series']; c = s.c; last = s.n - 1; price = c[last]['c']; a = s.a(last)
    summ = _summary(d)
    trend = summ['structure_trend']
    zone_pos = (summ['dealing_range'] or {}).get('position_percent')
    candidates = []
    for br in d['breakers']:
        if br['invalidated'] is not None or br['retests'] > 1:
            continue
        candidates.append(('breaker block', br['direction'], br['low'], br['high'], br['i'], 3, br['status']))
    for ob in d['order_blocks']:
        if ob['state'] == 'fresh':
            candidates.append(('order block', ob['direction'], ob['low'], ob['high'], ob['formed'], 2, 'fresh, not yet revisited'))
    for g in d['fvgs']:
        if g['state'] == 'unfilled' and g['i'] > last - 120:
            candidates.append(('fair value gap', g['direction'], g['low'], g['high'], g['i'], 1, 'unfilled'))
    out = []
    for kind, direction, lo, hi, idx, base, status in candidates:
        sell = direction == 'bearish'
        if bias == 'sell' and not sell or bias == 'buy' and sell:
            continue
        dist = _dist(price, lo, hi) / a
        if dist > 3:
            continue
        if sell and hi < price - 0.5 * a:
            continue  # sell zone already below price: no longer overhead resistance
        if not sell and lo > price + 0.5 * a:
            continue  # buy zone above price: no longer support underneath
        factors = []
        for lvl in d['key_levels']:
            if _overlap(lo, hi, lvl['low'], lvl['high'], 0.2 * a):
                factors.append(f"overlaps key level ({lvl['touches']} touches)"); break
        if any(sw['direction'] == direction and idx - 30 <= sw['i'] <= idx for sw in d['sweeps']):
            factors.append('liquidity sweep before it formed')
        if kind != 'fair value gap' and any(g['direction'] == direction and g['state'] != 'filled'
                                            and _overlap(lo, hi, g['low'], g['high'], 0.3 * a) for g in d['fvgs']):
            factors.append('fair value gap next to the zone')
        if zone_pos is not None and ((sell and zone_pos > 50) or (not sell and zone_pos < 50)):
            factors.append('premium zone' if sell else 'discount zone')
        if (sell and trend == 'bearish') or (not sell and trend == 'bullish'):
            factors.append('agrees with market structure')
        if (sell and summ['ema_bias'] == 'bearish') or (not sell and summ['ema_bias'] == 'bullish'):
            factors.append('agrees with EMA 50/200')
        if any(p['bias'] == direction and p['i'] >= last - 3 and _dist(c[p['i']]['c'], lo, hi) <= 0.5 * a for p in d['candles']):
            factors.append('confirming candle pattern at the zone')
        if any(dv['bias'] == direction and dv['i'] >= last - 30 for dv in d['divergences']):
            factors.append('RSI divergence')
        buffer = 0.1 * a
        if sell:
            entry = lo if price < lo else price
            stop = hi + buffer
        else:
            entry = hi if price > hi else price
            stop = lo - buffer
        risk = abs(stop - entry) or a
        target = _next_liquidity(d, direction, entry) or (entry - 2 * risk if sell else entry + 2 * risk)
        rr = abs(target - entry) / risk
        out.append({'setup': f"{'bearish' if sell else 'bullish'} {kind}", 'direction': 'sell' if sell else 'buy',
                    'zone_low': lo, 'zone_high': hi, 'zone_status': status, 'formed': _when(c, idx),
                    'price_location': 'price is inside the zone' if lo <= price <= hi else f'{dist:.1f} ATR away',
                    'entry_idea': entry, 'stop_idea': stop, 'target_idea': target, 'reward_to_risk': round(rr, 2),
                    'invalidation': f"candle close {'above' if sell else 'below'} {round(hi if sell else lo, _decimals(price))}",
                    'confluence': factors, 'score': base + len(factors)})
    out.sort(key=lambda x: (-x['score'], x['price_location'] != 'price is inside the zone'))
    return out[:6]


def _next_liquidity(d, direction, entry):
    sw = d['swings']
    c = d['series'].c
    if direction == 'bearish':
        lows = [p['price'] for p in sw if p['kind'] == 'low' and p['price'] < entry
                and not any(x['l'] < p['price'] for x in c[p['i'] + 1:])]
        return max(lows) if lows else None
    highs = [p['price'] for p in sw if p['kind'] == 'high' and p['price'] > entry
             and not any(x['h'] > p['price'] for x in c[p['i'] + 1:])]
    return min(highs) if highs else None


def _fmt(obj, dec):
    if isinstance(obj, float):
        return round(obj, dec)
    if isinstance(obj, dict):
        return {k: _fmt(v, dec) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fmt(v, dec) for v in obj]
    return obj


def analyse(data: dict, k=3, bias='both', learn=True) -> dict:
    """Pattern report for one instrument and timeframe, compact enough for a voice reply.

    learn=True attaches the forward-tracked record of each setup type (core.setup_tracker)
    and lets a large enough record nudge the ranking."""
    candles = data['candles']
    if bias not in ('both', 'buy', 'sell'):
        raise ValueError('bias must be both, buy or sell.')
    d = detect(candles, k)
    setups = _setups(d, bias)
    if learn:
        from core import setup_tracker
        setups = setup_tracker.annotate(setups)
    risk = None
    if str(data.get('symbol', '')).endswith('=X') and learn:
        from core.news_engine import news_risk
        risk = news_risk(data['symbol'], 24)
    s, c = d['series'], candles
    last = s.n - 1
    when = lambda i: _when(c, i)
    report = {
        'instrument': data.get('symbol'), 'interval': data.get('interval'), 'source': data.get('source'),
        'proxy_note': data.get('proxy_note') or None, 'fetched_at': data.get('fetched_at'),
        'offline_fallback': data.get('offline_fallback'), 'candles_analysed': s.n,
        'first_candle': when(0), 'last_candle': when(last),
        'note': 'Mechanical pattern detection on closed and current candles. The last candle may still be open. '
                'Zones and ideas are for your own chart review, not a recommendation or an order.',
        'summary': _summary(d),
        'news_risk': risk,
        'setups_ranked': setups,
        'breaker_blocks': [{'direction': b['direction'], 'low': b['low'], 'high': b['high'], 'broke_at': when(b['i']),
                            'status': b['status'], 'first_retest': when(b['first_retest']),
                            'first_retest_rejected': b['first_retest_rejected']}
                           for b in d['breakers'][-6:]],
        'order_blocks_active': [{'direction': o['direction'], 'low': o['low'], 'high': o['high'], 'candle': when(o['i']),
                                 'state': o['state'], 'from': o['from']}
                                for o in d['order_blocks'] if o['state'] != 'broken'][-5:],
        'fair_value_gaps_open': [{'direction': g['direction'], 'low': g['low'], 'high': g['high'], 'at': when(g['i']),
                                  'state': g['state']} for g in d['fvgs'] if g['state'] != 'filled'][-5:],
        'structure_breaks': [{'type': e['type'], 'direction': e['direction'], 'level': e['level'], 'at': when(e['i'])}
                             for e in d['events'][-6:]],
        'liquidity_sweeps': [{'direction': x['direction'], 'level': x['level'], 'at': when(x['i']), 'took': x['took']}
                             for x in d['sweeps'][-5:]],
        'liquidity_pools': [{**{k2: v for k2, v in e.items() if k2 != 'i'}, 'at': when(e['i'])}
                            for e in d['equal_levels'] if not e['taken']][-4:],
        'key_levels': [{k2: v for k2, v in z.items() if k2 != 'last_touch_i'} | {'last_touch': when(z['last_touch_i'])}
                       for z in d['key_levels']],
        'chart_patterns': [{**{k2: v for k2, v in p.items() if k2 not in ('i', 'start_i', 'confirmed_i')},
                            'from': when(p['start_i']), 'to': when(p['i'])} for p in d['chart_patterns'][-4:]],
        'candle_patterns_last_5': [{'pattern': p['pattern'], 'bias': p['bias'], 'at': when(p['i'])}
                                   for p in d['candles'] if p['i'] >= last - 4],
        'rsi_divergences': [{'type': v['type'], 'at': when(v['i']), 'rsi': v['rsi']} for v in d['divergences'][-3:]],
    }
    return _fmt(report, _decimals(c[-1]['c']))


FX_PAIRS = ('EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'NZDUSD', 'USDCAD',
            'EURJPY', 'GBPJPY', 'EURGBP', 'AUDJPY', 'EURAUD', 'GBPAUD', 'CADJPY')


def scan(pairs=None, interval='1h', bias='both', top=8) -> dict:
    """Analyse many forex pairs in parallel and rank their best setups against each other."""
    from concurrent.futures import ThreadPoolExecutor
    pairs = [re.sub(r'[\s/_]', '', p).upper() for p in (pairs or FX_PAIRS)][:20]

    def one(pair):
        try:
            rep = analyse(fetch_candles(pair, interval), bias=bias, learn=False)
            best = rep['setups_ranked'][0] if rep['setups_ranked'] else None
            return {'pair': pair, 'price': rep['summary']['price'], 'trend': rep['summary']['structure_trend'],
                    'rsi14': rep['summary']['rsi14'], 'best_setup': best and {k: best[k] for k in (
                        'setup', 'direction', 'zone_low', 'zone_high', 'price_location', 'stop_idea', 'target_idea',
                        'reward_to_risk', 'confluence', 'score')}, 'last_candle': rep['last_candle']}
        except Exception as exc:
            return {'pair': pair, 'error': str(exc)[:160]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, pairs))
    ok = [r for r in rows if r.get('best_setup')]
    ok.sort(key=lambda r: (-r['best_setup']['score'], r['best_setup']['price_location'] != 'price is inside the zone'))
    try:
        from core.setup_tracker import annotate
        for r in ok:
            r['best_setup'] = annotate([dict(r['best_setup'])])[0]
    except Exception:
        pass
    events = None
    try:
        from core.news_engine import calendar
        events = [{k: e[k] for k in ('time_utc', 'currency', 'event', 'in_hours')}
                  for e in calendar(None, 'High', hours_ahead=24)['events'] if e['status'] == 'upcoming'][:8]
    except Exception:
        pass
    return {'interval': interval, 'bias': bias, 'pairs_scanned': len(pairs), 'ranked': ok[:top],
            'no_setup_near_price': [r['pair'] for r in rows if 'best_setup' in r and not r['best_setup']],
            'errors': {r['pair']: r['error'] for r in rows if 'error' in r},
            'high_impact_next_24h': events,
            'note': 'Best setup per pair, ranked by confluence score. Check each on your broker chart before acting.'}


# ── backtesting ─────────────────────────────────────────────────────────────

STRATEGIES = ('ema_cross', 'rsi_reversion', 'breakout', 'breaker_retest', 'sweep_mss_breaker')


def _signals(candles, strategy, p):
    s = Series(candles, p.get('swing_length', 3))
    c, n = s.c, s.n
    out = []
    atr_stop = float(p.get('atr_stop', 1.5))

    def at_next_open(i, direction):
        if i + 1 >= n:
            return
        entry = c[i + 1]['o']; risk = atr_stop * s.a(i)
        stop = entry - risk if direction == 'long' else entry + risk
        out.append({'i': i + 1, 'direction': direction, 'entry': entry, 'stop': stop})

    if strategy == 'ema_cross':
        fast, slow = int(p.get('fast', 20)), int(p.get('slow', 50))
        if not 1 < fast < slow <= 400:
            raise ValueError('Use 1 < fast < slow ≤ 400.')
        closes = [x['c'] for x in c]
        f, sl = ema(closes, fast), ema(closes, slow)
        for i in range(1, n):
            if None in (f[i], sl[i], f[i - 1], sl[i - 1]):
                continue
            if f[i - 1] <= sl[i - 1] and f[i] > sl[i]:
                at_next_open(i, 'long')
            elif f[i - 1] >= sl[i - 1] and f[i] < sl[i]:
                at_next_open(i, 'short')
    elif strategy == 'rsi_reversion':
        lo, hi = float(p.get('oversold', 30)), float(p.get('overbought', 70))
        r = s.rsi
        for i in range(1, n):
            if r[i] is None or r[i - 1] is None:
                continue
            if r[i - 1] < lo <= r[i]:
                at_next_open(i, 'long')
            elif r[i - 1] > hi >= r[i]:
                at_next_open(i, 'short')
    elif strategy == 'breakout':
        length = int(p.get('length', 20))
        if not 2 <= length <= 400:
            raise ValueError('Breakout length must be 2 to 400.')
        for i in range(length, n):
            window = c[i - length:i]
            if c[i]['c'] > max(x['h'] for x in window) and c[i - 1]['c'] <= max(x['h'] for x in c[max(0, i - 1 - length):i - 1] or window):
                at_next_open(i, 'long')
            elif c[i]['c'] < min(x['l'] for x in window) and c[i - 1]['c'] >= min(x['l'] for x in c[max(0, i - 1 - length):i - 1] or window):
                at_next_open(i, 'short')
    elif strategy == 'breaker_retest':
        sw = swings(s)
        events, _ = structure(s, sw)
        _, breakers = order_blocks(s, events)
        for br in breakers:
            x = br['first_retest']
            if x is None:
                continue
            buffer = 0.1 * s.a(br['i'])
            if br['direction'] == 'bearish':
                entry = br['low'] if c[x]['o'] < br['low'] else c[x]['o']
                stop = br['high'] + buffer
                if entry < stop:
                    out.append({'i': x, 'direction': 'short', 'entry': entry, 'stop': stop, 'limit': entry != c[x]['o']})
            else:
                entry = br['high'] if c[x]['o'] > br['high'] else c[x]['o']
                stop = br['low'] - buffer
                if entry > stop:
                    out.append({'i': x, 'direction': 'long', 'entry': entry, 'stop': stop, 'limit': entry != c[x]['o']})
    elif strategy == 'sweep_mss_breaker':
        out += _sweep_mss_breaker(s, swings(s), p)
    else:
        raise ValueError('Strategy must be one of ' + ', '.join(STRATEGIES) + '.')
    return sorted(out, key=lambda e: e['i'])


def _sweep_mss_breaker(s: Series, sw, p):
    """Liquidity sweep → market structure shift → breaker retest (the user's setup).

    Bearish (mirror for bullish):
      1. sweep   a candle wicks above a confirmed swing high and closes back below it
      2. MSS     within sweep_window candles, a candle CLOSES below the swing low that started the
                 leg up into the sweep, before price trades above the sweep high again
      3. breaker the bullish order block at that low (last down-close candle at/just before it)
                 has now failed: it is the bearish breaker zone
      4. entry   sell limit at the zone's low edge on the first return into it, within
                 retest_window candles of the shift; cancelled if price first goes above the sweep high
      5. stop    above the sweep high (stop_at=sweep, default) or above the zone (stop_at=breaker)
    Only information available at each candle is used: swings count once confirmed.
    """
    c, n = s.c, s.n
    sweep_window = int(p.get('sweep_window', 30))
    retest_window = int(p.get('retest_window', 40))
    stop_at = str(p.get('stop_at', 'sweep')).lower()
    if stop_at not in ('sweep', 'breaker'):
        raise ValueError('stop_at must be sweep or breaker.')
    out, used = [], set()
    for ev in sweeps(s, sw):
        x = ev['i']
        bearish = ev['direction'] == 'bearish'
        extreme = c[x]['h'] if bearish else c[x]['l']
        want = 'low' if bearish else 'high'
        base = max((q for q in sw if q['kind'] == want and q['confirmed'] <= x and q['i'] < x),
                   key=lambda q: q['i'], default=None)
        if base is None:
            continue
        # a shift needs price to have held the base from the base to the sweep; already broken is not a shift
        held = all((c[k]['c'] > base['price']) if bearish else (c[k]['c'] < base['price']) for k in range(base['i'] + 1, x + 1))
        if not held:
            continue
        mss = None
        for j in range(x + 1, min(n, x + 1 + sweep_window)):
            if (c[j]['h'] > extreme) if bearish else (c[j]['l'] < extreme):
                break                                        # the sweep extreme was taken: no shift
            if (c[j]['c'] < base['price']) if bearish else (c[j]['c'] > base['price']):
                mss = j
                break
        if mss is None:
            continue
        b = base['i']                                        # order block: last opposite candle at the base
        ob = next((k for k in range(b, max(b - 6, -1), -1)
                   if (c[k]['c'] < c[k]['o'] if bearish else c[k]['c'] > c[k]['o'])), b)
        if ob in used:
            continue
        lo, hi = c[ob]['l'], c[ob]['h']
        buffer = 0.1 * s.a(mss)
        for y in range(mss + 1, min(n, mss + 1 + retest_window)):
            bar = c[y]
            if (bar['h'] > extreme) if bearish else (bar['l'] < extreme):
                break                                        # invalidated before a retest
            if (bar['h'] >= lo) if bearish else (bar['l'] <= hi):
                if bearish:
                    entry = lo if bar['o'] < lo else bar['o']
                    stop = (extreme if stop_at == 'sweep' else hi) + buffer
                    ok = entry < stop
                else:
                    entry = hi if bar['o'] > hi else bar['o']
                    stop = (extreme if stop_at == 'sweep' else lo) - buffer
                    ok = entry > stop
                if ok:
                    used.add(ob)
                    out.append({'i': y, 'direction': 'short' if bearish else 'long', 'entry': entry, 'stop': stop,
                                'limit': entry != bar['o'], 'setup': {'sweep_i': x, 'swept_level': ev['level'],
                                'mss_i': mss, 'zone': [lo, hi]}})
                break
    return out


def _curve(rs, limit=300):
    """[[trade number, cumulative R], …] starting at 0, thinned evenly so it stays small."""
    pts, total = [[0, 0.0]], 0.0
    for i, r in enumerate(rs, 1):
        total += r
        pts.append([i, round(total, 3)])
    if len(pts) > limit:
        step = (len(pts) - 1) / (limit - 1)
        pts = [pts[round(k * step)] for k in range(limit)]
    return pts


def backtest(data: dict, strategy: str, side='both', rr=2.0, max_hold=0, from_time=None, account_balance=None,
             risk_percent=1.0, risk_amount=None, spread=0.0, commission=0.0, compound=False, **params) -> dict:
    """Trades on the candles. Structure uses all the data; only entries at or after from_time are traded.

    Money: each trade risks risk_amount, or risk_percent of the balance (of the start balance unless
    compound). spread (price units) is paid once per trade and lowers its R; commission is money per trade.
    """
    candles = data['candles']
    rr = float(rr)
    spread, commission = max(0.0, float(spread or 0)), max(0.0, float(commission or 0))
    balance0 = float(account_balance) if account_balance not in (None, '', 0) else None
    if balance0 is not None and balance0 <= 0:
        raise ValueError('Account balance must be above zero.')
    risk_percent = float(risk_percent or 1.0)
    if not 0 < risk_percent <= 100:
        raise ValueError('Risk per trade must be between 0 and 100 percent.')
    if not 0.2 <= rr <= 20:
        raise ValueError('Reward-to-risk must be between 0.2 and 20.')
    if side not in ('both', 'long', 'short', 'buy', 'sell'):
        raise ValueError('side must be both, long or short.')
    side = {'buy': 'long', 'sell': 'short'}.get(side, side)
    max_hold = int(max_hold or 0)
    c, n = candles, len(candles)
    trades, busy_until = [], -1
    for e in _signals(candles, strategy, params):
        if e['i'] <= busy_until or (side != 'both' and e['direction'] != side):
            continue
        if from_time and c[e['i']]['t'] < from_time:
            continue
        long = e['direction'] == 'long'
        risk = abs(e['entry'] - e['stop'])
        if risk <= 0:
            continue
        target = e['entry'] + rr * risk if long else e['entry'] - rr * risk
        result, exit_i, exit_px = None, None, None
        for x in range(e['i'], n):
            bar = c[x]
            stop_hit = bar['l'] <= e['stop'] if long else bar['h'] >= e['stop']
            tgt_hit = bar['h'] >= target if long else bar['l'] <= target
            if x == e['i'] and e.get('limit'):
                tgt_hit = False  # a limit fill inside this candle: the target may have traded before the fill
            if stop_hit:  # stop first when both land in one candle: the conservative reading
                result, exit_i, exit_px = -1.0, x, e['stop']; break
            if tgt_hit:
                result, exit_i, exit_px = rr, x, target; break
            if max_hold and x - e['i'] + 1 >= max_hold:
                exit_px = bar['c']
                result, exit_i = ((exit_px - e['entry']) if long else (e['entry'] - exit_px)) / risk, x; break
        if result is None:
            trades.append({**e, 'target': target, 'open': True}); busy_until = n
            continue
        trades.append({**e, 'target': target, 'exit_i': exit_i, 'exit': exit_px, 'r': round(result, 3), 'open': False})
        busy_until = exit_i
    closed = [t for t in trades if not t['open']]
    dec = _decimals(c[-1]['c'])
    balance, money_curve, peak_m, dd_m = balance0, [[0, balance0]] if balance0 else [], balance0 or 0.0, 0.0
    blown = None
    for t in closed:                                         # costs and money, trade by trade
        cost_r = spread / abs(t['entry'] - t['stop']) if spread else 0.0
        t['gross_r'] = t['r']
        t['r'] = round(t['r'] - cost_r, 3)
        if balance0 is not None:
            if blown is not None:                            # an empty account takes no more trades
                t['risk'], t['pnl'], t['balance'] = 0.0, 0.0, 0.0
                continue
            risk_money = float(risk_amount) if risk_amount else (balance if compound else balance0) * risk_percent / 100
            t['risk'] = round(risk_money, 2)
            t['pnl'] = round(max(t['r'] * risk_money - commission, -balance), 2)    # cannot lose more than is there
            balance += t['pnl']
            if balance <= 0.005:
                balance, blown = 0.0, len(money_curve)
            t['balance'] = round(balance, 2)
            peak_m = max(peak_m, balance)
            dd_m = max(dd_m, peak_m - balance)
            money_curve.append([len(money_curve), round(balance, 2)])
    rs = [t['r'] for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    equity, peak, dd, streak, worst = 0.0, 0.0, 0.0, 0, 0
    for r in rs:
        equity += r; peak = max(peak, equity); dd = max(dd, peak - equity)
        streak = streak + 1 if r <= 0 else 0; worst = max(worst, streak)
    when = lambda i: _when(c, i)
    window = [when(next((i for i in range(n) if c[i]['t'] >= from_time), n - 1)) if from_time else when(0), when(n - 1)]
    stats = {'strategy': strategy, 'instrument': data.get('symbol'), 'interval': data.get('interval'),
             'source': data.get('source'), 'period': window, 'candles': n,
             'proxy_note': data.get('proxy_note') or None, 'requested': data.get('requested'),
             'settings': {'side': side, 'reward_to_risk': rr, 'max_hold_candles': max_hold or None,
                          'spread': spread or None, 'commission': commission or None,
                          'account_balance': balance0, 'risk_per_trade': (f'{risk_amount} per trade' if risk_amount else
                                                                          f'{risk_percent}%' + (' compounding' if compound else '')) if balance0 else None,
                          **{k: v for k, v in params.items() if v is not None}},
             'closed_trades': len(rs), 'wins': len(wins), 'losses': len(losses),
             'win_rate_percent': round(100 * len(wins) / len(rs), 1) if rs else None,
             'total_r': round(sum(rs), 2), 'average_r_per_trade': round(sum(rs) / len(rs), 3) if rs else None,
             'profit_factor': round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
             'max_drawdown_r': round(dd, 2), 'longest_losing_streak': worst,
             'equity_curve_r': _curve(rs),
             'money': ({'start_balance': balance0, 'end_balance': round(balance, 2),
                        'net_pnl': round(balance - balance0, 2), 'return_percent': round(100 * (balance - balance0) / balance0, 2),
                        'gross_profit': round(sum(t['pnl'] for t in closed if t['pnl'] > 0), 2),
                        'gross_loss': round(sum(t['pnl'] for t in closed if t['pnl'] <= 0), 2),
                        'largest_win': max((t['pnl'] for t in closed if t['pnl'] > 0), default=0),
                        'largest_loss': min((t['pnl'] for t in closed if t['pnl'] <= 0), default=0),
                        'max_drawdown': round(dd_m, 2), 'curve': money_curve[:301],
                        'account_blown_at_trade': blown,
                        'risk_warning': (f'Risking {risk_amount} on a {balance0:g} account is {100 * float(risk_amount) / balance0:.0f}% '
                                         'per trade; one loss can empty it.' if risk_amount and float(risk_amount) >= balance0 * .1 else None)}
                       if balance0 is not None else None),
             'trades': [{'n': k, 'direction': t['direction'], 'entry_time': when(t['i']), 'exit_time': when(t['exit_i']),
                         'entry': round(t['entry'], dec), 'stop': round(t['stop'], dec), 'target': round(t['target'], dec),
                         'exit': round(t['exit'], dec), 'r': t['r'],
                         'result': 'win' if t['r'] > 0 else 'loss',
                         **({'pnl': t['pnl'], 'balance': t['balance']} if 'pnl' in t else {})}
                        for k, t in enumerate(closed, 1)],
             'longs': sum(1 for t in closed if t['direction'] == 'long'),
             'shorts': sum(1 for t in closed if t['direction'] == 'short'),
             'open_trade': next(({'direction': t['direction'], 'entry': round(t['entry'], dec), 'stop': round(t['stop'], dec),
                                  'target': round(t['target'], dec), 'since': when(t['i'])} for t in trades if t['open']), None),
             'last_trades': [{'direction': t['direction'], 'entry_time': when(t['i']), 'entry': round(t['entry'], dec),
                              'stop': round(t['stop'], dec), 'exit_time': when(t['exit_i']), 'r': t['r']} for t in closed[-8:]],
             'reliability': ('Too few trades to judge; aim for 30+ before trusting the numbers.' if len(rs) < 30 else
                             'Enough trades for a first read; still check other symbols and periods.'),
             'assumptions': 'Results in R (1R = amount risked)' + (f', after a spread of {spread}' if spread else ', no spread')
                            + (f' and {commission} commission per trade' if commission else '') + '. No slippage or swap. '
                            'If stop and target fall in the same candle the stop is counted. Past results do not predict future ones.'}
    return stats


# ── playbook ────────────────────────────────────────────────────────────────

def _load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _all_entries():
    user = _load_json(USER_PLAYBOOK, {'entries': []}).get('entries', [])
    built = _load_json(PLAYBOOK, {'entries': []}).get('entries', [])
    return [dict(e, source='your saved strategy') for e in user] + [dict(e, source='built-in playbook') for e in built]


def playbook(query: str = '') -> dict:
    entries = _all_entries()
    q = str(query or '').strip().lower()
    if not q:
        return {'topics': [{'id': e['id'], 'name': e['name'], 'kind': e.get('kind', 'note'), 'source': e['source']}
                           for e in entries],
                'note': 'Ask for any topic by name for its full rules.'}
    words = [w for w in re.findall(r'[a-z0-9/]+', q) if len(w) > 2]

    def score(e):
        names = [e['id'].replace('_', ' '), e['name'].lower()] + [a.lower() for a in e.get('aliases', [])]
        val = 0
        for n in names:
            if n and (n in q or q in n):
                val += 10 if n == q else 5
        hay = json.dumps(e).lower()
        val += sum(1 for w in words if w in hay)
        return val

    ranked = sorted(((score(e), e) for e in entries), key=lambda x: -x[0])
    hits = [e for sc, e in ranked if sc > 0][:3]
    if not hits:
        return {'matches': [], 'note': 'No playbook entry matches. Ask for the topic list, or save your own strategy.'}
    return {'matches': hits}


def save_strategy(name: str, rules: str, aliases=None, notes: str = '') -> dict:
    name, rules = str(name or '').strip(), str(rules or '').strip()
    if not 2 <= len(name) <= 120 or not 10 <= len(rules) <= 6000:
        raise ValueError('Give the strategy a name (2-120 characters) and its rules (10-6000 characters).')
    data = _load_json(USER_PLAYBOOK, {'entries': []})
    sid = 'user_' + re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:60]
    entry = {'id': sid, 'name': name, 'kind': 'my strategy',
             'aliases': [str(a).strip().lower() for a in (aliases or []) if str(a).strip()][:12],
             'rules': [line.strip() for line in rules.splitlines() if line.strip()], 'notes': str(notes or '')[:2000],
             'saved': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    data['entries'] = [e for e in data.get('entries', []) if e.get('id') != sid] + [entry]
    USER_PLAYBOOK.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_PLAYBOOK.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.chmod(tmp, 0o600)
    os.replace(tmp, USER_PLAYBOOK)
    return {'saved': entry, 'path': str(USER_PLAYBOOK), 'total_saved_strategies': len(data['entries'])}


def delete_strategy(name: str) -> dict:
    data = _load_json(USER_PLAYBOOK, {'entries': []})
    key = str(name or '').strip().lower()
    keep = [e for e in data.get('entries', []) if key not in (e['id'], e['name'].lower(), 'user_' + key.replace(' ', '_'))]
    removed = len(data.get('entries', [])) - len(keep)
    if not removed:
        raise ValueError('No saved strategy with that name.')
    data['entries'] = keep
    USER_PLAYBOOK.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return {'removed': removed, 'remaining': len(keep)}


# ── code generation ─────────────────────────────────────────────────────────

_PINE_HEAD = '''//@version=5
strategy("$title", overlay=true, initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=10, commission_type=strategy.commission.percent, commission_value=0.0)
// Written by JARVIS trading lab. Test on a demo account before any real use.
rr = input.float($rr, "Reward to risk", minval=0.2, step=0.1)
side = input.string("$side", "Direction", options=["Both", "Long only", "Short only"])
longOk = side != "Short only"
shortOk = side != "Long only"
atr = ta.atr(14)
'''

PINE = {
    'ema_cross': _PINE_HEAD + '''fastLen = input.int($fast, "Fast EMA", minval=1)
slowLen = input.int($slow, "Slow EMA", minval=2)
atrMult = input.float($atr_stop, "Stop (ATR multiple)", minval=0.1, step=0.1)
fastEma = ta.ema(close, fastLen)
slowEma = ta.ema(close, slowLen)
plot(fastEma, "Fast EMA", color=color.aqua)
plot(slowEma, "Slow EMA", color=color.orange)
if ta.crossover(fastEma, slowEma) and longOk and strategy.position_size == 0
    stopDist = atr * atrMult
    strategy.entry("Long", strategy.long)
    strategy.exit("Long exit", "Long", stop=close - stopDist, limit=close + stopDist * rr)
if ta.crossunder(fastEma, slowEma) and shortOk and strategy.position_size == 0
    stopDist = atr * atrMult
    strategy.entry("Short", strategy.short)
    strategy.exit("Short exit", "Short", stop=close + stopDist, limit=close - stopDist * rr)
''',
    'rsi_reversion': _PINE_HEAD + '''rsiLen = input.int(14, "RSI length", minval=2)
oversold = input.float($oversold, "Oversold")
overbought = input.float($overbought, "Overbought")
atrMult = input.float($atr_stop, "Stop (ATR multiple)", minval=0.1, step=0.1)
r = ta.rsi(close, rsiLen)
if ta.crossover(r, oversold) and longOk and strategy.position_size == 0
    stopDist = atr * atrMult
    strategy.entry("Long", strategy.long)
    strategy.exit("Long exit", "Long", stop=close - stopDist, limit=close + stopDist * rr)
if ta.crossunder(r, overbought) and shortOk and strategy.position_size == 0
    stopDist = atr * atrMult
    strategy.entry("Short", strategy.short)
    strategy.exit("Short exit", "Short", stop=close + stopDist, limit=close - stopDist * rr)
plotshape(ta.crossover(r, oversold), "RSI up", shape.triangleup, location.belowbar, color.green)
plotshape(ta.crossunder(r, overbought), "RSI down", shape.triangledown, location.abovebar, color.red)
''',
    'breakout': _PINE_HEAD + '''rangeLen = input.int($length, "Range length", minval=2)
atrMult = input.float($atr_stop, "Stop (ATR multiple)", minval=0.1, step=0.1)
hh = ta.highest(high, rangeLen)[1]
ll = ta.lowest(low, rangeLen)[1]
plot(hh, "Range high", color=color.green)
plot(ll, "Range low", color=color.red)
if close > hh and close[1] <= hh[1] and longOk and strategy.position_size == 0
    stopDist = atr * atrMult
    strategy.entry("Long", strategy.long)
    strategy.exit("Long exit", "Long", stop=close - stopDist, limit=close + stopDist * rr)
if close < ll and close[1] >= ll[1] and shortOk and strategy.position_size == 0
    stopDist = atr * atrMult
    strategy.entry("Short", strategy.short)
    strategy.exit("Short exit", "Short", stop=close + stopDist, limit=close - stopDist * rr)
''',
    'breaker_retest': _PINE_HEAD + '''pivLen = input.int($swing_length, "Swing length", minval=1)
bufMult = input.float(0.1, "Stop buffer (ATR multiple)", minval=0.0, step=0.05)
ph = ta.pivothigh(high, pivLen, pivLen)
pl = ta.pivotlow(low, pivLen, pivLen)
var float swingHigh = na
var float swingLow = na
if not na(ph)
    swingHigh := ph
if not na(pl)
    swingLow := pl
// most recent down and up candles (order block candidates)
var float downHi = na
var float downLo = na
var float upHi = na
var float upLo = na
// live order blocks
var float bullObHi = na
var float bullObLo = na
var float bearObHi = na
var float bearObLo = na
// breakers: failed order blocks
var float bearBrkHi = na
var float bearBrkLo = na
var int bearBrkBar = na
var bool bearBrkLive = false
var float bullBrkHi = na
var float bullBrkLo = na
var int bullBrkBar = na
var bool bullBrkLive = false
// structure breaks create order blocks
if not na(swingHigh) and close > swingHigh
    bullObHi := downHi
    bullObLo := downLo
    swingHigh := na
if not na(swingLow) and close < swingLow
    bearObHi := upHi
    bearObLo := upLo
    swingLow := na
// a close through an order block turns it into a breaker
if not na(bullObLo) and close < bullObLo
    bearBrkHi := bullObHi
    bearBrkLo := bullObLo
    bearBrkBar := bar_index
    bearBrkLive := true
    bullObHi := na
    bullObLo := na
if not na(bearObHi) and close > bearObHi
    bullBrkHi := bearObHi
    bullBrkLo := bearObLo
    bullBrkBar := bar_index
    bullBrkLive := true
    bearObHi := na
    bearObLo := na
// invalidation
if bearBrkLive and close > bearBrkHi
    bearBrkLive := false
if bullBrkLive and close < bullBrkLo
    bullBrkLive := false
// first retest entries
if bearBrkLive and bar_index > bearBrkBar and high >= bearBrkLo and close < bearBrkHi
    if shortOk and strategy.position_size == 0
        stopPx = bearBrkHi + atr * bufMult
        strategy.entry("Breaker short", strategy.short)
        strategy.exit("Short exit", "Breaker short", stop=stopPx, limit=close - (stopPx - close) * rr)
    bearBrkLive := false
if bullBrkLive and bar_index > bullBrkBar and low <= bullBrkHi and close > bullBrkLo
    if longOk and strategy.position_size == 0
        stopPx = bullBrkLo - atr * bufMult
        strategy.entry("Breaker long", strategy.long)
        strategy.exit("Long exit", "Breaker long", stop=stopPx, limit=close + (close - stopPx) * rr)
    bullBrkLive := false
// remember candles after this bar's checks, so a structure break uses the candle before it
if close < open
    downHi := high
    downLo := low
if close > open
    upHi := high
    upLo := low
plot(bearBrkLive ? bearBrkHi : na, "Bearish breaker high", color=color.red, style=plot.style_linebr)
plot(bearBrkLive ? bearBrkLo : na, "Bearish breaker low", color=color.red, style=plot.style_linebr)
plot(bullBrkLive ? bullBrkHi : na, "Bullish breaker high", color=color.green, style=plot.style_linebr)
plot(bullBrkLive ? bullBrkLo : na, "Bullish breaker low", color=color.green, style=plot.style_linebr)
''',
}

_CODE_SYSTEM = (
    'You write trading code for a retail trader. Return ONLY the code in one block, no explanation outside comments. '
    'Pine Script: use //@version=5, compile-clean syntax, inputs for every number, strategy() when entries/exits are '
    'requested otherwise indicator(), no repainting (no future references, pivots confirmed with right bars). '
    'Python: standard library plus optional pandas/numpy only, read OHLC from a CSV path given on the command line '
    '(columns time,open,high,low,close), no broker or exchange order placement, no network calls unless asked, '
    'include a main() and print clear results. MQL5: compile-clean Expert Advisor or indicator. Comment the logic briefly.'
)
LANG_EXT = {'pine': '.pine', 'python': '.py', 'mql5': '.mq5', 'mql4': '.mq4'}


def _safe_name(text):
    return re.sub(r'[^A-Za-z0-9]+', '-', str(text)).strip('-')[:50].lower() or 'strategy'


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        cand = path.with_name(f'{path.stem}-{n}{path.suffix}')
        if not cand.exists():
            return cand
    raise ValueError('Too many files with that name.')


def _strip_fences(text):
    m = re.search(r'```[a-zA-Z0-9]*\n(.*?)```', text, re.S)
    return (m.group(1) if m else text).strip() + '\n'


def write_code(language='pine', strategy='', description='', name='', output_dir='', **params) -> dict:
    language = str(language or 'pine').lower().replace('pinescript', 'pine').replace('python3', 'python')
    if language not in LANG_EXT:
        raise ValueError('Language must be pine, python, mql5 or mql4.')
    folder = Path(os.path.expanduser(output_dir)).resolve() if output_dir else CODE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    strategy = str(strategy or '').strip().lower()
    method = 'template'
    if language == 'pine' and strategy in PINE and not description:
        values = {'title': name or 'JARVIS ' + strategy.replace('_', ' ').title(), 'rr': float(params.get('rr') or 2.0),
                  'side': {'long': 'Long only', 'buy': 'Long only', 'short': 'Short only', 'sell': 'Short only'}
                  .get(str(params.get('side', '')).lower(), 'Both'),
                  'fast': int(params.get('fast') or 20), 'slow': int(params.get('slow') or 50),
                  'atr_stop': float(params.get('atr_stop') or 1.5), 'oversold': float(params.get('oversold') or 30),
                  'overbought': float(params.get('overbought') or 70), 'length': int(params.get('length') or 20),
                  'swing_length': int(params.get('swing_length') or 3)}
        code = string.Template(PINE[strategy]).substitute(values)
    else:
        goal = str(description or '').strip()
        if strategy and not goal:
            entry = playbook(strategy).get('matches') or []
            goal = 'Implement this strategy: ' + json.dumps(entry[0] if entry else strategy, ensure_ascii=False)
        if len(goal) < 10:
            raise ValueError('Describe what the code should do, or name a built-in strategy: ' + ', '.join(PINE) + '.')
        code = _generate(language, goal)
        method = 'AI generated'
    check = check_code(language, code)
    if method == 'AI generated':
        rep = _generate.last_report
        check['repair_rounds'] = rep.get('rounds')
        if rep.get('run'):
            check['test_run'] = 'passed on sample data' if rep['run'].get('ok') else 'failed: ' + rep['run'].get('output', '')[-300:]
    path = _unique(folder / (_safe_name(name or strategy or description[:40]) + LANG_EXT[language]))
    path.write_text(code, encoding='utf-8')
    return {'path': str(path), 'language': language, 'method': method, 'lines': code.count('\n'), 'check': check,
            'how_to_use': {'pine': 'TradingView → Pine Editor → paste the file → Add to chart → Strategy Tester tab.',
                           'python': f'python "{path}" your_export.csv',
                           'mql5': 'MetaEditor → open the file → Compile (F7) → attach to a demo chart.',
                           'mql4': 'MetaEditor → open the file → Compile (F7) → attach to a demo chart.'}[language],
            'note': 'Not run against a live account. Review the code and test on demo data first.'}


def _sample_csv(folder: Path) -> Path:
    """Synthetic EURUSD-like hourly candles, used only to test-run generated Python."""
    import random
    rng = random.Random(7)
    path = folder / 'sample_eurusd_1h.csv'
    price, t, rows = 1.1, 1_700_000_000, ['time,open,high,low,close,volume']
    for _ in range(600):
        o = price; c = max(0.5, o + rng.gauss(0, 0.0012))
        h = max(o, c) + abs(rng.gauss(0, 0.0005)); l = min(o, c) - abs(rng.gauss(0, 0.0005))
        rows.append(f'{t},{o:.5f},{h:.5f},{l:.5f},{c:.5f},{rng.randint(100, 900)}'); price = c; t += 3600
    path.write_text('\n'.join(rows) + '\n')
    return path


def _python_runner(code: str) -> dict:
    import tempfile
    from core import code_quality as cq
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        script = folder / 'strategy.py'
        script.write_text(code, encoding='utf-8')
        return cq.run_file(script, [str(_sample_csv(folder))], timeout=60)


def _generate(language, goal):
    from core import code_quality as cq
    context = ('Trading code for a forex trader. Never place real orders or call broker/exchange APIs unless explicitly '
               'asked. Python scripts take the OHLC CSV path as the first command-line argument (columns '
               'time,open,high,low,close[,volume]; time may be unix seconds or ISO text) and print clear results.')
    code, report = cq.generate(goal, language, context=context, runner=_python_runner if language == 'python' else None,
                               max_rounds=5)
    _generate.last_report = report
    return code


_generate.last_report = {}


def check_code(language, code) -> dict:
    """Static checks from core.code_quality (Python: compile + pyflakes; Pine/MQL: rule linters). Nothing is executed."""
    from core import code_quality as cq
    r = cq.static_check(language, code)
    out = {'ok': r['ok'], 'checked': r['checker'], 'warnings': r['warnings']}
    if r['errors'] or r['missing_modules']:
        out['issue'] = (r['errors'] + ['missing modules: ' + ', '.join(r['missing_modules'])] * bool(r['missing_modules']))[0]
        out['all_issues'] = r['errors'][:10]
    return out
