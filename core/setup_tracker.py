"""Forward-tested learning for trading_lab setups.

Every setup the analyser ranks is logged with its entry, stop and target. Later
candles decide what actually happened: triggered or not, then stop or target.
The resulting track record per setup type and per confluence factor is fed back
into setup ranking. This is outcome bookkeeping on real subsequent prices, not
model training, and it never trades.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / 'memory' / 'trading-learning.db'
WATCH_LIMIT = 8
EXPIRE_CANDLES = 60
DEFAULT_WATCH = (('EURUSD', '1h'), ('GBPUSD', '1h'), ('USDJPY', '1h'), ('GBPJPY', '1h'), ('AUDUSD', '1h'))
MIN_SAMPLE = 20  # closed trades before a track record may move a ranking


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(DB_PATH, os.O_CREAT | os.O_WRONLY, 0o600); os.close(fd)
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS watchlist(symbol TEXT, interval TEXT, origin TEXT, last_used TEXT,'
                       ' PRIMARY KEY(symbol, interval))')
            db.execute('CREATE TABLE IF NOT EXISTS setups(id INTEGER PRIMARY KEY, key TEXT UNIQUE, symbol TEXT, interval TEXT,'
                       ' setup TEXT, direction TEXT, zone_low REAL, zone_high REAL, entry REAL, stop REAL, target REAL,'
                       ' score INTEGER, confluence TEXT, created_t INTEGER, status TEXT, triggered_t INTEGER,'
                       ' closed_t INTEGER, r REAL, recorded TEXT)')
            yield db
    finally:
        db.close()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


# ── watchlist ───────────────────────────────────────────────────────────────

def norm(symbol):
    return re.sub(r'[\s/_]', '', str(symbol or '')).upper()


def watch(symbol, interval, origin='analysed'):
    symbol, interval = norm(symbol), str(interval).lower().strip()
    if not symbol or not interval:
        return
    with connect() as db:
        db.execute('INSERT INTO watchlist VALUES(?,?,?,?) ON CONFLICT(symbol, interval) DO UPDATE SET last_used=excluded.last_used',
                   (symbol, interval, origin, _now()))


def unwatch(symbol, interval=None):
    with connect() as db:
        if interval:
            n = db.execute('DELETE FROM watchlist WHERE symbol=? AND interval=?', (norm(symbol), interval.lower())).rowcount
        else:
            n = db.execute('DELETE FROM watchlist WHERE symbol=?', (norm(symbol),)).rowcount
    return {'removed': n, 'watchlist': watchlist()}


def watchlist():
    with connect() as db:
        rows = db.execute('SELECT symbol, interval, origin, last_used FROM watchlist ORDER BY last_used DESC').fetchall()
        if not rows:
            for s, i in DEFAULT_WATCH:
                db.execute('INSERT OR IGNORE INTO watchlist VALUES(?,?,?,?)', (s, i, 'default', _now()))
            rows = db.execute('SELECT symbol, interval, origin, last_used FROM watchlist ORDER BY last_used DESC').fetchall()
    return [dict(r) for r in rows][:WATCH_LIMIT]


# ── recording and evaluating ────────────────────────────────────────────────

def _key(symbol, interval, s):
    span = abs(s['zone_high'] - s['zone_low']) or abs(s['entry']) * 1e-4
    q = lambda v: round(v / span)  # zone identity tolerant of tiny re-detection jitter
    return f"{symbol}|{interval}|{s['setup']}|{q(s['zone_low'])}|{q(s['zone_high'])}"


def record(symbol, interval, setups, last_t):
    symbol, added = norm(symbol), 0
    with connect() as db:
        for raw in setups:
            # trading_lab reports entry_idea/stop_idea/target_idea; accept plain names too.
            s = {**raw, **{k: raw.get(k + '_idea', raw.get(k)) for k in ('entry', 'stop', 'target')}}
            if None in (s['entry'], s['stop'], s['target']) or s.get('reward_to_risk', 0) <= 0 or s['entry'] == s['stop']:
                continue
            cur = db.execute('INSERT OR IGNORE INTO setups(key, symbol, interval, setup, direction, zone_low, zone_high, entry,'
                             ' stop, target, score, confluence, created_t, status, recorded) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             (_key(symbol, interval, s), symbol, interval, s['setup'], s['direction'], s['zone_low'],
                              s['zone_high'], s['entry'], s['stop'], s['target'],
                              s.get('score', 0), json.dumps(s.get('confluence', [])), int(last_t), 'waiting', _now()))
            added += cur.rowcount
    return added


def evaluate(symbol, interval, candles):
    """Advance open setups through closed candles (the last candle may still be forming)."""
    closed_candles = candles[:-1]
    changed = 0
    with connect() as db:
        rows = db.execute("SELECT * FROM setups WHERE symbol=? AND interval=? AND status IN ('waiting','triggered')",
                          (symbol, interval)).fetchall()
        for row in rows:
            r = dict(row)
            sell = r['direction'] == 'sell'
            status, trig, closed_t, result = r['status'], r['triggered_t'], None, None
            later = [c for c in closed_candles if c['t'] > r['created_t']]
            waited = 0
            for c in later:
                if status == 'waiting':
                    waited += 1
                    touched = c['h'] >= r['entry'] if sell else c['l'] <= r['entry']
                    if not touched:
                        if waited >= EXPIRE_CANDLES:
                            status, closed_t = 'expired', c['t']; break
                        continue
                    status, trig = 'triggered', c['t']
                    if (c['h'] >= r['stop']) if sell else (c['l'] <= r['stop']):
                        status, closed_t, result = 'lost', c['t'], -1.0; break
                    continue  # target is not counted on the fill candle: order inside the candle is unknown
                if trig is not None and c['t'] <= trig:
                    continue
                if (c['h'] >= r['stop']) if sell else (c['l'] <= r['stop']):
                    status, closed_t, result = 'lost', c['t'], -1.0; break
                if (c['l'] <= r['target']) if sell else (c['h'] >= r['target']):
                    risk = abs(r['stop'] - r['entry'])
                    status, closed_t, result = 'won', c['t'], round(abs(r['target'] - r['entry']) / risk, 3); break
            if status != r['status'] or trig != r['triggered_t']:
                db.execute('UPDATE setups SET status=?, triggered_t=?, closed_t=?, r=? WHERE id=?',
                           (status, trig, closed_t, result, r['id']))
                changed += 1
    return changed


# ── what was learned ────────────────────────────────────────────────────────

def _agg(rows):
    rs = [r['r'] for r in rows]
    wins = [x for x in rs if x > 0]
    return {'closed': len(rs), 'wins': len(wins), 'win_rate_percent': round(100 * len(wins) / len(rs), 1) if rs else None,
            'total_r': round(sum(rs), 2), 'avg_r': round(sum(rs) / len(rs), 3) if rs else None}


def stats():
    with connect() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM setups').fetchall()]
    closed = [r for r in rows if r['status'] in ('won', 'lost')]
    by_type, by_factor, by_market = {}, {}, {}
    for r in closed:
        by_type.setdefault(r['setup'], []).append(r)
        by_market.setdefault(f"{r['symbol']} {r['interval']}", []).append(r)
        for f in json.loads(r['confluence'] or '[]'):
            by_factor.setdefault(f.split(' (')[0], []).append(r)
    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return {'tracked_setups': len(rows), 'by_status': counts, 'overall': _agg(closed),
            'by_setup_type': {k: _agg(v) for k, v in sorted(by_type.items())},
            'by_confluence_factor': {k: _agg(v) for k, v in sorted(by_factor.items(), key=lambda kv: -len(kv[1]))},
            'by_market': {k: _agg(v) for k, v in sorted(by_market.items())},
            'watchlist': watchlist(),
            'note': f'Forward results on prices after each setup was logged, in R, no costs. A record needs {MIN_SAMPLE}+ closed '
                    'setups before it changes rankings; small samples are noise.'}


def edges():
    """Per setup type: track record, and the ranking nudge it has earned (-1, 0 or +1)."""
    out = {}
    for name, a in stats()['by_setup_type'].items():
        nudge = 0
        if a['closed'] >= MIN_SAMPLE and a['avg_r'] is not None:
            nudge = 1 if a['avg_r'] >= 0.15 else -1 if a['avg_r'] <= -0.15 else 0
        out[name] = {**a, 'ranking_nudge': nudge}
    return out


def annotate(setups):
    """Attach the learned record to each ranked setup and re-rank with earned nudges."""
    try:
        e = edges()
    except Exception:
        return setups
    for s in setups:
        rec = e.get(s['setup'])
        if rec and rec['closed']:
            s['learned_track_record'] = (f"{rec['wins']}/{rec['closed']} won, avg {rec['avg_r']}R in forward tracking"
                                         + ('' if rec['closed'] >= MIN_SAMPLE else ' (sample still small)'))
            s['score'] += rec['ranking_nudge']
    setups.sort(key=lambda x: -x['score'])
    return setups


# ── background cycle ────────────────────────────────────────────────────────

def cycle():
    """Evaluate open setups and log new ones for each watched market. Called by the background learner."""
    from core import trading_lab as lab
    summary = {'markets': [], 'errors': {}}
    for w in watchlist():
        try:
            data = lab.fetch_candles(w['symbol'], w['interval'], refresh=True)
            if len(data['candles']) < lab.MIN_CANDLES:
                continue
            updated = evaluate(w['symbol'], w['interval'], data['candles'])
            report = lab.analyse(data, learn=False)
            added = record(w['symbol'], w['interval'], report['setups_ranked'], data['candles'][-1]['t'])
            summary['markets'].append({'market': f"{w['symbol']} {w['interval']}", 'new_setups': added, 'resolved': updated,
                                       'top': report['setups_ranked'][0]['setup'] if report['setups_ranked'] else None})
        except Exception as exc:
            summary['errors'][f"{w['symbol']} {w['interval']}"] = str(exc)[:200]
    s = stats()
    summary['record'] = s['overall']
    summary['by_status'] = s['by_status']
    return summary


def context_line():
    try:
        s = stats()
    except Exception:
        return ''
    o = s['overall']
    if not s['tracked_setups']:
        return ''
    best = sorted(((k, v) for k, v in s['by_setup_type'].items() if v['closed'] >= 5), key=lambda kv: -(kv[1]['avg_r'] or 0))
    line = (f"Trading forward-tracking: {s['tracked_setups']} setups logged on {len(s['watchlist'])} watched markets, "
            + (f"{o['closed']} resolved ({o['win_rate_percent']}% won, {o['total_r']}R)." if o['closed']
               else 'none resolved yet; results build up as later candles arrive.'))
    if best:
        k, v = best[0]
        line += f" Best so far: {k} ({v['wins']}/{v['closed']}, avg {v['avg_r']}R)."
    return line
