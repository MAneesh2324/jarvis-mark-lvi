"""Bounded public-feed cache; offline data always retains its original timestamp."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,time,threading
import requests
from core.mission_store import write_file
ROOT=Path(__file__).resolve().parent.parent/'memory'/'intelligence'
_lock=threading.RLock()
def fetch(url,ttl=3600,force=False,before_request=None):
    key=hashlib.sha256(url.encode()).hexdigest();path=ROOT/(key+'.json')
    with _lock:
        cached=None
        try:cached=json.loads(path.read_text())
        except (OSError,ValueError):pass
        if cached and not force and time.time()-cached['timestamp']<ttl:return {**cached,'offline_fallback':False,'cache_hit':True}
        try:
            if before_request:before_request()
            with requests.get(url,headers={'User-Agent':'MarkLVI-Research/1.0 (personal learning workspace)'},timeout=(5,18),stream=True) as response:
                response.raise_for_status();chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>6_000_000:raise ValueError('Public feed exceeds the 6 MB limit.')
                    chunks.append(chunk)
            text=b''.join(chunks).decode('utf-8-sig');value={'url':url,'timestamp':time.time(),'fetched_at':datetime.now(timezone.utc).isoformat(),'text':text}
            ROOT.mkdir(parents=True,exist_ok=True,mode=0o700);write_file(path,json.dumps(value));return {**value,'offline_fallback':False,'cache_hit':False}
        except (requests.RequestException,ValueError,UnicodeError):
            if cached:return {**cached,'offline_fallback':True,'cache_hit':True,'warning':'Refresh failed; showing previously cached data, not newly verified data.'}
            raise RuntimeError('Public data source is unavailable and no cached copy exists.') from None

def metadata(data):return {k:data[k] for k in ('url','fetched_at','offline_fallback','cache_hit','warning') if k in data}
