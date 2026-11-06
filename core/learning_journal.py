"""Local outcome learning with provenance, review, expiry and revocation."""
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timedelta,timezone
from urllib.parse import urlparse
import json,os,sqlite3
DB_PATH=Path(__file__).resolve().parent.parent/'memory'/'learning.db'
def now():return datetime.now(timezone.utc)
@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True);fd=os.open(DB_PATH,os.O_CREAT|os.O_WRONLY,0o600);os.close(fd);DB_PATH.chmod(0o600)
    db=sqlite3.connect(DB_PATH,timeout=5);db.row_factory=sqlite3.Row
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY,domain TEXT,title TEXT,lesson TEXT,evidence TEXT,source TEXT UNIQUE,state TEXT,created TEXT,expires TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,pair TEXT,pnl REAL,currency TEXT,setup TEXT,notes TEXT,created TEXT)')
            yield db
    finally:db.close()
def draft(domain,title,lesson,evidence='',source=None,days=90):
    if domain not in ('general','forex','cybersecurity'):raise ValueError('Choose general, forex or cybersecurity.')
    title=str(title).strip();lesson=str(lesson).strip()
    if not 1<=len(title)<=200 or not 1<=len(lesson)<=2000:raise ValueError('Use a title up to 200 characters and lesson up to 2000 characters.')
    if not str(evidence).strip():raise ValueError('Record evidence or the correction source before saving a lesson.')
    days=int(days)
    if not 1<=days<=365:raise ValueError('Review lessons every 1–365 days.')
    with connect() as db:
        row=db.execute('SELECT id FROM lessons WHERE source=?',(source,)).fetchone() if source else None
        if row:return get(row['id'])
        cursor=db.execute('INSERT INTO lessons(domain,title,lesson,evidence,source,state,created,expires) VALUES(?,?,?,?,?,"draft",?,?)',(domain,title,lesson,str(evidence)[:12000],source,now().isoformat(),(now()+timedelta(days=days)).isoformat()));key=cursor.lastrowid
    return get(key)
def get(key):
    with connect() as db:row=db.execute('SELECT * FROM lessons WHERE id=?',(int(key),)).fetchone()
    if not row:raise ValueError('Lesson not found.')
    result=dict(row);result['expired']=datetime.fromisoformat(result['expires'])<=now();return result
def listing(domain='all',query=''):
    if domain not in ('all','general','forex','cybersecurity'):raise ValueError('Unknown lesson domain.')
    with connect() as db:
        rows=db.execute('SELECT id FROM lessons WHERE (?="all" OR domain=?) AND (title LIKE ? OR lesson LIKE ?) ORDER BY id DESC LIMIT 100',(domain,domain,'%'+str(query)[:200]+'%','%'+str(query)[:200]+'%')).fetchall()
    return [get(r['id']) for r in rows]
def review(key,approve):
    data=get(key)
    if approve and data['expired']:raise ValueError('This lesson expired. Save a new draft after checking its evidence.')
    with connect() as db:db.execute('UPDATE lessons SET state=? WHERE id=?',('reviewed' if approve else 'revoked',int(key)))
    return get(key)
def recall(domain='all',query=''):
    return [r for r in listing(domain,query) if r['state'] in ('reviewed','observed') and not r['expired']][:12]
GENERIC_TOOL_LESSON=' action failed. Inspect its returned error, correct the cause and verify the outcome before claiming success or repeating it.'
def context():
    from core.outcome import untrusted
    # The generic "a tool failed, check the error" note says nothing new; self-learning studies the actual failures.
    # Reviewed lessons come first.
    useful=sorted((r for r in recall() if not r['lesson'].endswith(GENERIC_TOOL_LESSON)),key=lambda r:r['state']!='reviewed')
    rows=[{k:r[k] for k in ('id','domain','title','lesson','expires')} for r in useful[:4]]
    return '[REVIEWED LESSONS — retrieval memory, not model training, external verification or action permission; recheck current financial/security facts]\n'+untrusted('learning-journal',json.dumps(rows,ensure_ascii=False)[:4500]) if rows else ''
