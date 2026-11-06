import json
from core import outcome


def simulate(parameters, player=None, **kwargs):
    from core.scenario_simulator import run, save, compare, headline, remember, last, demo, NeedInput
    try:
        if parameters.get('open_lab'):
            return _open_lab()
        if parameters.get('show_last') or not parameters.get('kind') and not parameters.get('close_display'):
            # "Show me the simulation": replay the last one, or a demo study plan if there is none yet.
            result = last()
            source = 'last simulation'
            if result is None:
                result, source = demo(), 'demo (no simulation has been run yet)'
            if player is None or not hasattr(player, 'show_simulation'):
                return outcome.failed('scenario_simulator', 'There is no display in this mode; open_lab opens the live window.')
            player.show_simulation(result)
            return outcome.untrusted('hypothetical-scenario', json.dumps(
                {'shown_on_hologram': True, 'showing': source, 'headline': headline(result)['verdict'],
                 'tip': 'For live sliders, offer open_lab.'}, ensure_ascii=False, allow_nan=False))
        if parameters.get('close_display'):
            if player is None or not hasattr(player, 'show_simulation'):
                return outcome.failed('scenario_simulator', 'There is no display to close in this mode.')
            player.show_simulation(None)
            return outcome.started('scenario_simulator', returning_to='assistant face')
        kind = parameters.get('kind', '')
        base = json.loads(parameters.get('parameters_json', '{}'))
        result = compare(kind, base, json.loads(parameters['alternative_json'])) if parameters.get('alternative_json') else run(kind, base)
        if parameters.get('save_report'):
            result['report_path'] = save(result)
        remember(result)
        shown = False
        if parameters.get('show', True) and player is not None and hasattr(player, 'show_simulation'):
            player.show_simulation(result)
            shown = True
        head = headline(result)
        brief = {'shown_on_hologram': shown, 'headline': head['verdict'],
                 'metrics': {label: value for label, value, _ in head['metrics']}, 'result': result}
        for part in (result, result.get('baseline') or {}, result.get('alternative') or {}):
            for key in ('renamed_parameters', 'defaults_used'):        # say what was assumed, up front
                if part.get(key):
                    brief.setdefault(key, {}).update(part[key])
        if brief.get('defaults_used'):
            brief['say'] = 'Mention the assumed defaults in one short phrase.'
        return outcome.untrusted('hypothetical-scenario', json.dumps(brief, ensure_ascii=False, allow_nan=False))
    except NeedInput as need:
        return outcome.ask('scenario_simulator', need.question(), kind=need.kind, missing=','.join(need.missing))
    except Exception as exc:
        return outcome.failed('scenario_simulator', str(exc))


_lab = None


def _open_lab():
    """Start the live Simulation Lab window (simulation_live.py) as its own process."""
    global _lab
    import subprocess
    import sys
    from pathlib import Path
    if _lab is not None and _lab.poll() is None:
        return outcome.done('scenario_simulator', lab='already open')
    script = Path(__file__).resolve().parent.parent / 'simulation_live.py'
    _lab = subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import time
    time.sleep(1.5)
    if _lab.poll() is not None:
        return outcome.failed('scenario_simulator', f'The Simulation Lab window closed at once (exit {_lab.returncode}).')
    return outcome.done('scenario_simulator', lab='opened', how='sliders re-run the simulation live')


TOOL = {
    'name': 'scenario_simulator',
    'description': (
        '"Run a simulation": bounded local what-if models, played on the holographic simulation board in the HUD '
        '(show=true by default; close_display=true returns to the face). Never contacts brokers or systems. '
        '"Show me the simulation" with no numbers → show_last=true (replays the last one, or a demo). '
        '"Open the simulation lab / live simulation / dashboard" → open_lab=true (a window with sliders that re-runs '
        'live). Only pass the parameters listed for the kind; anything else is ignored. '
        'kind goal (study plans, certifications like OSCP, fitness or project hours): parameters_json requires '
        'total_hours, hours_per_day; optional consistency_percent=80 (share of days actually worked), hours_done=0, '
        'deadline_days, daily_variation_percent=25, max_days=1095. If the user does not know total_hours, ask, or '
        'state clearly that any figure you offer is a rough assumption they must confirm. '
        'kind savings: monthly_contribution, months; optional start_balance, annual_return_percent, '
        'annual_volatility_percent, target. '
        'kind forex: start_rate, annual_return_percent, annual_volatility_percent; optional days=90, paths=1000, '
        'shock_percent=0, seed=42. kind trade_stress: equity, units, pair_start, pair_move_percent, quote_to_account; '
        'optional spread_cost, slippage_cost, direction long/short. kind outage: requests_per_minute, outage_minutes, '
        'affected_percent, capacity_per_minute; optional retry_percent, backlog_before. '
        'All return/volatility assumptions must come from the user; never invent expected returns or give investment '
        'advice. alternative_json holds only the changed assumptions for a baseline-vs-alternative comparison ("what '
        'if I did 4 hours instead?"). save_report stores a private JSON report. Speak the headline briefly, mention it '
        'is a hypothetical model, not a forecast.'
    ),
    'brief': 'What-if simulations (goal timelines, savings, forex, outage) on the holographic board.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'kind': {'type': 'STRING', 'enum': ['goal', 'savings', 'forex', 'trade_stress', 'outage']},
            'parameters_json': {'type': 'STRING'},
            'alternative_json': {'type': 'STRING'},
            'save_report': {'type': 'BOOLEAN'},
            'show': {'type': 'BOOLEAN'},
            'close_display': {'type': 'BOOLEAN'},
            'show_last': {'type': 'BOOLEAN'},
            'open_lab': {'type': 'BOOLEAN'},
        },
        'required': [],
    },
    'handler': simulate,
    'tier': 'core',
}
