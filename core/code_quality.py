"""Write code, check it, run it, repair it: the loop every JARVIS coding tool goes through.

static_check(language, code)  real checkers where they exist (Python compile + pyflakes +
                               import resolution, node --check, clang -fsyntax-only, bash -n,
                               JSON parse) and rule-based linters for Pine Script and MQL.
run_file(path, ...)            execution judged by exit code, not by words in the output.
generate(goal, language, ...)  model writes → checks → repairs with the exact findings,
                               then optionally runs and repairs with the real traceback,
                               until clean or out of rounds. Long files are continued when
                               the model hits its output limit instead of arriving truncated.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

LANG_ALIASES = {'py': 'python', 'python3': 'python', 'js': 'javascript', 'node': 'javascript', 'ts': 'typescript',
                'pinescript': 'pine', 'pine script': 'pine', 'tradingview': 'pine', 'sh': 'bash', 'shell': 'bash',
                'zsh': 'bash', 'c++': 'cpp', 'mq5': 'mql5', 'mq4': 'mql4', 'htm': 'html'}
EXT = {'python': '.py', 'javascript': '.js', 'typescript': '.ts', 'html': '.html', 'css': '.css', 'json': '.json',
       'bash': '.sh', 'c': '.c', 'cpp': '.cpp', 'java': '.java', 'go': '.go', 'rust': '.rs', 'sql': '.sql',
       'pine': '.pine', 'mql5': '.mq5', 'mql4': '.mq4', 'powershell': '.ps1', 'ruby': '.rb', 'php': '.php'}


def norm_lang(language: str) -> str:
    lang = str(language or 'python').strip().lower()
    return LANG_ALIASES.get(lang, lang)


# ── extracting code from a model reply ──────────────────────────────────────

def extract_code(text: str) -> str:
    """The code in a reply: the largest fenced block, or the whole reply when unfenced."""
    text = (text or '').strip()
    blocks = re.findall(r'```[^\n`]*\n(.*?)```', text, re.S)
    if blocks:
        return max(blocks, key=len).strip('\n') + '\n'
    text = re.sub(r'^```[^\n]*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip('\n') + '\n'


# ── static checks ───────────────────────────────────────────────────────────

_PLACEHOLDER = re.compile(r'#\s*(TODO|FIXME)\b|//\s*(TODO|FIXME)\b|your (code|logic|implementation) here|'
                          r'implement (this|me|the rest)|\.\.\.\s*rest of (the )?code', re.I)
_PYFLAKES_ERRORS = ('UndefinedName', 'UndefinedLocal', 'UndefinedExport', 'DuplicateArgument', 'ReturnOutsideFunction',
                    'YieldOutsideFunction', 'ContinueOutsideLoop', 'BreakOutsideLoop', 'TooManyExpressionsInStarredAssignment',
                    'TwoStarredExpressions', 'StringDotFormatExtraPositionalArguments', 'StringDotFormatMissingArgument',
                    'PercentFormatMissingArgument', 'PercentFormatExtraNamedArguments', 'ForwardAnnotationSyntaxError',
                    'DefaultExceptNotLast', 'IsLiteral', 'InvalidPrintSyntax', 'RaiseNotImplemented')


def _python(code, known_modules=()):
    errors, warnings, missing = [], [], []
    try:
        tree = compile(code, '<generated>', 'exec', flags=ast.PyCF_ONLY_AST, dont_inherit=True)
        compile(code, '<generated>', 'exec', dont_inherit=True)
    except SyntaxError as exc:
        last = len(code.rstrip().splitlines())
        cut = exc.lineno and exc.lineno >= last - 1 and ('EOF' in str(exc.msg) or 'was never closed' in str(exc.msg))
        errors.append(f'SyntaxError line {exc.lineno}: {exc.msg}' + (' (the file looks cut off at the end)' if cut else ''))
        return errors, warnings, missing
    try:
        from pyflakes import api as flakes_api, reporter as flakes_reporter

        class Collect(flakes_reporter.Reporter):
            def __init__(self):
                self.items = []

            def unexpectedError(self, filename, msg):
                self.items.append(('error', str(msg)))

            def syntaxError(self, filename, msg, lineno, offset, text):
                self.items.append(('error', f'line {lineno}: {msg}'))

            def flake(self, message):
                kind = 'error' if type(message).__name__ in _PYFLAKES_ERRORS else 'warning'
                self.items.append((kind, f'line {message.lineno}: {message.message % message.message_args}'))

        rep = Collect()
        flakes_api.check(code, 'generated.py', rep)
        for kind, msg in rep.items:
            (errors if kind == 'error' else warnings).append(msg)
    except ImportError:
        warnings.append('pyflakes not installed: undefined names were not checked')
    local = {m.split('.')[0] for m in known_modules}
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            top = name.split('.')[0]
            if top in local or top in missing:
                continue
            try:
                if importlib.util.find_spec(top) is None:
                    missing.append(top)
            except (ImportError, ValueError):
                missing.append(top)
    return errors, warnings, missing


def _tool(cmd, code, suffix):
    if not shutil.which(cmd[0]):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / ('check' + suffix)
        p.write_text(code, encoding='utf-8')
        try:
            r = subprocess.run(cmd + [str(p)], capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return ['checker timed out']
        out = (r.stderr or r.stdout).replace(str(p), 'file')
        return [] if r.returncode == 0 else [line for line in out.splitlines() if line.strip()][:12]


class _Tags(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr',
            'p', 'li', 'option', 'td', 'th', 'tr', 'thead', 'tbody', 'dt', 'dd'}

    def __init__(self):
        super().__init__(); self.stack, self.problems = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if tag in [t for t, _ in self.stack]:
            while self.stack and self.stack[-1][0] != tag:
                t, line = self.stack.pop(); self.problems.append(f'<{t}> opened on line {line} is never closed')
            self.stack.pop()
        else:
            self.problems.append(f'</{tag}> on line {self.getpos()[0]} has no matching opening tag')


def _balance(code, pairs='(){}[]'):
    """Bracket balance ignoring strings and comments (C-like and Pine syntax)."""
    stripped = re.sub(r'//[^\n]*|/\*.*?\*/', '', code, flags=re.S)
    stripped = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', '""', stripped)
    stack, problems = [], []
    opens, closes = pairs[0::2], pairs[1::2]
    for n, line in enumerate(stripped.splitlines(), 1):
        for ch in line:
            if ch in opens:
                stack.append((ch, n))
            elif ch in closes:
                want = opens[closes.index(ch)]
                if not stack or stack[-1][0] != want:
                    problems.append(f"line {n}: unexpected '{ch}'"); continue
                stack.pop()
    problems += [f"line {n}: '{ch}' is never closed" for ch, n in stack[:5]]
    return problems[:8]


_PINE_V4 = {'sma': 'ta.sma', 'ema': 'ta.ema', 'rma': 'ta.rma', 'wma': 'ta.wma', 'vwma': 'ta.vwma', 'rsi': 'ta.rsi',
            'atr': 'ta.atr', 'tr': 'ta.tr', 'crossover': 'ta.crossover', 'crossunder': 'ta.crossunder', 'cross': 'ta.cross',
            'highest': 'ta.highest', 'lowest': 'ta.lowest', 'highestbars': 'ta.highestbars', 'lowestbars': 'ta.lowestbars',
            'stdev': 'ta.stdev', 'pivothigh': 'ta.pivothigh', 'pivotlow': 'ta.pivotlow', 'change': 'ta.change',
            'valuewhen': 'ta.valuewhen', 'barssince': 'ta.barssince', 'macd': 'ta.macd', 'stoch': 'ta.stoch',
            'rising': 'ta.rising', 'falling': 'ta.falling', 'cum': 'ta.cum', 'vwap': 'ta.vwap', 'bb': 'ta.bb',
            'security': 'request.security', 'study': 'indicator', 'tostring': 'str.tostring', 'abs': 'math.abs',
            'max': 'math.max', 'min': 'math.min', 'round': 'math.round', 'pow': 'math.pow', 'sqrt': 'math.sqrt',
            'log': 'math.log', 'avg': 'math.avg', 'sum': 'math.sum', 'iff': 'the ?: ternary operator'}
_PINE_GLOBAL_ONLY = ('plot', 'plotshape', 'plotchar', 'plotarrow', 'plotcandle', 'plotbar', 'bgcolor', 'barcolor',
                     'hline', 'fill', 'indicator', 'strategy', 'library')


_IN = 'defval,title,tooltip,inline,group,confirm,display,active'
_PINE_KWARGS = {
    'plot': 'series,title,color,linewidth,style,trackprice,histbase,offset,join,editable,show_last,display,format,precision,force_overlay',
    'plotshape': 'series,title,style,location,color,offset,text,textcolor,editable,size,show_last,display,format,precision,force_overlay',
    'plotchar': 'series,title,char,location,color,offset,text,textcolor,editable,size,show_last,display,format,precision,force_overlay',
    'plotarrow': 'series,title,colorup,colordown,offset,minheight,maxheight,editable,show_last,display,format,precision,force_overlay',
    'bgcolor': 'color,offset,editable,show_last,title,display,force_overlay',
    'barcolor': 'color,offset,editable,show_last,title,display',
    'hline': 'price,title,color,linestyle,linewidth,editable,display',
    'fill': 'hline1,hline2,plot1,plot2,color,title,editable,fillgaps,display,top_value,bottom_value,top_color,bottom_color',
    'alertcondition': 'condition,title,message',
    'alert': 'message,freq',
    'indicator': 'title,shorttitle,overlay,format,precision,scale,max_bars_back,timeframe,timeframe_gaps,explicit_plot_zorder,'
                 'max_lines_count,max_labels_count,max_boxes_count,calc_bars_count,max_polylines_count,dynamic_requests,behind_chart',
    'strategy': 'title,shorttitle,overlay,format,precision,scale,pyramiding,calc_on_order_fills,calc_on_every_tick,max_bars_back,'
                'backtest_fill_limits_assumption,default_qty_type,default_qty_value,initial_capital,currency,slippage,commission_type,'
                'commission_value,process_orders_on_close,close_entries_rule,margin_long,margin_short,explicit_plot_zorder,'
                'max_lines_count,max_labels_count,max_boxes_count,calc_bars_count,risk_free_rate,use_bar_magnifier,'
                'fill_orders_on_standard_ohlc,max_polylines_count,dynamic_requests,behind_chart',
    'strategy.entry': 'id,direction,qty,limit,stop,oca_name,oca_type,comment,alert_message,disable_alert,when',
    'strategy.order': 'id,direction,qty,limit,stop,oca_name,oca_type,comment,alert_message,disable_alert,when',
    'strategy.exit': 'id,from_entry,qty,qty_percent,profit,limit,loss,stop,trail_price,trail_points,trail_offset,oca_name,comment,'
                     'comment_profit,comment_loss,comment_trailing,alert_message,alert_profit,alert_loss,alert_trailing,disable_alert,when',
    'strategy.close': 'id,comment,qty,qty_percent,alert_message,immediately,disable_alert,when',
    'strategy.close_all': 'comment,alert_message,immediately,disable_alert,when',
    'line.new': 'x1,y1,x2,y2,xloc,extend,color,style,width,force_overlay,first_point,second_point',
    'label.new': 'x,y,text,xloc,yloc,color,style,textcolor,size,textalign,tooltip,text_font_family,force_overlay,text_formatting,point',
    'box.new': 'left,top,right,bottom,border_color,border_width,border_style,extend,xloc,bgcolor,text,text_size,text_color,'
               'text_halign,text_valign,text_wrap,text_font_family,force_overlay,text_formatting,top_left,bottom_right',
    'table.new': 'position,columns,rows,bgcolor,frame_color,frame_width,border_color,border_width,force_overlay',
    'input.int': _IN + ',minval,maxval,step,options', 'input.float': _IN + ',minval,maxval,step,options',
    'input.bool': _IN, 'input.string': _IN + ',options', 'input.source': _IN, 'input.session': _IN + ',options',
    'input.color': _IN, 'input.timeframe': _IN + ',options', 'input.time': _IN, 'input.price': _IN, 'input.symbol': _IN,
    'input.text_area': _IN, 'input': _IN + ',minval,maxval,step,options',
    'request.security': 'symbol,timeframe,expression,gaps,lookahead,ignore_invalid_symbol,currency,calc_bars_count',
    'color.new': 'color,transp', 'color.rgb': 'red,green,blue,transp',
    'time': 'timeframe,session,timezone,bars_back,timeframe_bars_back',
}
_PINE_KWARGS = {k: set(v.split(',')) for k, v in _PINE_KWARGS.items()}


def _pine_calls(text):
    """(name, line, keyword-argument names) for each call of a function we know the signature of."""
    names = sorted(_PINE_KWARGS, key=len, reverse=True)
    pat = re.compile(r'(?<![\w.])(' + '|'.join(re.escape(n) for n in names) + r')\s*\(')
    for m in pat.finditer(text):
        depth, i, start, kws = 1, m.end(), m.end(), []
        while i < len(text) and depth:
            ch = text[i]
            if ch in '([':
                depth += 1
            elif ch in ')]':
                depth -= 1
            elif depth == 1 and ch == ',' or depth == 0:
                pass
            i += 1
        inner = text[start:i - 1]
        depth, seg = 0, ''
        for ch in inner + ',':
            if ch in '([':
                depth += 1
            elif ch in ')]':
                depth -= 1
            if ch == ',' and depth == 0:
                km = re.match(r'\s*([A-Za-z_]\w*)\s*=(?!=)', seg)
                if km:
                    kws.append(km.group(1))
                seg = ''
            else:
                seg += ch
        yield m.group(1), text[:m.start()].count('\n') + 1, kws


def _pine(code):
    errors, warnings = [], []
    body = re.sub(r'//[^\n]*', '', code)
    body_nostr = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', '""', body)
    m = re.search(r'^//@version=(\d+)', code, re.M)
    if not m:
        errors.append('first line must be //@version=5 (or 6)')
    elif int(m.group(1)) < 5:
        errors.append(f'//@version={m.group(1)} is outdated; write version 5 or 6 syntax')
    decls = re.findall(r'^(indicator|strategy|library)\s*\(', body_nostr, re.M)
    if not decls:
        errors.append('missing indicator(), strategy() or library() declaration at the top level')
    elif len(set(decls)) > 1 or len(decls) > 1:
        errors.append('only one declaration statement (indicator/strategy/library) is allowed')
    if decls and decls[0] == 'indicator' and re.search(r'\bstrategy\.(entry|exit|close|order|cancel)\b', body_nostr):
        errors.append('strategy.* order calls require strategy(), not indicator()')
    for old, new in _PINE_V4.items():
        for hit in re.finditer(r'(?<![\w.])' + old + r'\s*\(', body_nostr):
            line = body_nostr[:hit.start()].count('\n') + 1
            if old in ('max', 'min', 'abs', 'round', 'sum', 'avg', 'log', 'pow', 'sqrt'):
                # Only an error when no user function of that name exists.
                if re.search(r'^' + old + r'\s*\([^)]*\)\s*=>', body_nostr, re.M):
                    continue
            errors.append(f'line {line}: {old}() is version-4 syntax; use {new}')
            break
    for n, line in enumerate(body_nostr.splitlines(), 1):
        if re.match(r'^[ \t]+(' + '|'.join(_PINE_GLOBAL_ONLY) + r')\s*\(', line):
            prev = body_nostr.splitlines()[n - 2] if n > 1 else ''
            if not prev.rstrip().endswith((',', '(', '=', '?', ':', 'and', 'or')):
                errors.append(f'line {n}: {line.strip().split("(")[0]}() cannot be called inside a local block (if/for/function); '
                              'compute the value conditionally and call it at the top level')
        if re.search(r'[=!]=\s*na\b|\bna\s*[=!]=', line):
            errors.append(f'line {n}: comparing with na using == is always false; use na(x) or not na(x)')
        if 'transp=' in line.replace(' ', ''):
            errors.append(f'line {n}: transp= was removed in v5; use color.new(color, transparency)')
        if re.search(r'\blookahead\s*=\s*barmerge\.lookahead_on', line):
            warnings.append(f'line {n}: lookahead_on repaints on historical bars unless the series is offset by [1]')
        if re.search(r'\bwhen\s*=', line):
            warnings.append(f'line {n}: the when= argument is deprecated; wrap the call in an if block')
    for name, line, kws in _pine_calls(body_nostr):
        bad = [k for k in kws if k not in _PINE_KWARGS[name]]
        if bad:
            errors.append(f'line {line}: {name}() has no parameter named {", ".join(bad)}')
    # Drawing objects are not booleans: `if myLine` / `x and myLine` does not compile; use not na(myLine).
    objects = set(re.findall(r'^\s*(?:var\s+)?(?:line|label|box|table|polyline|linefill)\s+(\w+)\s*=', body_nostr, re.M))
    objects |= set(re.findall(r'^\s*(?:var\s+)?(\w+)\s*=\s*(?:line|label|box|table)\.new\s*\(', body_nostr, re.M))
    for obj in objects:
        hit = re.search(r'(?:\bif\s+|\band\s+|\bor\s+|\bnot\s+)' + obj + r'\b(?!\s*[.(\[])|\b' + obj
                        + r'\s+(?:and|or)\b|\b' + obj + r'\s*\?', body_nostr)
        if hit:
            errors.append(f'line {body_nostr[:hit.start()].count(chr(10)) + 1}: {obj} is a drawing object, not a bool; '
                          f'use not na({obj})')
    errors += _balance(code, '()[]')
    return errors, warnings


def _mql(code, version):
    errors, warnings = _balance(code), []
    if not re.search(r'\b(OnTick|OnCalculate|OnStart)\s*\(', code):
        errors.append('needs OnTick() (expert advisor), OnCalculate() (indicator) or OnStart() (script)')
    if version == 'mql5' and re.search(r'\b(OrderSend|OrderSelect)\s*\(\s*Symbol\(\)\s*,\s*OP_', code):
        errors.append('MQL4 OrderSend(Symbol(), OP_BUY, ...) style used in MQL5; use CTrade (trade.Buy/Sell) or MqlTradeRequest')
    return errors, warnings


def static_check(language: str, code: str, known_modules=()) -> dict:
    """Findings that stop code working. errors must be fixed; warnings are worth a look; missing_modules need installing."""
    lang = norm_lang(language)
    errors, warnings, missing, checker = [], [], [], 'none available'
    if not code or not code.strip():
        return {'ok': False, 'language': lang, 'errors': ['empty file'], 'warnings': [], 'missing_modules': [], 'checker': '-'}
    if lang == 'python':
        errors, warnings, missing = _python(code, known_modules); checker = 'python compile + pyflakes + import resolution'
    elif lang in ('javascript', 'typescript'):
        if lang == 'javascript':
            suffix = '.mjs' if re.search(r'^\s*(import|export)\s', code, re.M) else '.js'
            found = _tool(['node', '--check'], code, suffix)
            if found is not None:
                errors, checker = found, 'node --check'
        if checker == 'none available':
            errors, checker = _balance(code), 'bracket balance only'
    elif lang == 'json':
        try:
            json.loads(code); checker = 'json parser'
        except ValueError as exc:
            errors, checker = [str(exc)], 'json parser'
    elif lang == 'bash':
        found = _tool(['bash', '-n'], code, '.sh')
        errors, checker = (found or []), 'bash -n'
    elif lang in ('c', 'cpp'):
        found = _tool(['clang', '-fsyntax-only', '-x', 'c' if lang == 'c' else 'c++'] +
                      ([] if lang == 'c' else ['-std=c++17']), code, '.c' if lang == 'c' else '.cpp')
        if found is not None:
            errors, checker = [e for e in found if 'error' in e][:10], 'clang -fsyntax-only'
    elif lang == 'html':
        t = _Tags(); t.feed(code); t.close()
        errors = t.problems[:8] + [f'<{tag}> opened on line {line} is never closed' for tag, line in t.stack[:5]
                                   if tag not in ('html', 'body', 'head')]
        checker = 'tag balance'
    elif lang == 'css':
        errors, checker = _balance(code, '{}()'), 'brace balance'
    elif lang == 'pine':
        errors, warnings = _pine(code); checker = 'Pine v5/v6 rules linter (TradingView compiles for real)'
    elif lang in ('mql5', 'mql4'):
        errors, warnings = _mql(code, lang); checker = 'MQL structure linter (MetaEditor compiles for real)'
    else:
        errors, checker = _balance(code), 'bracket balance only'
    for n, line in enumerate(code.splitlines(), 1):
        if _PLACEHOLDER.search(line):
            errors.append(f'line {n}: unfinished placeholder ("{line.strip()[:60]}"); write the real implementation')
            break
    return {'ok': not errors and not missing, 'language': lang, 'errors': errors, 'warnings': warnings[:8],
            'missing_modules': missing, 'checker': checker}


# ── running ─────────────────────────────────────────────────────────────────

INTERPRETERS = {'.py': [sys.executable], '.js': ['node'], '.mjs': ['node'], '.sh': ['bash'], '.rb': ['ruby'], '.php': ['php']}


def run_file(path, args=(), timeout=30, stdin_text='') -> dict:
    """Run a file; success is exit code 0. A program still running at the timeout (server, GUI, loop) did not crash."""
    path = Path(path)
    interp = INTERPRETERS.get(path.suffix.lower())
    if not interp or not shutil.which(interp[0]) and interp[0] != sys.executable:
        return {'ok': None, 'ran': False, 'output': f'No interpreter available for {path.suffix} files.'}
    env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'MPLBACKEND': 'Agg'}
    try:
        r = subprocess.run(interp + [str(path)] + list(args), capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=timeout, cwd=str(path.parent), input=stdin_text or '', env=env)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or '') if isinstance(exc.stdout, str) else ''
        return {'ok': True, 'ran': True, 'timed_out': True, 'exit_code': None,
                'output': (out[-1500:] + f'\n[still running after {timeout}s; stopped. No crash before that.]').strip()}
    except FileNotFoundError:
        return {'ok': None, 'ran': False, 'output': f'Interpreter not found: {interp[0]}'}
    out = (r.stdout or '')[-2500:]
    err = (r.stderr or '')[-2500:]
    return {'ok': r.returncode == 0, 'ran': True, 'timed_out': False, 'exit_code': r.returncode,
            'output': '\n'.join(x for x in (out.strip() and 'Output:\n' + out.strip(),
                                            err.strip() and 'Stderr:\n' + err.strip()) if x) or 'Ran with no output.'}


# ── the write → check → run → repair loop ───────────────────────────────────

GENERAL_RULES = '''Rules for the code you write:
- Output the COMPLETE file in one ```fenced block```. No prose outside the block.
- Fully working: no placeholders, no TODO, no "..." gaps, no stub functions, no pseudo-code.
- Every name you use is defined or imported; every import is real and spelled correctly.
- Prefer the standard library. Only use a third-party package when the task needs it.
- Validate inputs and handle the errors that can really happen (files, network, parsing); fail with clear messages.
- Never block waiting for keyboard input unless the task asks for an interactive program.
- Small, clearly named functions; brief comments where the logic is not obvious.'''

LANG_RULES = {
    'python': 'Python 3.10+. Type hints on functions. Put the entry point under if __name__ == "__main__": main(). '
              'Use argparse for command-line options and give every option a sensible default so the script runs '
              'with no arguments where possible.',
    'javascript': 'Modern JavaScript for Node.js 18+ unless a browser is requested. Use const/let, async/await, try/catch.',
    'html': 'A single self-contained HTML5 file with inline CSS and JS, responsive, accessible labels.',
    'pine': 'TradingView Pine Script v5. Start with //@version=5 and exactly one indicator() or strategy() call. Use '
            'namespaced built-ins (ta.*, math.*, str.*, request.*, input.int/float/bool/string). plot/plotshape/bgcolor/'
            'hline/fill only at global scope. Use na(x), never x == na. var for persistent state, := to reassign. '
            'No repainting: pivots are confirmed bars later, request.security without lookahead_on. Inputs for every '
            'tunable number. Indent local blocks with 4 spaces.',
    'mql5': 'MQL5 for MetaTrader 5: #property strict, input parameters, OnInit/OnDeinit/OnTick (EA) or OnCalculate '
            '(indicator), #include <Trade/Trade.mqh> and CTrade for orders, check every return value, normalise prices '
            'with _Digits, respect SYMBOL_VOLUME_MIN/STEP.',
    'mql4': 'MQL4 for MetaTrader 4: #property strict, extern/input parameters, OnInit/OnTick, check OrderSend return values.',
    'bash': 'Bash with set -euo pipefail, quoted variables and a usage message.',
    'cpp': 'C++17, compiles with no warnings, includes every header it uses.',
    'c': 'C11, compiles with no warnings, includes every header it uses, checks every allocation and I/O call.',
}


def ask_model(prompt: str, timeout_ms=180_000, max_tokens=32_768, continuations=3) -> str:
    """One model answer, continued when it stops at the output limit, so long files are not truncated."""
    from core import gemini
    text = ''
    current = prompt
    for _ in range(continuations + 1):
        resp = gemini.call(current, tier=gemini.SMART, timeout_ms=timeout_ms, config={'max_output_tokens': max_tokens})
        if resp is None:
            if text:
                break
            raise RuntimeError('No AI model answered the coding request (quota or network). Try again shortly.')
        chunk = getattr(resp, 'text', None) or ''
        text += chunk
        reason = ''
        try:
            reason = str(resp.candidates[0].finish_reason)
        except Exception:
            pass
        if 'MAX_TOKENS' not in reason.upper():
            break
        current = (prompt + '\n\nYour previous answer stopped at the output limit. Here is what you wrote so far:\n'
                   + text[-12000:] + '\n\nContinue EXACTLY where it stopped. Output only the continuation, no repetition, '
                   'and close the code block when the file is complete.')
    return text


def build_prompt(goal: str, language: str, context: str = '', existing: str = '') -> str:
    lang = norm_lang(language)
    parts = [f'You are a senior {lang} engineer. Write production-quality {lang} code.', GENERAL_RULES,
             LANG_RULES.get(lang, '')]
    if context:
        parts.append('Context:\n' + context)
    if existing:
        parts.append('Current file to modify (return the whole updated file):\n```\n' + existing + '\n```')
    parts.append('Task:\n' + goal)
    return '\n\n'.join(p for p in parts if p)


def repair_prompt(goal: str, language: str, code: str, findings: list[str], context: str = '') -> str:
    lang = norm_lang(language)
    listed = '\n'.join(f'- {f}' for f in findings[:20])
    return (f'You are a senior {lang} engineer fixing code that failed checks.\n\n{GENERAL_RULES}\n{LANG_RULES.get(lang, "")}\n\n'
            + (f'Context:\n{context}\n\n' if context else '')
            + f'Original task:\n{goal}\n\nProblems found (fix every one, change nothing that already works, '
              f'keep the same features):\n{listed}\n\nCurrent code:\n```\n{code}\n```\n\nReturn the complete corrected file.')


NO_COMPILER = {'pine', 'mql5', 'mql4', 'typescript', 'java', 'go', 'rust', 'sql', 'powershell', 'ruby', 'php'}


def review(goal: str, language: str, code: str) -> list[str]:
    """A strict second read for languages with no checker here. Returns definite compile/runtime errors only."""
    lang = norm_lang(language)
    prompt = (f'You are a strict {lang} compiler and reviewer. Check the code below against the official {lang} '
              f'language reference ({LANG_RULES.get(lang, "")}). List ONLY definite errors that would stop it compiling '
              'or make it behave wrongly for the task: wrong parameter names, wrong argument types, undeclared variables, '
              'functions that do not exist in this language version, type misuse (e.g. using an object as a bool), '
              'scope rules, and logic that contradicts the task. Do not list style preferences. Report only errors you are '
              'CERTAIN of from the reference; if unsure whether a built-in exists, assume it does and do not report it.\n'
              'Reply with JSON only: {"errors": ["line N: problem and fix", ...]} and an empty list if it is correct.\n\n'
              f'Task:\n{goal}\n\nCode:\n```\n{code}\n```')
    try:
        raw = ask_model(prompt, timeout_ms=90_000, max_tokens=4096, continuations=0)
        raw = raw[raw.find('{'): raw.rfind('}') + 1]
        found = json.loads(raw).get('errors', [])
        return [str(e)[:300] for e in found if str(e).strip()][:10]
    except Exception:
        return []


def generate(goal: str, language: str, *, context: str = '', existing: str = '', runner=None,
             max_rounds: int = 4, known_modules=(), log=print, strict_warnings=False) -> tuple[str, dict]:
    """Write code and keep repairing it until static checks (and the runner, if given) pass.

    runner(code) -> dict with ok (True/False/None) and output. It is only called once static checks pass.
    Returns (code, report). report['ok'] is True only when every check that could run passed."""
    lang = norm_lang(language)
    code = extract_code(ask_model(build_prompt(goal, lang, context, existing)))
    rounds, history, check, ran, reviews = 0, [], None, None, 0
    for rounds in range(1, max_rounds + 1):
        check = static_check(lang, code, known_modules)
        findings = list(check['errors'])
        if strict_warnings:
            findings += check['warnings']
        if check['missing_modules']:
            findings.append('these imports are not installed: ' + ', '.join(check['missing_modules'])
                            + '. Use the standard library instead unless the task truly needs them.')
        ran = None
        if not findings and runner is not None:
            ran = runner(code)
            if ran.get('ok') is False:
                findings.append('Running the program failed:\n' + ran.get('output', '')[-2500:])
        if not findings and lang in NO_COMPILER and rounds < max_rounds and reviews < 2:
            # No real compiler here: a reference-based review catches what rule linters cannot (types, signatures, logic).
            reviews += 1
            findings = review(goal, lang, code)
            if findings:
                findings = ['Reviewer: ' + f for f in findings]
        if not findings:
            log(f'[CodeQuality] ✅ {lang} passed {check["checker"]}' + (' and a test run' if ran and ran.get('ok') else '')
                + (' and a reference review' if reviews else '') + f' in round {rounds}')
            return code, {'ok': True, 'rounds': rounds, 'checker': check['checker'], 'warnings': check['warnings'],
                          'run': ran, 'fixed_along_the_way': history}
        history.append(findings[0][:300])
        log(f'[CodeQuality] 🔧 round {rounds}: {len(findings)} problem(s), first: {findings[0][:160]}')
        if rounds == max_rounds:
            break
        code = extract_code(ask_model(repair_prompt(goal, lang, code, findings, context)))
    remaining = static_check(lang, code, known_modules)
    return code, {'ok': False, 'rounds': rounds, 'checker': remaining['checker'], 'remaining_errors': remaining['errors'],
                  'missing_modules': remaining['missing_modules'], 'warnings': remaining['warnings'], 'run': ran,
                  'fixed_along_the_way': history}


def repair(code: str, language: str, goal: str, *, context: str = '', known_modules=(), max_rounds=3, log=print):
    """Static-check existing code (e.g. a file another tool just wrote) and repair it in place if needed."""
    lang = norm_lang(language)
    for n in range(max_rounds):
        check = static_check(lang, code, known_modules)
        if not check['errors']:
            return code, check
        log(f'[CodeQuality] 🔧 repairing {lang}: {check["errors"][0][:160]}')
        code = extract_code(ask_model(repair_prompt(goal, lang, code, check['errors'], context)))
    return code, static_check(lang, code, known_modules)