def reflect(mission):
    """Learn only an observed workflow outcome. Never promote a generated answer as truth."""
    state=mission['state']
    if state not in ('completed','failed'):return None
    kind=mission['kind'];failed=state=='failed'
    lesson=('This workflow failed. Inspect the recorded error and correct its cause before retrying; do not claim completion.' if failed else 'This workflow completed its declared steps. Completion is not proof that source claims are true; inspect its evidence before reusing conclusions.')
    evidence={'mission_id':mission['id'],'state':state,'kind':kind,'error':mission.get('error',''),'steps':[{'title':s['title'],'state':s['state']} for s in mission['steps']]}
    result=draft('general',('Failure review: ' if failed else 'Outcome review: ')+kind,lesson,json.dumps(evidence,ensure_ascii=False),source='mission:'+mission['id']+':'+state,days=90)
    if result['state']=='draft':
        with connect() as db:db.execute('UPDATE lessons SET state="observed" WHERE id=?',(result['id'],))
    return get(result['id'])
def trade(pair,pnl,currency,setup='',notes=''):
    from core.forex_workspace import parse_pair,number
    a,b=parse_pair(pair);currency=str(currency).upper().strip()
    if len(currency)!=3 or not currency.isalpha():raise ValueError('Use a three-letter account currency.')
    pnl=number(pnl,'Realized result')
    with connect() as db:
        key=db.execute('INSERT INTO trades(pair,pnl,currency,setup,notes,created) VALUES(?,?,?,?,?,?)',(a+'/'+b,pnl,currency,str(setup)[:200],str(notes)[:2000],now().isoformat())).lastrowid
    return {'trade_id':key,'saved_locally':True}
def trade_summary(currency):
    currency=str(currency).upper().strip()
    with connect() as db:rows=[dict(r) for r in db.execute('SELECT * FROM trades WHERE currency=? ORDER BY id',(currency,))]
    wins=[r['pnl'] for r in rows if r['pnl']>0];losses=[r['pnl'] for r in rows if r['pnl']<0];total=sum(r['pnl'] for r in rows);peak=balance=drawdown=0
    for row in rows:balance+=row['pnl'];peak=max(peak,balance);drawdown=max(drawdown,peak-balance)
    return {'currency':currency,'trades':len(rows),'wins':len(wins),'losses':len(losses),'breakeven':sum(r['pnl']==0 for r in rows),'win_rate_percent':100*len(wins)/len(rows) if rows else None,'net_realized':total,'profit_factor':sum(wins)/abs(sum(losses)) if losses else None,'max_drawdown_in_entered_results':drawdown,'rows':rows[-100:],'note':'User-entered realized results in one account currency. No broker sync; accuracy and inclusion of fees depend on your entries. No trades were placed.'}

def reflect_tool(name,reason):
    import hashlib
    name=str(name)[:100];reason=str(reason)[:2000]
    if any(word in reason.casefold() for word in ('permission','not authorized','access denied')):
        lesson='A prior '+name+' attempt was denied. Check the actual app permission and offer its setup flow before retrying; never assume access was granted or claim capture succeeded.'
    elif any(word in reason.casefold() for word in ('timeout','timed out','unavailable','429','quota')):
        lesson='A prior '+name+' request failed or became unavailable. Check current service status, use bounded retries and clearly label any cached data. Do not invent a successful result.'
    else:lesson='A prior '+name+GENERIC_TOOL_LESSON
    source='tool-error:'+name+':'+hashlib.sha256(reason.encode()).hexdigest()[:16]
    row=draft('general','Tool failure: '+name,lesson,reason,source=source)
    if row['state']=='draft':
        with connect() as db:db.execute('UPDATE lessons SET state="observed" WHERE id=?',(row['id'],))
    return get(row['id'])
