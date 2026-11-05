"""Live simulation lab: the JARVIS holographic board with sliders.

    .venv/bin/python simulation_live.py

Drag a slider and the simulation re-runs while you drag (instant redraw); let
go and it replays the full build-up. "Auto demo" cycles through scenarios on its
own. Everything is local: the same core/scenario_simulator.py JARVIS uses, no
API key, no network.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
                             QPushButton, QSlider, QVBoxLayout, QWidget)

from core.scenario_simulator import compare, run
from core.simulation_view import SimulationHologram

BG, PANEL, PRI, TEXT, DIM = '#00060a', '#010d14', '#00d4ff', '#8ffcff', '#3a8a9a'

# name: (label, min, max, step, default, unit)
SCENARIOS = {
    'OSCP / study goal': ('goal', {
        'total_hours': ('Total hours needed', 20, 1000, 10, 300, 'h'),
        'hours_per_day': ('Hours per day', .5, 12, .5, 3, 'h'),
        'consistency_percent': ('Days you actually study', 10, 100, 5, 80, '%'),
        'hours_done': ('Hours already done', 0, 500, 10, 0, 'h'),
        'deadline_days': ('Deadline (0 = none)', 0, 365, 5, 150, 'd'),
        'daily_variation_percent': ('Day-to-day variation', 0, 100, 5, 25, '%'),
    }),
    'Savings plan': ('savings', {
        'monthly_contribution': ('Monthly contribution', 0, 100000, 500, 10000, ''),
        'months': ('Months', 6, 120, 6, 36, ''),
        'start_balance': ('Starting balance', 0, 1000000, 10000, 0, ''),
        'annual_return_percent': ('Assumed annual return', -10, 20, .5, 6, '%'),
        'annual_volatility_percent': ('Assumed volatility', 0, 40, 1, 10, '%'),
        'target': ('Target (0 = none)', 0, 5000000, 10000, 400000, ''),
    }),
    'Forex paths': ('forex', {
        'start_rate': ('Start rate', .5, 2, .01, 1.1, ''),
        'annual_return_percent': ('Assumed annual drift', -20, 20, 1, 0, '%'),
        'annual_volatility_percent': ('Assumed volatility', 1, 60, 1, 10, '%'),
        'days': ('Trading days', 10, 500, 10, 90, ''),
        'shock_percent': ('Immediate shock', -20, 20, 1, 0, '%'),
    }),
    'Service outage': ('outage', {
        'requests_per_minute': ('Requests / minute', 10, 5000, 10, 100, ''),
        'outage_minutes': ('Outage length', 1, 240, 1, 30, 'min'),
        'affected_percent': ('Traffic affected', 5, 100, 5, 100, '%'),
        'capacity_per_minute': ('Recovery capacity / min', 10, 10000, 10, 200, ''),
        'retry_percent': ('Failed requests retried', 0, 100, 5, 50, '%'),
    }),
}


class Control(QWidget):
    """A labelled slider over a float range."""

    def __init__(self, key, label, lo, hi, step, value, unit, on_move, on_release):
        super().__init__()
        self.key, self.lo, self.step, self.unit = key, lo, step, unit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(2)
        self.title = QLabel()
        self.title.setStyleSheet(f'color:{TEXT}; font: 11px "Courier New";')
        lay.addWidget(self.title)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, round((hi - lo) / step))
        self.slider.setValue(round((value - lo) / step))
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height:4px; background:#0d3347; border-radius:2px; }}
            QSlider::sub-page:horizontal {{ background:{PRI}; border-radius:2px; }}
            QSlider::handle:horizontal {{ background:#d8f8ff; width:12px; margin:-5px 0; border-radius:6px; }}""")
        lay.addWidget(self.slider)
        self._label = label
        self.slider.valueChanged.connect(lambda _: (self._refresh(), on_move()))
        self.slider.sliderReleased.connect(on_release)
        self._refresh()

    def value(self):
        v = self.lo + self.slider.value() * self.step
        return round(v, 4)

    def _refresh(self):
        v = self.value()
        shown = f'{v:,.0f}' if self.step >= 1 else f'{v:g}'
        self.title.setText(f'{self._label}:  {shown}{self.unit}')


