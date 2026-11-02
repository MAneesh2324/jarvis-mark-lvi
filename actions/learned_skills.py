import json
from core import outcome

def skills(parameters,player=None,**kwargs):
    from core import skill_learning as learn
    p=parameters
    try:
        action=p.get('action','list');name=p.get('name','')
        if action=='list':data=learn.listing()
        elif action=='preview':data=learn.get(name,p.get('version'))
        elif action=='from_mission':data=learn.from_mission(name,p.get('id',''))
        elif action=='from_routine':data=learn.from_routine(name,p.get('routine',''))
        elif action=='run':data=learn.run(name,p.get('version'),p.get('city',''),player)
        else:raise ValueError('Use list, preview, from_mission, from_routine or run.')
        return outcome.untrusted('learned-skill',json.dumps(data,ensure_ascii=False))
    except Exception as exc:return outcome.failed('learned_skills',str(exc))
TOOL={'name':'learned_skills','description':'List/preview versioned JARVIS skills, learn a draft from a completed mission or a saved routine, or run an exact user-requested approved version. New/edited versions require local review/approval in Mission Control → Skills. Creating a skill never approves or executes it. Ask for a city each restaurant-skill run. These are bounded declarative routines/mission recipes, not arbitrary code or passive recording.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['list','preview','from_mission','from_routine','run']},'name':{'type':'STRING'},'version':{'type':'INTEGER'},'id':{'type':'STRING'},'routine':{'type':'STRING'},'city':{'type':'STRING'}},'required':['action']},'handler':skills,'tier':'core'}
