"""Simulate any process from a small spec JARVIS writes: "an apple growing on a tree".

A spec is plain data — no code runs. Formulas are parsed with a whitelist (numbers, the
spec's own names, arithmetic, comparisons and a few maths functions), so a model can
describe growth, decay, populations, queues or chemistry and nothing else.

    {
      "title": "Apple growing on the tree",
      "time_unit": "days", "duration": 150, "steps": 300,
      "params":    {"sunlight_hours": 8, "water": 1.0, "temperature": 20},
      "variables": [
        {"name": "diameter_mm", "unit": "mm", "start": 2,
         "rate": "0.06 * (80 - diameter_mm) * min(1, sunlight_hours / 8) * water * between(t, 20, 140)"},
        {"name": "sugar_percent", "unit": "%", "start": 2, "rate": "0.08 * between(t, 90, 150) * (16 - sugar_percent) / 10"},
        {"name": "red_percent", "unit": "%", "value": "clamp((t - 110) * 2.5, 0, 100) * min(1, sunlight_hours / 6)"}
      ],
      "stages": [{"name": "bloom", "start": 0, "end": 12}, …],
      "events": [{"label": "ripe", "when": "sugar_percent >= 12 and red_percent >= 60"}],
      "focus": "diameter_mm",
      "uncertainty_percent": 10,
      "scene": {"type": "grow", "size": "diameter_mm", "max": 80, "color": "red_percent",
                "from": "#7cc242", "to": "#d62828", "label": "apple"}
    }

variables: "rate" is d/dt (integrated), "value" is computed directly each step; later
variables can use earlier ones. uncertainty_percent runs many paths with each param
varied by that much and shows the 5th–95th percentile band of the focus variable.
"""
from __future__ import annotations

import ast
import math
import re

import numpy as np

MAX_STEPS = 2000
MAX_VARS = 8
MAX_PATHS = 200
_NAME = re.compile(r'^[a-z_][a-z0-9_]{0,40}$')

_FUNCS = {
    'min': min, 'max': max, 'abs': abs, 'exp': math.exp, 'log': lambda x: math.log(max(x, 1e-12)),
    'sqrt': lambda x: math.sqrt(max(x, 0)), 'sin': math.sin, 'cos': math.cos, 'tanh': math.tanh,
    'clamp': lambda x, lo, hi: max(lo, min(hi, x)),
    'between': lambda t, a, b: 1.0 if a <= t < b else 0.0,            # 1 inside [a, b), else 0
    'ramp': lambda t, a, b: 0.0 if t <= a else 1.0 if t >= b else (t - a) / (b - a),
    'logistic': lambda x, mid, k: 1 / (1 + math.exp(-k * (x - mid))),
    'pulse': lambda t, at, width: math.exp(-((t - at) / max(width, 1e-9)) ** 2),
}
_CONST = {'pi': math.pi, 'e': math.e, 'true': 1.0, 'false': 0.0}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b if b else 0.0, ast.Pow: lambda a, b: a ** b if abs(b) <= 10 else 0.0,
        ast.Mod: lambda a, b: a % b if b else 0.0}
_CMP = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b, ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


