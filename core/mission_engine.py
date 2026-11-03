"""Bounded background workflows with persistent checkpoints and cooperative cancellation."""
import json, queue, threading
from core import mission_store as store
PLANS={
'research':['Gather web sources','Prepare evidence report'],
'restaurants':['Find candidate restaurants','Cross-check candidate websites','Export leads and report'],
'engineering':['Inspect selected project locally','Prepare engineering report'],
'routine':['Run the named saved routine and verify results'],
'briefing':['Assemble today’s local briefing'],
}
class Cancelled(Exception):pass
class MissionEngine:
    def __init__(self):
        self.lock=threading.RLock();self.jobs=queue.Queue(maxsize=12);self.workers=[];self.signals={};store.recover()
    def plan(self,kind,goal='',**params):
        if kind not in PLANS:raise ValueError('Choose research, restaurants, engineering, routine or briefing.')
        goal=str(goal).strip()
        if kind=='restaurants':
            city=str(params.get('city','')).strip()
            if not city:raise ValueError('Which city should I search? A city is required for each restaurant mission.')
            params={'city':city[:150],'limit':max(1,min(30,int(params.get('limit',12)))),'radius':max(500,min(10000,int(params.get('radius',5000))))}
            goal=f'Find restaurant website candidates in {city}'
        elif kind=='engineering':
            from core.engineering_workspace import files,read
            if not str(params.get('root','')).strip():raise ValueError('Choose an explicit project folder for engineering review.')
            root,paths=files(params.get('root',''))
            selected=params.get('files',[])
            if not isinstance(selected,list) or len(selected)>6:raise ValueError('Select at most 6 files to share for AI suggestions.')
            for relative in selected:read(root,str(relative))
            params={'root':str(root),'files':[str(x) for x in selected],'ai':bool(params.get('ai',False))}
            if params['ai'] and not selected:raise ValueError('Select files explicitly before requesting AI suggestions.')
            goal=goal or 'Inspect project syntax, structure and unfinished work'
        elif kind=='routine':
            from core.work_routines import preview
            name=str(params.get('name',''));definition=preview(name)
            params={'name':definition['name'],'definition':definition};goal='Run routine '+name
        elif kind=='briefing':params={};goal='Today’s briefing'
        else:
            if not goal or len(goal)>1000:raise ValueError('Describe the research goal in 1–1000 characters.')
            params={'ai':bool(params.get('ai',False))}
        return store.create(kind,goal,params,PLANS[kind])
    def start(self,key,player=None):
        with self.lock:
            item=store.get(key)
            if key in self.signals:raise ValueError('This mission is finishing an in-flight step. Wait for that step to exit before resuming.')
            if item['kind']=='routine' and item['state'] in ('interrupted','failed','paused','cancelled'):
                raise ValueError('A partially attempted routine cannot safely resume. Review its evidence and create a fresh plan if you want to run it again.')
            if not store.transition(key,{'planned','paused','failed','interrupted'},'queued'):raise ValueError('Only a planned, paused, failed or interrupted mission can start/resume.')
            stop=threading.Event();self.signals[key]=stop
            try:self.jobs.put_nowait((key,player,stop))
            except queue.Full:
                store.transition(key,{'queued'},'paused','Background queue is full. Try later.');self.signals.pop(key,None);raise ValueError('Background queue is full.')
            if not self.workers:
                for i in range(2):
                    t=threading.Thread(target=self._worker,daemon=True,name=f'jarvis-mission-{i}');t.start();self.workers.append(t)
            store.event(key,'Queued for background work.');return store.get(key)
    def stop(self,key,pause=False):
        with self.lock:
            state='paused' if pause else 'cancelled'
            if not store.transition(key,{'planned','queued','running'},state):raise ValueError('Mission is not active.')
            signal=self.signals.get(key)
            if signal:signal.set()
            store.event(key,'Paused at the next safe boundary.' if pause else 'Cancelled. In-flight network requests may finish, but their results will not continue the mission.')
            return store.get(key)
    def _learn(self,key):
        try:
            from core.learning_journal import reflect
            reflect(store.get(key))
        except Exception:pass # Learning failure must not alter the actual mission result.
    def _worker(self):
        while True:
            key,player,stop=self.jobs.get()
            try:self._run(key,player,stop)
            finally:
                with self.lock:
                    if self.signals.get(key) is stop:self.signals.pop(key,None)
                self.jobs.task_done()
    def _run(self,key,player,stop):
        if not store.transition(key,{'queued'},'running'):return
        def check():
            if stop.is_set() or store.get(key)['state']!='running':raise Cancelled()
        try:
            from core.mission_workflows import execute,export_report
            for step in store.get(key)['steps']:
                check()
                if step['state']=='done':continue
                store.checkpoint(key,step['position'],'running');store.event(key,step['title'])
                result=execute(store.get(key),step['position'],check,player)
                check()
                if not store.checkpoint(key,step['position'],'done',result):raise Cancelled()
                if isinstance(result,dict) and result.get('verification')=='incomplete':
                    export_report(store.get(key));store.transition(key,{'running'},'failed','Routine evidence contains failed or unverified actions. Review before creating a fresh plan.');return
            check();export_report(store.get(key))
            if store.transition(key,{'running'},'completed'):
                store.event(key,'Completed. Evidence and artifacts are ready to review.');self._learn(key)
        except Cancelled:pass
        except Exception as exc:
            # Never include credentials or provider response bodies in the log.
            if store.transition(key,{'running'},'failed',str(exc)[:1200]):
                store.event(key,'Failed: '+str(exc)[:1200]);self._learn(key)

_engine=None;_lock=threading.Lock()
def engine():
    global _engine
    with _lock:
        if _engine is None:_engine=MissionEngine()
    return _engine
