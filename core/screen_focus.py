"""Opt-in analysis scope: selected display, exact macOS window, or a region."""
from pathlib import Path
import os
import platform
import subprocess
import tempfile
import threading

_lock=threading.RLock()
_selection={'mode':'display','monitor':1}


def current():
    with _lock:return dict(_selection)

def windows():
    if platform.system()!='Darwin':raise RuntimeError('Window selection currently requires macOS. Display and region selection are still available.')
    import Quartz
    rows=Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly|Quartz.kCGWindowListExcludeDesktopElements,Quartz.kCGNullWindowID)
    result=[]
    for row in rows:
        bounds=row.get('kCGWindowBounds',{})
        if row.get('kCGWindowLayer',1)!=0 or bounds.get('Width',0)<80 or bounds.get('Height',0)<60:continue
        result.append({'window_id':int(row['kCGWindowNumber']),'app':str(row.get('kCGWindowOwnerName','')),'title':str(row.get('kCGWindowName','')),'bounds':bounds})
    return result

def select(mode='display',monitor=1,window_id=None,region=None):
    if mode=='display':
        if int(monitor)<1:raise ValueError('Choose display 1 or higher.')
        selected={'mode':'display','monitor':int(monitor)}
    elif mode=='window':
        if window_id is None:raise ValueError('Refresh visible windows and choose one first.')
        match=next((r for r in windows() if r['window_id']==int(window_id)),None)
        if not match:raise ValueError('That window is no longer available. List windows and choose again.')
        selected={'mode':'window','window_id':match['window_id'],'app':match['app'],'title':match['title']}
    elif mode=='region':
        if not isinstance(region,dict):raise ValueError('A region needs left, top, width and height.')
        box={k:int(region[k]) for k in ('left','top','width','height')}
        if min(box['width'],box['height'])<32 or max(box['width'],box['height'])>8192 or box['width']*box['height']>32000000:raise ValueError('Choose a region at least 32×32 pixels, at most 8192 per side and 32 megapixels.')
        selected={'mode':'region',**box}
    else:raise ValueError('Choose display, window or region.')
    with _lock:
        changed=_selection!=selected
        _selection.clear();_selection.update(selected)
    if changed:
        from core.screen_workspace import workspace
        with workspace._lock:
            workspace.generation+=1
            workspace.analysis_active=False
    return current()

def capture(scope=None):
    from core.screen_workspace import require_screen_permission
    require_screen_permission()
    scope=scope or current()
    if scope['mode']=='window':
        if not any(r['window_id']==scope['window_id'] for r in windows()):raise RuntimeError('The selected window closed. Select a new window; capture did not fall back to the entire desktop.')
        fd,path=tempfile.mkstemp(suffix='.png',prefix='jarvis-window-');os.close(fd)
        try:
            result=subprocess.run(['/usr/sbin/screencapture','-x','-o','-l',str(scope['window_id']),'-t','png',path],capture_output=True,text=True,timeout=6)
            if result.returncode or not Path(path).stat().st_size:raise RuntimeError(result.stderr.strip() or 'Window capture failed. Check Screen Recording permission.')
            return Path(path).read_bytes()
        finally:Path(path).unlink(missing_ok=True)
    import mss
    import mss.tools
    with mss.mss() as screen:
        if scope['mode']=='region':target={k:scope[k] for k in ('left','top','width','height')}
        else:
            index=scope['monitor']
            if index>=len(screen.monitors):raise RuntimeError('The selected display disconnected. Choose another display.')
            target=screen.monitors[index]
        shot=screen.grab(target)
        return mss.tools.to_png(shot.rgb,shot.size)
