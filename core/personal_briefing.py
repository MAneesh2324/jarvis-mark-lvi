"""Local briefing from project tasks, mission state and an explicitly imported calendar."""
from pathlib import Path
from datetime import datetime,timedelta
from core import mission_store as store
BASE=Path(__file__).resolve().parent.parent
CALENDAR=BASE/'config'/'briefing-calendar.ics'
SETTINGS=BASE/'config'/'briefing-settings.json'
def import_calendar(path):
    from icalendar import Calendar
    source=Path(path).expanduser().resolve()
    if source.suffix.lower()!='.ics' or source.stat().st_size>2_000_000:raise ValueError('Choose an ICS calendar export below 2 MB.')
    text=source.read_text(encoding='utf-8');cal=Calendar.from_ical(text)
    if not cal.walk('VEVENT'):raise ValueError('No calendar events found.')
    store.write_file(CALENDAR,text)
    return {'imported':True,'source':'Local calendar snapshot; import again to refresh.'}
def calendar_events():
    if not CALENDAR.exists():return {'connected':False,'events':[],'note':'Import an .ics export from your calendar to include events. No cloud account is connected.'}
    import icalendar,recurring_ical_events
    cal=icalendar.Calendar.from_ical(CALENDAR.read_bytes())
    today=datetime.now().astimezone();start=today.replace(hour=0,minute=0,second=0,microsecond=0);end=start+timedelta(days=1)
    rows=[]
    for event in recurring_ical_events.of(cal).between(start,end)[:100]:
        if str(event.get('STATUS',''))=='CANCELLED':continue
        when=event['DTSTART'].dt
        if isinstance(when,datetime) and when.tzinfo:when=when.astimezone()
        rows.append({'title':str(event.get('SUMMARY','Untitled'))[:200],'start':when.isoformat(),'location':str(event.get('LOCATION',''))[:200]})
    return {'connected':True,'events':sorted(rows,key=lambda r:r['start']),'snapshot_imported':datetime.fromtimestamp(CALENDAR.stat().st_mtime).astimezone().isoformat(),'note':'Imported calendar snapshot, not a live sync. Floating times use local time; all-day dates retain their date.'}
def build():
    from core import work_projects
    projects=work_projects.list_projects();active=work_projects.project()
    return {'generated':store.now(),'calendar':calendar_events(),'active_project':active,'projects':projects[:12],'missions':store.listing()[:12],'next_actions':[t['text'] for t in (active or {}).get('tasks',[]) if not t['done']][:8]}
def save_schedule(enabled,hour=9,minute=0):
    import json
    if not 0<=int(hour)<=23 or not 0<=int(minute)<=59:raise ValueError('Choose a valid local time.')
    store.write_file(SETTINGS,json.dumps({'enabled':bool(enabled),'hour':int(hour),'minute':int(minute)}))
def schedule():
    import json
    return json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {'enabled':False,'hour':9,'minute':0}
