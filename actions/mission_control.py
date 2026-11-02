import json
from core import outcome

def control(parameters,player=None,**kwargs):
    from core.mission_engine import engine
    from core import mission_store as store
    p=parameters;action=p.get('action','list')
    try:
        service=engine()
        if action=='plan':data=service.plan(p.get('kind','research'),p.get('goal',''),**{k:p[k] for k in ('city','limit','radius','root','files','ai','name') if k in p})
        elif action=='start':data=service.start(p.get('id',''),player)
        elif action in ('pause','cancel'):data=service.stop(p.get('id',''),action=='pause')
        elif action=='status':data=store.get(p.get('id',''))
        elif action=='list':data=store.listing()
        elif action=='note':
            note=str(p.get('note','')).strip()
            if not note or len(note)>1000:raise ValueError('Use a note of 1–1000 characters.')
            store.get(p.get('id',''));store.event(p['id'],'User correction/note: '+note);data=store.get(p['id'])
        elif action=='website_draft':
            from core.mission_workflows import draft_website
            data={'draft':draft_website(p.get('id',''),int(p.get('lead_index',0))),'published':False}
        elif action=='show':
            if player is None or not hasattr(player,'show_missions'):raise ValueError('Mission dashboard is unavailable in this session.')
            player.show_missions();data={'dashboard_requested':True}
        else:raise ValueError('Unknown mission action.')
        return outcome.untrusted('mission-result',json.dumps(data,ensure_ascii=False))
    except Exception as exc:return outcome.failed('mission_control',str(exc))

TOOL={'name':'mission_control','description':'Plan, start, inspect, pause or cancel persistent background missions: research, restaurants, engineering review, named saved Mac routine, or local personal briefing. A plan does not start work; after the user requests execution, start its returned ID. Ask for a city EACH restaurant search; do not use device location or a remembered default. Restaurant results are unverified leads, not proof of no website. website_draft creates a private local concept for a zero-based lead_index, never publishes or sends it. AI synthesis is opt-in with ai=true; engineering shares only the explicitly selected relative files. note stores user corrections for review; it does not automatically change running steps. Read actual mission state; queued is not completed. Show opens Mission Control.',
'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['plan','start','pause','cancel','status','list','show','note','website_draft']},'kind':{'type':'STRING','enum':['research','restaurants','engineering','routine','briefing']},'id':{'type':'STRING'},'goal':{'type':'STRING'},'city':{'type':'STRING'},'radius':{'type':'INTEGER'},'limit':{'type':'INTEGER'},'root':{'type':'STRING'},'files':{'type':'ARRAY','items':{'type':'STRING'}},'ai':{'type':'BOOLEAN'},'name':{'type':'STRING'},'note':{'type':'STRING'},'lead_index':{'type':'INTEGER'}},'required':['action']},'handler':control,'tier':'core'}
