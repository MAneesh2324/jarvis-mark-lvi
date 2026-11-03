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
  return outcome.done('hand_gestures',control_requested=action,note='The local UI will check camera permission and report tracking status. A start request is not proof tracking started. Hand frames stay local; recording and AI camera analysis are separate. Pinch/drag rotates, two open hands zoom, held fist resets the visible hologram/Earth view.')
 except Exception as exc:return outcome.failed('hand_gestures',str(exc))
TOOL={'name':'hand_gestures','description':'Opt-in local camera hand gestures for the visible assistant hologram/reactor or Earth/map panel. Start only when the user asks for gestures; stop disables tracking, status reads actual state, reset resets the hologram. Camera access needs user permission. Local landmarks only: no gesture frames saved, recorded or uploaded. This does not control other apps, execute actions, approve dialogs or submit forms. Never claim perfect recognition or physical holographic projection.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['start','stop','reset','status']}},'required':['action']},'handler':gestures,'tier':'core'}
