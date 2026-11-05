"""Voice tool: the live simulation session — "JARVIS, run a simulation… now try it with…"."""
import json
import threading
import time

from core import outcome

MONTAGE_SECONDS = 3.6          # each search attempt stays on the board this long (build + verdict)
_montage_lock = threading.Lock()
_montage_id = 0


def _show(player, board):
    if player is not None and hasattr(player, 'show_simulation'):
        player.show_simulation(board)
        return True
    return False


def _montage(player, boards):
    """Play search attempts one after another; a newer command cancels an older montage."""
    global _montage_id
    with _montage_lock:
        _montage_id += 1
        me = _montage_id

    def run():
        for k, b in enumerate(boards):
            if me != _montage_id:
                return
            _show(player, b)
            if k < len(boards) - 1:
                time.sleep(MONTAGE_SECONDS)
    try:
        from core.scenario_simulator import remember
        remember(boards[-1])                                 # "show me the simulation" brings it back
    except Exception:
        pass
    threading.Thread(target=run, daemon=True, name='jarvis-sim-montage').start()


def _summary(board, extra=None):
    from core import sim_session as S
    from core.scenario_simulator import headline
    sess = board.get('session', {})
    last = (sess.get('attempts') or [{}])[-1]
    data = {'attempt': sess.get('attempt'), 'goal': sess.get('criterion'),
            'verdict': {'success': 'MODEL SUCCESSFUL', 'failed': 'MODEL FAILED'}.get(sess.get('status'), 'no goal set'),
            'this_attempt': {k: last.get(k) for k in ('change', 'value', 'passed')},
            'headline': headline(board)['verdict'], 'current_settings': S.status().get('current_settings')}
    if board.get('model_warnings'):
        data['model_warnings'] = board['model_warnings']
        data['say'] = ('The result looks unrealistic. Tell the user in one line, then start again with a corrected spec '
                       '(bounded growth, realistic magnitudes) without waiting to be asked.')
    cur = data['current_settings'] or {}
    if isinstance(cur.get('variables'), list):               # a process: the settings, not the whole spec
        data['current_settings'] = cur.get('params', {})
        data['can_change'] = sorted(cur.get('params', {})) + ['focus', 'duration', 'uncertainty_percent']
    if extra:
        data.update(extra)
    return data


def session(parameters, player=None, **kwargs):
    from core import sim_session as S
    p = dict(parameters or {})
    action = p.get('action') or ('start' if p.get('parameters_json') else 'change' if p.get('changes_json')
                                 else 'search' if p.get('param') else 'status')
    if action == 'start' and not p.get('kind'):
        try:
            p['kind'] = 'process' if 'variables' in json.loads(p.get('parameters_json') or '{}') else ''
        except ValueError:
            pass
    try:
        def criterion():
            if p.get('goal_metric') is None:
                return None
            return {'metric': p['goal_metric'], 'op': p.get('goal_op'), 'value': p.get('goal_value')}

        if action == 'start':
            kind = p.get('kind', '')
            spec = json.loads(p.get('parameters_json') or '{}')
            board = S.start(kind, spec, criterion(), p.get('label', ''))
            _montage(player, [board])
            return outcome.untrusted('live-simulation', json.dumps(_summary(board), ensure_ascii=False, default=str))
        if action == 'change':
            board = S.change(json.loads(p.get('changes_json') or '{}'))
            _montage(player, [board])
            return outcome.untrusted('live-simulation', json.dumps(_summary(board), ensure_ascii=False, default=str))
        if action == 'goal':
            board = S.set_goal(criterion() or {})
            _montage(player, [board])
            return outcome.untrusted('live-simulation', json.dumps(_summary(board), ensure_ascii=False, default=str))
        if action == 'search':
            values = p.get('values') or json.loads(p.get('values_json') or '[]')
            boards = S.search(p.get('param', ''), values)
            if not boards:
                raise ValueError('None of those values changes the model.')
            _montage(player, boards)
            tries = [{k: b['session']['attempts'][-1].get(k) for k in ('n', 'change', 'value', 'passed')} for b in boards]
            won = next((t for t in tries if t['passed']), None)
            return outcome.untrusted('live-simulation', json.dumps(_summary(boards[-1], {
                'tries': tries, 'first_success': won,
                'montage_seconds': round(MONTAGE_SECONDS * (len(boards) - 1), 1),
                'say': 'The board is playing the attempts in order; narrate briefly, then give the result.'}),
                ensure_ascii=False, default=str))
        if action == 'show':
            board = S.board()
            if board is None:
                raise ValueError('No live simulation is running yet.')
            _montage(player, [board])
            return outcome.untrusted('live-simulation', json.dumps(_summary(board), ensure_ascii=False, default=str))
        if action == 'status':
            return outcome.untrusted('live-simulation', json.dumps(S.status(), ensure_ascii=False, default=str))
        if action == 'reset':
            S.reset()
            if player is not None and hasattr(player, 'show_simulation'):
                player.show_simulation(None)
            return outcome.done('simulation_session', reset=True)
        raise ValueError('Unknown simulation_session action.')
    except Exception as exc:
        return outcome.failed('simulation_session', str(exc)[:400])


