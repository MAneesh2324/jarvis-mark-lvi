import json
from core import outcome
from core import work_routines as routines


def manage(parameters,player=None,**kwargs):
    try:
        action=parameters.get('action','list');name=parameters.get('name','')
        if action=='save':data=routines.save(name,parameters.get('steps'))
        elif action=='preview':data=routines.preview(name)
        elif action=='run':data=routines.run(name,player)
        elif action=='list':data=routines.list_routines()
        else:raise ValueError('Choose save, preview, run or list.')
        return outcome.untrusted('routine-result',json.dumps(data,ensure_ascii=False))
    except Exception as exc:return outcome.failed('work_routines',str(exc))

TOOL={'name':'work_routines','description':'Save, preview, list and run named work routines. Only run when the user explicitly requests that routine. Steps can open apps/documents/folders, arrange an existing app window, set volume or activate a saved project. No arbitrary scripts or shell commands. Report requested launches separately from verified outcomes; stop on a failed step. Newly launched apps may take time before a later window-arrangement step succeeds.',
'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['save','preview','run','list']},'name':{'type':'STRING'},'steps':{'type':'ARRAY','items':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['open_app','open_path','arrange_app','volume','activate_project']},'app':{'type':'STRING'},'position':{'type':'STRING','enum':['left','right','maximize']},'path':{'type':'STRING'},'percent':{'type':'INTEGER'},'name':{'type':'STRING'}},'required':['action']}}},'required':['action']},'handler':manage,'tier':'core'}
