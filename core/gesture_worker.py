"""Private local landmark process. stdout carries bounded local preview images and navigation metadata only."""
from pathlib import Path
import sys,json,threading
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PyQt6.QtWidgets import QApplication
app=QApplication(['JarvisLocalHandTracker']);app.setQuitOnLastWindowClosed(False)
from core.hand_gestures import GestureController
controller=GestureController();controller.generation=int(sys.argv[1])
def publish(event):print(json.dumps(event),flush=True)
controller._run_native(controller.generation,threading.Event(),publish)
publish({'kind':'worker_status','generation':controller.generation,'state':controller.state,'error':controller.error})
