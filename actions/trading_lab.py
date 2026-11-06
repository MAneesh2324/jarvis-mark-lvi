"""Voice tool for the trading lab: chart pattern analysis, playbook, backtests and code writing."""
import difflib
import json
import threading

from core import outcome


# What the last analysis or backtest in this process used, so "now check it for one week" works without
# repeating the symbol. Only filled from calls that succeeded.
_LAST: dict = {}
_LAST_LOCK = threading.Lock()
_REUSE_SYMBOL = ('symbol', 'interval')
_REUSE_SETTINGS = ('strategy', 'rr', 'side', 'account_balance', 'risk_percent', 'risk_amount', 'spread', 'commission',
                   'compound', 'stop_at', 'sweep_window', 'retest_window', 'max_hold', 'fast', 'slow', 'length',
                   'atr_stop', 'oversold', 'overbought', 'swing_length')


def remember(p: dict, backtest: bool = False):
    """Keep the symbol (and, for a backtest, its strategy and money settings) of a call that worked."""
    if not p.get('symbol') or p.get('csv_path'):
        return
    with _LAST_LOCK:
        if str(p['symbol']).upper() != str(_LAST.get('symbol', '')).upper():
            _LAST.clear()                                   # settings belong to the old symbol's test
        _LAST.update({k: p[k] for k in _REUSE_SYMBOL if p.get(k) is not None})
        if backtest:
            _LAST.update({k: p[k] for k in _REUSE_SETTINGS if p.get(k) is not None})


def reuse_last(p: dict, backtest: bool = False) -> tuple[dict, dict]:
    """When a call names no symbol (and no CSV), fill it from the last one. Returns (params, facts)."""
    p = dict(p)
    if p.get('symbol') or p.get('csv_path'):
        return p, {}
    with _LAST_LOCK:
        last = dict(_LAST)
    if not last.get('symbol'):
        return p, {}
    p['symbol'] = last['symbol']
    filled = [k for k in ('interval',) + (_REUSE_SETTINGS if backtest else ()) if p.get(k) is None and k in last]
    p.update({k: last[k] for k in filled})
    return p, {'symbol_reused': last['symbol'], 'settings_reused': {k: last[k] for k in filled} or None}


def run_backtest(p):
    """A backtest from tool parameters: the window, history range, money and strategy settings. Raw stats.

    A window the requested interval cannot cover (Yahoo keeps 1m for ~7 days, 5m-30m for ~60, 1h for ~2
    years, and a test holds at most MAX_CANDLES candles) runs on the finest interval that covers it, and
    says so in interval_requested / interval_used."""
    p, facts = reuse_last(p, backtest=True)
    import time as _time
    from core import trading_lab as lab
    hours = float(p.get('past_days') or 0) * 24 or float(p.get('past_hours') or 0)
    from_time = int(_time.time() - hours * 3600) if hours else None
    if hours and not p.get('csv_path'):
        given = p.get('interval') is not None
        asked = str(p.get('interval') or '1h').lower().replace('60m', '1h')
        used = lab.interval_for_window(asked, hours / 24)
        if used != asked:
            p['interval'] = used
            p.pop('range', None)                          # a range picked for the old interval no longer fits
            facts.update(interval_requested=asked + ('' if given else ' (default)'),
                         interval_used=used,
                         interval_note=f'{asked} candles cannot cover {hours / 24:g} days from this data source; '
                                       f'tested on {used}, the finest interval that does.')
    if hours and not p.get('range') and not p.get('csv_path'):
        # enough history for the window plus room for swings to form before it
        need = hours / 24 + 3
        p['range'] = next(r for r, d in (('5d', 5), ('1mo', 30), ('3mo', 90), ('6mo', 180), ('1y', 365),
                                         ('2y', 730), ('5y', 1825), ('max', 1e9)) if d >= need)
        interval = p.get('interval', '1h')
        # Yahoo serves 1m for about 7 days, intraday candles below 1h for about 60 days, 1h/4h for about 2 years
        if interval == '1m':
            p['range'] = '5d'
        elif interval in ('2m', '5m', '15m', '30m') and p['range'] not in ('5d', '1mo'):
            p['range'] = '1mo'
        elif interval in ('1h', '4h') and p['range'] in ('5y', 'max'):
            p['range'] = '2y'
    data = lab.load(p)
    clipped = None
    if from_time and data['candles'] and data['candles'][0]['t'] > from_time + 86400:
        have = (data['candles'][-1]['t'] - data['candles'][0]['t']) / 86400
        clipped = (f"Asked for the past {hours / 24:.0f} days, but {p.get('interval', '1h')} candles only go back "
                   f"{have:.0f} days from this data source; the test covers those {have:.0f} days. Use 1h or 4h for longer.")
    stats = _backtest(lab, data, p, from_time)
    if clipped:
        stats['window_note'] = clipped
    if data.get('range_note'):
        stats['range_note'] = data['range_note']
    remember(p, backtest=True)
    return {**{k: v for k, v in facts.items() if v is not None}, **stats}