TOOL = {
    'name': 'simulation_session',
    'description': (
        'LIVE SIMULATION LAB, Stark-workshop style: build a model of ANYTHING, run it on the holographic board, then '
        're-run it on every spoken command until it works. Each run is a numbered attempt with what changed, the '
        'measured value and MODEL SUCCESSFUL / MODEL FAILED against the goal. Use this (not scenario_simulator) when '
        'the user wants to iterate ("now try…", "run it again with…", "invert it", "what if…") or simulate something '
        'that is not a built-in kind.\n'
        'start: kind + parameters_json, optional goal_metric/goal_op/goal_value and label. Kinds:\n'
        ' • process — ANY real-world process ("apple growing on a tree", "coffee cooling", "a city\'s population", '
        '"battery draining", "virus spreading", "bread dough rising"). YOU write the spec as parameters_json: '
        '{"title", "time_unit", "duration", "steps"(≤2000), "params": {setting: number}, "variables": [{"name", '
        '"unit", "start", "rate": "d/dt formula"} or {"name", "unit", "value": "formula"}] (1-8; snake_case names), '
        '"stages": [{"name","start","end"}], "events": [{"label","when": "condition"}], "focus": variable to plot, '
        '"uncertainty_percent" (0-80, varies params for a band), "scene": {"type": "grow"|"fill"|"dots", "size": '
        'variable, "max": number, "color": variable, "color_max": number, "from": "#hex", "to": "#hex", "label"}}. '
        'Formulas use bare names (t, setting names, variable names — not params.x), + - * / ** %, comparisons, '
        'and/or, x if c else y, and min max abs exp log sqrt sin cos tan tanh floor ceil round pow sign sigmoid '
        'clamp(x,lo,hi) between(t,a,b) ramp(t,a,b) logistic(x,mid,k) pulse(t,at,width) step(x,at) lerp(a,b,k). '
        'Growth must level off: write rate = k * (max_value - x) or logistic forms, never plain k * x over a long '
        'duration; give each variable a realistic max. Use realistic, well-known magnitudes (an apple is ~7-8 cm, '
        'a tree ~3-5 m) and say the model is illustrative. Pick a scene: grow for fruit/plants/'
        'tumours/balloons, fill for tanks/batteries/reservoirs, dots for populations/crowds/infections.\n'
        ' • goal, savings, forex, outage, trade_stress — the same parameters as scenario_simulator.\n'
        ' • backtest — trading_lab backtest parameters (symbol, interval, strategy e.g. sweep_mss_breaker, '
        'past_days, rr, account_balance, risk_percent, spread, side, stop_at…).\n'
        'goal: set/replace the success condition (goal_metric, goal_op >,>=,<,<=, goal_value). Metrics — process: '
        'any variable (final value) or event label (when it happened); goal: finish_day, done_by_deadline_percent; '
        'savings: final_balance, reach_target_percent; backtest: net_pnl, return_percent, total_r, win_rate_percent, '
        'profit_factor, max_drawdown_r, trades.\n'
        'change: changes_json with only what changed, e.g. {"water": 0.5}, {"rr": 3}, {"side": "invert"}, '
        '{"focus": "sugar_percent"}.\n'
        'search: param + values (≤8) — tries them in order as a montage and stops at the first success ("run '
        'through options until it works").\n'
        'show: put the current attempt back on the board. status: settings and attempt log. reset: end the session.\n'
        'Speak like a lab partner: one short line per attempt ("Attempt four: sunlight ten hours — model successful, '
        'ripe on day 142").'
    ),
    'brief': 'Live iterative simulation of anything (process models, plans, backtests) with attempts and verdicts.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['start', 'change', 'search', 'goal', 'show', 'status', 'reset']},
            'kind': {'type': 'STRING', 'enum': ['process', 'goal', 'savings', 'forex', 'outage', 'trade_stress', 'backtest']},
            'parameters_json': {'type': 'STRING'},
            'changes_json': {'type': 'STRING'},
            'param': {'type': 'STRING'},
            'values': {'type': 'ARRAY', 'items': {'type': 'NUMBER'}},
            'values_json': {'type': 'STRING', 'description': 'Values as a JSON list when they are not numbers'},
            'goal_metric': {'type': 'STRING'},
            'goal_op': {'type': 'STRING', 'enum': ['>', '>=', '<', '<=']},
            'goal_value': {'type': 'NUMBER'},
            'label': {'type': 'STRING'},
        },
        'required': ['action'],
    },
    'handler': session,
    'tier': 'core',
}
