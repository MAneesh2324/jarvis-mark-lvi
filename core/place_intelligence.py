"""User-requested city research. No implicit use of the device's location."""
import csv, io, math, threading, time, json
from pathlib import Path
from urllib.parse import urlparse
import requests
UA={'User-Agent':'MarkLVI-Jarvis/1.0 (local personal research app; github.com/FatihMakes/Mark-LVI)'}
_geo_lock=threading.Lock();_geo_time=0.;_cities={}
SERVICES=Path(__file__).resolve().parent.parent/'config'/'place-services.json'
def service(name,default):
    settings=json.loads(SERVICES.read_text()) if SERVICES.exists() else {}
    url=str(settings.get(name,default));parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Place service endpoints must use HTTPS without embedded credentials.')
    return url
def cached_city(city,value=None):
    from core.mission_store import connect
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS place_cache(query TEXT PRIMARY KEY,result TEXT,created REAL)')
        if value is not None:db.execute('INSERT OR REPLACE INTO place_cache VALUES(?,?,?)',(city,json.dumps(value),time.time()));return value
        row=db.execute('SELECT result,created FROM place_cache WHERE query=?',(city,)).fetchone()
        return json.loads(row['result']) if row and time.time()-row['created']<7*86400 else None
def city_lookup(city):
    global _geo_time
    city=str(city).strip()
    if not city or len(city)>150:raise ValueError('Please provide a city for this search. No default city is used.')
    with _geo_lock:
        cached=cached_city(city.casefold())
        if cached:return dict(cached)
        time.sleep(max(0,1.1-(time.monotonic()-_geo_time)));_geo_time=time.monotonic()
        response=requests.get(service('geocoder','https://nominatim.openstreetmap.org/search'),params={'q':city,'format':'jsonv2','limit':1},headers=UA,timeout=12)
        response.raise_for_status();rows=response.json()
        if not rows:raise ValueError('City not found. Include the state/country to disambiguate.')
        item=rows[0];result={'query':city,'name':item['display_name'],'latitude':float(item['lat']),'longitude':float(item['lon']),'source':'https://www.openstreetmap.org/'+item['osm_type']+'/'+str(item['osm_id'])}
        cached_city(city.casefold(),result);return dict(result)
def restaurants(city,radius=5000,limit=30):
    center=city_lookup(city);radius=max(500,min(10000,int(radius)));limit=max(1,min(50,int(limit)))
    query=f'[out:json][timeout:20];nwr["amenity"="restaurant"](around:{radius},{center["latitude"]},{center["longitude"]});out center tags 200;'
    response=requests.post(service('overpass','https://overpass-api.de/api/interpreter'),data={'data':query},headers=UA,timeout=28);response.raise_for_status();data=response.json()
    if data.get('remark'):raise RuntimeError('The map provider returned an incomplete query. Try a smaller radius.')
    rows=[]
    for element in data.get('elements',[]):
        tags=element.get('tags',{});name=tags.get('name','').strip()
        if not name or tags.get('website') or tags.get('contact:website'):continue
        pos=element.get('center',element)
        if 'lat' not in pos or 'lon' not in pos:continue
        rows.append({'id':f'{element["type"]}/{element["id"]}','name':name,'city':city,'latitude':pos['lat'],'longitude':pos['lon'],'cuisine':tags.get('cuisine',''),'phone':tags.get('phone',tags.get('contact:phone','')),'address':' '.join(tags.get(k,'') for k in ('addr:housenumber','addr:street','addr:city')).strip(),'source':f'https://www.openstreetmap.org/{element["type"]}/{element["id"]}','website_status':'No website tag in OpenStreetMap; independent verification required','search_results':[]})
    rows.sort(key=lambda r:(float(r['latitude'])-center['latitude'])**2+(float(r['longitude'])-center['longitude'])**2)
    return {'center':center,'radius_m':radius,'leads':rows[:limit],'fetched_at':__import__('core.mission_store',fromlist=['now']).now(),'coverage':'A bounded sample within the radius, not every restaurant. Missing OSM website tags do not prove that a business has no website.','attribution':'© OpenStreetMap contributors; ODbL https://www.openstreetmap.org/copyright'}
def search_sources(query,limit=6):
    from actions.web_search import _ddg_search
    rows=_ddg_search(str(query)[:600],max_results=max(1,min(10,limit)))
    result=[]
    for row in rows:
        url=str(row.get('url',''))
        if urlparse(url).scheme in ('https','http') and urlparse(url).hostname:
            result.append({'title':str(row.get('title',''))[:500],'snippet':str(row.get('snippet',''))[:2000],'url':url})
    return result

def csv_text(leads):
    stream=io.StringIO();fields=['name','city','address','cuisine','phone','latitude','longitude','website_status','source']
    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
    for row in leads:
        # CSVs may be opened in spreadsheet apps; neutralize formula injection.
        safe={k:("'"+str(row.get(k,'')) if str(row.get(k,'')).lstrip().startswith(('=','+','-','@')) else row.get(k,'')) for k in fields}
        writer.writerow(safe)
    return stream.getvalue()

def route(start,end):
    from core.earth_maps import valid_coordinates
    if not valid_coordinates(*start) or not valid_coordinates(*end):raise ValueError('Both endpoints need valid latitude/longitude.')
    a,b=[(float(p[0]),float(p[1])) for p in (start,end)]
    url=service('router','https://router.project-osrm.org').rstrip('/')+f'/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}'
    response=requests.get(url,params={'overview':'simplified','geometries':'geojson','steps':'false'},headers=UA,timeout=12);response.raise_for_status();data=response.json()
    if data.get('code')!='Ok' or not data.get('routes'):raise ValueError('No driving route returned for those endpoints.')
    r=data['routes'][0]
    return {'distance_m':r['distance'],'duration_s':r['duration'],'geometry':r['geometry'],'source':'OSRM / OpenStreetMap','note':'Estimated driving route. No live traffic; not navigation guidance.'}
