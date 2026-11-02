"""Loopback-only Earth assets and volatile map/location state."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import mimetypes
import threading
from urllib.parse import unquote,urlparse
import math

WEB_ROOT=Path(__file__).resolve().parent.parent/'web'/'earth'
_lock=threading.RLock()
_state={'view':'globe','latitude':0.0,'longitude':0.0,'location':None}
_server=None


def valid_coordinates(latitude,longitude):
    try:
        latitude,longitude=float(latitude),float(longitude)
        return math.isfinite(latitude) and math.isfinite(longitude) and -90<=latitude<=90 and -180<=longitude<=180
    except (TypeError,ValueError):return False


def validate_options(options):
    result={}
    view=options.get('view','globe')
    if view not in ('globe','street','satellite'):raise ValueError('Choose globe, street or satellite.')
    result['view']=view
    if 'latitude' in options or 'longitude' in options:
        if not valid_coordinates(options.get('latitude'),options.get('longitude')):raise ValueError('Latitude must be −90–90 and longitude −180–180.')
        result.update(latitude=float(options['latitude']),longitude=float(options['longitude']),zoom=max(1,min(19,int(options.get('zoom',13)))))
    if 'markers' in options:
        markers=options['markers']
        if not isinstance(markers,list) or len(markers)>100:raise ValueError('Use at most 100 map markers.')
        result['markers']=[]
        for item in markers:
            if not valid_coordinates(item.get('latitude'),item.get('longitude')):raise ValueError('Invalid map marker coordinates.')
            result['markers'].append({'latitude':float(item['latitude']),'longitude':float(item['longitude']),'label':str(item.get('label','Place'))[:250]})
    if 'route' in options:
        route=options['route'];geometry=route.get('geometry',{});points=geometry.get('coordinates',[])
        if geometry.get('type')!='LineString' or not 2<=len(points)<=5000 or any(not isinstance(point,list) or len(point)<2 or not valid_coordinates(point[1],point[0]) for point in points):raise ValueError('Invalid route geometry.')
        result['route']={'geometry':{'type':'LineString','coordinates':[[float(p[0]),float(p[1])] for p in points]},'distance_m':float(route['distance_m']),'duration_s':float(route['duration_s'])}
    if options.get('locate'):result['locate']=True
    return result


def update_view(data):
    options=validate_options(data)
    with _lock:_state.update({k:v for k,v in options.items() if k in ('view','latitude','longitude')})


def update_location(data):
    if not valid_coordinates(data.get('latitude'),data.get('longitude')):raise ValueError('Invalid location fix.')
    if data.get('source') not in ('device','approximate_ip'):raise ValueError('Unknown location source.')
    location={k:data.get(k) for k in ('latitude','longitude','accuracy','source','timestamp','city')}
    with _lock:_state['location']=location


def clear_location():
    with _lock:_state['location']=None


def status():
    with _lock:return {**_state,'location':dict(_state['location']) if _state['location'] else None,'location_saved_to_disk':False}


def approximate_location():
    # Called only after a user-facing consent dialog, never at startup.
    import requests
    response=requests.get('https://ipapi.co/json/',headers={'User-Agent':'JarvisEarth/1.0'},timeout=8)
    response.raise_for_status();data=response.json()
    if data.get('error') or not valid_coordinates(data.get('latitude'),data.get('longitude')):raise RuntimeError('The network-location provider could not determine a location.')
    return {'latitude':round(float(data['latitude']),2),'longitude':round(float(data['longitude']),2),'city':str(data.get('city',''))[:100],'accuracy':None,'source':'approximate_ip'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        if path=='/':path='/index.html'
        allowed=path in ('/index.html','/app.js','/style.css','/config.js') or path.startswith('/vendor/')
        target=(WEB_ROOT/path.lstrip('/')).resolve()
        if not allowed or WEB_ROOT.resolve() not in target.parents or not target.is_file():self.send_error(404);return
        data=target.read_bytes()
        self.send_response(200)
        mime=mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        if target.suffix=='.wasm':mime='application/wasm'
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','public, max-age=604800' if path.startswith('/vendor/') else 'no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' blob: qrc: 'unsafe-eval' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org https://services.arcgisonline.com; connect-src 'self' https://tile.openstreetmap.org https://services.arcgisonline.com; worker-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(data)


def start_server():
    global _server
    with _lock:
        if _server is None:
            _server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            _server.daemon_threads=True
            threading.Thread(target=_server.serve_forever,daemon=True,name='earth-assets').start()
        return f'http://127.0.0.1:{_server.server_port}/'
