import json
from core import outcome

def portable(parameters,player=None,**kwargs):
 try:
  action=parameters.get('action','open')
  if action=='status':
   from core.portable_memory import collect,summary,ROOT
   return outcome.untrusted('memory-portability-status',json.dumps({**summary(collect(False)),'restore_queued':(ROOT/'memory'/'restore-pending.json').exists()}))
  if action!='open':raise ValueError('Use open or status.')
  if player is None or not hasattr(player,'show_portable_memory'):raise ValueError('The local memory vault controls are unavailable.')
  player.show_portable_memory();return outcome.done('portable_memory',controls_requested=True,note='Ask the user to choose a local file and enter a passphrase only in the local masked field. No backup or restore has happened yet. Never ask for or handle the vault passphrase in conversation.')
 except Exception as exc:return outcome.failed('portable_memory',str(exc))
TOOL={'name':'portable_memory','description':'Open local encrypted memory export/restore controls, or read component counts. The passphrase is entered only in a masked local field, never in chat, voice, tool arguments, memory or cloud requests. Creating/opening controls does not create a backup or restore data. The UI authenticates and previews a vault before an explicit queued startup-only replacement restore, with local rollback. Credentials, recordings, artifacts and device permissions are excluded.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['open','status']}},'required':['action']},'handler':portable,'tier':'core'}
