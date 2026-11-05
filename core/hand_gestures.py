"""Opt-in local hand landmarks → hologram navigation. Camera preview stays in local process memory; no frame storage or network transfer."""
from pathlib import Path
from contextlib import ExitStack
import base64
import atexit,hashlib,importlib.util,math,threading,time,os,json,subprocess,sys,select
MODEL=Path(__file__).resolve().parent.parent/'models'/'gestures'/'hand_landmarker.task'
MODEL_SHA256='fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1'
def distance(a,b):return math.sqrt(sum((float(a[i])-float(b[i]))**2 for i in range(2)))
def angle(a,b,c):
 u=[a[i]-b[i] for i in range(2)];v=[c[i]-b[i] for i in range(2)];norm=math.hypot(*u)*math.hypot(*v)
 return math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(u,v))/norm)))) if norm>1e-8 else 0
class Interpreter:
 """Hand landmarks → gestures. Each frame returns one event dict with a 'kind' and a 'label'.

 Kept from before (the face, Earth and board all use them):
   rotate     pinch thumb+index and drag            dx, dy
   zoom       two open hands moving apart/together  factor
   reset      fist held still ~0.8 s
   point      index finger only                     x, y of the fingertip
   swipe      open palm flicked left/right/up/down  direction
   palm_hold  open palm held still ~1 s
 Workshop gestures:
   throw      a fist flung and opened mid-move      direction, speed
   explode    two hands close together, then burst apart
   implode    two hands brought back together quickly
   twist      two open hands turned like a wheel    direction (cw/ccw), degrees
   push/pull  open palm moved towards / away from the camera
 """
 def __init__(self):self.clear()
 def clear(self):
  self.anchor=None;self.span=None;self.fist_at=None;self.fist_latched=False;self.pinched=False
  self.trail=[];self.swiped_at=-9.;self.still_at=None;self.palm_latched=False
  self.fist_trail=[];self.was_fist=False;self.thrown_at=-9.
  self.pair=[];self.pair_event_at=-9.;self.depth=[];self.depth_at=-9.

 def update(self,hands,now=None):
  now=time.monotonic() if now is None else now
  if not isinstance(hands,list) or not 1<=len(hands)<=2:self.clear();return {'kind':'idle','label':'Show your hand'}
  for hand in hands:
   if len(hand)!=21 or any(len(p)<2 or not all(math.isfinite(float(v)) and -.5<=float(v)<=1.5 for v in p[:2]) for p in hand):self.clear();return {'kind':'idle','label':'Hand tracking lost'}
  def opened(h):return sum(angle(h[mcp],h[pip],h[tip])>155 and distance(h[tip],h[0])>distance(h[pip],h[0])*1.05 for mcp,pip,tip in ((5,6,8),(9,10,12),(13,14,16),(17,18,20)))
  h=hands[0];fingers=opened(h)

  # ── two open hands: zoom, plus twist / explode / implode from how the pair moves ──
  if len(hands)==2 and fingers>=3 and opened(hands[1])>=3:
   self.pinched=False;self.anchor=None;self.fist_at=None;self.trail=[]
   a,b=h[9],hands[1][9]
   span=distance(a,b);turn=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
   self.pair=[q for q in self.pair if now-q[0]<=.6]+[(now,span,turn)]
   if now-self.pair_event_at>1.0 and len(self.pair)>=3:
    t0,s0,a0=self.pair[0]
    da=(turn-a0+180)%360-180
    if s0<.22 and span>s0*2.0 and span>.35:
     self.pair_event_at=now;self.pair=[];self.span=span
     return {'kind':'explode','label':'Explode view'}
    if s0>.35 and span<s0*.5:
     self.pair_event_at=now;self.pair=[];self.span=span
     return {'kind':'implode','label':'Bring it together'}
    if abs(da)>28 and .6<span/max(s0,1e-6)<1.6:
     self.pair_event_at=now;self.pair=[];self.span=span
     return {'kind':'twist','direction':'cw' if da>0 else 'ccw','degrees':round(da,1),'label':'Twist '+('clockwise' if da>0 else 'anticlockwise')}
   previous=self.span;self.span=span
   factor=max(.90,min(1.10,span/previous)) if previous and previous>.08 and span>.08 else 1.
   return {'kind':'zoom','factor':factor,'label':'Two-hand zoom · burst apart to explode · turn to twist'}
  self.span=None;self.pair=[]

  wrist=(float(h[0][0]),float(h[0][1]))
  # ── fist: held still resets; flung and opened is a throw ──
  if fingers==0:
   self.pinched=False;self.anchor=None;self.trail=[]
   self.fist_trail=[q for q in self.fist_trail if now-q[0]<=.3]+[(now,wrist[0],wrist[1])]
   self.was_fist=True
   moved=max((abs(x-wrist[0])+abs(y-wrist[1]) for _,x,y in self.fist_trail),default=0)
   if moved>.04:self.fist_at=now;self.fist_latched=False         # a moving fist is a grab, not a reset
   if self.fist_at is None:self.fist_at=now
   if now-self.fist_at>=.8 and not self.fist_latched:self.fist_latched=True;return {'kind':'reset','label':'View reset'}
   return {'kind':'idle','label':'Grab: fling and open to throw · hold still to reset'}
  if self.was_fist and fingers>=3 and self.fist_trail and now-self.thrown_at>1.0:
   t0,x0,y0=self.fist_trail[0];t1,x1,y1=self.fist_trail[-1];dt=max(t1-t0,1e-3)
   vx,vy=(x1-x0)/dt,(y1-y0)/dt;speed=math.hypot(vx,vy)
   self.was_fist=False;self.fist_trail=[]
   if speed>.9 and now-t1<.25:
    self.thrown_at=now;self.fist_at=None;self.fist_latched=False
    direction=('right' if vx>0 else 'left') if abs(vx)>=abs(vy) else ('down' if vy>0 else 'up')
    return {'kind':'throw','direction':direction,'speed':round(speed,2),'label':'Throw '+direction}
  if fingers>0:self.was_fist=False;self.fist_trail=[]
  self.fist_at=None;self.fist_latched=False

  # ── pinch + drag ──
  palm=max(.04,distance(h[0],h[9]));pinch=distance(h[4],h[8])/palm
  grabbing=pinch<(.45 if self.pinched else .30) and fingers>=2;self.pinched=grabbing
  if grabbing:
   current=((h[4][0]+h[8][0])/2,(h[4][1]+h[8][1])/2);old=self.anchor;self.anchor=current
   dx=max(-.06,min(.06,current[0]-old[0])) if old else 0;dy=max(-.06,min(.06,current[1]-old[1])) if old else 0
   return {'kind':'rotate','dx':dx,'dy':dy,'label':'Grab / rotate'}
  self.anchor=None

  # ── pointing ──
  if fingers==1 and angle(h[5],h[6],h[8])>155 and distance(h[8],h[0])>distance(h[6],h[0])*1.1:
   self.trail=[];self.still_at=None;self.palm_latched=False;self.depth=[]
   return {'kind':'point','x':float(h[8][0]),'y':float(h[8][1]),'label':'Pointing'}

  # ── open palm: swipe in four directions, push / pull, hold still ──
  if fingers>=4:
   self.trail=[(t,x,y) for t,x,y in self.trail if now-t<=.35]+[(now,wrist[0],wrist[1])]
   self.depth=[q for q in self.depth if now-q[0]<=.4]+[(now,palm)]
   t0,x0,y0=self.trail[0];dx,dy=wrist[0]-x0,wrist[1]-y0
   if now-self.swiped_at>.9:
    if abs(dx)>.22 and abs(dy)<.12:
     self.swiped_at=now;self.trail=[];self.still_at=None;self.depth=[]
     return {'kind':'swipe','direction':'right' if dx>0 else 'left','label':'Swipe '+('right' if dx>0 else 'left')}
    if abs(dy)>.20 and abs(dx)<.12:
     self.swiped_at=now;self.trail=[];self.still_at=None;self.depth=[]
     return {'kind':'swipe','direction':'down' if dy>0 else 'up','label':'Swipe '+('down' if dy>0 else 'up')}
   d0=self.depth[0][1]
   if now-self.depth_at>1.0 and len(self.depth)>=3 and abs(dx)<.08 and abs(dy)<.08:
    if palm>d0*1.35:
     self.depth_at=now;self.depth=[];self.still_at=None
     return {'kind':'push','label':'Push: run it again'}
    if palm<d0*.72:
     self.depth_at=now;self.depth=[];self.still_at=None
     return {'kind':'pull','label':'Pull back: zoom out'}
   moving=max((abs(x-wrist[0])+abs(y-wrist[1]) for _,x,y in self.trail),default=0)>.03 or abs(palm-d0)>d0*.1
   if moving:self.still_at=None;self.palm_latched=False
   elif self.still_at is None:self.still_at=now
   elif now-self.still_at>=1.0 and not self.palm_latched:
    self.palm_latched=True;return {'kind':'palm_hold','label':'Open palm held: replay'}
   return {'kind':'idle','label':'Open hand: swipe · push / pull · hold still to replay'}
  self.trail=[];self.still_at=None;self.palm_latched=False;self.depth=[]
  return {'kind':'idle','label':'Point · pinch + drag · open hand swipe/push · two hands zoom/twist/explode · fist throw/reset'}

