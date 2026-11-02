"""Check permission before OpenCV touches macOS camera APIs."""
import platform

def status():
    if platform.system()!='Darwin':return {'granted':True,'declared':True,'state':'platform-managed'}
    import Foundation
    bundle=Foundation.NSBundle.mainBundle();info=bundle.infoDictionary() or {}
    if not info.get('NSCameraUsageDescription'):return {'granted':False,'declared':False,'state':'missing-purpose'}
    from PyQt6.QtCore import QCoreApplication,QCameraPermission,Qt
    app=QCoreApplication.instance()
    if app is None:return {'granted':False,'declared':True,'state':'no-app'}
    permission=app.checkPermission(QCameraPermission())
    return {'granted':permission==Qt.PermissionStatus.Granted,'declared':True,'state':permission.name}

def require():
    state=status()
    if state['granted']:return
    if not state['declared']:raise PermissionError('Camera setup is incomplete. Open the updated Desktop Mark LVI.app; camera access was blocked safely before capture.')
    raise PermissionError('Mark LVI needs Camera permission. Use Controls → Camera Permission, approve the macOS prompt if desired, then ask again. No camera image was captured or shared.')

def request(callback):
    import threading
    if threading.current_thread() is not threading.main_thread():raise RuntimeError('Camera permission must be requested on the GUI thread.')
    state=status()
    if not state['declared']:raise PermissionError('The app does not declare a camera purpose. Reopen the updated Mark LVI.app.')
    if state['granted']:callback(state);return
    from PyQt6.QtCore import QCoreApplication,QCameraPermission
    app=QCoreApplication.instance()
    if app is None:raise RuntimeError('Open Mark LVI before requesting camera access.')
    app.requestPermission(QCameraPermission(),lambda permission:callback(status()))
