import sys,unittest
from unittest.mock import Mock,patch
from core import camera_permission as camera
class CameraTests(unittest.TestCase):
    def test_missing_purpose_is_blocked_before_qt_or_opencv(self):
        bundle=Mock();bundle.infoDictionary.return_value={};foundation=Mock();foundation.NSBundle.mainBundle.return_value=bundle
        with patch.object(camera.platform,'system',return_value='Darwin'),patch.dict(sys.modules,{'Foundation':foundation}):
            self.assertFalse(camera.status()['declared'])
            with self.assertRaisesRegex(PermissionError,'setup is incomplete'):camera.require()
    def test_camera_capture_denied_before_device_detection(self):
        from actions import screen_processor as capture
        with patch.object(camera,'require',side_effect=PermissionError('Camera denied')),patch.object(capture,'_CV2',True),patch.object(capture,'_get_camera_index') as detect,patch.object(capture.cv2,'VideoCapture') as device:
            with self.assertRaises(PermissionError):capture._capture_camera()
            detect.assert_not_called();device.assert_not_called()
    def test_camera_probe_is_also_permission_guarded(self):
        from actions import screen_processor as capture
        with patch.object(camera,'require',side_effect=PermissionError('Camera denied')),patch.object(capture,'_CV2',True),patch.object(capture.cv2,'VideoCapture') as device:
            with self.assertRaises(PermissionError):capture._probe_camera(0,0)
            device.assert_not_called()
    def test_denial_is_recoverable_without_native_prompt(self):
        with patch.object(camera,'status',return_value={'granted':False,'declared':True,'state':'Denied'}):
            with self.assertRaisesRegex(PermissionError,'No camera image was captured'):camera.require()
    def test_camera_request_dispatches_asynchronously_on_qt_thread(self):
        from PyQt6.QtCore import QCoreApplication
        app=Mock();callback=Mock()
        with patch.object(camera,'status',return_value={'granted':False,'declared':True}),patch.object(QCoreApplication,'instance',return_value=app):camera.request(callback)
        app.requestPermission.assert_called_once();callback.assert_not_called()
