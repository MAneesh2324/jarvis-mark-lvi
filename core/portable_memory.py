"""Authenticated local memory vaults and startup-only restore. No network or passwords in tools."""
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
import hashlib,json,os,re,shutil,sqlite3,tempfile,uuid
ROOT=Path(__file__).resolve().parent.parent
MAGIC=b'JARVIS-MEMORY-1\n'
LIMIT=64*1024*1024
PREFS={'assistant_name','user_name','voice_style','response_speed','hud_style','voice'}
# Fixed schemas: a vault never supplies SQL, table names or destination paths.
SCHEMAS={
'workspaces.db':[
 ('projects','name,goal,progress,next_step,root,updated','CREATE TABLE projects(name TEXT PRIMARY KEY,goal TEXT NOT NULL,progress TEXT NOT NULL DEFAULT "",next_step TEXT NOT NULL DEFAULT "",root TEXT NOT NULL DEFAULT "",updated TEXT NOT NULL)'),
 ('tasks','id,project,text,done','CREATE TABLE tasks(id INTEGER PRIMARY KEY,project TEXT NOT NULL,text TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0)'),
 ('state','key,value','CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')],
'skills.db':[('skills','name,version,definition,approved,created','CREATE TABLE skills(name TEXT,version INTEGER,definition TEXT,approved INTEGER DEFAULT 0,created TEXT,PRIMARY KEY(name,version))')],
'learning.db':[
 ('lessons','id,domain,title,lesson,evidence,source,state,created,expires','CREATE TABLE lessons(id INTEGER PRIMARY KEY,domain TEXT,title TEXT,lesson TEXT,evidence TEXT,source TEXT UNIQUE,state TEXT,created TEXT,expires TEXT)'),
 ('trades','id,pair,pnl,currency,setup,notes,created','CREATE TABLE trades(id INTEGER PRIMARY KEY,pair TEXT,pnl REAL,currency TEXT,setup TEXT,notes TEXT,created TEXT)')],
'conversation_journal.db':[
 ('sessions','id,created,hidden','CREATE TABLE sessions(id TEXT PRIMARY KEY,created TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0)'),
 ('turns','id,session,role,text,created','CREATE TABLE turns(id INTEGER PRIMARY KEY,session TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,created TEXT NOT NULL)'),
 ('settings','key,value','CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)'),
 ('corrections','heard,intended','CREATE TABLE corrections(heard TEXT PRIMARY KEY,intended TEXT NOT NULL)')],
'conversations.db':[('summaries','id,date,summary,language','CREATE TABLE summaries(id INTEGER PRIMARY KEY,date TEXT NOT NULL,summary TEXT NOT NULL,language TEXT NOT NULL,UNIQUE(date,summary))')]
}
def _json(value):return json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
def _write(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);temp=path.with_name('.'+path.name+'-'+uuid.uuid4().hex)
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(temp,path)
 finally:
  if temp.exists():temp.unlink()
def _key(password,salt):
 from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
 if not isinstance(password,str) or not 12<=len(password)<=1024:raise ValueError('Use a passphrase of 12–1024 characters. It is not saved or recoverable.')
 return Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password.encode())
