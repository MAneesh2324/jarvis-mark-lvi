"""The 3D viewport on the simulation board: web/sim3d (three.js, bundled locally) in a QWebEngineView.

Everything is local: the page is a file under web/sim3d and loads only its own bundle.
Python pushes the model and the time to show; the page reports the time it is showing
so the chart can mark it during the time-lapse loop.
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

PAGE = Path(__file__).resolve().parent.parent / 'web' / 'sim3d' / 'index.html'


REQUESTS = ('gestures:start', 'gestures:stop')               # the only things the page can ask for


class _Page(QWebEnginePage):
    request = pyqtSignal(str)

    def acceptNavigationRequest(self, url, kind, main):
        return url.isLocalFile()                             # nothing but the local scene page

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith('[[sim3d]] '):
            if message[10:] in REQUESTS:
                self.request.emit(message[10:])
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print('[Sim3D JS]', message[:300])


class Sim3DView(QWebEngineView):
    gesture_request = pyqtSignal(str)                        # 'gestures:start' | 'gestures:stop' from the ✋ button

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ready = False
        self.current_time = None
        self._model = None
        self._time = 'unset'
        self._status = 'unset'
        page = _Page(self)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        self.setPage(page)
        page.request.connect(self.gesture_request.emit)
        page.setBackgroundColor(QColor('#00060a'))
        self.loadFinished.connect(self._loaded)
        self.setUrl(QUrl.fromLocalFile(str(PAGE)))
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._ask_time)
        self._poll.start(120)

    @staticmethod
    def available() -> bool:
        return PAGE.is_file() and (PAGE.parent / 'vendor' / 'sim3d.bundle.js').is_file()

    def _loaded(self, ok):
        self.ready = bool(ok)
        if ok and self._model is not None:
            self._push()

    def _js(self, code, cb=None):
        if self.ready:
            if cb is None:
                self.page().runJavaScript(code)
            else:
                self.page().runJavaScript(code, cb)

    def _push(self):
        self._js('window.Sim3D && Sim3D.load(' + json.dumps(self._model, allow_nan=False) + ');')
        self._time = self._status = 'unset'

    def show_model(self, result: dict, status=None) -> None:
        """Send a board result's 3D part: the series, times, units and scene."""
        scene = dict(result.get('scene') or {'type': 'columns'})
        self._model = {'series': result.get('series') or {}, 'series_t': result.get('series_t') or [0, 1],
                       'units': result.get('units') or {}, 'title': result.get('title') or '',
                       'x_unit': result.get('x_unit') or '', 'scene': scene, 'status': status}
        self._push()

    def set_time(self, t) -> None:
        """Show the state at time t; None plays the whole run as a time-lapse loop."""
        value = None if t is None else round(float(t), 3)
        if value != self._time:
            self._time = value
            self._js('window.Sim3D && Sim3D.setTime(' + ('null' if value is None else repr(value)) + ');')

    def set_status(self, status) -> None:
        if status != self._status:
            self._status = status
            self._js('window.Sim3D && Sim3D.setStatus(' + json.dumps(status) + ');')

    def _ask_time(self):
        if self.ready and self.isVisible():
            self._js('window.Sim3D ? Sim3D.currentTime() : null', self._got_time)

    def _got_time(self, value):
        self.current_time = value if isinstance(value, (int, float)) else None

    def hand(self, frame: dict) -> None:
        """One hand-tracker frame: {t, hands: [{id, x, y, s, p, pts}]}. The page does the smoothing and controls."""
        self._js('window.Sim3D && Sim3D.hands(' + json.dumps(frame, allow_nan=False) + ');')

    def gesture_state(self, state: dict) -> None:
        self._js('window.Sim3D && Sim3D.gestureState(' + json.dumps(state, default=str) + ');')
