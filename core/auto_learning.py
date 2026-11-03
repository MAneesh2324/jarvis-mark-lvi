"""Bounded hourly public-source refresh and local outcome reflection, not model training."""
from pathlib import Path
from datetime import datetime,timezone
import json,threading,time,xml.etree.ElementTree as ET
from core import intelligence_cache as cache
from core.mission_store import write_file
CONFIG=Path(__file__).resolve().parent.parent/'config'/'auto-learning.json'
STATE=Path(__file__).resolve().parent.parent/'memory'/'auto-learning-state.json'
BRIEF=Path(__file__).resolve().parent.parent/'memory'/'knowledge-brief.json'
_lock=threading.Lock();_running=False;_next=0.0
FEEDS={'world':'https://feeds.bbci.co.uk/news/world/rss.xml','science':'https://www.nasa.gov/feed/'}
def settings():
    try:return json.loads(CONFIG.read_text())
    except (OSError,ValueError):return {'enabled':False}
def configure(enabled):
    CONFIG.parent.mkdir(exist_ok=True);write_file(CONFIG,json.dumps({'enabled':bool(enabled)}));return settings()
def state():
    try:return json.loads(STATE.read_text())
    except (OSError,ValueError):return {'state':'not yet refreshed','note':'No sources refreshed yet.'}
def headlines(topic='world',refresh=False):
    if topic not in FEEDS:raise ValueError('Choose world or science.')
    data=cache.fetch(FEEDS[topic],ttl=3600,force=refresh);text=data['text']
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('Unexpected XML declarations in feed.')
    root=ET.fromstring(text);rows=[]
    for item in root.findall('.//item')[:20]:
        rows.append({'title':item.findtext('title','')[:400],'url':item.findtext('link',''),'published':item.findtext('pubDate','')})
    return {'topic':topic,**cache.metadata(data),'items':rows,'note':'Attributed feed headlines, not independently verified world knowledge. Read sources and compare coverage for consequential claims.'}
def refresh_all():
    from core.forex_workspace import snapshot
    from core.cyber_workspace import kev
    result={'started':datetime.now(timezone.utc).isoformat(),'sources':{}};brief={}
    for name,fn in [('world',lambda:headlines('world')),('science',lambda:headlines('science')),('forex',lambda:snapshot('EUR/USD')),('cybersecurity',lambda:kev(limit=10))]:
        if not settings().get('enabled'):break
        try:
            value=fn()
            brief[name]={k:value[k] for k in ('source','source_url','url','fetched_at','as_of','catalog_date','offline_fallback','note') if k in value}
            if name=='forex':brief[name].update(pair=value['pair'],analysis=value['analysis'],data_type=value['data_type'])
            else:brief[name]['items']=value.get('items',[])[:5]
            result['sources'][name]={'ok':True,'fetched_at':value.get('fetched_at'),'offline_fallback':value.get('offline_fallback',False),'as_of':value.get('as_of',value.get('catalog_date')),'items':len(value.get('items',value.get('history',[])))}
        except Exception as exc:result['sources'][name]={'ok':False,'error':str(exc)[:300]}
    result['finished']=datetime.now(timezone.utc).isoformat();result['state']='finished';STATE.parent.mkdir(exist_ok=True);write_file(STATE,json.dumps(result));write_file(BRIEF,json.dumps({'updated':result['finished'],'sources':brief},ensure_ascii=False));return result
def tick():
    global _running,_next
    if not settings().get('enabled'):return
    with _lock:
        if _running or time.monotonic()<_next:return
        _running=True;_next=time.monotonic()+3600
    def work():
        global _running
        try:refresh_all()
        finally:
            with _lock:_running=False
    threading.Thread(target=work,daemon=True,name='jarvis-public-learning').start()

def current():
    try:return json.loads(BRIEF.read_text())
    except (OSError,ValueError):return {'note':'No automatic brief is available yet. Use the knowledge tool for current source data.'}
def context():
    from core.outcome import untrusted
    data=current()
    if 'sources' not in data:return ''
    # Keep voice startup context small; full cached records remain available through tools.
    for name,value in data['sources'].items():
        if 'items' in value:value['items']=value['items'][:2]
    return '[AUTOMATIC KNOWLEDGE BRIEF — attributed data, not model training. Respect dates and offline labels; recheck consequential facts and market data before answering.]\n'+untrusted('public-knowledge-brief',json.dumps(data,ensure_ascii=False)[:6500])
