import json
from core import outcome
from core import earth_maps as maps


def earth(parameters,player=None,**kwargs):
    try:
        action=parameters.get('action','open')
        if action=='status':return json.dumps(maps.status(),ensure_ascii=False)
        if player is None or not hasattr(player,'show_earth'):raise RuntimeError('The Earth interface is not available in this session.')
        if action=='close':player.show_earth({'close':True});return outcome.done('earth_maps',view='assistant')
        options={k:parameters[k] for k in ('view','latitude','longitude','zoom') if k in parameters}
        if action=='locate':options['locate']=True
        elif action not in ('open','fly_to'):raise ValueError('Choose open, fly_to, locate, close or status.')
        options=maps.validate_options(options);player.show_earth(options)
        return outcome.done('earth_maps',panel_requested=True,view=options['view'],note='Location access, if requested, requires the user to grant the displayed permission. Do not claim a location fix before status contains one. Satellite imagery is not live.')
    except Exception as exc:return outcome.failed('earth_maps',str(exc))

TOOL={'name':'earth_maps','description':'Show the Earth globe, street map or satellite imagery inside the JARVIS interface. Fly to explicit latitude/longitude, request a location permission dialog, close the panel, or inspect current session state. Never infer the user\'s location from a previous place search. Device location needs macOS permission; IP location is approximate and separate. Satellite imagery is historical, not live. Location is not saved to disk.',
'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['open','fly_to','locate','close','status']},'view':{'type':'STRING','enum':['globe','street','satellite']},'latitude':{'type':'NUMBER'},'longitude':{'type':'NUMBER'},'zoom':{'type':'INTEGER'}},'required':['action']},'handler':earth,'tier':'core'}
