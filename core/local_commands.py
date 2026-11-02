"""Deterministic commands and optional local CPU speech recognition."""
from pathlib import Path
from datetime import datetime
import json
import atexit
import queue
import re
import subprocess
import threading
import time

MODEL_ROOT=Path(__file__).resolve().parent.parent/'models'/'whisper'


def _number(value):
    value=value.strip().casefold().replace('-',' ')
    if value.isdigit():return int(value)
    units={'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,'seventeen':17,'eighteen':18,'nineteen':19,'twenty':20,'thirty':30,'forty':40,'fifty':50,'sixty':60,'seventy':70,'eighty':80,'ninety':90}
    if value in ('one hundred','a hundred'):return 100
    words=value.split()
    if len(words)==1:return units.get(value)
    if len(words)==2 and units.get(words[0],0)>=20 and 0<units.get(words[1],100)<10:return units[words[0]]+units[words[1]]
    return None


def parse(text):
    text=str(text).strip().rstrip('.!?')
    lowered=text.casefold()
    if lowered in ('undo','undo that'):return 'undo',{}
    if lowered in ('what time is it','what is the time','time','tell me the time'):return 'time',{}
    match=re.fullmatch(r'(?:open|launch) (.+)',text,re.I)
    if match:return 'open_app',{'app_name':match.group(1).strip()}
    match=re.fullmatch(r'(?:set )?volume(?: to)? (.+)',text,re.I)
    if match:
        value=_number(re.sub(r'\s*(?:percent|%)$','',match.group(1),flags=re.I))
        if value is not None and 0<=value<=100:return 'volume',{'percent':value}
    if lowered in ('mute','mute volume'):return 'volume',{'percent':0}
    match=re.fullmatch(r'(?:set |start )?(?:a )?timer (?:for )?(.+?) (second|minute|hour)s?',text,re.I)
    if match:
        value=_number(match.group(1))
        seconds=(value or 0)*{'second':1,'minute':60,'hour':3600}[match.group(2).lower()]
        if value is not None and 1<=seconds<=86400:return 'timer',{'seconds':seconds}
    match=re.fullmatch(r'remember (.{1,80}?) is (.{1,380})',text,re.I)
    if match:return 'remember',{'key':re.sub(r'[^\w]+','_',match.group(1).casefold()).strip('_'),'value':match.group(2)}
    match=re.fullmatch(r'(?:recall|what do you remember about) (.+)',text,re.I)
    if match:return 'recall',{'query':match.group(1)}
    match=re.fullmatch(r'(?:run|start) routine (.+)',text,re.I)
    if match:return 'routine',{'name':match.group(1)}
    if lowered in ('project status','current project','what is my next step'):return 'project',{}
    return None


def _db_timers():
    from core.work_projects import connect
    return connect()


def execute(text,player=None):
    parsed=parse(text)
    if not parsed:return 'No matching local command. Try: open Safari; volume 30; timer 5 minutes; remember coffee is black; recall coffee; run routine Work; project status.'
    kind,args=parsed
    if kind=='undo':
        from core.undo import undo_last
        return undo_last()
    if kind=='time':return datetime.now().astimezone().strftime('It is %I:%M %p %Z.')
    if kind=='open_app':
        from actions.open_app import open_app
        return open_app(args,player=player)
    if kind=='volume':
        from actions.computer_settings import volume_set,volume_get
        before=volume_get();volume_set(args['percent']);actual=volume_get()
        if before is not None and actual is not None and abs(actual-args['percent'])<=3:
            from core.undo import push_undo
            push_undo('local volume change',lambda:volume_set(before) or 'Previous volume restored.')
        return f"Volume is {actual} percent." if actual is not None and abs(actual-args['percent'])<=3 else 'Volume change requested, but the actual level could not be verified.'
    if kind=='timer':
        with _db_timers() as db:
            db.execute('CREATE TABLE IF NOT EXISTS local_timers(id INTEGER PRIMARY KEY,deadline REAL NOT NULL,seconds INTEGER NOT NULL,fired INTEGER NOT NULL DEFAULT 0)')
            cursor=db.execute('INSERT INTO local_timers(deadline,seconds) VALUES(?,?)',(time.time()+args['seconds'],args['seconds']))
        return f"Timer {cursor.lastrowid} set for {args['seconds']} seconds. JARVIS must be running to announce it; overdue timers are announced on next startup."
    if kind=='remember':
        from memory.memory_manager import remember
        remember(args['key'],args['value'])
        return 'Remembered '+args['key'].replace('_',' ')+'.'
    if kind=='recall':
        from memory.memory_manager import search_memory
        return search_memory(args['query'],limit=5)
    if kind=='routine':
        from core.work_routines import run
        return json.dumps(run(args['name'],player),ensure_ascii=False)
    from core.work_projects import project
    data=project()
    if not data:return 'No active project. Create and activate one in Project Workspace.'
    return f"{data['name']}. Goal: {data['goal']}. Next step: {data['next_step'] or 'Not set'}. {sum(not t['done'] for t in data['tasks'])} open tasks."


def due_timers(now=None):
    from core.work_projects import connect
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS local_timers(id INTEGER PRIMARY KEY,deadline REAL NOT NULL,seconds INTEGER NOT NULL,fired INTEGER NOT NULL DEFAULT 0)')
        rows=db.execute('UPDATE local_timers SET fired=1 WHERE fired=0 AND deadline<=? RETURNING id,seconds',(time.time() if now is None else now,)).fetchall()
    return [dict(r) for r in rows]


class LocalVoice:
    def __init__(self,on_text,on_status=None,suppressed=None):
        self.on_text=on_text
        self.on_status=on_status or (lambda text:None)
        self.suppressed=suppressed or (lambda:False)
        self._capture_stop=threading.Event()
        atexit.register(self.set_enabled,False)
        self.enabled=False
        self.state='off'
        self.speaking=False
        self._speech_tail_until=0
        self._model=None
        self._frames=[]
        self._silence=0
        self._voiced=0
        self._busy=False
        self._lock=threading.RLock()
        self._generation=0
        self._jobs=queue.Queue(maxsize=1)
        threading.Thread(target=self._worker,daemon=True,name='local-command-stt').start()

    def set_enabled(self,enabled):
        with self._lock:
            self._generation+=1
            self._capture_stop.set()
            self._capture_stop=threading.Event()
            self.enabled=bool(enabled)
            self._frames=[];self._silence=0;self._voiced=0
            self.state='loading' if enabled and self._model is None else 'ready' if enabled else 'off'
        if enabled:threading.Thread(target=self._load,daemon=True).start()
        self.on_status('Local voice '+self.state+'.')

    def _load(self):
        generation=self._generation
        try:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model=WhisperModel('tiny',device='cpu',compute_type='int8',cpu_threads=2,download_root=str(MODEL_ROOT),local_files_only=True)
                import numpy as np
                segments,_=self._model.transcribe(np.zeros(1600,dtype=np.float32),beam_size=1,vad_filter=False)
                list(segments)
            if generation==self._generation and self.enabled:
                self.state='ready'
                threading.Thread(target=self._capture,args=(generation,self._capture_stop),daemon=True,name='local-command-mic').start()
        except Exception as exc:
            if generation==self._generation:
                self.state='error'
                self.on_status('Local voice unavailable: '+str(exc)+'. Microphone remains blocked from cloud until local mode is turned off.')

    def _capture(self,generation,stop):
        try:
            import sounddevice as sd
            from core.audio_devices import resolve
            from memory.config_manager import get_input_device
            device=resolve(get_input_device(),'input')
            def callback(data,frames,clock,status):
                if not self.suppressed():self.feed(data,16000)
            with sd.InputStream(device=device,samplerate=16000,channels=1,dtype='int16',blocksize=1024,callback=callback):
                self.on_status('Local voice ready. Microphone commands stay on this Mac.')
                while self.enabled and generation==self._generation and not stop.wait(.2):pass
        except Exception as exc:
            if generation==self._generation and self.enabled:
                self.state='error'
                self.on_status('Local microphone unavailable: '+str(exc))

    def feed(self,pcm,rate=16000):
        if not self.enabled or self.state!='ready' or self._busy or self.speaking or time.monotonic()<self._speech_tail_until:return
        import numpy as np
        samples=np.asarray(pcm,dtype=np.int16).reshape(-1).astype(np.float32)/32768
        ms=len(samples)*1000/rate
        rms=float(np.sqrt(np.mean(samples*samples))) if samples.size else 0
        with self._lock:
            if rms>=0.008:
                self._voiced+=ms;self._silence=0;self._frames.append(samples)
            elif self._frames:
                self._frames.append(samples);self._silence+=ms
            if self._frames and (self._silence>=600 or sum(len(x) for x in self._frames)>=rate*8):self.flush()

    def flush(self):
        with self._lock:
            if not self._frames:return
            import numpy as np
            frames,self._frames=self._frames,[]
            voiced,self._voiced=self._voiced,0;self._silence=0
            if voiced<160:return
            try:
                self._jobs.put_nowait((self._generation,np.concatenate(frames)))
                self._busy=True
            except queue.Full:pass

    def _worker(self):
        while True:
            generation,samples=self._jobs.get()
            try:
                self.state='transcribing'
                segments,info=self._model.transcribe(samples,language='en',beam_size=1,vad_filter=True,condition_on_previous_text=False,
                    initial_prompt='Commands: open Safari. Set volume to thirty percent. Start a timer for five minutes. Remember coffee is black. Recall coffee. Run routine Start work. Project status.')
                segments=list(segments)
                unclear=not segments or any(getattr(segment,'no_speech_prob',0)>.6 or getattr(segment,'avg_logprob',0)<-1 for segment in segments)
                text='' if unclear else ' '.join(segment.text.strip() for segment in segments).strip()
                if unclear:self.on_status('Speech was unclear; no local command executed.')
                if text and self.enabled and generation==self._generation:self.on_text(text)
            except Exception as exc:self.on_status('Local recognition failed: '+str(exc))
            finally:
                self._busy=False
                self.state='ready' if self.enabled and self._model is not None else 'off'
                self._jobs.task_done()

    def speak(self,text):
        # System TTS, not the movie actor or an external service.
        self.speaking=True
        with self._lock:
            self._frames=[];self._silence=0;self._voiced=0
        try:
            subprocess.run(['/usr/bin/say','--',str(text)[:500]],timeout=35,check=False)
        except (OSError,subprocess.TimeoutExpired):pass
        finally:
            self._speech_tail_until=time.monotonic()+0.4
            self.speaking=False
