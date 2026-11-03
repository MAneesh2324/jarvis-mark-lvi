import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading,unittest
from unittest.mock import Mock,patch
from core.hand_gestures import Interpreter,GestureController
from core import camera_access

def hand(dx=0,closed=False,pinch=False):
 points=[(.5+dx,.9)]*21
 for mcp,pip,dip,tip,x,y in ((5,6,7,8,.35,.65),(9,10,11,12,.45,.62),(13,14,15,16,.55,.65),(17,18,19,20,.65,.68)):
  points[mcp]=(x+dx,y);points[pip]=(x+dx,y-.12);points[dip]=(x+dx,y-.20);points[tip]=(x+dx,y+.05 if closed else y-.32)
 points[4]=points[8] if pinch else (.2+dx,.72)
 return points
class GestureTests(unittest.TestCase):
 def test_pinch_drag_rotates_and_limits_abrupt_jumps(self):
  tracker=Interpreter();first=tracker.update([hand(pinch=True)],0);self.assertEqual(first['kind'],'rotate');self.assertEqual(first['dx'],0)
  second=tracker.update([hand(.05,pinch=True)],.05);self.assertAlmostEqual(second['dx'],.05)
  third=tracker.update([hand(.3,pinch=True)],.1);self.assertLessEqual(third['dx'],.06)
 def test_two_hands_zoom_and_loss_resets_baseline(self):
  tracker=Interpreter();a=tracker.update([hand(-.1),hand(.1)],0);self.assertEqual(a['factor'],1)
  b=tracker.update([hand(-.2),hand(.2)],.1);self.assertEqual(b['kind'],'zoom');self.assertGreater(b['factor'],1);self.assertLessEqual(b['factor'],1.1)
  tracker.update([],1);self.assertEqual(tracker.update([hand(-.2),hand(.2)],1.1)['factor'],1)
 def test_fist_reset_requires_hold_and_emits_once(self):
  tracker=Interpreter();self.assertEqual(tracker.update([hand(closed=True)],0)['kind'],'idle');self.assertEqual(tracker.update([hand(closed=True)],.4)['kind'],'idle');self.assertEqual(tracker.update([hand(closed=True)],.9)['kind'],'reset');self.assertEqual(tracker.update([hand(closed=True)],1.5)['kind'],'idle')
 def test_no_hand_or_invalid_landmarks_never_move_hologram(self):
  tracker=Interpreter();self.assertEqual(tracker.update([])['kind'],'idle');points=hand();points[8]=(float('nan'),.3);self.assertEqual(tracker.update([points])['kind'],'idle')
 def test_permission_denial_never_starts_camera_worker(self):
  controller=GestureController()
  with patch('core.camera_permission.require',side_effect=PermissionError('Permission required')),patch('core.hand_gestures.threading.Thread') as worker:
   with self.assertRaises(PermissionError):controller.start(Mock())
   worker.assert_not_called();self.assertFalse(controller.status()['enabled'])
 def test_camera_lease_excludes_other_threads_and_releases_after_error(self):
  errors=[]
  def attempt():
   try:
    with camera_access.claim('other'):pass
   except RuntimeError as e:errors.append(str(e))
  with camera_access.claim('test owner'):
   thread=threading.Thread(target=attempt);thread.start();thread.join();self.assertIn('test owner',errors[0])
  with camera_access.claim('next owner'):pass
 def test_stale_gesture_events_are_ignored_after_stop(self):
  from ui import MainWindow
  from types import SimpleNamespace
  host=SimpleNamespace(hud=Mock());event={'generation':1,'kind':'rotate','dx':.1}
  with patch('core.hand_gestures.controller.status',return_value={'generation':2,'enabled':False}):MainWindow._apply_hand_gesture(host,event)
  host.hud.apply_hand_gesture.assert_not_called()
 def test_hologram_navigation_clamps_zoom_and_can_reset(self):
  from PyQt6.QtWidgets import QApplication
  from ui import HudCanvas
  app=QApplication.instance() or QApplication(['GestureTest']);hud=HudCanvas('face.png')
  hud.apply_hand_gesture({'kind':'zoom','factor':100});self.assertEqual(hud.gesture_zoom,1.6)
  hud.apply_hand_gesture({'kind':'rotate','dx':10,'dy':10});self.assertEqual(hud.gesture_yaw,1.2)
  hud.apply_hand_gesture({'kind':'reset'});self.assertEqual(hud.gesture_zoom,1);self.assertEqual(hud.gesture_yaw,0);hud.close()

if __name__=='__main__':unittest.main()

class IsolatedTrackerTests(unittest.TestCase):
 def test_native_worker_failure_does_not_escape_into_host_or_keep_camera_lease(self):
  import tempfile
  from pathlib import Path
  from core import hand_gestures as hand_module
  process=Mock();process.poll.return_value=-6;process.stdout.closed=False;process.stdout.fileno.return_value=99;callback=Mock();controller=GestureController();controller.generation=1
  with tempfile.TemporaryDirectory() as folder,patch.object(hand_module,'__file__',str(Path(folder)/'core'/'hand_gestures.py')),patch.object(hand_module.sys,'platform','linux'),patch('core.camera_permission.require'),patch.object(hand_module.subprocess,'Popen',return_value=process),patch.object(hand_module.select,'select',return_value=([process.stdout],[],[])),patch.object(hand_module.os,'read',return_value=b''):
   controller._supervise(1,threading.Event(),callback)
  self.assertEqual(controller.state,'failed');self.assertIn('Mark LVI is still running',controller.error);callback.assert_not_called()
  with camera_access.claim('after tracker failure'):pass