def _tables(path,schema):
 if not path.exists():return None
 # SQLite online backup gives a consistent per-database snapshot, including WAL data.
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as src,closing(sqlite3.connect(':memory:')) as db:
  src.backup(db);result={}
  names={r[0] for r in db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
  for table,columns,sql in schema:
   rows=db.execute('SELECT '+columns+' FROM '+table+' LIMIT 50001').fetchall() if table in names else []
   if len(rows)>50000:raise ValueError('A memory table exceeds 50,000 rows. Export a smaller history first.')
   result[table]=rows
  return result
def collect(history=False):
 components={};memory=ROOT/'memory';facts=memory/'long_term.json'
 if facts.exists():
  components['facts']=json.loads(facts.read_text())
  if not history:components['facts'].pop('sessions',None)
 for name,schema in SCHEMAS.items():
  if name.startswith('conversation') and not history:continue
  data=_tables(memory/name,schema)
  if data is not None:components[name]=data
 config=ROOT/'config'/'api_keys.json'
 if config.exists():
  data=json.loads(config.read_text());components['preferences']={k:data[k] for k in PREFS if k in data}
 routines=_tables(memory/'workspaces.db',[('routines','name,steps,updated','')])
 if routines and routines['routines']:
  skill_rows=components.setdefault('skills.db',{'skills':[]})['skills']
  for name,steps,updated in routines['routines']:
   if name.startswith('skill-run-'):continue
   version=max([r[1] for r in skill_rows if r[0].casefold()==name.casefold()]+[0])+1
   skill_rows.append([name,version,json.dumps({'type':'routine','steps':json.loads(steps)}),0,updated])
 result={'version':1,'created':datetime.now(timezone.utc).isoformat(),'components':components}
 validate(result);return result

def validate(payload):
 if not isinstance(payload,dict) or payload.get('version')!=1 or not isinstance(payload.get('components'),dict):raise ValueError('Unsupported memory vault format.')
 if len(_json(payload))>LIMIT:raise ValueError('Memory vault exceeds 64 MB.')
 for name,data in payload['components'].items():
  if name=='facts':
   if not isinstance(data,dict) or len(_json(data))>2_000_000:raise ValueError('Invalid facts store.')
   if any(k in data and not isinstance(data[k],dict) for k in ('identity','preferences','projects','relationships','wishes','notes')):raise ValueError('Invalid personal-memory category.')
  elif name=='preferences':
   if not isinstance(data,dict) or set(data)-PREFS or any(not isinstance(v,str) or len(v)>200 for v in data.values()):raise ValueError('Invalid portable preferences.')
  elif name in SCHEMAS:
   expected={t for t,c,s in SCHEMAS[name]}
   if not isinstance(data,dict) or set(data)!=expected:raise ValueError('Invalid memory table set.')
   for table,columns,sql in SCHEMAS[name]:
    rows=data[table]
    if not isinstance(rows,list) or len(rows)>50000:raise ValueError('Invalid memory row count.')
    for row in rows:
     if not isinstance(row,(list,tuple)) or len(row)!=len(columns.split(',')) or any(not isinstance(v,(str,int,float,type(None))) or isinstance(v,str) and len(v)>100000 for v in row):raise ValueError('Invalid memory row.')
     if table=='lessons':
      if row[1] not in ('general','forex','cybersecurity') or not all(isinstance(row[i],str) for i in (2,3,4,7,8)):raise ValueError('Invalid lesson fields.')
      datetime.fromisoformat(row[7]);datetime.fromisoformat(row[8])
     if table=='skills':
      try:definition=json.loads(row[2])
      except (ValueError,TypeError):raise ValueError('Invalid skill definition.') from None
      if not isinstance(definition,dict) or definition.get('type') not in ('routine','mission'):raise ValueError('Invalid skill definition.')
      if definition['type']=='routine':
       steps=definition.get('steps')
       if not isinstance(steps,list) or not 1<=len(steps)<=12 or any(not isinstance(x,dict) or x.get('action') not in ('open_app','open_path','arrange_app','volume','activate_project') for x in steps):raise ValueError('Unsupported saved workflow steps.')
      elif definition.get('kind') not in ('research','restaurants','engineering','briefing'):raise ValueError('Unsupported saved mission recipe.')
     if table=='trades':
      if not isinstance(row[2],(int,float)) or not re.fullmatch('[A-Z]{3}',str(row[3])):raise ValueError('Invalid trade-journal fields.')
  else:raise ValueError('Unrecognized memory component: '+name)
 return payload

def summary(payload):
 validate(payload);out={}
 for name,data in payload['components'].items():
  out[name]={t:len(rows) for t,rows in data.items()} if name in SCHEMAS else {'fields':len(data)}
 return {'created':payload.get('created'),'components':out,'excluded':'API keys, tokens, recordings, screenshots, caches, calendar exports, mission artifacts, app binaries and device permissions. File paths are not portable permissions.','restore_policy':'Selected stores replace their current counterparts at next app startup, after a local rollback snapshot. Skill approvals are revoked, lessons return to draft, project roots cleared. Existing local routines are retained.'}
def export(path,password,history=False):
 from cryptography.hazmat.primitives.ciphers.aead import AESGCM
 payload=collect(history);raw=_json(payload);salt=os.urandom(16);nonce=os.urandom(12)
 encrypted=MAGIC+salt+nonce+AESGCM(_key(password,salt)).encrypt(nonce,raw,MAGIC)
 path=Path(path).expanduser()
 if path.suffix!='.jarvismem':raise ValueError('Use a .jarvismem file.')
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(encrypted);stream.flush();os.fsync(stream.fileno())
 except Exception:
  path.unlink(missing_ok=True);raise
 return {'path':str(path),'bytes':len(encrypted),'encrypted':True,**summary(payload)}
def unlock(path,password):
 from cryptography.hazmat.primitives.ciphers.aead import AESGCM
 from cryptography.exceptions import InvalidTag
 path=Path(path).expanduser()
 if path.stat().st_size>LIMIT+100:raise ValueError('Memory vault is too large.')
 raw=path.read_bytes();offset=len(MAGIC)
 if not raw.startswith(MAGIC) or len(raw)<offset+16+12+16:raise ValueError('Not a JARVIS memory vault.')
 salt=raw[offset:offset+16];nonce=raw[offset+16:offset+28]
 try:plain=AESGCM(_key(password,salt)).decrypt(nonce,raw[offset+28:],MAGIC)
 except InvalidTag:raise ValueError('Wrong passphrase or damaged vault. Nothing was restored.') from None
 try:payload=json.loads(plain,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Invalid numeric value')))
 except (ValueError,UnicodeError,RecursionError):raise ValueError('Invalid decrypted memory data.') from None
 return validate(payload)

def queue_restore(payload):
 validate(payload)
 if not payload['components']:raise ValueError('This vault has no memory components to restore.')
 # Validate database constraints by constructing fresh fixed-schema databases before queueing.
 with tempfile.TemporaryDirectory() as folder:_build(payload,Path(folder))
 path=ROOT/'memory'/'restore-pending.json'
 if path.exists():raise ValueError('A restore is already queued. Restart or cancel it first.')
 _write(path,_json(payload));return {'queued':True,'restart_required':True,**summary(payload)}
def cancel_restore():
 path=ROOT/'memory'/'restore-pending.json'
 if path.exists():path.unlink()
 return {'queued':False}
def _build(payload,folder):
 out={}
 for name,data in payload['components'].items():
  if name=='facts':
   target=folder/'long_term.json';_write(target,_json(data));out['memory/long_term.json']=target
  elif name=='preferences':continue
  else:
   target=folder/name
   with closing(sqlite3.connect(target)) as db:
    for table,columns,sql in SCHEMAS[name]:
     db.execute(sql);rows=[list(r) for r in data[table]]
     if table=='skills':
      for row in rows:row[3]=0
     if table=='lessons':
      for row in rows:
       row[6]='draft'
       for i in (7,8):
        value=datetime.fromisoformat(row[i]);row[i]=(value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
     if table=='projects':
      for row in rows:row[4]=''
     if table=='settings':rows=[['capture','off']]
     db.executemany('INSERT INTO '+table+'('+columns+') VALUES('+','.join('?' for _ in columns.split(','))+')',rows)
    db.commit()
   target.chmod(0o600);out['memory/'+name]=target
 return out

def _recover(state):
 if not re.fullmatch('[a-f0-9]{32}',str(state.get('id',''))):raise ValueError('Invalid restore recovery ID.')
 backup=ROOT/'memory'/'restore-rollback'/state['id']
 for relative,existed in state['files'].items():
  if relative not in {'memory/long_term.json',*(('memory/'+n) for n in SCHEMAS),'config/api_keys.json'}:raise ValueError('Invalid restore recovery path.')
  dest=ROOT/relative
  if existed:_write(dest,(backup/relative).read_bytes())
  elif dest.exists():dest.unlink()
  for suffix in ('-wal','-shm','-journal'):
   side=Path(str(dest)+suffix)
   if side.exists():side.unlink()

def apply_pending():
 """Call once before memory writers, timers, mission workers or voice startup."""
 state_path=ROOT/'memory'/'restore-state.json';pending=ROOT/'memory'/'restore-pending.json'
 if state_path.exists():
  old=json.loads(state_path.read_text())
  if old.get('phase')=='applying':
   _recover(old);old['phase']='rolled_back';_write(state_path,_json(old));pending.unlink(missing_ok=True)
   return {'restored':False,'recovered_interrupted_restore':True}
 if not pending.exists():return {'restored':False}
 if pending.stat().st_size>LIMIT:raise ValueError('Queued restore exceeds the size limit.')
 payload=validate(json.loads(pending.read_text()));key=uuid.uuid4().hex;backup=ROOT/'memory'/'restore-rollback'/key;backup.mkdir(parents=True,mode=0o700)
 work=ROOT/'memory'/'restore-work';work.mkdir(parents=True,exist_ok=True,mode=0o700)
 with tempfile.TemporaryDirectory(dir=work) as folder:
  outputs=_build(payload,Path(folder))
  if 'preferences' in payload['components']:
   config=ROOT/'config'/'api_keys.json';data=json.loads(config.read_text()) if config.exists() else {};data.update(payload['components']['preferences'])
   target=Path(folder)/'preferences.json';_write(target,_json(data));outputs['config/api_keys.json']=target
  # Keep this device's existing routines; do not import executable workflow permissions.
  current=ROOT/'memory'/'workspaces.db'
  if 'memory/workspaces.db' in outputs:
   with closing(sqlite3.connect(outputs['memory/workspaces.db'])) as db:
    db.execute('CREATE TABLE routines(name TEXT PRIMARY KEY,steps TEXT NOT NULL,updated TEXT NOT NULL)')
    if current.exists():
     with closing(sqlite3.connect(current.as_uri()+'?mode=ro',uri=True)) as source:
      if source.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name="routines"').fetchone():db.executemany('INSERT INTO routines VALUES(?,?,?)',source.execute('SELECT name,steps,updated FROM routines').fetchall())
    db.commit()
  state={'id':key,'phase':'applying','files':{relative:(ROOT/relative).exists() for relative in outputs}}
  for relative,existed in state['files'].items():
   if not existed:continue
   original=ROOT/relative;target=backup/relative;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   if original.suffix=='.db':
    with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(target)) as dst:src.backup(dst)
    target.chmod(0o600)
   else:_write(target,original.read_bytes())
  _write(state_path,_json(state))
  try:
   for relative,target in outputs.items():
    dest=ROOT/relative
    for suffix in ('-wal','-shm','-journal'):Path(str(dest)+suffix).unlink(missing_ok=True)
    _write(dest,target.read_bytes())
   state['phase']='complete';_write(state_path,_json(state));pending.unlink()
  except Exception:
   _recover(state);state['phase']='rolled_back';_write(state_path,_json(state));pending.unlink(missing_ok=True);raise
 return {'restored':True,'rollback_snapshot':str(backup),'restart_applied':True}