def _backtest(lab, data, p, from_time):
    return lab.backtest(data, p.get('strategy', 'breaker_retest'), side=p.get('side', 'both'),
                        rr=p.get('rr', 2.0), max_hold=p.get('max_hold', 0), from_time=from_time,
                        **{k: p[k] for k in ('account_balance', 'risk_percent', 'risk_amount', 'spread',
                                             'commission', 'compound') if p.get(k) is not None},
                        **{k: p[k] for k in ('fast', 'slow', 'length', 'atr_stop', 'oversold', 'overbought',
                                             'swing_length', 'stop_at', 'sweep_window', 'retest_window')
                           if p.get(k) is not None})


def _show_backtest(data, player):
    """Put a finished backtest on the holographic board and keep it for "show me the simulation"."""
    try:
        from core.scenario_simulator import from_backtest, remember
        board = from_backtest(data)
        remember(board)
        if player is not None and hasattr(player, 'show_simulation'):
            player.show_simulation(board)
            return True
    except Exception as exc:
        print(f'[TradingLab] board failed: {exc}')
    return False


def _trade_table(data, player):
    """Every trade, as a table in the content panel below the board."""
    trades = data.get('trades') or []
    if player is None or not hasattr(player, 'show_content'):
        return
    money = data.get('money')
    head = f"{'#':>3}  {'RESULT':6} {'SIDE':5} {'ENTRY TIME (UTC)':16}  {'ENTRY':>10} {'STOP':>10} {'EXIT':>10} {'R':>7}"
    head += f" {'P&L':>10} {'BALANCE':>11}" if money else ''
    lines = [head, '─' * len(head)]
    for t in trades:
        row = (f"{t['n']:>3}  {('✔ WIN' if t['result'] == 'win' else '✘ LOSS'):6} {t['direction'][:5]:5} "
               f"{(t['entry_time'] or '')[:16]:16}  {t['entry']:>10} {t['stop']:>10} {t['exit']:>10} {t['r']:>+7.2f}")
        if money:
            row += f" {t['pnl']:>+10,.2f} {t['balance']:>11,.2f}"
        lines.append(row)
    if not trades:
        lines.append('No closed trades in this period.')
    lines.append('─' * len(head))
    lines.append(f"{data.get('wins', 0)} wins · {data.get('losses', 0)} losses · {data.get('total_r', 0):+.2f}R"
                 + (f" · net {money['net_pnl']:+,.2f} ({money['return_percent']:+.2f}%)" if money else ''))
    title = f"TRADES · {str(data.get('strategy', '')).replace('_', ' ')} · {str(data.get('requested') or data.get('instrument') or '').upper()}"
    try:
        player.show_content(title, '\n'.join(lines))
    except Exception as exc:
        print(f'[TradingLab] trade table failed: {exc}')


ACTIONS = ('analyse', 'backtest', 'compare', 'playbook', 'save_strategy', 'delete_strategy', 'write_code',
           'learning', 'watch', 'unwatch', 'scan', 'calendar')
