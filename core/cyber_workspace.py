"""Read-only public security intelligence. No network scanning or exploitation."""
import json,re,threading,time
from urllib.parse import urlencode,urlparse
from core import intelligence_cache as cache
CISA='https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json'
MIRROR='https://raw.githubusercontent.com/cisagov/kev-data/develop/known_exploited_vulnerabilities.json'
_nvd_lock=threading.Lock();_last_nvd=0.0

def kev(query='',limit=30,refresh=False):
    try:data=cache.fetch(CISA,ttl=21600,force=refresh)
    except RuntimeError:data=cache.fetch(MIRROR,ttl=21600,force=refresh)
    payload=json.loads(data['text']);rows=payload.get('vulnerabilities')
    if not isinstance(rows,list):raise ValueError('The KEV feed has an unexpected format.')
    term=str(query).casefold().strip();matching=[]
    for row in rows:
        if term and term not in ' '.join(str(row.get(k,'')) for k in ('cveID','vendorProject','product','vulnerabilityName','shortDescription')).casefold():continue
        matching.append({k:row.get(k,'') for k in ('cveID','vendorProject','product','vulnerabilityName','dateAdded','shortDescription','requiredAction','dueDate','knownRansomwareCampaignUse','notes')})
    matching.sort(key=lambda r:(r['dateAdded'],r['cveID']),reverse=True)
    return {'source':'CISA Known Exploited Vulnerabilities','source_url':CISA,**cache.metadata(data),'catalog_version':payload.get('catalogVersion'),'catalog_date':payload.get('dateReleased'),'matching':len(matching),'items':matching[:max(1,min(100,int(limit)))],'note':'KEV records known exploitation, not a scan of your device. Due dates are catalog directives, not a personal patch deadline. Check vendor guidance and affected versions; not listed does not mean safe.'}
def _throttle():
    global _last_nvd
    with _nvd_lock:
        time.sleep(max(0,6.2-(time.monotonic()-_last_nvd)));_last_nvd=time.monotonic()
def cve(identifier,refresh=False):
    identifier=str(identifier).upper().strip()
    if not re.fullmatch(r'CVE-\d{4}-\d{4,}',identifier):raise ValueError('Use a CVE ID, such as CVE-2021-44228.')
    url='https://services.nvd.nist.gov/rest/json/cves/2.0?'+urlencode({'cveId':identifier})
    data=cache.fetch(url,ttl=21600,force=refresh,before_request=_throttle);payload=json.loads(data['text']);items=payload.get('vulnerabilities',[])
    if not items:raise ValueError('NVD returned no matching CVE. This does not establish that the product is safe.')
    entry=items[0]['cve'];metrics=[]
    for kind,values in entry.get('metrics',{}).items():
        for value in values:
            cvss=value.get('cvssData',{});metrics.append({'kind':kind,'source':value.get('source'),'score':cvss.get('baseScore'),'severity':cvss.get('baseSeverity',value.get('baseSeverity')),'vector':cvss.get('vectorString')})
    return {'id':entry.get('id'),'published':entry.get('published'),'last_modified':entry.get('lastModified'),'status':entry.get('vulnStatus'),'description':next((r['value'] for r in entry.get('descriptions',[]) if r.get('lang')=='en'),''),'metrics':metrics,'references':[r['url'] for r in entry.get('references',[])[:20]],'source_url':'https://nvd.nist.gov/vuln/detail/'+identifier,**cache.metadata(data),'note':'Severity scores are not evidence your system is affected or exploitable. Confirm vendor advisories, versions and your deployment.'}
def research(topic):
    from core.place_intelligence import search_sources
    domains=('cisa.gov','nist.gov','nvd.nist.gov','owasp.org','mitre.org','attack.mitre.org','portswigger.net')
    rows=search_sources(str(topic)[:300]+' ('+' OR '.join('site:'+d for d in domains)+')',10)
    rows=[r for r in rows if any((urlparse(r['url']).hostname or '').lower()==d or (urlparse(r['url']).hostname or '').lower().endswith('.'+d) for d in domains)]
    return {'query':topic,'sources':rows,'note':'Search snippets from primary/security-training sources, not full-page verification. No scans or attacks were performed.'}
