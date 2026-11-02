"""Home Assistant setup for later. Credentials never enter voice tools or mission records."""
from pathlib import Path
from urllib.parse import urlparse
import ipaddress,json,re,time
import requests
from core.mission_store import write_file
CONFIG=Path(__file__).resolve().parent.parent/'config'/'home-assistant-private.json'
def setup(url,token,entities):
    url=str(url).strip().rstrip('/');p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):raise ValueError('Use a Home Assistant origin such as http://homeassistant.local:8123.')
    try:local=ipaddress.ip_address(p.hostname).is_private or ipaddress.ip_address(p.hostname).is_loopback
    except ValueError:local=p.hostname=='localhost' or p.hostname.endswith('.local')
    if p.scheme=='http' and not local:raise ValueError('Use HTTPS for a remote Home Assistant server.')
    if not token or len(token)>4096:raise ValueError('Enter a long-lived access token from your Home Assistant profile.')
    allowed=[x.strip() for x in entities if x.strip()]
    if len(allowed)>100 or any(not re.fullmatch(r'(light|switch)\.[a-z0-9_]+',x) for x in allowed):raise ValueError('Allow only explicit light.* or switch.* entity IDs (up to 100).')
    write_file(CONFIG,json.dumps({'url':url,'token':token,'entities':allowed}));return status()
def status():
    if not CONFIG.exists():return {'configured':False,'note':'No smart-home platform is connected. Add your own Home Assistant server and allowed lights/switches in Mission Control.'}
    c=json.loads(CONFIG.read_text());return {'configured':True,'url':c['url'],'entities':c['entities']}
def disconnect():
    if CONFIG.exists():CONFIG.unlink()
    return status()
def _request(method,path,**kwargs):
    if not CONFIG.exists():raise ValueError('Set up Home Assistant first.')
    c=json.loads(CONFIG.read_text())
    try:
        result=requests.request(method,c['url']+'/api/'+path,headers={'Authorization':'Bearer '+c['token'],'Content-Type':'application/json'},timeout=8,allow_redirects=False,**kwargs)
        if result.status_code not in (200,201):raise RuntimeError(f'Home Assistant returned HTTP {result.status_code}; check the connection/token.')
        return result.json()
    except requests.RequestException:raise RuntimeError('Home Assistant connection failed; check its URL, certificate and network.') from None

def states():
    c=status()
    if not c['configured']:return c
    rows=[]
    data=_request('GET','states')
    for item in data:
        entity=str(item.get('entity_id',''))
        if entity in c['entities']:rows.append({'entity':entity,'state':str(item.get('state','unknown')),'name':str(item.get('attributes',{}).get('friendly_name',entity))[:120]})
    return {'configured':True,'states':rows}
def control(entity,on):
    allowed=status().get('entities',[])
    if entity not in allowed:raise ValueError('That entity is not in your explicitly configured light/switch allowlist.')
    desired='on' if on else 'off';domain=entity.split('.')[0]
    _request('POST',f'services/{domain}/turn_{desired}',json={'entity_id':entity})
    observed='unknown'
    for _ in range(3):
        data=_request('GET','states/'+entity);observed=str(data.get('state','unknown'))
        if observed==desired:break
        time.sleep(.3)
    return {'entity':entity,'requested':desired,'observed':observed,'verified':observed==desired}
