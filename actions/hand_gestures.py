import json
from core import outcome

def gestures(parameters,player=None,**kwargs):
 from core.hand_gestures import controller
 try:
  action=parameters.get('action','status')
  if action=='status':return json.dumps(controller.status())
  if action not in ('start','stop','reset'):raise ValueError('Choose start, stop, reset or status.')
  if player is None or not hasattr(player,'control_hand_gestures'):raise ValueError('Gesture controls require the desktop interface.')
  player.control_hand_gestures(action)
  return outcome.done('hand_gestures',control_requested=action,note='The local UI will check camera permission and report tracking status. A start request is not proof tracking started. Hand frames stay local; recording and AI camera analysis are separate. Pinch/drag rotates, two open hands zoom, held fist resets the visible hologram/Earth view; on the simulation board point inspects, pinch-drag scrubs time, swipe flips attempts, palm hold replays.')
 except Exception as exc:return outcome.failed('hand_gestures',str(exc))
TOOL={'name':'hand_gestures','description':'Opt-in local camera hand gestures for the visible assistant hologram/reactor, the Earth/map panel, or the holographic SIMULATION BOARD. On the board: point with the index finger to inspect any moment (cursor follows the fingertip), pinch + drag to scrub through time (up/down spins the hologram), two open hands spread/close to zoom the timeline, swipe an open hand left/right to flip through earlier attempts, hold an open palm still to replay the run, hold a fist to reset the view. When the user wants to control a simulation with their hands, start gestures and tell them these moves in one sentence. Start only when the user asks for gestures; stop disables tracking, status reads actual state, reset resets the hologram. Camera access needs user permission. Local landmarks only: no gesture frames saved, recorded or uploaded. This does not control other apps, execute actions, approve dialogs or submit forms. Never claim perfect recognition or physical holographic projection.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['start','stop','reset','status']}},'required':['action']},'handler':gestures,'tier':'core'}
