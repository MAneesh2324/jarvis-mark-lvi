"""Embedded maps with explicitly requested, session-only location access."""
import json
import threading
import platform
from PyQt6.QtCore import QObject,QUrl,pyqtSignal,pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QMessageBox
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEnginePermission
from core import earth_maps


class EarthPage(QWebEnginePage):
    def __init__(self,profile,origin,parent):
        super().__init__(profile,parent);self.origin=origin
    def acceptNavigationRequest(self,url,kind,is_main_frame):
        if not is_main_frame:return True
        parsed=QUrl(self.origin)
        local=url.scheme()=='http' and url.host()=='127.0.0.1' and url.port()==parsed.port()
        if local or url.toString()=='about:blank':return True
        if kind==QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ('http','https'):QDesktopServices.openUrl(url)
        return False
    def javaScriptConsoleMessage(self,level,message,line,source):
        if level==QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:print('[Earth JS]',message[:300])


class Bridge(QObject):
    def __init__(self,panel):super().__init__(panel);self.panel=panel
    @pyqtSlot()
    def ready(self):self.panel.ready=True;self.panel.apply_pending()
    @pyqtSlot(str)
    def reportView(self,value):
        try:earth_maps.update_view(json.loads(value))
        except (ValueError,TypeError):pass
    @pyqtSlot(str)
    def reportLocation(self,value):
        try:earth_maps.update_location(json.loads(value))
        except (ValueError,TypeError):pass
    @pyqtSlot()
    def clearLocation(self):
        earth_maps.clear_location()
        self.panel._device_authorized=False
    @pyqtSlot()
    def requestDeviceLocation(self):self.panel.request_device_location()
    @pyqtSlot()
    def requestApproximateLocation(self):self.panel.request_approximate_location()


class EarthPanel(QWidget):
    _location_result=pyqtSignal(object)
    def __init__(self,parent=None):
        super().__init__(parent);self.ready=False;self.pending={};self._device_authorized=False
        self.origin=earth_maps.start_server()
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.view=QWebEngineView(self);layout.addWidget(self.view)
        self.profile=QWebEngineProfile(self)
        self.profile.setHttpUserAgent('JarvisEarth/1.0 '+self.profile.httpUserAgent())
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.page=EarthPage(self.profile,self.origin,self.view)
        self.view.setPage(self.page)
        self.channel=QWebChannel(self.page);self.bridge=Bridge(self)
        self.channel.registerObject('earth',self.bridge);self.page.setWebChannel(self.channel)
        self.page.permissionRequested.connect(self._permission)
        self._location_result.connect(self._set_location)
        self.view.setUrl(QUrl(self.origin))
    def apply(self,options):
        self.pending=earth_maps.validate_options(options)
        self.apply_pending()
    def apply_pending(self):
        if self.ready and self.pending:
            payload=self.pending;self.pending={}
            self.page.runJavaScript('window.JarvisEarth.apply('+json.dumps(payload)+');')
    def _permission(self,permission):
        parsed=permission.origin();local=parsed.host()=='127.0.0.1' and parsed.port()==QUrl(self.origin).port()
        if local and self._device_authorized and permission.permissionType()==QWebEnginePermission.PermissionType.Geolocation:permission.grant()
        else:permission.deny()
    def request_device_location(self):
        if platform.system()=='Darwin':
            import Foundation
            info=Foundation.NSBundle.mainBundle().infoDictionary()
            if not info or not info.get('NSLocationWhenInUseUsageDescription'):
                QMessageBox.information(self,'Use the location-ready launcher','Open Mark LVI.app from your Desktop to request macOS device location. The plain Python launcher does not declare a location purpose. Approximate location and manual coordinates remain available here.')
                return
        if not self._device_authorized:
            choice=QMessageBox.question(self,'Use device location?','Allow JARVIS to request your device location from macOS for this session? If you view street or satellite maps there, area tiles are requested from OpenStreetMap or Esri. Your fix is not saved to disk.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if choice!=QMessageBox.StandardButton.Yes:return
            self._device_authorized=True
        self.page.runJavaScript('window.JarvisEarth.beginDeviceLocation();')
    def request_approximate_location(self):
        choice=QMessageBox.question(self,'Approximate network location?','Ask ipapi.co for an approximate city-level location based on your public IP? The service receives your IP address. This is not GPS and may reflect a VPN. Map tiles for a viewed area are requested from OpenStreetMap or Esri.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if choice!=QMessageBox.StandardButton.Yes:return
        def locate():
            try:self._location_result.emit(earth_maps.approximate_location())
            except Exception as exc:self._location_result.emit({'error':str(exc)})
        threading.Thread(target=locate,daemon=True,name='approximate-location').start()
    def _set_location(self,result):
        if 'error' in result:
            QMessageBox.information(self,'Location unavailable',result['error']);return
        self.page.runJavaScript('window.JarvisEarth.setFix('+json.dumps(result)+');')
    def hideEvent(self,event):
        if self.ready:self.page.runJavaScript('window.JarvisEarth.setPaused(true);')
        super().hideEvent(event)
    def showEvent(self,event):
        if self.ready:self.page.runJavaScript('window.JarvisEarth.setPaused(false);')
        super().showEvent(event)
