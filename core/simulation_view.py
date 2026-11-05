"""The holographic simulation board: "JARVIS, run a simulation".

It takes the place of the face in the HUD stack (like the Earth panel and the
video) and plays a short build-up: grid, scanning beam drawing the percentile
band left to right, then the metric cards and verdict typing out. Everything
it shows comes from core/scenario_simulator.headline(), so what is drawn and
what JARVIS says are the same numbers.
"""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

BUILD_SECONDS = 2.6       # band drawn by the scanning beam
CARD_STAGGER = 0.35       # each metric card after the previous
TYPE_CPS = 70             # verdict characters per second


def _num(v, unit=''):
    """Compact numbers for a small display: 1,234 · 12.3k · 4.5M; R values keep a sign."""
    a = abs(v)
    if unit == 'R':
        return f'{v:+.1f}R'
    if a >= 1e6:
        s = f'{v / 1e6:.2f}M'
    elif a >= 1e4:
        s = f'{v / 1e3:.1f}k'
    elif a >= 100:
        s = f'{v:,.0f}'
    elif a >= 10:
        s = f'{v:.1f}'.rstrip('0').rstrip('.')
    elif a >= 1:
        s = f'{v:.4f}'.rstrip('0').rstrip('.')               # forex rates need the decimals
    else:
        s = f'{v:.4f}'.rstrip('0').rstrip('.') or '0'
    return s + (' h' if unit == 'hours' else '')


def _at(rows, day):
    """Linear interpolation of a fan row at a fractional day."""
    if not rows:
        return None
    if day <= rows[0]['day']:
        return rows[0]
    for a, b in zip(rows, rows[1:]):
        if a['day'] <= day <= b['day']:
            k = (day - a['day']) / max(1e-9, b['day'] - a['day'])
            return {key: a[key] + (b[key] - a[key]) * k for key in ('p05', 'median', 'p95')}
    return rows[-1]


