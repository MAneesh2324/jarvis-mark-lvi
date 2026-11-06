"""Live simulation session: one model, re-run by spoken commands until it works.

    start   a model (goal, savings, forex, outage, trade_stress, or a trading backtest)
    goal    the success condition, e.g. net_pnl > 0 or finish_day <= 120
    change  "run it again with 4 hours", "try 1 to 3", "invert it" → merge, re-run, judge
    search  try several values of one setting, in order, and stop at the first success

Every run is an attempt with a number, what changed, the measured value and a verdict.
The board shows the attempt log, MODEL SUCCESSFUL / MODEL FAILED and a hologram whose
shape changes with each attempt. All local; backtests use the same engine as trading_lab.
"""
from __future__ import annotations

import copy
import difflib
import threading

_lock = threading.RLock()
_state: dict = {}

# Spoken metric names → where the number lives in a result. Lower-is-better metrics are
# only a default for the comparison when the user does not say which way.
METRICS = {
    'goal': {'finish_day': 'finish_day_median', 'done_by_deadline_percent': 'simulated_fraction_done_by_deadline_percent'},
    'savings': {'final_balance': 'final_balance_median', 'reach_target_percent': 'simulated_fraction_reaching_target_percent'},
    'forex': {'end_rate': 'terminal_rate_median', 'drawdown_p95': 'p95_path_max_drawdown_percent'},
    'outage': {'clear_minutes': 'estimated_backlog_clearance_minutes', 'backlog': 'total_recovery_backlog'},
    'trade_stress': {'net_pnl': 'net_pnl_account_currency', 'equity_change_percent': 'equity_change_percent'},
    'backtest': {'net_pnl': 'money.net_pnl', 'return_percent': 'money.return_percent', 'total_r': 'stats.total_r',
                 'win_rate_percent': 'stats.win_rate_percent', 'profit_factor': 'stats.profit_factor',
                 'max_drawdown_r': 'stats.max_drawdown_r', 'trades': 'stats.closed_trades'},
}
LOWER_IS_BETTER = {'finish_day', 'drawdown_p95', 'clear_minutes', 'backlog', 'max_drawdown_r'}
OPS = {'>': lambda a, b: a > b, '>=': lambda a, b: a >= b, '<': lambda a, b: a < b, '<=': lambda a, b: a <= b}
MAX_ATTEMPTS_SHOWN = 8
MAX_SEARCH = 8