def _finish_process(process):
 if process.poll() is None:
  process.terminate()
  try:process.wait(timeout=1)
  except subprocess.TimeoutExpired:process.kill();process.wait()
 if process.stdout and not process.stdout.closed:process.stdout.close()

class GestureController:
 def __init__(self):self._lock=threading.RLock();self._thread=None;self._stop=threading.Event();self.generation=0;self.state='off';self.error='';self.frames=0;self.label='Off'
 def status(self):
  with self._lock:return {'enabled':bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),'state':self.state,'error':self.error,'frames_processed':self.frames,'gesture':self.label,'generation':self.generation,'processing':'local only; no recording or image upload'}
 def start(self,callback):
  from core.camera_permission import require
  require()
  if importlib.util.find_spec('mediapipe') is None:raise RuntimeError('Install requirements-gestures.txt before enabling gestures.')
  if not MODEL.is_file():raise RuntimeError('Hand model is missing. Run native/setup_gestures.py to install the official model.')
  if hashlib.sha256(MODEL.read_bytes()).hexdigest()!=MODEL_SHA256:raise RuntimeError('The installed hand model differs from the tested model. Reinstall it with native/setup_gestures.py.')
  with self._lock:
   if self._thread and self._thread.is_alive():raise RuntimeError('A gesture worker is already running or stopping.')
   self.generation+=1;generation=self.generation;self._stop=threading.Event();self.state='loading';self.error='';self.frames=0;self.label='Loading local tracker'
   self._thread=threading.Thread(target=self._supervise,args=(generation,self._stop,callback),daemon=True,name='local-hologram-gestures');self._thread.start()
  return self.status()
 def stop(self):
  with self._lock:self.generation+=1;self._stop.set();self.state='off';self.label='Off';thread=self._thread
  if thread and thread is not threading.current_thread():thread.join(timeout=2)
  return self.status()
 def _supervise(self,generation,stop,callback):
  process=None
  try:
   from core.camera_access import claim
   from core.camera_permission import require
   require()
   root=Path(__file__).resolve().parent.parent
   executable=Path(sys.executable)
   if sys.platform=='darwin':
    executable=root.parent/'Mark LVI.app'/'Contents'/'MacOS'/'MarkLVI'
    if not executable.is_file():raise RuntimeError('Launch the dedicated Desktop Mark LVI.app for local hand gestures.')
   log=root/'gesture-worker.log'
   if not log.exists():
    fd=os.open(log,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
   with ExitStack() as resources:
    resources.enter_context(claim('local hand gestures'));errors=resources.enter_context(log.open('ab'))
    env=dict(os.environ);env['MPLCONFIGDIR']=str(MODEL.parent/'.matplotlib');env['PYTHONUNBUFFERED']='1'
    process=subprocess.Popen([str(executable),str(root/'core'/'gesture_worker.py'),str(generation)],cwd=root,env=env,stdout=subprocess.PIPE,stderr=errors,bufsize=0)
    resources.callback(_finish_process,process)
    buffer=b''
    while not stop.is_set():
     ready,_,_=select.select([process.stdout],[],[],.15)
     if ready:
      chunk=os.read(process.stdout.fileno(),8192)
      if not chunk:break
      buffer+=chunk
      if len(buffer)>65536:raise RuntimeError('Gesture worker sent an invalid status stream.')
      while b'\n' in buffer:
       line,buffer=buffer.split(b'\n',1)
       try:event=json.loads(line)
       except (ValueError,UnicodeError):continue
       if not isinstance(event,dict) or event.get('generation')!=generation:continue
       with self._lock:
        if generation!=self.generation:return
        if event.get('kind')=='worker_status':
         if event.get('state')=='failed':self.state='failed';self.error=str(event.get('error','Tracking failed.'))[:500]
         continue
        if event.get('kind')=='preview':
         payload=event.get('jpeg','')
         if not isinstance(payload,str) or len(payload)>48000:continue
        elif event.get('kind') not in ('idle','rotate','zoom','reset','point','swipe','palm_hold','throw','explode','implode','twist','push','pull'):continue
        self.state='tracking';self.frames+=1;self.label=str(event.get('label','Tracking'))[:100]
       if not stop.is_set():callback(event)
     if process.poll() is not None:break
    if not stop.is_set() and generation==self.generation:
     with self._lock:
      if self.state!='failed':self.state='failed';self.error='The isolated hand tracker stopped. Mark LVI is still running. Check gesture-worker.log and camera permission.';self.label='Tracking stopped'
  except Exception as exc:
   with self._lock:
    if generation==self.generation:self.state='failed';self.error=str(exc);self.label='Tracking stopped'
  finally:
   if process is not None:_finish_process(process)
 def _run_native(self,generation,stop,callback):
  cap=None
  try:
   from core.camera_access import claim
   from core.camera_permission import require
   with ExitStack() as resources:
    resources.enter_context(claim('local hand gestures'))
    require()
    cache=MODEL.parent/'.matplotlib';cache.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str(cache))
    import cv2,mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    options=vision.HandLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(MODEL),delegate=python.BaseOptions.Delegate.CPU),running_mode=vision.RunningMode.VIDEO,num_hands=2,min_hand_detection_confidence=.65,min_hand_presence_confidence=.65,min_tracking_confidence=.65)
    with vision.HandLandmarker.create_from_options(options) as detector:
     if stop.is_set():return
     from actions.screen_processor import _load_config,_cv2_backend
     index=int(_load_config().get('camera_index',0));cap=cv2.VideoCapture(index,_cv2_backend());resources.callback(cap.release)
     if not cap.isOpened():raise RuntimeError('Camera could not open for gestures. Close other camera apps and try again.')
     cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480);interpreter=Interpreter();last_stamp=0;misses=0;last_preview=0
     with self._lock:
      if generation==self.generation:self.state='tracking'
     while not stop.is_set():
      before=time.monotonic();ok,frame=cap.read()
      if not ok or frame is None:
       misses+=1
       if misses>=10:raise RuntimeError('Camera stopped returning frames.')
       stop.wait(.05);continue
      misses=0;frame=cv2.flip(cv2.resize(frame,(640,480)),1);rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB);stamp=max(last_stamp+1,int(time.monotonic()*1000));last_stamp=stamp
      result=detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb),stamp)
      hands=[[(p.x,p.y) for p in hand] for hand in result.hand_landmarks];event=interpreter.update(hands);event['generation']=generation
      with self._lock:
       if generation!=self.generation:return
       self.frames+=1;self.label=event['label']
      if not stop.is_set():callback(event)
      if time.monotonic()-last_preview>=.15 and not stop.is_set():
       last_preview=time.monotonic();preview=cv2.resize(frame,(320,240))
       edges=((0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(0,17),(17,18),(18,19),(19,20))
       for hand in hands:
        points=[(int(x*320),int(y*240)) for x,y in hand]
        for a,b in edges:cv2.line(preview,points[a],points[b],(255,220,0),2)
        for point in points:cv2.circle(preview,point,3,(0,255,120),-1)
       ok,encoded=cv2.imencode('.jpg',preview,[cv2.IMWRITE_JPEG_QUALITY,45])
       if ok and len(encoded)<=36000:callback({'kind':'preview','generation':generation,'jpeg':base64.b64encode(encoded).decode('ascii'),'label':event['label'],'hands':len(hands)})
      stop.wait(max(0,.05-(time.monotonic()-before)))
  except Exception as exc:
   with self._lock:
    if generation==self.generation:self.state='failed';self.error=str(exc);self.label='Tracking stopped'
  finally:
   if cap is not None:cap.release()
   with self._lock:
    if generation==self.generation and self.state!='failed':self.state='off'
controller=GestureController()
atexit.register(controller.stop)
