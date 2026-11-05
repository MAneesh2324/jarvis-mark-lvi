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
        self._attach_3d()
        self.update()

    # ── the 3D viewport (process models) ─────────────────────────────────────
    @staticmethod
    def make_3d(parent):
        """The real three.js viewport, or None where it cannot run (no web engine, headless tests)."""
        import os
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen' or os.environ.get('JARVIS_NO_3D'):
            return None
        try:
            from core.sim3d_view import Sim3DView
            return Sim3DView(parent) if Sim3DView.available() else None
        except Exception as exc:                             # missing QtWebEngine: the board still works in 2D
            print(f'[Sim3D] 3D view unavailable: {exc}')
            return None

    def _attach_3d(self):
        wants = self.shown.get('kind') == 'process' and bool(self.shown.get('series'))
        view = getattr(self, '_view3d', None)
        if wants and view is None and not getattr(self, '_3d_failed', False):
            view = self._view3d = self.make_3d(self)
            self._3d_failed = view is None
        self._3d_on = bool(wants and view is not None)
        if view is not None:
            if self._3d_on:
                session = self.result.get('session') or {}
                view.show_model(self.shown, session.get('status'))
                view.show()
            else:
                view.hide()

    def _sync_3d(self, p, chart, t):
        """Keep the 3D scene on the chart's time, and mark the chart where the 3D scene is."""
        view = getattr(self, '_view3d', None)
        if not getattr(self, '_3d_on', False) or view is None or not self.rows:
            return
        X, _Y, _lo, _hi, last = self._scale(chart)
        reveal = 1 - (1 - min(1.0, t / BUILD_SECONDS)) ** 3
        hover = getattr(self, '_hover', None)
        if reveal < 1:
            view.set_time(last * reveal)                     # the scene grows with the scanning beam
        elif hover is not None and chart.contains(hover):
            view.set_time((hover.x() - chart.left()) / chart.width() * last)
        else:
            view.set_time(None)                              # then plays the run as a time-lapse loop
            now = view.current_time
            if isinstance(now, (int, float)) and 0 <= now <= last:
                x = X(now)
                p.setPen(QPen(self._c('acc2', 170), 1.2))
                p.drawLine(QPointF(x, chart.top()), QPointF(x, chart.bottom()))
                p.setFont(QFont('Courier New', 7, QFont.Weight.Bold))
                p.setPen(self._c('acc2'))
                p.drawText(QRectF(x + 3, chart.top() + 2, 40, 10), Qt.AlignmentFlag.AlignLeft, '3D')
        view.set_status((self.result.get('session') or {}).get('status'))

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

    def showEvent(self, e):
        # Adding the native 3D viewport makes Qt hide and re-show this widget once; keep animating.
        super().showEvent(e)
        if self.result:
            self._timer.start(33 if not self.finished() else 50)

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
        hero = None
        if getattr(self, '_3d_on', False):                   # the 3D scene is the main picture, the chart below it
            if side:
                avail = h - 64 - 150
                hero = QRectF(28, 64, w * .64 - 48, avail * .62)
                chart = QRectF(left, hero.bottom() + 12, w * .64 - left - 20, avail - hero.height() - 12)
            else:
                hero = QRectF(28, 64, w - 56, max(150.0, h * .36))
                chart = QRectF(left, hero.bottom() + 12, w - left - 24,
                               max(90.0, h - hero.bottom() - 12 - 110 - cards_h - 40))
            geo = hero.toRect()
            if self._view3d.geometry() != geo:
                self._view3d.setGeometry(geo)
        elif side:
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
        if scene and self.rows and not getattr(self, '_3d_on', False):
            self._scene(p, eq, t, scene)                     # the flat picture, when 3D is not available
        if self.rows:
            self._sync_3d(p, eq, t)
        if hero is not None:                                 # a thin frame around the 3D viewport
            p.setPen(QPen(self._c('pri', 120), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(hero.adjusted(-1, -1, 1, 1))
        if self._deferred:                                   # hover readouts sit on top of everything
            self._readout(p, *self._deferred)
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
        return (lambda day: r.left() + r.width() * day / last), (lambda v: r.top() + r.height() * (hi - v) / (hi - lo)), lo, hi, last

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
        if isinstance(dl, (int, float)) and dl <= last:
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
            d = last * i / 10
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
                x1, x2 = X(st['start']), X(st['end'])
                active = x1 <= edge
                p.setPen(self._c('text' if active else 'dim', 230 if active else 120))
                p.drawText(QRectF(x1 + 2, r.top() + 2 + (k % 2) * 10, max(10.0, x2 - x1 - 4), 10), Qt.AlignmentFlag.AlignLeft,
                           p.fontMetrics().elidedText(st['name'].upper(), Qt.TextElideMode.ElideRight, int(max(10.0, x2 - x1 - 4))))
        for ev in self.shown.get('events') or []:
            if ev.get('at') is None or X(ev['at']) > edge:
                continue
            x = X(ev['at'])
            p.setPen(QPen(self._c('green', 200), 1.2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, r.top() + 22), QPointF(x, r.bottom()))
            p.setFont(QFont('Courier New', 8, QFont.Weight.Bold))
            p.setPen(self._c('green'))
            p.drawText(QRectF(x - 124, r.bottom() - 32, 120, 14), Qt.AlignmentFlag.AlignRight, '◆ ' + ev['label'].upper())

        if reveal < 1:                                       # live numbers riding the beam
            day = last * reveal
            row = _at(self.rows, day)
            if row:
                self._tag(p, QPointF(edge, Y(row['median'])), f"{unit[:-1] if unit.endswith('s') else unit} {day:,.0f}",
                          _num(row['median'], yu), r, live=True)
        else:
            end = self.rows[-1]                              # final value pinned to the end of the line
            self._tag(p, QPointF(X(end['day']), Y(end['median'])), 'END', _num(end['median'], yu), r)
            hover = getattr(self, '_hover', None)
            if hover is not None and r.contains(hover):
                day = (hover.x() - r.left()) / r.width() * last
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
        ang, tilt = t * (.9 if status != 'success' else .4), .55 + .25 * math.sin(t * .5)
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
        day = last * reveal
        if reveal >= 1 and hover is not None and r.contains(hover):
            day = (hover.x() - r.left()) / r.width() * last
        k = min(range(len(ts)), key=lambda i: abs(ts[i] - day))
        val = lambda name, default=0.0: (series.get(name) or [default] * len(ts))[k]
        frac = lambda name, top: max(0.0, min(1.0, val(name) / top)) if name in series and top else 0.0
        side = min(140.0, max(90.0, r.height() * .52), r.width() * .36)
        box = QRectF(r.right() - side - 8, r.bottom() - side - 4, side, side)
        p.setPen(QPen(self._c('pri', 70), 1))
        p.setBrush(self._c('bg', 170))
        p.drawRoundedRect(box, 6, 6)
        kind = str(scene.get('type', 'grow'))
        if kind == 'columns':
            return                                           # columns only exist in 3D; the chart says it all in 2D
        kind = 'grow' if kind == 'tree' else kind
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
            if x > edge + 1:
                break
            k = (tr.get('r') or 0) / top
            hgt = abs(k) * (r.height() / 2 - 2)
            win = tr.get('result') == 'win'
            p.setBrush(self._c('green' if win else 'red', 220))
            p.drawRect(QRectF(x - bw / 2, mid - hgt if win else mid, bw, max(1.0, hgt)))
        hover = getattr(self, '_hover', None)
        if hover is not None and r.contains(hover) and self.finished():
            n = round((hover.x() - eq.left()) / eq.width() * last)
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