def metric(result: dict, name: str):
    """The named metric from a board result, or None when it cannot be read."""
    kind = result.get('kind')
    if kind == 'comparison':
        result, kind = result.get('alternative', {}), result.get('scenario_kind')
    if kind == 'process':                                   # any variable's final value, or when an event happened
        if name in (result.get('finals') or {}):
            return float(result['finals'][name])
        ev = next((e for e in result.get('events', []) if e['label'].lower().replace(' ', '_') == name), None)
        return None if ev is None or ev['at'] is None else float(ev['at'])
    path = METRICS.get(kind, {}).get(name)
    if not path:
        return None
    value = result
    for part in path.split('.'):
        value = value.get(part) if isinstance(value, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _criterion_text(c):
    return f"{c['metric'].replace('_', ' ')} {c['op']} {c['value']:g}" if c else 'no success condition yet'


# What a backtest reports about itself that the model must pass on (switched interval, reused symbol…)
BACKTEST_FACTS = ('interval_requested', 'interval_used', 'interval_note', 'symbol_reused', 'settings_reused',
                  'window_note', 'range_note')
PROCESS_SPEC_KEYS = ('focus', 'duration', 'steps', 'uncertainty_percent', 'seed', 'title', 'time_unit')


def _run(kind: str, params: dict) -> dict:
    """One model run as a board result."""
    if kind == 'backtest':
        from actions.trading_lab import run_backtest
        from core.scenario_simulator import from_backtest
        stats = run_backtest(params)
        board = from_backtest(stats)
        facts = {k: stats[k] for k in BACKTEST_FACTS if stats.get(k)}
        if facts:
            board['facts'] = facts
        return board
    from core.scenario_simulator import run
    return run(kind, params)


def known_settings(kind: str, params: dict) -> list[str]:
    """Every setting name a change may use for this kind of model."""
    if isinstance(params.get('variables'), list):
        return sorted(params.get('params') or {}) + list(PROCESS_SPEC_KEYS)
    if kind == 'backtest':
        from actions.trading_lab import TOOL
        names = set(TOOL['parameters']['properties']) - {'action', 'pairs', 'currencies', 'impact', 'hours_ahead',
                                                          'query', 'name', 'rules', 'aliases', 'notes', 'language',
                                                          'description', 'output_dir'}
        return sorted(names | set(params))
    from core.scenario_simulator import accepted_keys
    return sorted(set(accepted_keys(kind)) | set(params))


def match_changes(kind: str, params: dict, changes: dict) -> tuple[dict, dict]:
    """Map each changed name onto a real setting: exact, a known other spelling, or a close match
    (sunlight → sunlight_hours). Returns (changes by real name, {said: matched}). Unknown names raise."""
    known = known_settings(kind, params)
    out, matched = {}, {}
    aliases = {}
    if kind not in ('process', 'backtest'):
        from core.scenario_simulator import ALIASES
        aliases = ALIASES.get(kind, {})
    for k, v in (changes or {}).items():
        key = str(k).strip()
        for prefix in ('params.', 'parameters.', 'settings.'):
            key = key.removeprefix(prefix)
        if key in known:
            out[key] = v
            continue
        low = key.lower().replace(' ', '_').replace('-', '_')
        real = (low if low in known else aliases.get(low)
                or next(iter(difflib.get_close_matches(low, known, n=1, cutoff=0.75)), None)
                or next((n for n in known if low and (n.startswith(low + '_') or n.endswith('_' + low))), None))
        if real is None:
            raise ValueError(f'"{key}" is not a setting of this {kind} model; settings: {", ".join(known)}.')
        out[real] = v
        matched[str(k)] = real
    return out, matched


def _apply(params: dict, changes: dict) -> tuple[dict, list[str]]:
    """Merge spoken changes. 'invert' flips side/direction; None removes a setting.
    For a process spec, a setting name changes spec.params; focus/duration/... change the spec itself."""
    if isinstance(params.get('variables'), list):
        new, said = copy.deepcopy(params), []
        inner = new.setdefault('params', {})
        for k, v in (changes or {}).items():
            k = str(k).removeprefix('params.')
            target = inner if k in inner or k not in PROCESS_SPEC_KEYS else new
            old = target.get(k)
            if old != v:
                target[k] = v
                said.append(f"{k.replace('_', ' ')} {old if old is not None else '—'}→{v}")
        return new, said
    new, said = dict(params), []
    for k, v in (changes or {}).items():
        if isinstance(v, str) and v.lower() in ('invert', 'flip', 'reverse'):
            flip = {'long': 'short', 'short': 'long', 'buy': 'sell', 'sell': 'buy', 'both': 'both'}
            v = flip.get(str(new.get(k, 'both')).lower(), new.get(k))
        old = new.get(k)
        if v is None:
            new.pop(k, None)
        else:
            new[k] = v
        if old != v:
            said.append(f"{k.replace('_', ' ')} {old if old is not None else '—'}→{v if v is not None else '—'}")
    return new, said


def _judge(result, criterion):
    if not criterion:
        return None, None
    value = metric(result, criterion['metric'])
    if value is None:
        return None, False
    return value, OPS[criterion['op']](value, criterion['value'])


def _attempt(kind, params, change_text, criterion, facts=None):
    result = _run(kind, params)
    if facts:
        result['facts'] = {**(result.get('facts') or {}), **facts}
    value, passed = _judge(result, criterion)
    from core.scenario_simulator import headline
    head = headline(result)
    key = criterion['metric'] if criterion else None
    if value is None and head['metrics']:
        shown = head['metrics'][0][1]
    else:
        shown = f'{value:,.2f}'.rstrip('0').rstrip('.') if value is not None else '—'
    return result, {'change': change_text or 'baseline', 'value': shown, 'metric': key,
                    'passed': passed, 'headline': head['verdict']}


def _board(result: dict) -> dict:
    """The result with the session overlay the board draws."""
    with _lock:
        attempts = _state.get('attempts', [])
        board = dict(result)
        last = attempts[-1] if attempts else {}
        board['session'] = {'label': _state.get('label') or '', 'attempt': len(attempts),
                            'criterion': _criterion_text(_state.get('criterion')),
                            'status': ('success' if last.get('passed') else 'failed' if last.get('passed') is False else None),
                            'attempts': attempts[-MAX_ATTEMPTS_SHOWN:]}
        return board


def _record(result, info, params):
    with _lock:
        info['n'] = len(_state['attempts']) + 1
        _state['attempts'].append(info)
        _state['params'] = params
        _state['last'] = result
        if info['passed'] and _state.get('best') is None:
            _state['best'] = info['n']
        return _board(result)


# ── public ──────────────────────────────────────────────────────────────────
def start(kind: str, params: dict, criterion: dict | None = None, label: str = '') -> dict:
    facts = {}
    if kind == 'backtest':                                  # "same test for a week": the last symbol and settings
        from actions.trading_lab import reuse_last
        params, facts = reuse_last(params, backtest=True)
        facts = {k: v for k, v in facts.items() if v is not None}
    with _lock:
        _state.clear()
        _state.update(kind=kind, params=copy.deepcopy(params), criterion=None, attempts=[], label=label, best=None)
        try:
            criterion = _check_criterion(kind, criterion) if criterion else None
        except ValueError:
            _state.clear()
            raise
        _state['criterion'] = criterion
    try:
        result, info = _attempt(kind, copy.deepcopy(params), 'baseline', criterion, facts)
    except Exception:
        with _lock:
            _state.clear()                                  # a model that never ran is not a live session
        raise
    return _record(result, info, copy.deepcopy(params))


def active() -> bool:
    return bool(_state.get('kind'))


def _need():
    if not active():
        raise ValueError('No live simulation is running. Start one first (action start).')


def set_goal(criterion: dict) -> dict:
    """Change the success condition and judge the current model against it again."""
    _need()
    with _lock:
        _state['criterion'] = _check_criterion(_state['kind'], criterion)
        params = dict(_state['params'])
    result, info = _attempt(_state['kind'], params, 'new goal: ' + _criterion_text(_state['criterion']), _state['criterion'])
    return _record(result, info, params)


def change(changes: dict) -> dict:
    _need()
    if not changes:
        raise ValueError('That changes nothing; name a setting and a new value.')
    changes, matched = match_changes(_state['kind'], _state['params'], changes)
    params, said = _apply(_state['params'], changes)
    if not said:
        cur = _state['params'].get('params', _state['params']) if isinstance(_state['params'].get('variables'), list) \
            else _state['params']
        same = ', '.join(f"{k} is already {cur.get(k, _state['params'].get(k))}" for k in changes)
        raise ValueError(f'That changes nothing: {same}. Name a different value, or use show to see the current run.')
    result, info = _attempt(_state['kind'], params, ', '.join(said), _state.get('criterion'),
                            {'matched_settings': matched} if matched else None)
    return _record(result, info, params)


def search(param: str, values: list) -> list[dict]:
    """Try each value of one setting in order. Stops after the first success; returns every board shown."""
    _need()
    values = list(values or [])[:MAX_SEARCH]
    if not param or not values:
        raise ValueError('Name one setting and at least one value to try.')
    base, boards, found = dict(_state['params']), [], False
    param = next(iter(match_changes(_state['kind'], base, {param: None})[0]))
    for v in values:
        params, said = _apply(base, {param: v})              # every try starts from the same base
        if not said:
            continue
        result, info = _attempt(_state['kind'], params, ', '.join(said), _state.get('criterion'))
        boards.append(_record(result, info, params))
        if info['passed']:
            found = True
            break
    if not found:
        with _lock:
            _state['params'] = base                          # nothing worked: keep the model as it was
    return boards


def status() -> dict:
    if not active():
        return {'active': False}
    with _lock:
        return {'active': True, 'kind': _state['kind'], 'label': _state.get('label'),
                'criterion': _criterion_text(_state.get('criterion')), 'current_settings': copy.deepcopy(_state['params']),
                'attempts': copy.deepcopy(_state['attempts'][-12:]), 'first_success': _state.get('best')}


def board() -> dict | None:
    return _board(_state['last']) if active() and _state.get('last') else None


def reset() -> dict:
    with _lock:
        _state.clear()
    return {'active': False}


def _check_criterion(kind, c):
    if not isinstance(c, dict) or not c.get('metric'):
        raise ValueError('A goal needs a metric, a comparison and a value, e.g. net_pnl > 0.')
    name = str(c['metric']).lower().replace(' ', '_')
    if kind == 'process':
        spec = _state.get('params') or {}
        allowed = [v.get('name') for v in spec.get('variables', [])] + \
                  [str(e.get('label', '')).lower().replace(' ', '_') for e in spec.get('events', [])]
    else:
        allowed = list(METRICS.get(kind, {}))
    if name not in allowed:
        raise ValueError(f"For {kind} the goal can use: {', '.join(allowed)}.")
    op = str(c.get('op') or ('<=' if name in LOWER_IS_BETTER else '>=')).strip()
    if op not in OPS:
        raise ValueError('Use >, >=, < or <= in the goal.')
    try:
        value = float(c['value'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('The goal needs a number to compare with.') from None
    return {'metric': name, 'op': op, 'value': value}