class SimulationHologram(QWidget):
    closed = pyqtSignal()

    def __init__(self, palette: dict | None = None, parent=None):
        super().__init__(parent)
        p = palette or {}
        self.col = {
            'bg': QColor(p.get('BG', '#00060a')), 'pri': QColor(p.get('PRI', '#00d4ff')),
            'dim': QColor(p.get('TEXT_DIM', '#3a8a9a')), 'text': QColor(p.get('TEXT', '#8ffcff')),
            'white': QColor(p.get('WHITE', '#d8f8ff')), 'acc2': QColor(p.get('ACC2', '#ffcc00')),
            'green': QColor(p.get('GREEN', '#00ff88')), 'red': QColor(p.get('RED', '#ff3355')),
            'acc': QColor(p.get('ACC', '#ff6b00')),
        }
        self.result: dict = {}
        self.head: dict = {'title': '', 'metrics': [], 'verdict': ''}
        self.rows: list = []
        self.ghost: list = []
        self.started = 0.0
        self._close_rect = QRectF()
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    # ── data ────────────────────────────────────────────────────────────────
    def set_result(self, result: dict, animate: bool = True) -> None:
        """animate=False draws the finished board at once — used while a slider is being dragged."""
        from core.scenario_simulator import headline
        self.result = dict(result or {})
        self.head = headline(self.result)
        shown = self.result.get('alternative', self.result) if self.result.get('kind') == 'comparison' else self.result
        self.shown = shown
        self.rows = list(shown.get('fan_chart') or [])
        base = self.result.get('baseline') if self.result.get('kind') == 'comparison' else None
        self.ghost = list((base or {}).get('fan_chart') or [])
        self.started = time.monotonic() - (0 if animate else 600)
        self._timer.start(33 if animate else 120)
        self.update()

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def finished(self) -> bool:
        t = self.elapsed()
        done_cards = BUILD_SECONDS + CARD_STAGGER * len(self.head['metrics'])
        return t > done_cards + len(self.head['verdict']) / TYPE_CPS + 0.5

    def mousePressEvent(self, e):
        if self._close_rect.contains(e.position()):
            self._timer.stop()
            self.closed.emit()
        elif self.finished():
            self.set_result(self.result)           # click the board to replay the build

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    # ── painting ────────────────────────────────────────────────────────────
    def _c(self, key, alpha=255):
        c = QColor(self.col.get(key, self.col['pri']))
        c.setAlpha(int(max(0, min(255, alpha))))
        return c

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = self.elapsed()
        fly = getattr(self, '_fly', None)
        if fly is not None:                                  # thrown: slide off that way, spin a little, fade
            k = min(1.0, (time.monotonic() - fly[0]) / .55)
            if k >= 1:
                self._fly = None
                QTimer.singleShot(0, self._finish_throw)
            ease = k * k
            p.fillRect(self.rect(), self.col['bg'])
            p.translate(fly[1] * w * 1.3 * ease + w / 2, fly[2] * h * 1.3 * ease + h / 2)
            p.rotate(fly[1] * 18 * ease)
            p.scale(1 - .35 * ease, 1 - .35 * ease)
            p.translate(-w / 2, -h / 2)
            p.setOpacity(1 - ease)
        if self.finished() and self._timer.isActive():
            # idle shimmer only — but a live session's hologram keeps turning smoothly
            self._timer.setInterval(50 if self.result.get('session') or self.shown.get('scene') else 120)

        self._deferred = None
        p.fillRect(self.rect(), self.col['bg'])
        glow = QRadialGradient(QPointF(w * .4, h * .45), max(w, h) * .6)
        glow.setColorAt(0, self._c('pri', 34))
        glow.setColorAt(1, self._c('pri', 0))
        p.fillRect(self.rect(), QBrush(glow))

        side = w >= 720
        metrics = self.head['metrics']
        if not side and len(metrics) > 4 and h < 820:
            metrics = metrics[:4]                            # small panel: the four that matter most
        self._metrics = metrics
        n = len(metrics)
        cards_h = math.ceil(n / 2) * 62 if not side else 0
        left = 74                                            # room for the value scale
        if side:
            chart = QRectF(left, 64, w * .64 - left - 20, h - 64 - 150)
        else:
            chart = QRectF(left, 64, w - left - 24, max(110.0, h - 64 - 110 - cards_h - 40))
        self._chart = chart
        trades = self.shown.get('trades') if hasattr(self, 'shown') else None
        if trades:
            eq = QRectF(chart.left(), chart.top(), chart.width(), chart.height() * .66)
            strip = QRectF(chart.left(), eq.bottom() + 36, chart.width(), max(24.0, chart.bottom() - eq.bottom() - 36))
            self._eq = eq
        else:
            eq, strip = chart, None
        self._grid(p, eq, t)
        self._header(p, w, t)
        if self.rows:
            self._band(p, eq, t)
            if strip is not None:
                self._trade_bars(p, strip, eq, t, trades)
        else:
            self._no_chart(p, chart, t)
        cards = QRectF(w * .66, 64, w * .34 - 24, h - 64 - 110) if side else QRectF(28, chart.bottom() + 40, w - 56, cards_h - 6)
        self._cards(p, cards, t, side)
        top = h - 92 if side else min(h - 92, cards.bottom() + 16)
        self._verdict(p, QRectF(28, top, w - 56, h - 26 - top), t, small=not side)
        session = self.result.get('session')
        if session:
            self._session(p, eq if self.rows else chart, t, session, side)
        scene = self.shown.get('scene')
        if scene and self.rows:
            self._scene(p, eq, t, scene)
        if self._deferred:                                   # hover readouts sit on top of everything
            self._readout(p, *self._deferred)
        if getattr(self, '_exploded', False) or time.monotonic() - getattr(self, '_explode_at', -99) < .5:
            self._exploded_view(p, chart, w, h)
        if getattr(self, '_hood', False) or time.monotonic() - getattr(self, '_hood_at', -99) < .35:
            self._under_the_hood(p, w, h)
        self._gesture_layer(p, w, h, chart)
        self._scanlines(p, w, h, t)

    def _header(self, p, w, t):
        p.setPen(self._c('pri'))
        p.setFont(QFont('Courier New', 11, QFont.Weight.Bold))
        dots = '.' * (int(t * 3) % 4) if t < BUILD_SECONDS else ''
        state = 'RUNNING' + dots if t < BUILD_SECONDS else 'COMPLETE'
        fm = p.fontMetrics()
        p.drawText(QPointF(28, 30), fm.elidedText(f"SIMULATION // {self.head['title']}", Qt.TextElideMode.ElideRight, w - 28 - 150))
        p.setFont(QFont('Courier New', 9))
        p.setPen(self._c('acc2' if t < BUILD_SECONDS else 'green'))
        a = self.shown.get('assumptions', {}) if hasattr(self, 'shown') else {}
        paths = a.get('paths')
        session = self.result.get('session')
        if session:
            info = f"ATTEMPT {session['attempt']:02d}   ·   GOAL: {session['criterion'].upper()}"
        elif self.shown.get('kind') == 'backtest':
            st = self.shown.get('stats', {})
            info = f"{st.get('closed_trades', 0)} trades   ·   RR 1:{a.get('reward_to_risk') or '?'}"
        else:
            info = f"{paths or 1} {'paths' if paths else 'case'}   ·   seed {a.get('seed', '—')}"
        p.drawText(QPointF(28, 48), p.fontMetrics().elidedText(f"{state}   ·   {info}", Qt.TextElideMode.ElideRight, w - 28 - 150))
        self._close_rect = QRectF(w - 128, 14, 104, 26)
        p.setPen(QPen(self._c('pri', 160), 1))
        p.setBrush(self._c('pri', 18))
        p.drawRoundedRect(self._close_rect, 4, 4)
        p.setPen(self._c('text'))
        p.drawText(self._close_rect, Qt.AlignmentFlag.AlignCenter, '✕  RETURN')

    def _grid(self, p, r, t):
        appear = min(1.0, t / .5)
        p.setPen(QPen(self._c('pri', 34 * appear), 1))
        for i in range(11):
            x = r.left() + r.width() * i / 10
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        for i in range(7):
            y = r.top() + r.height() * i / 6
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(self._c('pri', 120 * appear), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        L = 14
        for cx, cy, dx, dy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + L * dx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + L * dy))

    def _scale(self, r):
        rows = self.rows + self.ghost
        vals = [x[k] for x in rows for k in ('p05', 'median', 'p95')]
        tgt = self.shown.get('target')
        if isinstance(tgt, (int, float)):
            vals.append(float(tgt))
        lo, hi = min(vals), max(vals)
        span = max(hi - lo, abs(hi) * .01, 1e-9)
        lo, hi = (0.0 if lo >= 0 and lo - span * .06 < 0 else lo - span * .06), hi + span * .08
        last = max(1, max(x['day'] for x in rows))
        dl = self.shown.get('deadline')
        if isinstance(dl, (int, float)) and last < dl <= last * 1.6:
            last = int(dl)                                   # keep a nearby deadline on the chart
        zoom = max(1.0, min(12.0, getattr(self, '_zoom', 1.0)))
        span = last / zoom
        center = getattr(self, '_zoom_center', None)
        center = last / 2 if center is None else center
        w0 = max(0.0, min(last - span, center - span / 2))
        self._w0, self._span = w0, span                      # the visible time window (hand-gesture zoom)
        return (lambda day: r.left() + r.width() * (day - w0) / span), (lambda v: r.top() + r.height() * (hi - v) / (hi - lo)), lo, hi, last

    def _band(self, p, r, t):
        X, Y, lo, hi, last = self._scale(r)
        reveal = min(1.0, t / BUILD_SECONDS)
        reveal = 1 - (1 - reveal) ** 3                       # ease-out
        edge = r.left() + r.width() * reveal
        p.save()
        p.setClipRect(QRectF(r.left() - 2, r.top() - 4, edge - r.left() + 4, r.height() + 8))

        stages = self.shown.get('stages') or []
        for k, st in enumerate(stages):                      # process stages as alternating bands
            x1, x2 = X(st['start']), X(st['end'])
            p.fillRect(QRectF(x1, r.top(), x2 - x1, r.height()), self._c('pri', 16 if k % 2 else 6))
        if self.ghost:                                       # baseline of a comparison, faint
            p.setPen(QPen(self._c('dim', 160), 1.4, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)          # an open path with a brush would fill as a wedge
            path = QPainterPath(QPointF(X(self.ghost[0]['day']), Y(self.ghost[0]['median'])))
            for row in self.ghost[1:]:
                path.lineTo(X(row['day']), Y(row['median']))
            p.drawPath(path)

        band = QPainterPath(QPointF(X(self.rows[0]['day']), Y(self.rows[0]['p95'])))
        for row in self.rows[1:]:
            band.lineTo(X(row['day']), Y(row['p95']))
        for row in reversed(self.rows):
            band.lineTo(X(row['day']), Y(row['p05']))
        band.closeSubpath()
        grad = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
        grad.setColorAt(0, self._c('pri', 90))
        grad.setColorAt(1, self._c('pri', 25))
        p.setPen(QPen(self._c('pri', 110), 1))
        p.setBrush(QBrush(grad))
        p.drawPath(band)

        med = QPainterPath(QPointF(X(self.rows[0]['day']), Y(self.rows[0]['median'])))
        for row in self.rows[1:]:
            med.lineTo(X(row['day']), Y(row['median']))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((9, 35), (5, 70), (2.2, 255)):     # glow by layering
            p.setPen(QPen(self._c('white' if width < 3 else 'pri', alpha), width))
            p.drawPath(med)
        p.restore()

        tgt = self.shown.get('target')
        if isinstance(tgt, (int, float)) and lo <= tgt <= hi:
            y = Y(float(tgt))
            p.setPen(QPen(self._c('acc2', 200), 1.2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setFont(QFont('Courier New', 8))
            p.drawText(QPointF(r.left() + 6, y - 5), f'TARGET {tgt:,.0f}')
        dl = self.shown.get('deadline')
        if isinstance(dl, (int, float)) and dl <= last and r.left() <= X(dl) <= r.right():
            x = X(dl)
            p.setPen(QPen(self._c('red', 200), 1.2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setFont(QFont('Courier New', 8))
            label = f'DEADLINE D{int(dl)}'
            p.drawText(QRectF(x - 124, r.bottom() - 16, 120, 14) if x > r.right() - 110 else QRectF(x + 4, r.bottom() - 16, 120, 14),
                       Qt.AlignmentFlag.AlignRight if x > r.right() - 110 else Qt.AlignmentFlag.AlignLeft, label)

        if reveal < 1:                                       # the scanning beam
            beam = QLinearGradient(QPointF(edge - 40, 0), QPointF(edge + 4, 0))
            beam.setColorAt(0, self._c('pri', 0))
            beam.setColorAt(1, self._c('pri', 120))
            p.fillRect(QRectF(edge - 40, r.top(), 44, r.height()), QBrush(beam))
            p.setPen(QPen(self._c('white', 230), 1.5))
            p.drawLine(QPointF(edge, r.top()), QPointF(edge, r.bottom()))

        unit = self.shown.get('x_unit') or ('trading days' if self.shown.get('kind') == 'forex' else 'steps')
        yu = self.shown.get('y_unit', '')
        p.setFont(QFont('Courier New', 8))
        p.setPen(self._c('text', 200))
        for i in range(7):                                   # value scale on every horizontal grid line
            v = hi - (hi - lo) * i / 6
            p.drawText(QRectF(r.left() - 72, r.top() + r.height() * i / 6 - 8, 66, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, _num(v, yu))
        for i in range(0, 11, 2):                            # time scale under every other vertical line
            d = self._w0 + self._span * i / 10
            x = r.left() + r.width() * i / 10
            align = Qt.AlignmentFlag.AlignLeft if i == 0 else Qt.AlignmentFlag.AlignRight if i == 10 else Qt.AlignmentFlag.AlignHCenter
            box = QRectF(x - (0 if i == 0 else 80 if i == 10 else 40), r.bottom() + 4, 80, 14)
            p.drawText(box, align, f'{d:,.0f}')
        p.setPen(self._c('dim'))
        legend = self.shown.get('band_label') or 'line = median  ·  band = 5th–95th percentile'
        text = f'{unit.upper()} →    ' + legend + ('  ·  dashed = baseline' if self.ghost else '')
        p.drawText(QRectF(r.left(), r.bottom() + 18, r.width(), 14), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(r.width())))

        if stages:
            p.setFont(QFont('Courier New', 7))
            for k, st in enumerate(stages):
                x1, x2 = max(r.left(), X(st['start'])), min(r.right(), X(st['end']))
                if x2 <= x1:
                    continue
                active = x1 <= edge
                p.setPen(self._c('text' if active else 'dim', 230 if active else 120))
                p.drawText(QRectF(x1 + 2, r.top() + 2 + (k % 2) * 10, max(10.0, x2 - x1 - 4), 10), Qt.AlignmentFlag.AlignLeft,
                           p.fontMetrics().elidedText(st['name'].upper(), Qt.TextElideMode.ElideRight, int(max(10.0, x2 - x1 - 4))))
        for ev in self.shown.get('events') or []:
            if ev.get('at') is None or X(ev['at']) > edge or X(ev['at']) < r.left():
                continue
            x = X(ev['at'])
            p.setPen(QPen(self._c('green', 200), 1.2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, r.top() + 22), QPointF(x, r.bottom()))
            p.setFont(QFont('Courier New', 8, QFont.Weight.Bold))
            p.setPen(self._c('green'))
            left_side = x - 124 >= r.left()
            p.drawText(QRectF(x - 124, r.bottom() - 32, 120, 14) if left_side else QRectF(x + 4, r.bottom() - 32, 120, 14),
                       Qt.AlignmentFlag.AlignRight if left_side else Qt.AlignmentFlag.AlignLeft, '◆ ' + ev['label'].upper())

        if reveal < 1:                                       # live numbers riding the beam
            day = self._w0 + self._span * reveal
            row = _at(self.rows, day)
            if row:
                self._tag(p, QPointF(edge, Y(row['median'])), f"{unit[:-1] if unit.endswith('s') else unit} {day:,.0f}",
                          _num(row['median'], yu), r, live=True)
        else:
            end = self.rows[-1]                              # final value pinned to the end of the line
            if r.left() <= X(end['day']) <= r.right() + 1:
                self._tag(p, QPointF(X(end['day']), Y(end['median'])), 'END', _num(end['median'], yu), r)
            hover = getattr(self, '_hover', None)
            if hover is not None and r.contains(hover):
                day = self._w0 + (hover.x() - r.left()) / r.width() * self._span
                row = _at(self.rows, day)
                if row:
                    p.setPen(QPen(self._c('white', 120), 1, Qt.PenStyle.DotLine))
                    p.drawLine(QPointF(hover.x(), r.top()), QPointF(hover.x(), r.bottom()))
                    lines = [f"{unit[:-1] if unit.endswith('s') else unit} {day:,.0f}", f"median {_num(row['median'], yu)}"]
                    if self.shown.get('kind') == 'process' and self.shown.get('series'):
                        ts = self.shown['series_t']
                        k = min(range(len(ts)), key=lambda i: abs(ts[i] - day))
                        lines = [f"{unit[:-1] if unit.endswith('s') else unit} {ts[k]:,.0f}"] + [
                            f"{n.replace('_', ' ')[:14]:14} {v[k]:,.1f} {self.shown['units'].get(n, '')}"
                            for n, v in list(self.shown['series'].items())[:5]]
                    elif self.shown.get('kind') == 'backtest':
                        lines = [f"after trade {day:,.0f}", f"{'balance' if yu == 'money' else 'equity'}  {_num(row['median'], yu)}",
                                 f"peak     {_num(row['p95'], yu)}", f"drawdown {_num(row['p95'] - row['median'], yu)}"]
                    elif abs(row['p95'] - row['p05']) > 1e-9:
                        lines.insert(1, f"95th   {_num(row['p95'], yu)}")
                        lines.append(f"5th    {_num(row['p05'], yu)}")
                    self._defer(QPointF(hover.x(), Y(row['median'])), lines, r)

    # ── live session: attempt log, verdict, hologram ─────────────────────────
    def _session(self, p, r, t, session, side):
        status = session.get('status')
        tone = 'green' if status == 'success' else 'red' if status == 'failed' else 'pri'
        # spinning wireframe knot; its shape changes with every attempt and it glows with the verdict
        size = min(92.0, r.width() * .22, r.height() * .42)
        cx, cy = r.right() - size * .62, r.top() + size * .62 + 6
        knots = ((2, 3), (3, 4), (2, 5), (3, 5), (4, 5), (3, 7), (5, 6), (4, 7))
        pk, qk = knots[(session.get('attempt', 1) - 1) % len(knots)]
        ang = t * (.9 if status != 'success' else .4) + getattr(self, '_spin', 0.0)
        tilt = .55 + .25 * math.sin(t * .5)
        pts = []
        for i in range(181):
            u = 2 * math.pi * i / 180
            rr = 2 + math.cos(qk * u)
            x, y, z = rr * math.cos(pk * u), rr * math.sin(pk * u), -math.sin(qk * u)
            x, z = x * math.cos(ang) + z * math.sin(ang), -x * math.sin(ang) + z * math.cos(ang)
            y, z = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)
            k = size / 7.2 * (1 + z * .06)
            pts.append(QPointF(cx + x * k, cy + y * k))
        build = min(1.0, t / BUILD_SECONDS)
        path = QPainterPath(pts[0])
        for q in pts[1:int(1 + 180 * build)]:
            path.lineTo(q)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((6, 40), (1.4, 230)):
            p.setPen(QPen(self._c(tone, alpha), width))
            p.drawPath(path)
        if status == 'success':                              # lock-on rings
            for i in range(2):
                rad = size * (.5 + .12 * i + .04 * math.sin(t * 4 + i))
                p.setPen(QPen(self._c('green', 110 - 40 * i), 1.2))
                p.drawEllipse(QPointF(cx, cy), rad, rad)

        # attempt log, newest last
        rows = session.get('attempts', [])[-(5 if side else 3):]
        if rows:
            lw = min(r.width() - size - 30, 330.0)
            lh = 14 * len(rows) + 10
            box = QRectF(r.left() + 8, r.top() + 22, lw, lh)
            p.setPen(QPen(self._c('pri', 90), 1))
            p.setBrush(self._c('bg', 200))
            p.drawRoundedRect(box, 3, 3)
            p.setFont(QFont('Courier New', 8))
            for i, a in enumerate(rows):
                mark = '✔' if a.get('passed') else '✘' if a.get('passed') is False else '·'
                col = 'green' if a.get('passed') else 'red' if a.get('passed') is False else 'text'
                text = f"{mark} #{a['n']:02d} {a['change']}  →  {a['value']}"
                p.setPen(self._c(col, 235))
                p.drawText(QRectF(box.left() + 6, box.top() + 5 + 14 * i, lw - 10, 14), Qt.AlignmentFlag.AlignLeft,
                           p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(lw - 10)))

        # the verdict, big, once the build finishes
        if status in ('success', 'failed'):
            k = t - BUILD_SECONDS
            if 0 < k < 3.2:
                a = min(1.0, k / .25) * (1 if k < 2.4 else max(0.0, (3.2 - k) / .8))
                flicker = .75 + .25 * math.sin(k * 30) if k < .6 else 1
                word = 'MODEL SUCCESSFUL' if status == 'success' else 'MODEL FAILED'
                p.setFont(QFont('Courier New', 22 if side else 15, QFont.Weight.Bold))
                band = QRectF(r.left(), r.center().y() - 26, r.width(), 52)
                p.fillRect(band, self._c('bg', 190 * a))
                p.setPen(QPen(self._c(tone, 230 * a), 1.5))
                p.drawLine(QPointF(band.left(), band.top()), QPointF(band.right(), band.top()))
                p.drawLine(QPointF(band.left(), band.bottom()), QPointF(band.right(), band.bottom()))
                p.setPen(self._c(tone, 255 * a * flicker))
                p.drawText(band, Qt.AlignmentFlag.AlignCenter, word)

    def _scene(self, p, r, t, scene):
        """A small picture of the process, driven by its own variables as the beam sweeps."""
        series, ts = self.shown.get('series') or {}, self.shown.get('series_t') or []
        if not ts:
            return
        X, _Y, _lo, _hi, last = self._scale(r)
        reveal = 1 - (1 - min(1.0, t / BUILD_SECONDS)) ** 3
        hover = getattr(self, '_hover', None)
        day = self._w0 + self._span * reveal
        if reveal >= 1 and hover is not None and r.contains(hover):
            day = self._w0 + (hover.x() - r.left()) / r.width() * self._span
        k = min(range(len(ts)), key=lambda i: abs(ts[i] - day))
        val = lambda name, default=0.0: (series.get(name) or [default] * len(ts))[k]
        frac = lambda name, top: max(0.0, min(1.0, val(name) / top)) if name in series and top else 0.0
        side = min(140.0, max(90.0, r.height() * .52), r.width() * .36)
        box = QRectF(r.right() - side - 8, r.bottom() - side - 4, side, side)
        p.setPen(QPen(self._c('pri', 70), 1))
        p.setBrush(self._c('bg', 170))
        p.drawRoundedRect(box, 6, 6)
        kind = str(scene.get('type', 'grow'))
        cx, cy = box.center().x(), box.center().y() + 6
        mix = frac(scene.get('color'), float(scene.get('color_max', 100) or 100))
        a, b = QColor(str(scene.get('from', '#7cc242'))), QColor(str(scene.get('to', '#d62828')))
        col = QColor(int(a.red() + (b.red() - a.red()) * mix), int(a.green() + (b.green() - a.green()) * mix),
                     int(a.blue() + (b.blue() - a.blue()) * mix))
        if kind == 'grow':
            # a branch, a stem and a fruit that swells and changes colour
            p.setPen(QPen(QColor('#6b4b2a'), 4))
            p.drawLine(QPointF(box.left() + 10, box.top() + 20), QPointF(box.right() - 10, box.top() + 14))
            p.setPen(QPen(QColor('#6b4b2a'), 2))
            p.drawLine(QPointF(cx, box.top() + 17), QPointF(cx, box.top() + side * .3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#3fa34d'))
            leaf = QPainterPath(QPointF(cx, box.top() + 24))
            leaf.quadTo(QPointF(cx + 22, box.top() + 14), QPointF(cx + 30, box.top() + 30))
            leaf.quadTo(QPointF(cx + 12, box.top() + 36), QPointF(cx, box.top() + 24))
            p.drawPath(leaf)
            hang = box.top() + side * .3                     # where the stem meets the fruit
            room = (box.bottom() - 18 - hang) / 2
            rad = 3 + (room - 3) * frac(scene.get('size'), float(scene.get('max', 1) or 1))
            g = QRadialGradient(QPointF(cx - rad * .35, hang + rad * .65), rad * 1.3)
            g.setColorAt(0, col.lighter(150))
            g.setColorAt(1, col.darker(130))
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx, hang + rad), rad, rad * .94)
        elif kind == 'fill':
            level = frac(scene.get('size'), float(scene.get('max', 1) or 1))
            tank = QRectF(box.left() + 30, box.top() + 22, box.width() - 60, box.height() - 44)
            p.setPen(QPen(self._c('text', 200), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(tank)
            p.fillRect(QRectF(tank.left() + 1, tank.bottom() - tank.height() * level, tank.width() - 2, tank.height() * level), col)
        else:                                                # dots: a population that grows or shrinks
            import random as _r
            rnd = _r.Random(7)
            count = int(120 * frac(scene.get('size'), float(scene.get('max', 1) or 1)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            for _ in range(count):
                p.drawEllipse(QPointF(box.left() + 10 + rnd.random() * (box.width() - 20),
                                      box.top() + 18 + rnd.random() * (box.height() - 36)), 2.2, 2.2)
        p.setFont(QFont('Courier New', 8))
        p.setPen(self._c('text'))
        label = str(scene.get('label', '')).upper()
        unit = self.shown.get('x_unit', '')
        p.drawText(QRectF(box.left() + 6, box.bottom() - 16, box.width() - 12, 14), Qt.AlignmentFlag.AlignLeft,
                   f"{label}  {unit[:-1] if unit.endswith('s') else unit} {ts[k]:,.0f}")

    def _trade_bars(self, p, r, eq, t, trades):
        """One bar per closed trade under the equity line: green up for a win, red down for a loss."""
        X, _Y, _lo, _hi, last = self._scale(eq)
        reveal = 1 - (1 - min(1.0, t / BUILD_SECONDS)) ** 3
        edge = eq.left() + eq.width() * reveal
        mid = r.center().y()
        top = max((abs(x.get('r') or 0) for x in trades), default=1) or 1
        bw = max(1.5, min(14.0, eq.width() / max(1, last) * .7))
        p.setPen(QPen(self._c('pri', 70), 1))
        p.drawLine(QPointF(r.left(), mid), QPointF(r.right(), mid))
        p.setFont(QFont('Courier New', 7))
        p.setPen(self._c('dim'))
        p.drawText(QRectF(r.left() - 72, r.top() - 2, 66, 12), Qt.AlignmentFlag.AlignRight, 'WIN')
        p.drawText(QRectF(r.left() - 72, r.bottom() - 10, 66, 12), Qt.AlignmentFlag.AlignRight, 'LOSS')
        p.setPen(Qt.PenStyle.NoPen)
        for tr in trades:
            x = X(tr['n'])
            if x > edge + 1 or x > eq.right() + 1:
                break
            if x < eq.left() - 1:
                continue
            k = (tr.get('r') or 0) / top
            hgt = abs(k) * (r.height() / 2 - 2)
            win = tr.get('result') == 'win'
            p.setBrush(self._c('green' if win else 'red', 220))
            p.drawRect(QRectF(x - bw / 2, mid - hgt if win else mid, bw, max(1.0, hgt)))
        hover = getattr(self, '_hover', None)
        if hover is not None and r.contains(hover) and self.finished():
            n = round(self._w0 + (hover.x() - eq.left()) / eq.width() * self._span)
            tr = next((x for x in trades if x['n'] == n), None)
            if tr:
                lines = [f"#{tr['n']}  {'WIN' if tr.get('result') == 'win' else 'LOSS'}  {tr.get('direction', '')}",
                         f"{(tr.get('entry_time') or '')[:16]}",
                         f"entry {tr.get('entry')}  exit {tr.get('exit')}",
                         f"R {tr.get('r', 0):+.2f}" + (f"   P&L {tr['pnl']:+,.2f}" if tr.get('pnl') is not None else '')]
                self._defer(QPointF(X(n), mid), lines, QRectF(eq.left(), eq.top(), eq.width(), r.bottom() - eq.top()))

    def _tag(self, p, at, small, big, r, live=False):
        """A value flag on the line: a dot and a small box with the number."""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._c('white'))
        p.drawEllipse(at, 3.5, 3.5)
        w = max(70, 9 * max(len(big), len(small)) + 14)
        x = at.x() + 10 if at.x() + 10 + w < min(self.width() - 6, r.right() + 24) else at.x() - 10 - w
        y = min(max(at.y() - 34, r.top() + 2), r.bottom() - 36)
        box = QRectF(x, y, w, 32)
        p.setPen(QPen(self._c('acc2' if live else 'pri', 220), 1))
        p.setBrush(self._c('bg', 225))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(self._c('dim'))
        p.setFont(QFont('Courier New', 7))
        p.drawText(QRectF(x + 6, y + 2, w - 8, 12), Qt.AlignmentFlag.AlignLeft, small.upper())
        p.setPen(self._c('white'))
        p.setFont(QFont('Courier New', 10, QFont.Weight.Bold))
        p.drawText(QRectF(x + 6, y + 13, w - 8, 18), Qt.AlignmentFlag.AlignLeft, big)

    def _readout(self, p, at, lines, r):
        w = 9 * max(len(s) for s in lines) + 16
        h = 15 * len(lines) + 8
        x = at.x() + 12 if at.x() + 12 + w < r.right() else at.x() - 12 - w
        x = min(max(4.0, x), self.width() - w - 4)
        y = min(max(at.y() - h / 2, r.top()), r.bottom() - h)
        p.setPen(QPen(self._c('pri', 230), 1))
        p.setBrush(self._c('bg', 235))
        p.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
        p.setFont(QFont('Courier New', 9))
        for i, s in enumerate(lines):
            p.setPen(self._c('white' if i == 0 else 'text'))
            p.drawText(QPointF(x + 8, y + 17 + 15 * i), s)
        p.setBrush(self._c('white'))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(at, 4, 4)

    # ── hand gestures ───────────────────────────────────────────────────────
    GESTURE_HINT = ('☝ point · 🤏 drag = scrub · 👐 spread = zoom, burst = explode, turn = twist · ✋ swipe ←→ attempts, '
                    '↑ under the hood, ↓ close · ✋ push = re-run · ✊ fling = throw away, hold = reset')

    def _finish_throw(self):
        self._exploded = self._hood = False
        self._zoom, self._zoom_center = 1.0, None
        self._timer.stop()
        self.closed.emit()

    def _cycle_focus(self, step):
        """Twist: turn through the model's quantities like a dial (process models), keeping the session."""
        series = self.result.get('series') or (self.shown.get('series') if hasattr(self, 'shown') else None)
        if not series:
            self._toast('↻ TWIST')
            return
        names = list(series)
        current = self.shown.get('focus') if self.shown.get('focus') in names else names[0]
        name = names[(names.index(current) + step) % len(names)]
        from core.scenario_simulator import headline
        ts = self.shown.get('series_t') or []
        rows = [{'day': t, 'p05': v, 'median': v, 'p95': v} for t, v in zip(ts, series[name])]
        shown = dict(self.shown, focus=name, fan_chart=rows, y_unit=(self.shown.get('units') or {}).get(name, ''),
                     band_label='line = ' + name.replace('_', ' ') + '  ·  twist again for the next one')
        self.shown, self.rows = shown, rows
        self.head = headline(dict(self.result, **{k: shown[k] for k in ('focus', 'fan_chart', 'y_unit')}))
        self._toast('↻ ' + name.replace('_', ' ').upper())

    def _panels(self):
        """What the exploded view breaks the model into: one panel per quantity."""
        sh = self.shown
        if sh.get('series'):
            ts = sh.get('series_t') or []
            return [(n.replace('_', ' '), (sh.get('units') or {}).get(n, ''), list(zip(ts, v))) for n, v in sh['series'].items()]
        out = [('median' if sh.get('kind') != 'backtest' else ('balance' if sh.get('y_unit') == 'money' else 'equity R'),
                sh.get('y_unit', ''), [(r['day'], r['median']) for r in self.rows])]
        if any(abs(r['p95'] - r['p05']) > 1e-9 for r in self.rows) and sh.get('kind') != 'backtest':
            out += [('95th percentile', sh.get('y_unit', ''), [(r['day'], r['p95']) for r in self.rows]),
                    ('5th percentile', sh.get('y_unit', ''), [(r['day'], r['p05']) for r in self.rows])]
        if sh.get('trades'):
            out.append(('trade R', 'R', [(tr['n'], tr.get('r') or 0) for tr in sh['trades']]))
            peak, dd = float('-inf'), []
            for r in self.rows:
                peak = max(peak, r['median'])
                dd.append((r['day'], peak - r['median']))
            out.append(('drawdown', sh.get('y_unit', ''), dd))
        return out

    def _exploded_view(self, p, chart, w, h):
        panels = self._panels()[:6]
        if not panels:
            return
        k = min(1.0, (time.monotonic() - getattr(self, '_explode_at', 0)) / .5)
        k = 1 - (1 - k) ** 3
        if not getattr(self, '_exploded', False):
            k = 1 - k                                        # imploding: fly back in
        area = QRectF(chart.left() - 40, chart.top() - 6, chart.width() + 46, chart.height() + 12)
        p.fillRect(area, self._c('bg', 225 * k))
        cols = 2 if len(panels) <= 4 else 3
        rows = math.ceil(len(panels) / cols)
        gw, gh = area.width() / cols, area.height() / rows
        hover = getattr(self, '_hover', None)
        day = None
        if hover is not None and hasattr(self, '_w0') and chart.width():
            day = self._w0 + (hover.x() - chart.left()) / chart.width() * self._span
        cx, cy = area.center().x(), area.center().y()
        for i, (name, unit, pts) in enumerate(panels):
            target = QRectF(area.left() + (i % cols) * gw + 6, area.top() + (i // cols) * gh + 6, gw - 12, gh - 12)
            box = QRectF(cx + (target.left() - cx) * k, cy + (target.top() - cy) * k, target.width() * (.3 + .7 * k),
                         target.height() * (.3 + .7 * k))
            p.setPen(QPen(self._c('pri', 200 * k), 1.2))
            p.setBrush(self._c('bg', 235 * k))
            p.drawRoundedRect(box, 6, 6)
            if k < .6 or len(pts) < 2:
                continue
            vals = [v for _, v in pts]
            lo, hi = min(vals), max(vals)
            hi = hi if hi > lo else lo + 1
            t0, t1 = pts[0][0], pts[-1][0] if pts[-1][0] > pts[0][0] else pts[0][0] + 1
            inner = QRectF(box.left() + 10, box.top() + 34, box.width() - 20, box.height() - 46)
            path = QPainterPath()
            for j, (tt, v) in enumerate(pts):
                q = QPointF(inner.left() + inner.width() * (tt - t0) / (t1 - t0), inner.bottom() - inner.height() * (v - lo) / (hi - lo))
                path.moveTo(q) if j == 0 else path.lineTo(q)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for width, alpha in ((5, 40), (1.6, 240)):
                p.setPen(QPen(self._c('pri' if i else 'white', alpha * k), width))
                p.drawPath(path)
            p.setPen(self._c('dim', 255 * k))
            p.setFont(QFont('Courier New', 8))
            p.drawText(QRectF(box.left() + 10, box.top() + 6, box.width() - 20, 12), Qt.AlignmentFlag.AlignLeft, name.upper())
            shown_v, shown_t = vals[-1], pts[-1][0]
            if day is not None and t0 <= day <= t1:
                near = min(pts, key=lambda q: abs(q[0] - day))
                shown_t, shown_v = near
                x = inner.left() + inner.width() * (near[0] - t0) / (t1 - t0)
                p.setPen(QPen(self._c('acc2', 200 * k), 1, Qt.PenStyle.DotLine))
                p.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
            p.setPen(self._c('white', 255 * k))
            p.setFont(QFont('Courier New', 12, QFont.Weight.Bold))
            unit_x = self.shown.get('x_unit', '')
            p.drawText(QRectF(box.left() + 10, box.top() + 16, box.width() - 20, 18), Qt.AlignmentFlag.AlignLeft,
                       f"{_num(shown_v, 'R' if unit == 'R' else '')} {'' if unit == 'R' else unit}".strip()
                       + f"   @ {shown_t:,.0f}" + (f" {unit_x}" if unit_x else ''))

    def _under_the_hood(self, p, w, h):
        """Swipe up: the model's formulas and settings slide up over the board."""
        k = min(1.0, (time.monotonic() - getattr(self, '_hood_at', 0)) / .35)
        k = 1 - (1 - k) ** 3
        if not getattr(self, '_hood', False):
            k = 1 - k
        sh = self.shown
        lines = []
        if sh.get('formulas'):
            lines.append(('MODEL', 'pri'))
            for name, (kind, text) in sh['formulas'].items():
                lines.append((f"{'d/dt ' if kind == 'rate' else ''}{name} = {text}", 'text'))
        a = sh.get('assumptions') or {}
        settings = a.get('settings') if isinstance(a.get('settings'), dict) else {k2: v for k2, v in a.items() if not isinstance(v, (dict, list))}
        if settings:
            lines.append(('SETTINGS', 'pri'))
            lines += [(f"{k2.replace('_', ' ')} = {v}", 'text') for k2, v in settings.items() if v is not None]
        st = sh.get('stats') or {}
        if st:
            lines.append(('RESULT', 'pri'))
            lines += [(f"{k2.replace('_', ' ')} = {v}", 'text') for k2, v in st.items() if v is not None]
        for key in ('method', 'limits'):
            if sh.get(key):
                lines.append((key.upper(), 'pri'))
                lines.append((str(sh[key]), 'dim'))
        hh = min(h * .78, 22 + 15 * len(lines) + 40)
        box = QRectF(24, h - hh * k, w - 48, hh)
        p.setPen(QPen(self._c('pri', 220 * k), 1.2))
        p.setBrush(self._c('bg', 240 * k))
        p.drawRoundedRect(box, 8, 8)
        p.setFont(QFont('Courier New', 9))
        y = box.top() + 18
        p.setPen(self._c('acc2', 255 * k))
        p.drawText(QPointF(box.left() + 14, y), 'UNDER THE HOOD   ·   swipe down to close')
        y += 20
        for text, tone in lines:
            if y > box.bottom() - 8:
                break
            p.setPen(self._c(tone, 255 * k))
            p.setFont(QFont('Courier New', 9, QFont.Weight.Bold if tone == 'pri' else QFont.Weight.Normal))
            p.drawText(QRectF(box.left() + 14, y - 11, box.width() - 28, 14), Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(box.width() - 28)))
            y += 15

    def apply_hand_gesture(self, event: dict) -> None:
        """Camera hand gestures on the board: point, scrub, zoom, swipe through attempts, replay, reset."""
        kind = event.get('kind')
        now = time.monotonic()
        self._gesture_seen = now
        self._gesture_label = str(event.get('label', ''))[:80]
        chart = getattr(self, '_chart', QRectF(0, 0, self.width(), self.height()))
        if kind == 'point':
            # the camera frame spans the whole board, like reaching into the projection
            self._hover = QPointF(float(event.get('x', .5)) * self.width(), float(event.get('y', .5)) * self.height())
            self._cursor_kind = 'point'
        elif kind == 'rotate':                               # pinch + drag
            hover = getattr(self, '_hover', None) or QPointF(chart.center().x(), chart.center().y())
            x = min(chart.right() - 1, max(chart.left() + 1, hover.x() + float(event.get('dx', 0)) * chart.width() * 2.4))
            self._hover = QPointF(x, hover.y())
            self._spin = getattr(self, '_spin', 0.0) + float(event.get('dy', 0)) * 6
            self._cursor_kind = 'grab'
        elif kind == 'zoom':
            self._zoom = max(1.0, min(12.0, getattr(self, '_zoom', 1.0) * float(event.get('factor', 1))))
            hover = getattr(self, '_hover', None)
            if hover is not None and hasattr(self, '_w0') and chart.width():
                self._zoom_center = self._w0 + (hover.x() - chart.left()) / chart.width() * self._span
            self._toast(f"ZOOM ×{self._zoom:.1f}")
        elif kind == 'swipe' and event.get('direction') in ('left', 'right'):
            self._step_attempt(-1 if event.get('direction') == 'left' else 1)
        elif kind == 'swipe' and event.get('direction') == 'up':
            self._hood, self._hood_at = True, now
            self._toast('UNDER THE HOOD')
        elif kind == 'swipe' and event.get('direction') == 'down':
            if getattr(self, '_hood', False):
                self._hood, self._hood_at = False, now
            elif getattr(self, '_exploded', False):
                self._exploded, self._explode_at = False, now
            else:
                self._fly = (now, 0, 1)                      # swipe down on the plain board puts it away
        elif kind == 'palm_hold':
            self._toast('▶ REPLAY')
            self.set_result(self.result)
        elif kind == 'reset':
            self._zoom, self._zoom_center, self._spin, self._hover = 1.0, None, 0.0, None
            self._exploded = self._hood = False
            self._toast('VIEW RESET')
            self.set_result(self.result)
        elif kind == 'throw':
            vec = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}.get(event.get('direction'), (1, 0))
            self._fly = (now, vec[0], vec[1])
            self._toast('')
        elif kind == 'explode':
            self._exploded, self._explode_at = True, now
            self._toast('◇ EXPLODED VIEW')
        elif kind == 'implode':
            if getattr(self, '_exploded', False):
                self._exploded, self._explode_at = False, now
                self._toast('◆ ASSEMBLED')
        elif kind == 'twist':
            self._spin = getattr(self, '_spin', 0.0) + (1.2 if event.get('direction') == 'cw' else -1.2)
            self._cycle_focus(1 if event.get('direction') == 'cw' else -1)
        elif kind == 'push':
            self._toast('▶ RE-RUNNING')
            self.set_result(self.result)
        elif kind == 'pull':
            self._zoom, self._zoom_center = 1.0, None
            self._toast('◁ ZOOMED OUT')
        if not self._timer.isActive():
            self._timer.start(50)
        self.update()

    def _step_attempt(self, step: int) -> None:
        session = self.result.get('session')
        if not session:
            self._toast('NO OTHER ATTEMPTS')
            return
        from core import sim_session
        total = session.get('of') or session.get('attempt', 1)
        n = session.get('attempt', 1) + step
        board = sim_session.attempt_board(n) if 1 <= n <= total else None
        if board is None:
            self._toast('FIRST ATTEMPT' if step < 0 else 'LATEST ATTEMPT')
            return
        self.set_result(board, animate=False)
        self._toast(('◀ ' if step < 0 else '') + f'ATTEMPT {n:02d} OF {total:02d}' + (' ▶' if step > 0 else ''))

    def _toast(self, text: str) -> None:
        self._toast_text, self._toast_at = text, time.monotonic()

    def _gesture_layer(self, p, w, h, chart):
        now = time.monotonic()
        seen = now - getattr(self, '_gesture_seen', -99) < 6
        if seen:                                             # which gestures are live, along the bottom
            p.setFont(QFont('Courier New', 8))
            p.setPen(self._c('acc2', 220))
            p.drawText(QRectF(28, h - 22, w - 56, 14), Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText('✋ GESTURES  ' + (getattr(self, '_gesture_label', '') or self.GESTURE_HINT),
                                                  Qt.TextElideMode.ElideRight, int(w * .6)))
            hover = getattr(self, '_hover', None)
            if hover is not None and now - getattr(self, '_gesture_seen', -99) < 1.5:
                grab = getattr(self, '_cursor_kind', 'point') == 'grab'
                ring = 9 if grab else 13
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(self._c('acc2', 240), 2))
                p.drawEllipse(hover, ring, ring)
                p.setPen(QPen(self._c('acc2', 120), 1))
                p.drawEllipse(hover, ring + 6 + 3 * math.sin(now * 8), ring + 6 + 3 * math.sin(now * 8))
                if grab:
                    p.setBrush(self._c('acc2', 200))
                    p.drawEllipse(hover, 3, 3)
        k = now - getattr(self, '_toast_at', -99)
        if k < 1.4:
            a = 1 if k < 1 else (1.4 - k) / .4
            p.setFont(QFont('Courier New', 13, QFont.Weight.Bold))
            top = getattr(self, '_hood', False) or getattr(self, '_exploded', False)
            box = QRectF(chart.center().x() - 150, chart.top() - 30 if top else chart.bottom() - 74, 300, 30)
            p.setPen(QPen(self._c('acc2', 220 * a), 1))
            p.setBrush(self._c('bg', 210 * a))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(self._c('acc2', 255 * a))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, getattr(self, '_toast_text', ''))

    def _defer(self, at, lines, r):
        self._deferred = (at, lines, r)

    def mouseMoveEvent(self, e):
        self._hover = e.position()
        if self.finished():
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def _no_chart(self, p, r, t):
        """Single-case scenarios have no band: draw a pulsing reticle instead."""
        cx, cy = r.center().x(), r.center().y()
        rad = min(r.width(), r.height()) * .32
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            k = rad * (.45 + .3 * i)
            p.setPen(QPen(self._c('pri', 140 - 35 * i), 1.3))
            span = int(min(1.0, t / BUILD_SECONDS) * 360 * 16)
            p.drawArc(QRectF(cx - k, cy - k, 2 * k, 2 * k), int((t * 40 * (i + 1)) % 360 * 16), span)
        p.setPen(QPen(self._c('pri', 200), 1))
        p.drawLine(QPointF(cx - rad, cy), QPointF(cx + rad, cy))
        p.drawLine(QPointF(cx, cy - rad), QPointF(cx, cy + rad))

    def _cards(self, p, r, t, side):
        metrics = getattr(self, '_metrics', self.head['metrics'])
        if not metrics:
            return
        cols = 1 if side else 2
        rows = math.ceil(len(metrics) / cols)
        gap = 10
        ch = min(78, max(44.0, (r.height() - gap * (rows - 1)) / max(1, rows)))
        cw = (r.width() - gap * (cols - 1)) / cols
        for i, (label, value, tone) in enumerate(metrics):
            show = (t - BUILD_SECONDS * (.6 if side else .8) - CARD_STAGGER * i) / .35
            if show <= 0:
                continue
            a = min(1.0, show)
            x = r.left() + (i % cols) * (cw + gap) + (1 - a) * 24
            y = r.top() + (i // cols) * (ch + gap)
            box = QRectF(x, y, cw, ch)
            p.setPen(QPen(self._c(tone if tone != 'dim' else 'pri', 140 * a), 1))
            p.setBrush(self._c('pri', 14 * a))
            p.drawRoundedRect(box, 5, 5)
            p.fillRect(QRectF(x, y + 8, 3, ch - 16), self._c(tone if tone != 'dim' else 'pri', 230 * a))
            p.setPen(self._c('dim', 255 * a))
            p.setFont(QFont('Courier New', 8))
            p.drawText(QRectF(x + 12, y + 6, cw - 18, 16), Qt.AlignmentFlag.AlignLeft, label)
            p.setPen(self._c('white' if tone == 'dim' else tone, 255 * a))
            p.setFont(QFont('Courier New', 15 if ch > 56 else 11, QFont.Weight.Bold))
            p.drawText(QRectF(x + 12, y + 22, cw - 18, ch - 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                       | Qt.TextFlag.TextWordWrap, value)

    def _verdict(self, p, r, t, small=False):
        begin = BUILD_SECONDS + CARD_STAGGER * len(getattr(self, '_metrics', self.head['metrics']))
        n = int(max(0.0, t - begin) * TYPE_CPS)
        text = self.head['verdict'][:n]
        cursor = '▌' if n < len(self.head['verdict']) or int(t * 2) % 2 else ''
        p.setPen(QPen(self._c('pri', 90), 1))
        p.drawLine(QPointF(r.left(), r.top() - 4), QPointF(r.right(), r.top() - 4))
        p.setPen(self._c('text'))
        p.setFont(QFont('Courier New', 9 if small else 10))
        p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, text + cursor)
        p.setPen(self._c('dim'))
        p.setFont(QFont('Courier New', 7))
        p.drawText(QRectF(r.left(), r.bottom(), r.width(), 14), Qt.AlignmentFlag.AlignRight,
                   'PAST DATA · NO GUARANTEE OF FUTURE RESULTS' if self.shown.get('kind') == 'backtest'
                   else 'ILLUSTRATIVE MODEL BUILT BY JARVIS · NOT MEASURED DATA' if self.shown.get('kind') == 'process'
                   else 'HYPOTHETICAL MODEL ON YOUR ASSUMPTIONS · NOT A FORECAST')

    def _scanlines(self, p, w, h, t):
        y = (t * 90) % (h + 60) - 30
        g = QLinearGradient(QPointF(0, y - 30), QPointF(0, y + 30))
        g.setColorAt(0, self._c('pri', 0))
        g.setColorAt(.5, self._c('pri', 16))
        g.setColorAt(1, self._c('pri', 0))
        p.fillRect(QRectF(0, y - 30, w, 60), QBrush(g))
