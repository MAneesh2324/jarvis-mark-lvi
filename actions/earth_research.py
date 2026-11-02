import json
from core import outcome

def research(parameters,player=None,**kwargs):
    from core import place_intelligence as places,mission_store
    p=parameters
    try:
        action=p.get('action','city')
        if player is None or not hasattr(player,'show_earth'):raise ValueError('The Earth interface is unavailable.')
        if action=='city':
            data=places.city_lookup(p.get('city',''))
            player.show_earth({'view':'street','latitude':data['latitude'],'longitude':data['longitude'],'zoom':12})
        elif action=='mission_markers':
            item=mission_store.get(p.get('id',''))
            if item['kind']!='restaurants':raise ValueError('Choose a restaurant mission.')
            data=item['steps'][1]['result'] or item['steps'][0]['result']
            if not data:raise ValueError('The mission has not collected any places yet.')
            center=data['center'];player.show_earth({'view':'street','latitude':center['latitude'],'longitude':center['longitude'],'zoom':12,'markers':[{'latitude':r['latitude'],'longitude':r['longitude'],'label':r['name']+' — website status unverified'} for r in data['leads']]})
        elif action=='compare':
            from core.mission_engine import engine
            a=str(p.get('city','')).strip();b=str(p.get('other_city','')).strip()
            if not a or not b:raise ValueError('Provide both public cities/areas to compare.')
            item=engine().plan('research',f'Compare {a} and {b}: restaurants, transport, amenities and uncertainties, citing current sources.')
            data=engine().start(item['id'],player)
        elif action=='route':
            data=places.route((p['start_latitude'],p['start_longitude']),(p['end_latitude'],p['end_longitude']))
            player.show_earth({'view':'street','route':data})
        else:raise ValueError('Choose city, compare, mission_markers or route.')
        return outcome.untrusted('earth-research',json.dumps(data,ensure_ascii=False))
    except Exception as exc:return outcome.failed('earth_research',str(exc))
TOOL={'name':'earth_research','description':'Find a city and show it on Earth, compare two explicit public cities/areas with a background evidence mission, plot restaurant mission leads as markers, or fetch an estimated driving route between two explicit coordinate pairs. City lookup sends the city to Nominatim/OSM; routes send both endpoints to OSRM. Use only user-requested public city searches; do not send personal/confidential addresses. Never infer endpoints from device location without the user asking. Routing has no live traffic. Search results must retain source attribution.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['city','compare','mission_markers','route']},'city':{'type':'STRING'},'other_city':{'type':'STRING'},'id':{'type':'STRING'},'start_latitude':{'type':'NUMBER'},'start_longitude':{'type':'NUMBER'},'end_latitude':{'type':'NUMBER'},'end_longitude':{'type':'NUMBER'}},'required':['action']},'handler':research,'tier':'core'}