# Other words a model uses for an action ("analyze" was sent in the live app and refused)
ACTION_ALIASES = {
    'analyze': 'analyse', 'analysis': 'analyse', 'analyse_chart': 'analyse', 'analyze_chart': 'analyse',
    'chart': 'analyse', 'check': 'analyse', 'review': 'analyse', 'look': 'analyse', 'structure': 'analyse',
    'setups': 'analyse', 'zones': 'analyse', 'patterns': 'analyse', 'detect': 'analyse',
    'test': 'backtest', 'back_test': 'backtest', 'backtesting': 'backtest', 'run_backtest': 'backtest',
    'simulate': 'backtest', 'simulation': 'backtest', 'test_strategy': 'backtest',
    'compare_strategies': 'compare', 'comparison': 'compare',
    'scanner': 'scan', 'screen': 'scan', 'screener': 'scan', 'scan_pairs': 'scan', 'scan_markets': 'scan',
    'news': 'calendar', 'events': 'calendar', 'economic_calendar': 'calendar', 'econ_calendar': 'calendar',
    'stats': 'learning', 'record': 'learning', 'learning_stats': 'learning', 'track_record': 'learning',
    'code': 'write_code', 'generate_code': 'write_code', 'pine': 'write_code', 'pinescript': 'write_code',
    'write': 'write_code', 'save': 'save_strategy', 'add_strategy': 'save_strategy',
    'remove_strategy': 'delete_strategy', 'explain': 'playbook', 'define': 'playbook', 'lookup': 'playbook',
    'follow': 'watch', 'track': 'watch', 'stop_watching': 'unwatch', 'untrack': 'unwatch',
}


def resolve_action(name) -> str | None:
    """The trading_lab action meant by `name`, or None."""
    key = str(name or 'analyse').strip().lower().replace('-', '_').replace(' ', '_')
    if key in ACTIONS:
        return key
    if key in ACTION_ALIASES:
        return ACTION_ALIASES[key]
    near = difflib.get_close_matches(key, list(ACTIONS) + list(ACTION_ALIASES), n=1, cutoff=0.8)
    return (ACTION_ALIASES.get(near[0], near[0])) if near else None


def trading_lab(parameters, player=None, **kwargs):
    p = dict(parameters or {})
    asked = p.get('action', 'analyse')
    action = resolve_action(asked)
    if action is None:
        return outcome.failed('trading_lab', f'Unknown trading_lab action "{asked}". Use one of: ' + ', '.join(ACTIONS) + '.')
    facts = {'action_requested': asked, 'action_used': action} if action != asked else {}
    if action in ('analyse', 'backtest', 'compare') and not p.get('symbol') and not p.get('csv_path'):
        filled, reused = reuse_last(p, backtest=action == 'backtest')
        if not filled.get('symbol'):
            return outcome.ask('trading_lab', 'Which symbol should I use, for example XAUUSD, EURUSD or NAS100?',
                               missing='symbol', **facts)
        if action != 'backtest':                       # run_backtest fills and reports its own reuse
            p = filled
            facts.update({k: v for k, v in reused.items() if v is not None})
    try:
        from core import trading_lab as lab
        if action == 'analyse':
            candles = lab.load(p)
            data = lab.analyse(candles, k=p.get('swing_length', 3), bias=p.get('bias', 'both'))
            if p.get('symbol') and not p.get('csv_path'):
                # What the user analyses is what the background learner forward-tests.
                from core import setup_tracker
                try:
                    interval = candles.get('interval', '1h')
                    setup_tracker.watch(p['symbol'], interval)
                    if p.get('bias', 'both') == 'both':
                        setup_tracker.record(p['symbol'], interval, data['setups_ranked'], candles['candles'][-1]['t'])
                except Exception as exc:
                    print(f'[TradingLab] learning log skipped: {exc}')
            remember(p)
        elif action == 'scan':
            data = lab.scan(p.get('pairs'), p.get('interval', '1h'), p.get('bias', 'both'))
        elif action == 'calendar':
            from core.news_engine import calendar
            data = calendar(p.get('currencies'), p.get('impact', 'High'), p.get('hours_ahead', 48), p.get('past_hours', 0))
        elif action == 'learning':
            from core import setup_tracker
            data = setup_tracker.stats()
        elif action == 'watch':
            from core import setup_tracker
            setup_tracker.watch(p['symbol'], p.get('interval', '1h'), origin='requested')
            data = {'watchlist': setup_tracker.watchlist()}
        elif action == 'unwatch':
            from core import setup_tracker
            data = setup_tracker.unwatch(p['symbol'], p.get('interval'))
        elif action == 'backtest':
            data = run_backtest(p)
            data['shown_on_hologram'] = _show_backtest(data, player)
            _trade_table(data, player)
            data.pop('equity_curve_r', None)          # the board has it; keep the spoken payload small
            if data.get('money'):
                data['money'].pop('curve', None)
            trades = data.pop('trades', [])
            data['trades_shown'] = 'every trade is listed in the panel under the board'
            data['last_trades'] = trades[-10:]
        elif action == 'compare':
            data = {'instrument': p.get('symbol') or p.get('csv_path'), 'results': []}
            candles = lab.load(p)
            for name in lab.STRATEGIES:
                r = lab.backtest(candles, name, side=p.get('side', 'both'), rr=p.get('rr', 2.0))
                data['results'].append({k: r[k] for k in ('strategy', 'closed_trades', 'win_rate_percent', 'total_r',
                                                          'profit_factor', 'max_drawdown_r', 'reliability')})
            data['note'] = 'Same data, default settings, no costs. Compare on several symbols and periods before trusting a winner.'
        elif action == 'playbook':
            data = lab.playbook(p.get('query', ''))
        elif action == 'save_strategy':
            data = lab.save_strategy(p.get('name', ''), p.get('rules', ''), p.get('aliases'), p.get('notes', ''))
        elif action == 'delete_strategy':
            data = lab.delete_strategy(p.get('name', ''))
        elif action == 'write_code':
            data = lab.write_code(p.get('language', 'pine'), p.get('strategy', ''), p.get('description', ''),
                                  p.get('name', ''), p.get('output_dir', ''),
                                  **{k: p.get(k) for k in ('rr', 'side', 'fast', 'slow', 'atr_stop', 'oversold',
                                                           'overbought', 'length', 'swing_length')})
            return outcome.done('trading_lab', **facts, **data)
        else:
            raise ValueError('Unknown trading_lab action.')
        if facts and isinstance(data, dict):
            data = {**facts, **data}
        return outcome.untrusted('trading-lab', json.dumps(data, ensure_ascii=False, default=str))
    except Exception as exc:
        return outcome.failed('trading_lab', str(exc)[:500], **facts)


