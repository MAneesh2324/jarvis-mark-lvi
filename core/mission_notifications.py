"""Quiet main-window notifications. No background cloud work at startup."""
from datetime import datetime
import json,threading
from core import mission_store as store

class Notifications:
    def __init__(self,host):
        from core.mission_engine import engine
        engine();self.host=host;self.seen={r['id']:r['state'] for r in store.listing()};self.briefing_busy=False;self.checks=0
    def tick(self):
        for row in store.listing():
            old=self.seen.get(row['id']);new=row['state'];self.seen[row['id']]=new
            if old!=new and new in ('completed','failed','interrupted'):
                self.host._log.append_log('MISSION: '+row['goal'][:90]+' — '+new+('. '+row['error'][:180] if row['error'] else '. Open Mission Control for evidence.'))
        self.checks+=1
        if self.checks%10 or self.briefing_busy:return
        from core.personal_briefing import schedule
        c=schedule();now=datetime.now().astimezone();today=now.date().isoformat()
        if not c.get('enabled') or c.get('last_shown')==today or (now.hour,now.minute)<(c['hour'],c['minute']):return
        self.briefing_busy=True
        # Mark before dispatch so a restart does not repeat today's notification.
        c['last_shown']=today
        from core.personal_briefing import SETTINGS
        store.write_file(SETTINGS,json.dumps(c))
        def work():
            try:
                from core.personal_briefing import build
                result=build();self.host._content_sig.emit('DAILY BRIEFING',json.dumps(result,ensure_ascii=False,indent=2)[:16000])
            except Exception:self.host._content_sig.emit('BRIEFING','Could not read the local briefing. Check the calendar import in Mission Control.')
            finally:self.briefing_busy=False
        threading.Thread(target=work,daemon=True).start()
