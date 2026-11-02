import json
from core import outcome

def home(parameters,**kwargs):
    from core import home_bridge
    try:
        action=parameters.get('action','status')
        if action=='status':data=home_bridge.status()
        elif action=='states':data=home_bridge.states()
        elif action in ('on','off'):data=home_bridge.control(parameters.get('entity',''),action=='on')
        else:raise ValueError('Choose status, states, on or off.')
        return outcome.untrusted('home-assistant-result',json.dumps(data))
    except Exception as exc:return outcome.failed('home_assistant',str(exc))
TOOL={'name':'home_assistant','description':'Connect to the user’s configured Home Assistant server. Read status/allowed states or turn an explicitly allowed light/switch on or off when the user requests it. Setup and tokens are entered in the local Mission Control UI only. No server/device is connected by default. Only claim success if verified is true; otherwise report the observed state.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['status','states','on','off']},'entity':{'type':'STRING'}},'required':['action']},'handler':home,'tier':'core'}