class Formula:
    """A whitelisted arithmetic expression, compiled once and evaluated many times."""

    def __init__(self, text: str, names: set[str]):
        text = str(text or '0').strip()
        if len(text) > 600:
            raise ValueError('A formula is limited to 600 characters.')
        try:
            self.tree = ast.parse(text.replace('^', '**'), mode='eval').body
        except SyntaxError:
            raise ValueError(f'Could not read the formula: {text}') from None
        self.text = text
        self._check(self.tree, names)

    def _check(self, node, names):
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise ValueError('Formulas use numbers only.')
        elif isinstance(node, ast.Name):
            if node.id not in names and node.id not in _CONST and node.id != 't':
                raise ValueError(f'Unknown name "{node.id}" in formula: {self.text}')
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            self._check(node.left, names); self._check(node.right, names)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            self._check(node.operand, names)
        elif isinstance(node, ast.BoolOp):
            for v in node.values:
                self._check(v, names)
        elif isinstance(node, ast.Compare) and all(type(o) in _CMP for o in node.ops):
            self._check(node.left, names)
            for v in node.comparators:
                self._check(v, names)
        elif isinstance(node, ast.IfExp):
            for v in (node.test, node.body, node.orelse):
                self._check(v, names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            for a in node.args:
                self._check(a, names)
        else:
            raise ValueError(f'Formulas may only use arithmetic, comparisons and {", ".join(sorted(_FUNCS))}: {self.text}')

    def __call__(self, env: dict) -> float:
        try:
            return float(self._eval(self.tree, env))
        except (OverflowError, ZeroDivisionError, ValueError, TypeError) as exc:
            raise ValueError(f'The formula "{self.text}" could not be calculated ({exc}); it may grow too fast.') from None

    def _eval(self, n, env):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            return env[n.id] if n.id in env else _CONST[n.id]
        if isinstance(n, ast.BinOp):
            return _BIN[type(n.op)](self._eval(n.left, env), self._eval(n.right, env))
        if isinstance(n, ast.UnaryOp):
            v = self._eval(n.operand, env)
            return -v if isinstance(n.op, ast.USub) else (not v) if isinstance(n.op, ast.Not) else v
        if isinstance(n, ast.BoolOp):
            vals = [self._eval(v, env) for v in n.values]
            return float(all(vals) if isinstance(n.op, ast.And) else any(vals))
        if isinstance(n, ast.Compare):
            left = self._eval(n.left, env)
            for op, right in zip(n.ops, n.comparators):
                r = self._eval(right, env)
                if not _CMP[type(op)](left, r):
                    return 0.0
                left = r
            return 1.0
        if isinstance(n, ast.IfExp):
            return self._eval(n.body, env) if self._eval(n.test, env) else self._eval(n.orelse, env)
        return _FUNCS[n.func.id](*[self._eval(a, env) for a in n.args])


def _num(v, name):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number.') from None
    if not math.isfinite(x):
        raise ValueError(f'{name} must be finite.')
    return x


def compile_spec(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError('Describe the process as a spec object.')
    duration = _num(spec.get('duration', 100), 'duration')
    if not 0 < duration <= 1e7:
        raise ValueError('duration must be above zero.')
    steps = int(_num(spec.get('steps', 300), 'steps'))
    steps = max(20, min(MAX_STEPS, steps))
    params = {}
    for k, v in (spec.get('params') or {}).items():
        if not _NAME.match(str(k)):
            raise ValueError(f'Setting names use lowercase letters, digits and _: {k}')
        params[str(k)] = _num(v, k)
    raw = list(spec.get('variables') or [])
    if not 1 <= len(raw) <= MAX_VARS:
        raise ValueError(f'Give 1 to {MAX_VARS} variables.')
    names = set(params)
    variables = []
    for v in raw:
        name = str(v.get('name', ''))
        if not _NAME.match(name) or name in names or name == 't':
            raise ValueError(f'Bad or repeated variable name: {name!r}')
        names.add(name)
    for v in raw:                                            # formulas may refer to any variable or setting
        kind = 'rate' if 'rate' in v else 'value'
        variables.append({'name': v['name'], 'unit': str(v.get('unit', ''))[:12], 'kind': kind,
                          'start': _num(v.get('start', 0), v['name'] + ' start'),
                          'f': Formula(v.get(kind, '0'), names),
                          'min': None if v.get('min') is None else _num(v['min'], 'min'),
                          'max': None if v.get('max') is None else _num(v['max'], 'max')})
    events = [{'label': str(e.get('label', 'event'))[:40], 'f': Formula(e.get('when', '0'), names)}
              for e in (spec.get('events') or [])[:8]]
    stages = []
    for s in (spec.get('stages') or [])[:10]:
        a, b = _num(s.get('start', 0), 'stage start'), _num(s.get('end', duration), 'stage end')
        if b > a:
            stages.append({'name': str(s.get('name', ''))[:24], 'start': a, 'end': min(b, duration)})
    focus = str(spec.get('focus') or variables[0]['name'])
    if focus not in [v['name'] for v in variables]:
        raise ValueError(f'focus must be one of the variables: {", ".join(v["name"] for v in variables)}')
    unc = max(0.0, min(80.0, _num(spec.get('uncertainty_percent', 0), 'uncertainty_percent')))
    return {'title': str(spec.get('title') or 'Process')[:60], 'unit': str(spec.get('time_unit') or 'steps')[:12],
            'duration': duration, 'steps': steps, 'params': params, 'variables': variables, 'events': events,
            'stages': stages, 'focus': focus, 'uncertainty': unc, 'paths': int(spec.get('paths', 60)),
            'seed': int(_num(spec.get('seed', 42), 'seed')), 'scene': spec.get('scene') if isinstance(spec.get('scene'), dict) else None}


def _path(c, params):
    """One run: every variable sampled at every step, and when each event first happened."""
    dt = c['duration'] / c['steps']
    state = {v['name']: v['start'] for v in c['variables']}
    env = {**params, **state, 't': 0.0}
    for v in c['variables']:
        if v['kind'] == 'value':
            env[v['name']] = state[v['name']] = v['f'](env)
    out = {v['name']: [state[v['name']]] for v in c['variables']}
    events = {e['label']: None for e in c['events']}
    for step in range(1, c['steps'] + 1):
        t = step * dt
        env = {**params, **state, 't': t}
        for v in c['variables']:
            if v['kind'] == 'rate':
                x = state[v['name']] + v['f'](env) * dt
            else:
                x = v['f'](env)
            if v['min'] is not None:
                x = max(v['min'], x)
            if v['max'] is not None:
                x = min(v['max'], x)
            if not math.isfinite(x):
                raise ValueError(f"{v['name']} ran off to infinity; check its formula.")
            state[v['name']] = env[v['name']] = x
            out[v['name']].append(x)
        for e in c['events']:
            if events[e['label']] is None and e['f'](env):
                events[e['label']] = t
    return out, events


def simulate(spec: dict) -> dict:
    c = compile_spec(spec)
    base, base_events = _path(c, c['params'])
    times = [c['duration'] * k / c['steps'] for k in range(c['steps'] + 1)]
    picks = sorted(set(np.linspace(0, c['steps'], min(61, c['steps'] + 1), dtype=int)))
    focus = c['focus']
    paths = []
    if c['uncertainty'] > 0:
        rng = np.random.default_rng(c['seed'])
        n = max(20, min(MAX_PATHS, c['paths']))
        for _ in range(n):
            varied = {k: v * float(rng.normal(1, c['uncertainty'] / 100)) for k, v in c['params'].items()}
            paths.append(_path(c, varied)[0][focus])
    fan = []
    for k in picks:
        med = base[focus][k]
        if paths:
            col = [p[k] for p in paths]
            lo, hi = float(np.percentile(col, 5)), float(np.percentile(col, 95))
        else:
            lo = hi = med
        fan.append({'day': round(times[k], 6), 'p05': min(lo, med), 'median': med, 'p95': max(hi, med)})
    units = {v['name']: v['unit'] for v in c['variables']}
    finals = {v['name']: base[v['name']][-1] for v in c['variables']}
    return {'kind': 'process', 'title': c['title'], 'x_unit': c['unit'], 'y_unit': units[focus], 'focus': focus,
            'target': None, 'fan_chart': fan,
            'band_label': 'line = ' + focus.replace('_', ' ') + ('  ·  band = 5th–95th with settings varied ±%g%%' % c['uncertainty']
                                                                 if paths else ''),
            'series': {name: [round(base[name][k], 6) for k in picks] for name in base},
            'series_t': [round(times[k], 6) for k in picks], 'units': units, 'finals': finals,
            'events': [{'label': k, 'at': v} for k, v in base_events.items()],
            'stages': c['stages'], 'scene': c['scene'],
            'assumptions': {'settings': c['params'], 'duration': c['duration'], 'time_unit': c['unit'],
                            'uncertainty_percent': c['uncertainty'], 'paths': len(paths) or None, 'seed': c['seed']},
            'formulas': {v['name']: (v['kind'], v['f'].text) for v in c['variables']},
            'method': 'Step-by-step model JARVIS wrote from your description: rate formulas are integrated, value formulas computed each step.',
            'limits': 'An illustrative model built from general knowledge, not measured data or a scientific prediction.'}


def headline(r: dict) -> dict:
    units, finals = r.get('units', {}), r.get('finals', {})
    m = []
    for name, val in list(finals.items())[:4]:
        u = units.get(name, '')
        m.append((('FINAL ' if name != r.get('focus') else '▶ ') + name.replace('_', ' ').upper(),
                  f"{val:,.1f} {u}".strip(), 'pri' if name == r.get('focus') else 'dim'))
    for e in r.get('events', [])[:2]:
        m.append((e['label'].upper(), f"{r.get('x_unit', '')[:-1] if r.get('x_unit', '').endswith('s') else r.get('x_unit', '')} {e['at']:,.0f}".strip()
                  if e['at'] is not None else 'did not happen', 'green' if e['at'] is not None else 'red'))
    ev = '; '.join(f"{e['label']} at {e['at']:,.0f} {r.get('x_unit', '')}" if e['at'] is not None else f"no {e['label']}"
                   for e in r.get('events', [])[:3])
    f = r.get('focus', '')
    verdict = (f"{r.get('title', 'Process')}: {f.replace('_', ' ')} reaches {finals.get(f, 0):,.1f} {units.get(f, '')} by "
               f"{r.get('assumptions', {}).get('duration', 0):,.0f} {r.get('x_unit', '')}" + (f"; {ev}" if ev else '') + '.')
    return {'title': r.get('title', 'PROCESS').upper(), 'metrics': m, 'verdict': verdict}
