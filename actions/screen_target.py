import json
from core import outcome
from core import screen_focus


def select(parameters,**kwargs):
    try:
        action=parameters.get('action','status')
        if action=='list_windows':data=screen_focus.windows()
        elif action=='select':data=screen_focus.select(parameters.get('mode','display'),parameters.get('monitor',1),parameters.get('window_id'),parameters.get('region'))
        elif action=='status':data=screen_focus.current()
        else:raise ValueError('Choose status, list_windows or select.')
        return outcome.untrusted('screen-target',json.dumps(data,ensure_ascii=False,default=lambda o:dict(o) if hasattr(o,'keys') else str(o)))
    except Exception as exc:return outcome.failed('screen_target',str(exc))

TOOL={'name':'screen_target','description':'Choose what screen analysis may see: a display, an exact macOS window ID, or a rectangular region. List windows first to find the requested app/title; ask which one if ambiguous. Window capture stops if that window closes; it never silently switches to the full desktop. Region selection captures only visible pixels and can contain overlapping windows. This controls AI screen analysis, not the independent whole-display video recording.',
'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['status','list_windows','select']},'mode':{'type':'STRING','enum':['display','window','region']},'monitor':{'type':'INTEGER'},'window_id':{'type':'INTEGER'},'region':{'type':'OBJECT','properties':{k:{'type':'INTEGER'} for k in ('left','top','width','height')},'required':['left','top','width','height']}},'required':['action']},'handler':select,'tier':'core'}