TOOL = {
    'name': 'trading_lab',
    'description': (
        'Forex chart pattern analysis and trading research (the user trades forex only). '
        'scan: analyse many forex pairs at once and rank their best setups (default 14 majors/crosses). '
        'calendar: this week\'s economic events (NFP, CPI, rate decisions) by currency and impact, with forecast/previous. '
        'analyse also returns the open trading session, today\'s Asian range and whether it was swept, and news_risk: '
        'high-impact events for the pair in the next 24h. '
        'analyse: fetch candles (symbol like EURUSD, XAUUSD, GBPJPY, BTCUSD, NAS100, AAPL; interval 1m-1mo) or read a '
        'TradingView CSV export (csv_path), then detect market structure (HH/HL/LH/LL, BOS, CHoCH), order blocks, '
        'breaker blocks with retest status, fair value gaps, liquidity sweeps and equal highs/lows, key support/resistance '
        'zones, candlestick patterns, double tops/bottoms, head and shoulders, triangles and RSI divergence, and rank '
        'setups by confluence with entry/stop/target ideas. bias=sell or buy filters setups. '
        'backtest: test ema_cross, rsi_reversion, breakout, breaker_retest (any failed order block) or '
        'sweep_mss_breaker (THE USER\'S OWN SETUP: liquidity sweep of a high/low → market structure shift → breaker '
        'retest entry; stop_at sweep (default) or breaker; sweep_window, retest_window candles). Use sweep_mss_breaker '
        'whenever the user says "my setup", "my strategy", sweep/MSS/breaker. past_hours or past_days limits the test '
        'to that recent window (the right history range is fetched; a window the interval cannot cover runs on the '
        'finest interval that can, reported as interval_used — tell the user). With no symbol the last one is reused. For P&L in money pass account_balance and '
        'risk_percent (or risk_amount); spread (price units, e.g. 0.3 on gold) and commission per trade make it '
        'realistic. Results are drawn on the holographic board and every win/loss trade is listed under it; say '
        'wins, losses, win rate, R and net P&L. '
        'compare: all built-in strategies side by side. '
        'playbook: definitions and rules for trading concepts and strategies (query any term; empty lists topics). '
        'save_strategy/delete_strategy: store or remove the user\'s own strategy rules when they dictate them. '
        'write_code: write Pine Script, Python, MQL5 or MQL4 to a file (built-in Pine templates for the four strategies, '
        'AI generation from a description otherwise). '
        'learning: the forward-tracked record of logged setups (won/lost/expired by setup type, confluence factor and '
        'market) that the background learner builds on watched markets; watch/unwatch: change which symbol+interval '
        'it tracks (anything the user analyses is watched automatically). '
        'Data is delayed/indicative (Yahoo Finance; gold uses futures as a proxy) and may differ from the broker chart. '
        'Never place orders. Report zones and statistics as found, with their dates; do not call them guaranteed or advice.'
    ),
    'brief': 'Trading chart patterns (breakers, OB, FVG, structure, S/R), backtests, strategy playbook, Pine/Python code.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['analyse', 'backtest', 'compare', 'playbook', 'save_strategy',
                                                  'delete_strategy', 'write_code', 'learning', 'watch', 'unwatch',
                                                  'scan', 'calendar']},
            'pairs': {'type': 'ARRAY', 'items': {'type': 'STRING'}, 'description': 'Forex pairs to scan (default 14 majors and crosses)'},
            'currencies': {'type': 'ARRAY', 'items': {'type': 'STRING'}, 'description': 'Calendar currencies, e.g. USD, EUR'},
            'impact': {'type': 'STRING', 'enum': ['High', 'Medium', 'Low', 'All']},
            'hours_ahead': {'type': 'INTEGER'},
            'past_hours': {'type': 'INTEGER'},
            'symbol': {'type': 'STRING', 'description': 'EURUSD, XAUUSD, BTCUSD, NAS100, AAPL…'},
            'interval': {'type': 'STRING', 'enum': ['1m', '2m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk', '1mo']},
            'range': {'type': 'STRING', 'description': '1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y (default fits the interval)'},
            'csv_path': {'type': 'STRING', 'description': 'OHLC CSV, e.g. a TradingView chart export'},
            'refresh': {'type': 'BOOLEAN'},
            'bias': {'type': 'STRING', 'enum': ['both', 'buy', 'sell']},
            'swing_length': {'type': 'INTEGER', 'description': 'Candles each side of a swing point (default 3)'},
            'strategy': {'type': 'STRING', 'description': 'ema_cross, rsi_reversion, breakout, breaker_retest, or a playbook topic'},
            'side': {'type': 'STRING', 'enum': ['both', 'long', 'short']},
            'rr': {'type': 'NUMBER', 'description': 'Reward to risk (default 2)'},
            'past_days': {'type': 'NUMBER', 'description': 'Backtest only the last N days'},
            'account_balance': {'type': 'NUMBER', 'description': 'Starting balance for P&L in money'},
            'risk_percent': {'type': 'NUMBER', 'description': 'Risk per trade, % of balance (default 1)'},
            'risk_amount': {'type': 'NUMBER', 'description': 'Fixed money risked per trade (instead of %)'},
            'spread': {'type': 'NUMBER', 'description': 'Spread in price units paid per trade (gold ≈ 0.2–0.4)'},
            'commission': {'type': 'NUMBER', 'description': 'Commission per trade in money'},
            'compound': {'type': 'BOOLEAN', 'description': 'Risk % of the current balance instead of the start'},
            'stop_at': {'type': 'STRING', 'enum': ['sweep', 'breaker'], 'description': 'sweep_mss_breaker stop placement'},
            'sweep_window': {'type': 'INTEGER', 'description': 'Max candles from sweep to structure shift (default 30)'},
            'retest_window': {'type': 'INTEGER', 'description': 'Max candles from shift to breaker retest (default 40)'},
            'atr_stop': {'type': 'NUMBER'},
            'fast': {'type': 'INTEGER'},
            'slow': {'type': 'INTEGER'},
            'length': {'type': 'INTEGER'},
            'oversold': {'type': 'NUMBER'},
            'overbought': {'type': 'NUMBER'},
            'max_hold': {'type': 'INTEGER', 'description': 'Close a backtest trade after this many candles (0 = never)'},
            'query': {'type': 'STRING'},
            'name': {'type': 'STRING'},
            'rules': {'type': 'STRING'},
            'aliases': {'type': 'ARRAY', 'items': {'type': 'STRING'}},
            'notes': {'type': 'STRING'},
            'language': {'type': 'STRING', 'enum': ['pine', 'python', 'mql5', 'mql4']},
            'description': {'type': 'STRING', 'description': 'What the code should do (custom code)'},
            'output_dir': {'type': 'STRING'},
        },
        'required': ['action'],
    },
    'handler': trading_lab,
    'tier': 'core',
}