class LiveLab(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('JARVIS · Simulation Lab (live)')
        self.resize(1320, 760)
        root = QWidget()
        root.setStyleSheet(f'background:{BG};')
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)

        side = QFrame()
        side.setFixedWidth(300)
        side.setStyleSheet(f'QFrame {{ background:{PANEL}; border-right:1px solid #0d3347; }} QLabel {{ border:none; }}')
        self.side = QVBoxLayout(side)
        self.side.setContentsMargins(16, 16, 16, 16)
        head = QLabel('SIMULATION LAB')
        head.setStyleSheet(f'color:{PRI}; font: bold 15px "Courier New"; letter-spacing:2px;')
        self.side.addWidget(head)
        sub = QLabel('Drag to re-run live. Release to replay.')
        sub.setStyleSheet(f'color:{DIM}; font: 10px "Courier New";')
        self.side.addWidget(sub)

        self.kind = QComboBox()
        self.kind.addItems(SCENARIOS)
        self.kind.setStyleSheet(f'QComboBox {{ color:{TEXT}; background:#011520; border:1px solid #1a5c7a; padding:5px; '
                                f'font: 12px "Courier New"; }} QComboBox QAbstractItemView {{ color:{TEXT}; background:#011520; }}')
        self.kind.currentTextChanged.connect(self._build_controls)
        self.side.addWidget(self.kind)

        self.controls_box = QVBoxLayout()
        self.side.addLayout(self.controls_box)
        self.side.addStretch(1)

        self.compare = QCheckBox('Compare with pinned baseline')
        self.compare.setStyleSheet(f'color:{TEXT}; font: 11px "Courier New";')
        self.compare.toggled.connect(lambda _: self._run(animate=True))
        self.side.addWidget(self.compare)
        btns = QHBoxLayout()
        for text, fn in (('PIN BASELINE', self._pin), ('▶ REPLAY', lambda: self._run(animate=True))):
            b = QPushButton(text)
            b.setStyleSheet(f'QPushButton {{ color:{TEXT}; background:#001f2e; border:1px solid #1a5c7a; padding:7px; '
                            f'font: bold 11px "Courier New"; }} QPushButton:hover {{ border-color:{PRI}; }}')
            b.clicked.connect(fn)
            btns.addWidget(b)
        self.side.addLayout(btns)
        self.auto = QCheckBox('Auto demo (cycle scenarios)')
        self.auto.setStyleSheet(f'color:{TEXT}; font: 11px "Courier New";')
        self.auto.toggled.connect(lambda on: self.demo.start(12000) if on else self.demo.stop())
        self.side.addWidget(self.auto)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f'color:{DIM}; font: 10px "Courier New";')
        self.side.addWidget(self.status)
        row.addWidget(side)

        self.board = SimulationHologram()
        self.board.closed.connect(self.close)
        row.addWidget(self.board, 1)

        self.baseline = None
        self.controls: list[Control] = []
        self._debounce = QTimer(self, singleShot=True, interval=60)
        self._debounce.timeout.connect(lambda: self._run(animate=False))
        self.demo = QTimer(self)
        self.demo.timeout.connect(self._next_demo)
        self._build_controls(self.kind.currentText())

    def _build_controls(self, name):
        while self.controls_box.count():
            w = self.controls_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        kind, spec = SCENARIOS[name]
        self.controls = [Control(k, *v, on_move=self._debounce.start, on_release=lambda: self._run(animate=True))
                         for k, v in spec.items()]
        for c in self.controls:
            self.controls_box.addWidget(c)
        self.baseline = None
        self.compare.setChecked(False)
        self._run(animate=True)

    def _params(self):
        kind, _ = SCENARIOS[self.kind.currentText()]
        values = {c.key: c.value() for c in self.controls}
        for k in ('deadline_days', 'target'):
            if values.get(k) == 0:
                values.pop(k)
        for k in ('days', 'months', 'deadline_days'):
            if k in values:
                values[k] = int(values[k])
        if kind == 'forex':
            values['paths'] = 1000
        if kind in ('goal', 'savings'):
            values['paths'] = 1000           # snappier while dragging; same seed keeps runs comparable
        return kind, values

    def _pin(self):
        self.baseline = self._params()
        self.compare.setChecked(True)
        self.status.setText('Baseline pinned. Move a slider to see the alternative against it (dashed line).')

    def _run(self, animate=True):
        kind, values = self._params()
        try:
            if self.compare.isChecked() and self.baseline and self.baseline[0] == kind:
                changed = {k: v for k, v in values.items() if self.baseline[1].get(k) != v}
                result = compare(kind, self.baseline[1], changed) if changed else run(kind, values)
            else:
                result = run(kind, values)
        except Exception as exc:
            self.status.setText('⚠ ' + str(exc))
            return
        self.board.set_result(result, animate=animate)
        self.status.setText('Hypothetical model on your assumptions — not a forecast.')

    def _next_demo(self):
        i = (self.kind.currentIndex() + 1) % self.kind.count()
        self.kind.setCurrentIndex(i)


def main():
    app = QApplication(sys.argv)
    win = LiveLab()
    win.show()
    win.raise_()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
