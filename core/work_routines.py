"""Inspectable routines with a deliberately small action vocabulary. No shell steps."""
from pathlib import Path
import json
import platform
import subprocess
import time
from datetime import datetime
from core import work_projects as store

ALLOWED={'open_app','open_path','arrange_app','volume','activate_project'}
DOCUMENTS={'.txt','.md','.pdf','.png','.jpg','.jpeg','.csv','.xlsx','.docx','.pptx','.mp4','.mov','.html'}

def validate(steps):
    if not isinstance(steps,list) or not 1<=len(steps)<=12:raise ValueError('A routine needs 1–12 steps.')
    result=[]
    for step in steps:
        if not isinstance(step,dict) or step.get('action') not in ALLOWED:raise ValueError('Supported steps: open_app, open_path, arrange_app, volume, activate_project. Shell commands are not supported.')
        item=dict(step);kind=item['action']
        if kind in ('open_app','arrange_app'):
            if not isinstance(item.get('app'),str) or not 1<=len(item['app'].strip())<=100:raise ValueError('App steps need an app name.')
        if kind=='arrange_app' and item.get('position') not in ('left','right','maximize'):raise ValueError('Window position must be left, right or maximize.')
        if kind=='volume':
            value=int(item.get('percent',-1))
            if not 0<=value<=100:raise ValueError('Volume must be 0–100.')
            item['percent']=value
        if kind=='activate_project' and not store.project(item.get('name','')):raise ValueError('The routine project must already exist.')
        if kind=='open_path':
            path=Path(str(item.get('path',''))).expanduser().resolve()
            if not path.exists() or (not path.is_dir() and path.suffix.lower() not in DOCUMENTS):raise ValueError('Open paths must be existing folders or supported documents/media; executable scripts are not allowed.')
            item['path']=str(path)
        result.append(item)
    return result

def save(name,steps):
    name=store._name(name);steps=validate(steps)
    with store.connect() as db:db.execute('INSERT OR REPLACE INTO routines VALUES(?,?,?)',(name,json.dumps(steps),datetime.now().astimezone().isoformat(timespec='seconds')))
    return preview(name)

def preview(name):
    with store.connect() as db:row=db.execute('SELECT * FROM routines WHERE name=? COLLATE NOCASE',(name,)).fetchone()
    if not row:raise ValueError('No routine with that name.')
    return {'name':row['name'],'steps':json.loads(row['steps']),'updated':row['updated']}

def list_routines():
    with store.connect() as db:return [dict(r) for r in db.execute('SELECT name,updated FROM routines ORDER BY name')]

def arrange(app,position):
    if platform.system()!='Darwin':raise RuntimeError('This window-layout implementation requires macOS.')
    import Quartz
    bounds=Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    x,y,w,h=int(bounds.origin.x),int(bounds.origin.y)+28,int(bounds.size.width),int(bounds.size.height)-55
    if position=='left':w//=2
    if position=='right':x+=w//2;w//=2
    script='''on run argv
set appName to item 1 of argv
set targetX to (item 2 of argv) as integer
set targetY to (item 3 of argv) as integer
set targetW to (item 4 of argv) as integer
set targetH to (item 5 of argv) as integer
tell application "System Events"
tell process appName
if not (exists window 1) then error "No accessible window for that app."
set frontmost to true
set position of window 1 to {targetX, targetY}
set size of window 1 to {targetW, targetH}
set actualPosition to position of window 1
set actualSize to size of window 1
return ((item 1 of actualPosition) as text) & "," & ((item 2 of actualPosition) as text) & "," & ((item 1 of actualSize) as text) & "," & ((item 2 of actualSize) as text)
end tell
end tell
end run'''
    result=subprocess.run(['osascript','-e',script,app,str(x),str(y),str(w),str(h)],capture_output=True,text=True,timeout=8)
    if result.returncode:raise RuntimeError(result.stderr.strip() or 'Window arrangement failed; check Accessibility permission.')
    observed=[int(v.strip()) for v in result.stdout.strip().split(',')]
    if len(observed)!=4:raise RuntimeError('Could not verify window bounds.')
    return {'requested':[x,y,w,h],'observed':observed,'matches':all(abs(a-b)<30 for a,b in zip(observed,[x,y,w,h]))}

def _arrange_when_ready(app,position):
    for attempt in range(12):
        try:return arrange(app,position)
        except RuntimeError as exc:
            text=str(exc).casefold()
            transient='no accessible window' in text or 'can’t get process' in text or "can't get process" in text or 'does not exist' in text
            if not transient or attempt==11:raise
            time.sleep(.4)

def run(name,player=None,cancel=lambda:None):
    definition=preview(name);steps=validate(definition['steps']);results=[]
    for index,step in enumerate(steps,1):
        cancel()
        try:
            kind=step['action']
            if kind=='open_app':
                from actions.open_app import open_app
                result=open_app({'app_name':step['app']},player=player)
                if result.startswith(('status=failed','status=ask')):raise RuntimeError(result)
                status='requested' if not result.startswith('status=done') else 'verified'
            elif kind=='open_path':
                completed=subprocess.run(['open','--',step['path']],capture_output=True,text=True,timeout=8)
                if completed.returncode:raise RuntimeError(completed.stderr.strip())
                result='Open request accepted by macOS.';status='requested'
            elif kind=='arrange_app':
                result=_arrange_when_ready(step['app'],step['position']);status='verified' if result['matches'] else 'unverified'
            elif kind=='volume':
                from actions.computer_settings import volume_set,volume_get
                volume_set(step['percent']);actual=volume_get()
                result={'requested':step['percent'],'observed':actual};status='verified' if actual is not None and abs(actual-step['percent'])<=3 else 'unverified'
            else:result=store.activate(step['name']);status='verified'
            results.append({'step':index,'action':kind,'status':status,'result':result})
            from core.skill_learning import observe
            observe(step,status)
        except Exception as exc:
            results.append({'step':index,'action':step['action'],'status':'failed','reason':str(exc)})
            break
    return {'name':name,'results':results,'steps_attempted':len(results),'steps_total':len(steps),'all_verified':len(results)==len(steps) and all(r['status']=='verified' for r in results)}
