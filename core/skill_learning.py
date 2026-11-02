"""Versioned, reviewable JARVIS workflows. No arbitrary scripts or hidden recording."""
from contextlib import contextmanager
from pathlib import Path
import hashlib,json,os,sqlite3,threading
from core.mission_store import now
DB_PATH=Path(__file__).resolve().parent.parent/'memory'/'skills.db'
_lock=threading.RLock();_recording=None
@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True);fd=os.open(DB_PATH,os.O_CREAT|os.O_WRONLY,0o600);os.close(fd);DB_PATH.chmod(0o600)
    db=sqlite3.connect(DB_PATH,timeout=5);db.row_factory=sqlite3.Row
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS skills(name TEXT,version INTEGER,definition TEXT,approved INTEGER DEFAULT 0,created TEXT,PRIMARY KEY(name,version))');yield db
    finally:db.close()
def validate(definition):
    if not isinstance(definition,dict):raise ValueError('A skill definition must be a JSON object.')
    kind=definition.get('type')
    if kind=='routine':
        from core.work_routines import validate as validate_steps
        return {'type':'routine','steps':validate_steps(definition.get('steps'))}
    if kind=='mission':
        if definition.get('kind') not in ('research','restaurants','engineering','briefing'):raise ValueError('Use a research, restaurant, engineering or briefing mission template.')
        params=definition.get('params',{})
        if not isinstance(params,dict):raise ValueError('Mission params must be an object.')
        params={k:v for k,v in params.items() if k in ('root','files','limit','radius')}
        if definition['kind']=='restaurants':params.pop('city',None)
        return {'type':'mission','kind':definition['kind'],'goal':str(definition.get('goal',''))[:1000],'params':params}
    raise ValueError('Choose type routine or mission. Skills cannot contain shell commands.')
def save(name,definition):
    name=str(name).strip()
    if not name or len(name)>100:raise ValueError('Name the skill using 1–100 characters.')
    definition=validate(definition)
    with connect() as db:
        version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM skills WHERE name=? COLLATE NOCASE',(name,)).fetchone()[0]
        db.execute('INSERT INTO skills VALUES(?,?,?,0,?)',(name,version,json.dumps(definition),now()))
    return get(name,version)
def listing():
    with connect() as db:return [dict(r) for r in db.execute('SELECT name,version,approved,created FROM skills ORDER BY created DESC,name,version DESC LIMIT 200')]
def get(name,version=None):
    with connect() as db:
        if version is None:row=db.execute('SELECT * FROM skills WHERE name=? COLLATE NOCASE ORDER BY version DESC LIMIT 1',(name,)).fetchone()
        else:row=db.execute('SELECT * FROM skills WHERE name=? COLLATE NOCASE AND version=?',(name,int(version))).fetchone()
    if not row:raise ValueError('Skill/version not found.')
    data=dict(row);data['definition']=json.loads(data['definition']);data['fingerprint']=hashlib.sha256(json.dumps(data['definition'],sort_keys=True).encode()).hexdigest();return data
def approve(name,version,fingerprint):
    data=get(name,version);validate(data['definition'])
    if data['fingerprint']!=fingerprint:raise ValueError('Definition changed. Review this version again.')
    with connect() as db:db.execute('UPDATE skills SET approved=1 WHERE name=? AND version=?',(data['name'],data['version']))
    return get(name,version)
def revoke(name,version):
    data=get(name,version)
    with connect() as db:db.execute('UPDATE skills SET approved=0 WHERE name=? AND version=?',(data['name'],data['version']))
    return get(name,version)
def from_mission(name,key):
    from core.mission_store import get as mission
    item=mission(key)
    if item['state']!='completed' or item['kind']=='routine':raise ValueError('Choose a completed research, restaurant, engineering or briefing mission.')
    return save(name,{'type':'mission','kind':item['kind'],'goal':item['goal'],'params':item['params']})
def from_routine(name,routine):
    from core.work_routines import preview
    return save(name,{'type':'routine','steps':preview(routine)['steps']})
def run(name,version=None,city='',player=None):
    data=get(name,version)
    if not data['approved']:raise ValueError('This version needs review and approval in the Skills panel before it can run.')
    definition=validate(data['definition'])
    if definition['type']=='mission':
        from core.mission_engine import engine
        if definition['kind']=='restaurants' and not str(city).strip():raise ValueError('Which city should this restaurant skill search this time?')
        params={**definition['params'],'city':city,'ai':False}
        item=engine().plan(definition['kind'],definition['goal'],**params);return engine().start(item['id'],player)
    # Reuse the routine executor with an immutable, private temporary routine name.
    from core import work_routines as routines,work_projects
    import uuid
    temporary='skill-run-'+uuid.uuid4().hex
    routines.save(temporary,definition['steps'])
    try:return routines.run(temporary,player)
    finally:
        with work_projects.connect() as db:db.execute('DELETE FROM routines WHERE name=?',(temporary,))
def begin(name):
    global _recording
    with _lock:
        if _recording is not None:raise ValueError('Stop the current teaching session first.')
        if not str(name).strip():raise ValueError('Name the skill first.')
        _recording={'name':str(name).strip(),'steps':[],'evidence':[]};return {'recording':True,'note':'Captures supported steps from routines you explicitly run. No screen, keyboard, microphone or arbitrary app activity is recorded.'}
def observe(step,status):
    with _lock:
        if _recording is None or len(_recording['steps'])>=12:return
        if status not in ('verified','requested','unverified'):return
        _recording['steps'].append(dict(step));_recording['evidence'].append(status)
def finish():
    global _recording
    with _lock:
        if _recording is None:raise ValueError('No teaching session is active.')
        data=_recording;_recording=None
    if not data['steps']:raise ValueError('No supported routine steps were observed. Run a routine during teaching, or enter a definition manually.')
    result=save(data['name'],{'type':'routine','steps':data['steps']});result['observed_statuses']=data['evidence'];return result
