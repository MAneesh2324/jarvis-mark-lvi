"""Apple Calendar and Reminders for JARVIS, through EventKit (pyobjc-framework-EventKit).

Why EventKit and not AppleScript: it reads the same store Calendar.app and Reminders.app use, in
milliseconds, with exact dates and stable identifiers, and it does not need Calendar.app open.
AppleScript against Calendar.app takes seconds per query and gets slower with every calendar.

Everything here works in LOCAL time with naive datetimes. Callers echo the resolved absolute time
back to the model so it can confirm "Saturday 7 November at 15:00" out loud before anyone relies on it.

Permissions:
  * macOS asks once per app ("Mark LVI" would like full access to your Calendars / Reminders). A
    missing or refused permission raises PermissionNeeded with a sentence the user can act on —
    never a traceback.
  * macOS kills an app that asks for calendar access without declaring why in its Info.plist. So
    the request is only made when the running bundle declares NSCalendarsFullAccessUsageDescription
    / NSRemindersFullAccessUsageDescription; otherwise PermissionNeeded('missing_purpose') explains
    how to fix the launcher instead of crashing JARVIS.

Safety:
  * Event titles, notes, locations and attendees are often written by other people (invitations,
    shared calendars). Callers wrap them with outcome.untrusted.
  * Deleting and moving go through core/confirm in actions/mac_calendar.py; adding is reversible
    through core/undo.

Tests replace the store with set_backend(fake); nothing in the test suite touches the real calendar.
"""
from __future__ import annotations

import re
import sys
import threading
from datetime import date, datetime, time as dtime, timedelta

EVENTS = 'events'
REMINDERS = 'reminders'

# How long to wait for the user to answer the macOS permission prompt, and for a reminders fetch.
PROMPT_TIMEOUT = 45.0
FETCH_TIMEOUT = 10.0

SETTINGS_PATH = {EVENTS: 'Calendars', REMINDERS: 'Reminders'}
PURPOSE_KEYS = {
    EVENTS: ('NSCalendarsFullAccessUsageDescription', 'NSCalendarsUsageDescription'),
    REMINDERS: ('NSRemindersFullAccessUsageDescription', 'NSRemindersUsageDescription'),
}


class CalendarError(Exception):
    """Something the user can be told about in one sentence."""


class PermissionNeeded(CalendarError):
    """Calendars or Reminders access is missing. `str(exc)` is the instruction for the user."""

    def __init__(self, kind: str, state: str, bundle: str = ''):
        self.kind, self.state = kind, state
        pane = SETTINGS_PATH.get(kind, 'Calendars')
        where = f'System Settings → Privacy & Security → {pane}'
        if state == 'write_only':
            msg = (f'JARVIS can only add to {pane}, not read it. Ask the user to open {where} and set '
                   f'"Mark LVI" to Full Access, then ask again.')
        elif state == 'pending':
            msg = (f'macOS is showing a permission prompt for {pane}. Ask the user to click Allow / '
                   f'Allow Full Access for "Mark LVI", then ask again.')
        elif state == 'missing_purpose':
            msg = (f'This copy of JARVIS{f" ({bundle})" if bundle else ""} does not declare {pane} access, so '
                   f'macOS cannot ask for it. Open JARVIS from Mark LVI.app after its launcher has been rebuilt '
                   f'with the {pane} purpose strings (native/build_launcher.py), then ask again; if it is '
                   f'already allowed, switch on "Mark LVI" in {where}.')
        elif state == 'unavailable':
            msg = ('Apple Calendar and Reminders need macOS and the pyobjc-framework-EventKit package '
                   '(.venv/bin/pip install -r requirements.txt).')
        else:   # denied, restricted, not granted
            msg = (f'JARVIS is not allowed to use {pane}. Ask the user to open {where}, switch on "Mark LVI" '
                   f'(Full Access), then ask again.')
        super().__init__(msg)


# ═════════════════════════════════════════════════════════════════════════════
#  Words → local datetimes
# ═════════════════════════════════════════════════════════════════════════════
WEEKDAYS = {'monday': 0, 'mon': 0, 'tuesday': 1, 'tue': 1, 'tues': 1, 'wednesday': 2, 'wed': 2,
            'thursday': 3, 'thu': 3, 'thur': 3, 'thurs': 3, 'friday': 4, 'fri': 4,
            'saturday': 5, 'sat': 5, 'sunday': 6, 'sun': 6}
MONTHS = {'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3, 'april': 4, 'apr': 4,
          'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9,
          'sep': 9, 'sept': 9, 'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12}
PARTS_OF_DAY = {'morning': (9, 0), 'noon': (12, 0), 'midday': (12, 0), 'afternoon': (14, 0),
                'evening': (18, 0), 'tonight': (20, 0), 'night': (20, 0), 'midnight': (0, 0)}

_WD = '|'.join(sorted(WEEKDAYS, key=len, reverse=True))
_MO = '|'.join(sorted(MONTHS, key=len, reverse=True))
_FILLER = re.compile(r'\b(?:on|at|the|of|this coming|for|by|o\'?clock)\b|,')
_REL = re.compile(r'(?:in\s+)?(half an|an?|\d+(?:\.\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|weeks?)'
                  r'(?:\s+from\s+now)?')


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now()).replace(microsecond=0)


def _iso(s: str) -> tuple[datetime, bool] | None:
    s = s.strip().upper().replace(' ', 'T', 1) if re.match(r'\d{4}-\d{2}-\d{2}[ t]\d', s) else s.strip().upper()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:?\d{2})?)?', s):
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0), 'T' in s


def _take_time(s: str) -> tuple[tuple[int, int] | None, str]:
    """Pull a clock time out of `s`. Returns ((hour, minute) or None, the rest)."""
    ampm = r'\s*(a\.?m\.?|p\.?m\.?)'
    patterns = ((r'\b(\d{1,2}):(\d{2})(?:' + ampm + r')?(?![\w:])', False),
                (r'\b(\d{1,2})()' + ampm + r'(?!\w)', False),
                (r"\b(?:at\s+)?(\d{1,2})()()\s*o'?clock\b", True),
                (r'\bat\s+(\d{1,2})()()(?!\s*(?:st|nd|rd|th)\b)(?![\w:])', True))
    for pat, bare in patterns:
        m = re.search(pat, s)
        if not m:
            continue
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        suffix = (m.group(3) or '').replace('.', '')
        if suffix:
            if not 1 <= hour <= 12:
                raise ValueError(f'"{m.group(0).strip()}" is not a valid time')
            hour = (hour % 12) + (12 if suffix == 'pm' else 0)
        elif bare and 1 <= hour <= 7:
            hour += 12          # "at 3" means the afternoon far more often than 3 in the morning
        if hour > 23 or minute > 59:
            raise ValueError(f'"{m.group(0).strip()}" is not a valid time')
        return (hour, minute), (s[:m.start()] + ' ' + s[m.end():])
    for word, hm in PARTS_OF_DAY.items():
        m = re.search(rf'\b(?:this\s+|in the\s+)?{word}\b', s)
        if m:
            rest = s[:m.start()] + ' ' + s[m.end():]
            if word == 'tonight':
                rest += ' today'
            return hm, rest
    return None, s


def _date_part(s: str, today: date, future: bool) -> date | None:
    s = re.sub(r'\s+', ' ', _FILLER.sub(' ', s)).strip()
    if not s:
        return None
    if s in ('today', 'now'):
        return today
    if s in ('tomorrow', 'tmrw', 'tmr', 'tomorow'):
        return today + timedelta(days=1)
    if s in ('day after tomorrow', 'the day after tomorrow', 'overmorrow'):
        return today + timedelta(days=2)
    if s == 'yesterday':
        return today - timedelta(days=1)
    if s == 'next week':
        return today + timedelta(days=7 - today.weekday())
    hit = _iso(s)
    if hit:
        return hit[0].date()
    m = re.fullmatch(rf'(this|next|coming)?\s*({_WD})', s)
    if m:
        target = WEEKDAYS[m.group(2)]
        ahead = (target - today.weekday()) % 7
        if m.group(1) in ('next', 'coming') and ahead == 0:
            ahead = 7
        return today + timedelta(days=ahead)
    m = (re.fullmatch(rf'(?:({_WD})\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MO})\.?(?:\s+(\d{{4}}))?', s)
         or re.fullmatch(rf'(?:({_WD})\s+)?({_MO})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(\d{{4}}))?', s))
    if m:
        a, b = m.group(2), m.group(3)
        day, month = (int(a), MONTHS[b]) if a.isdigit() else (int(b), MONTHS[a])
        year = int(m.group(4)) if m.group(4) else today.year
        d = date(year, month, day)
        if future and not m.group(4) and d < today:
            d = date(year + 1, month, day)
        return d
    m = re.fullmatch(r'(\d{1,2})(?:st|nd|rd|th)', s)
    if m:
        day = int(m.group(1))
        d = today.replace(day=day)
        if future and d < today:
            d = (today.replace(day=1) + timedelta(days=32)).replace(day=day)
        return d
    raise ValueError(f'could not understand the date "{s}"')


def parse_when(text, now: datetime | None = None, *, base: date | datetime | None = None,
               future: bool = True) -> tuple[datetime, bool]:
    """'tomorrow 3pm', 'next monday at 9', 'in 2 hours', '2026-11-09T15:00' → (local datetime, has_time).

    `base` is the day a bare time belongs to ("move it to 4pm" → the event's own day). Without a
    base, a bare time that has already passed today rolls to tomorrow when `future` is set.
    Raises ValueError with a readable reason when the words cannot be pinned to a moment.
    """
    now = _now(now)
    raw = str(text or '').strip()
    s = re.sub(r'\s+', ' ', raw.lower()).strip(' .')
    if not s:
        raise ValueError('no date or time given')
    hit = _iso(s)
    if hit:
        return hit
    if s == 'now':
        return now, True
    m = _REL.fullmatch(s)
    if m and (s.startswith('in ') or s.endswith('from now')):
        n = 0.5 if m.group(1) == 'half an' else 1.0 if m.group(1) in ('a', 'an') else float(m.group(1))
        unit = m.group(2)[0]
        if unit in 'dw':
            return datetime.combine(now.date() + timedelta(days=round(n * (7 if unit == 'w' else 1))),
                                    dtime()), False
        return now + timedelta(minutes=n * (60 if unit == 'h' else 1)), True
    hm, rest = _take_time(s)
    d = _date_part(rest, now.date(), future)
    if hm is None:
        if d is None:
            raise ValueError(f'could not understand "{raw}"')
        return datetime.combine(d, dtime()), False
    if d is None:
        day = base.date() if isinstance(base, datetime) else base
        dt = datetime.combine(day or now.date(), dtime(*hm))
        if future and base is None and dt < now - timedelta(minutes=1):
            dt += timedelta(days=1)
        return dt, True
    return datetime.combine(d, dtime(*hm)), True


def _midnight(d) -> datetime:
    return datetime.combine(d if isinstance(d, date) and not isinstance(d, datetime) else d.date(), dtime())


def parse_range(text, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """'today', 'tomorrow', 'this week', 'next week', 'weekend', 'next 3 days', 'this month',
    '2026-11-09 to 2026-11-12', or any single day → (start, end exclusive, label)."""
    now = _now(now)
    today = _midnight(now)
    s = re.sub(r'\s+', ' ', str(text or '').lower()).strip(' .') or 'today'
    s = re.sub(r'^(?:what(?:\'s| is) )?(?:on |for |during |over )?(?:the )?', '', s) or 'today'
    if s in ('today', 'rest of today', 'rest of the day'):
        start, end = today, today + timedelta(days=1)
    elif s in ('week', 'this week', 'rest of the week', 'rest of this week'):
        start, end = today, today + timedelta(days=7 - today.weekday())
    elif s == 'next week':
        start = today + timedelta(days=7 - today.weekday())
        end = start + timedelta(days=7)
    elif s in ('weekend', 'this weekend', 'next weekend'):
        wd = today.weekday()
        sat = today - timedelta(days=wd - 5) if wd >= 5 else today + timedelta(days=5 - wd)
        if s == 'next weekend' and wd >= 5:
            sat += timedelta(days=7)
        start, end = max(sat, today), sat + timedelta(days=2)
    elif s in ('month', 'this month', 'rest of the month'):
        start = today
        end = _midnight((today.replace(day=1) + timedelta(days=32)).replace(day=1))
    elif re.fullmatch(r'(?:the )?(?:next|coming|upcoming)?\s*(\d+|a|one|two|three|four|five|six|seven|'
                      r'ten|fourteen) days?', s):
        word = re.search(r'(\d+|a|one|two|three|four|five|six|seven|ten|fourteen) days?', s).group(1)
        n = {'a': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'ten': 10,
             'fourteen': 14}.get(word) or int(word)
        start, end = today, today + timedelta(days=max(1, min(n, 62)))
    else:
        m = re.fullmatch(r'(?:between |from )?(.+?)\s*(?: to | until | till | through | and |\.\.| – | - )\s*(.+)', s)
        if m and not _iso(s):
            a, _ = parse_when(m.group(1), now)
            b, b_time = parse_when(m.group(2), now)
            start = a if a.time() != dtime() else _midnight(a)
            end = b if b_time else _midnight(b) + timedelta(days=1)
        else:
            when, has_time = parse_when(s, now)
            start = when if has_time else _midnight(when)
            end = _midnight(when) + timedelta(days=1)
    if end <= start:
        raise ValueError(f'"{text}" ends before it starts')
    return start, end, describe_range(start, end)


def fmt(dt: datetime | None, has_time: bool = True) -> str:
    """'Sat 7 Nov 2026 15:00' — unambiguous, and easy for the model to say."""
    if dt is None:
        return ''
    out = f'{dt:%a} {dt.day} {dt:%b %Y}'
    return f'{out} {dt:%H:%M}' if has_time else out


def describe_range(start: datetime, end: datetime) -> str:
    last = end - timedelta(seconds=1)
    if start.date() == last.date():
        return fmt(start, start.time() != dtime())
    return f'{fmt(start, False)} – {fmt(last, False)}'


# ═════════════════════════════════════════════════════════════════════════════
#  Derived views (pure — they work on the dicts the backend returns)
# ═════════════════════════════════════════════════════════════════════════════

def event_line(e: dict, with_date: bool = True) -> str:
    if e.get('all_day'):
        when = (fmt(e['start'], False) + ' ' if with_date else '') + 'all day'
    else:
        day = fmt(e['start'], False) + ' ' if with_date else ''
        end = e.get('end')
        when = f'{day}{e["start"]:%H:%M}' + (f'–{end:%H:%M}' if end else '')
        if end and end.date() != e['start'].date():
            when += f' (ends {fmt(end)})'
    out = f'{when} — {e.get("title") or "(no title)"}'
    if e.get('calendar'):
        out += f' [{e["calendar"]}]'
    if e.get('location'):
        out += f' @ {e["location"]}'
    if e.get('recurring'):
        out += ' (repeats)'
    if e.get('attendees'):
        names = list(e['attendees'])
        out += ' with ' + ', '.join(names[:5]) + (f' +{len(names) - 5}' if len(names) > 5 else '')
    return out


def reminder_line(r: dict, now: datetime | None = None) -> str:
    now = _now(now)
    out = r.get('title') or '(no title)'
    due = r.get('due')
    if due:
        out += f' — due {fmt(due, r.get("due_has_time", True))}'
        if (due < now if r.get('due_has_time', True) else due.date() < now.date()):
            out += ' (OVERDUE)'
    if r.get('list'):
        out += f' [{r["list"]}]'
    return out


def free_slots(events: list[dict], day: date, *, day_start: int = 9, day_end: int = 18,
               now: datetime | None = None, min_minutes: int = 15) -> list[tuple[datetime, datetime]]:
    """Gaps between timed events on `day` within working hours. All-day events do not block time.
    On today, the past is not free time: the window starts at the next 5-minute mark."""
    now = _now(now)
    lo = datetime.combine(day, dtime(max(0, min(23, day_start))))
    hi = datetime.combine(day, dtime()) + timedelta(hours=max(1, min(24, day_end)))
    if day == now.date():
        nxt = now + timedelta(minutes=(-now.minute) % 5, seconds=-now.second)
        lo = max(lo, nxt)
    if hi <= lo:
        return []
    busy = sorted((max(e['start'], lo), min(e['end'] or e['start'], hi)) for e in events
                  if not e.get('all_day') and e.get('start') and (e.get('end') or e['start']) > lo and e['start'] < hi)
    slots, cursor = [], lo
    for b0, b1 in busy:
        if b0 > cursor and (b0 - cursor) >= timedelta(minutes=min_minutes):
            slots.append((cursor, b0))
        cursor = max(cursor, b1)
    if hi > cursor and (hi - cursor) >= timedelta(minutes=min_minutes):
        slots.append((cursor, hi))
    return slots


def slot_text(slots) -> str:
    def one(a, b):
        mins = int((b - a).total_seconds() // 60)
        length = f'{mins // 60}h{mins % 60:02d}' if mins >= 60 else f'{mins}min'
        return f'{a:%H:%M}–{"24:00" if b.time() == dtime() and b.date() > a.date() else f"{b:%H:%M}"} ({length})'
    return ', '.join(one(a, b) for a, b in slots) or 'none'


def overlapping(events: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [e for e in events if not e.get('all_day') and e['start'] < end and (e.get('end') or e['start']) > start]


# ═════════════════════════════════════════════════════════════════════════════
#  EventKit store
# ═════════════════════════════════════════════════════════════════════════════

def _nsdate(dt: datetime):
    import Foundation
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _pydate(nsd) -> datetime | None:
    if nsd is None:
        return None
    return datetime.fromtimestamp(nsd.timeIntervalSince1970()).replace(microsecond=0)


def _text(v) -> str:
    return str(v).strip() if v is not None else ''


class EventKitBackend:
    """Thin, synchronous wrapper over one EKEventStore. Returns plain dicts with naive local datetimes."""

    def __init__(self, ek=None, foundation=None):
        self._ek = ek
        self._fd = foundation
        self._store = None
        self._lock = threading.RLock()

    # ── plumbing ──
    def _mods(self):
        if self._ek is None or self._fd is None:
            if sys.platform != 'darwin':
                raise PermissionNeeded(EVENTS, 'unavailable')
            try:
                import EventKit
                import Foundation
            except Exception:
                raise PermissionNeeded(EVENTS, 'unavailable') from None
            self._ek = self._ek or EventKit
            self._fd = self._fd or Foundation
        return self._ek, self._fd

    def _entity(self, kind: str) -> int:
        ek, _ = self._mods()
        return ek.EKEntityTypeReminder if kind == REMINDERS else ek.EKEntityTypeEvent

    def _get_store(self):
        with self._lock:
            if self._store is None:
                ek, _ = self._mods()
                self._store = ek.EKEventStore.alloc().init()
            return self._store

    def access_state(self, kind: str) -> str:
        """'ok', 'not_determined', 'denied', 'restricted', 'write_only' or 'unavailable'. Never prompts."""
        try:
            ek, _ = self._mods()
            st = int(ek.EKEventStore.authorizationStatusForEntityType_(self._entity(kind)))
        except PermissionNeeded:
            return 'unavailable'
        except Exception:
            return 'unavailable'
        return {0: 'not_determined', 1: 'restricted', 2: 'denied', 3: 'ok', 4: 'write_only'}.get(st, 'denied')

    def _bundle(self) -> tuple[str, dict]:
        _, fd = self._mods()
        b = fd.NSBundle.mainBundle()
        info = b.infoDictionary() or {}
        return _text(b.bundleIdentifier() or b.bundlePath()), dict(info)

    def _ensure(self, kind: str) -> None:
        state = self.access_state(kind)
        if state == 'ok':
            return
        if state == 'unavailable':
            raise PermissionNeeded(kind, 'unavailable')
        if state != 'not_determined':
            raise PermissionNeeded(kind, state)
        ident, info = self._bundle()
        full_key, legacy_key = PURPOSE_KEYS[kind]
        ek, _ = self._mods()
        store = self._get_store()
        modern = hasattr(store, 'requestFullAccessToEventsWithCompletion_')   # macOS 14+
        declared = info.get(full_key) or (not modern and info.get(legacy_key))
        if not declared:
            # Asking without a declared purpose makes macOS terminate the whole app.
            raise PermissionNeeded(kind, 'missing_purpose', ident)
        answered, result = threading.Event(), {}

        def done(granted, error=None):
            result['granted'] = bool(granted)
            answered.set()

        if modern:
            if kind == REMINDERS:
                store.requestFullAccessToRemindersWithCompletion_(done)
            else:
                store.requestFullAccessToEventsWithCompletion_(done)
        else:
            store.requestAccessToEntityType_completion_(self._entity(kind), done)
        if not answered.wait(PROMPT_TIMEOUT):
            raise PermissionNeeded(kind, 'pending')
        if not result.get('granted'):
            raise PermissionNeeded(kind, self.access_state(kind) if self.access_state(kind) != 'ok' else 'denied')
        with self._lock:                 # a store made before the grant may not see the data yet
            self._store = None

    # ── conversion ──
    def _event(self, ev) -> dict:
        cal = ev.calendar()
        try:
            people = [_text(p.name()) or _text(p.URL()).replace('mailto:', '') for p in (ev.attendees() or [])]
        except Exception:
            people = []
        return {
            'id': _text(ev.eventIdentifier()), 'title': _text(ev.title()), 'start': _pydate(ev.startDate()),
            'end': _pydate(ev.endDate()), 'all_day': bool(ev.isAllDay()),
            'calendar': _text(cal.title()) if cal is not None else '',
            'writable': bool(cal.allowsContentModifications()) if cal is not None else False,
            'location': _text(ev.location()), 'notes': _text(ev.notes())[:400],
            'attendees': [p for p in people if p], 'recurring': bool(ev.hasRecurrenceRules()),
        }

    def _comps_to_dt(self, comps) -> tuple[datetime | None, bool]:
        if comps is None:
            return None, False
        _, fd = self._mods()
        nsd = fd.NSCalendar.currentCalendar().dateFromComponents_(comps)
        has_time = 0 <= int(comps.hour()) <= 23
        return _pydate(nsd), has_time

    def _reminder(self, r) -> dict:
        due, has_time = self._comps_to_dt(r.dueDateComponents())
        cal = r.calendar()
        return {'id': _text(r.calendarItemIdentifier()), 'title': _text(r.title()), 'due': due,
                'due_has_time': has_time, 'list': _text(cal.title()) if cal is not None else '',
                'notes': _text(r.notes())[:400], 'completed': bool(r.isCompleted()),
                'priority': int(r.priority() or 0)}

    def _calendar_named(self, kind: str, name: str):
        want = str(name or '').strip().lower()
        cals = list(self._get_store().calendarsForEntityType_(self._entity(kind)) or [])
        exact = [c for c in cals if _text(c.title()).lower() == want]
        return (exact or [c for c in cals if want and want in _text(c.title()).lower()] or [None])[0]

    def _find_event(self, event_id: str, start: datetime | None):
        store = self._get_store()
        if start is not None:   # a repeating event: find this very occurrence, not the first one
            pred = store.predicateForEventsWithStartDate_endDate_calendars_(
                _nsdate(start - timedelta(minutes=1)), _nsdate(start + timedelta(days=1)), None)
            for ev in store.eventsMatchingPredicate_(pred) or []:
                if _text(ev.eventIdentifier()) == event_id and _pydate(ev.startDate()) == start:
                    return ev
        return store.eventWithIdentifier_(event_id)

    @staticmethod
    def _check(res, what: str):
        ok, err = res if isinstance(res, tuple) else (res, None)
        if not ok:
            reason = _text(err.localizedDescription()) if err is not None else 'macOS refused'
            raise CalendarError(f'{what}: {reason}')

    # ── calendars ──
    def calendars(self) -> list[dict]:
        self._ensure(EVENTS)
        return [{'title': _text(c.title()), 'writable': bool(c.allowsContentModifications())}
                for c in self._get_store().calendarsForEntityType_(self._entity(EVENTS)) or []]

    def reminder_lists(self) -> list[str]:
        self._ensure(REMINDERS)
        return [_text(c.title()) for c in self._get_store().calendarsForEntityType_(self._entity(REMINDERS)) or []]

    def events(self, start: datetime, end: datetime) -> list[dict]:
        self._ensure(EVENTS)
        store = self._get_store()
        pred = store.predicateForEventsWithStartDate_endDate_calendars_(_nsdate(start), _nsdate(end), None)
        out = [self._event(ev) for ev in store.eventsMatchingPredicate_(pred) or []]
        return sorted(out, key=lambda e: (e['start'] or start, not e['all_day']))

    def get_event(self, event_id: str, start: datetime | None = None) -> dict | None:
        self._ensure(EVENTS)
        ev = self._find_event(event_id, start)
        return self._event(ev) if ev is not None else None

    def add_event(self, title, start, end, all_day=False, calendar='', location='', notes='') -> dict:
        self._ensure(EVENTS)
        ek, _ = self._mods()
        store = self._get_store()
        cal = self._calendar_named(EVENTS, calendar) if calendar else store.defaultCalendarForNewEvents()
        if cal is None:
            raise CalendarError(f'no calendar called "{calendar}"' if calendar else 'there is no default calendar')
        ev = ek.EKEvent.eventWithEventStore_(store)
        ev.setTitle_(title)
        ev.setCalendar_(cal)
        ev.setAllDay_(bool(all_day))
        ev.setStartDate_(_nsdate(start))
        ev.setEndDate_(_nsdate(end))
        if location:
            ev.setLocation_(location)
        if notes:
            ev.setNotes_(notes)
        self._check(store.saveEvent_span_commit_error_(ev, ek.EKSpanThisEvent, True, None), 'could not add the event')
        return self._event(ev)

    def remove_event(self, event_id: str, start: datetime | None = None) -> None:
        self._ensure(EVENTS)
        ek, _ = self._mods()
        ev = self._find_event(event_id, start)
        if ev is None:
            raise CalendarError('that event is no longer in the calendar')
        self._check(self._get_store().removeEvent_span_commit_error_(ev, ek.EKSpanThisEvent, True, None),
                    'could not delete the event')

    def move_event(self, event_id: str, start: datetime | None, new_start: datetime, new_end: datetime) -> dict:
        self._ensure(EVENTS)
        ek, _ = self._mods()
        ev = self._find_event(event_id, start)
        if ev is None:
            raise CalendarError('that event is no longer in the calendar')
        ev.setStartDate_(_nsdate(new_start))
        ev.setEndDate_(_nsdate(new_end))
        self._check(self._get_store().saveEvent_span_commit_error_(ev, ek.EKSpanThisEvent, True, None),
                    'could not move the event')
        return self._event(ev)

    # ── reminders ──
    def _fetch(self, pred) -> list:
        got, box = threading.Event(), {}

        def done(items):
            box['items'] = list(items or [])
            got.set()

        self._get_store().fetchRemindersMatchingPredicate_completion_(pred, done)
        if not got.wait(FETCH_TIMEOUT):
            raise CalendarError('Reminders did not answer in time')
        return box['items']

    def reminders(self, list_name: str = '') -> list[dict]:
        self._ensure(REMINDERS)
        store = self._get_store()
        cals = None
        if list_name:
            cal = self._calendar_named(REMINDERS, list_name)
            if cal is None:
                raise CalendarError(f'no reminders list called "{list_name}"')
            cals = [cal]
        pred = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, cals)
        return [self._reminder(r) for r in self._fetch(pred)]

    def _reminder_obj(self, rid: str):
        item = self._get_store().calendarItemWithIdentifier_(rid)
        if item is None or not hasattr(item, 'isCompleted'):
            return None
        return item

    def get_reminder(self, rid: str) -> dict | None:
        self._ensure(REMINDERS)
        r = self._reminder_obj(rid)
        return self._reminder(r) if r is not None else None

    def add_reminder(self, title, due=None, due_has_time=True, list_name='', notes='') -> dict:
        self._ensure(REMINDERS)
        ek, fd = self._mods()
        store = self._get_store()
        cal = self._calendar_named(REMINDERS, list_name) if list_name else store.defaultCalendarForNewReminders()
        if cal is None:
            raise CalendarError(f'no reminders list called "{list_name}"' if list_name else 'there is no default reminders list')
        r = ek.EKReminder.reminderWithEventStore_(store)
        r.setTitle_(title)
        r.setCalendar_(cal)
        if notes:
            r.setNotes_(notes)
        if due is not None:
            c = fd.NSDateComponents.alloc().init()
            c.setYear_(due.year)
            c.setMonth_(due.month)
            c.setDay_(due.day)
            if due_has_time:
                c.setHour_(due.hour)
                c.setMinute_(due.minute)
                r.addAlarm_(ek.EKAlarm.alarmWithAbsoluteDate_(_nsdate(due)))
            r.setDueDateComponents_(c)
        self._check(store.saveReminder_commit_error_(r, True, None), 'could not add the reminder')
        return self._reminder(r)

    def set_reminder_completed(self, rid: str, completed: bool = True) -> dict:
        self._ensure(REMINDERS)
        r = self._reminder_obj(rid)
        if r is None:
            raise CalendarError('that reminder no longer exists')
        r.setCompleted_(bool(completed))
        self._check(self._get_store().saveReminder_commit_error_(r, True, None), 'could not update the reminder')
        return self._reminder(r)

    def remove_reminder(self, rid: str) -> None:
        self._ensure(REMINDERS)
        r = self._reminder_obj(rid)
        if r is None:
            raise CalendarError('that reminder no longer exists')
        self._check(self._get_store().removeReminder_commit_error_(r, True, None), 'could not delete the reminder')


_backend = None
_backend_lock = threading.Lock()


def backend():
    """The shared store. Created on first use, so importing this module costs nothing."""
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = EventKitBackend()
        return _backend


def set_backend(b) -> None:
    """Swap the store (tests pass a fake; None goes back to EventKit on next use)."""
    global _backend
    with _backend_lock:
        _backend = b


# ═════════════════════════════════════════════════════════════════════════════
#  Briefing
# ═════════════════════════════════════════════════════════════════════════════

def _short(t: str, n: int = 32) -> str:
    t = ' '.join(str(t or '').split())
    return t if len(t) <= n else t[:n - 1].rstrip() + '…'


def today_summary(now: datetime | None = None) -> str:
    """One or two short lines: what is left on the calendar today and which reminders are due.

    For a morning briefing. Never raises and never pops a permission prompt: when access has not
    been granted it says so in a line instead. Titles come from the user's calendars and may have
    been written by others — a caller handing this to the model should wrap it with outcome.untrusted.
    """
    try:
        now = _now(now)
        today = _midnight(now)
        b = backend()
        lines = []
        if b.access_state(EVENTS) == 'ok':
            evs = b.events(today, today + timedelta(days=1))
            all_day = [e for e in evs if e.get('all_day')]
            left = [e for e in evs if not e.get('all_day') and (e.get('end') or e['start']) > now]
            bits = [f'{e["start"]:%H:%M} {_short(e["title"])}' for e in left[:3]]
            if len(left) > 3:
                bits.append(f'{len(left) - 3} more')
            if all_day:
                bits.append('all day: ' + ', '.join(_short(e['title'], 24) for e in all_day[:2]))
            lines.append(('Today: ' + '; '.join(bits) + '.') if bits else 'Nothing else on the calendar today.')
        else:
            lines.append('Calendar not connected (allow Calendars for "Mark LVI" in System Settings → '
                         'Privacy & Security).')
        if b.access_state(REMINDERS) == 'ok':
            rs = [r for r in b.reminders() if r.get('due')]
            overdue = [r for r in rs if r['due'].date() < now.date()]
            due = [r for r in rs if r['due'].date() == now.date()]
            if due or overdue:
                text = 'Reminders: '
                if due:
                    text += f'{len(due)} due today (' + ', '.join(_short(r['title'], 24) for r in due[:3]) + ')'
                if overdue:
                    text += (', ' if due else '') + f'{len(overdue)} overdue'
                lines.append(text + '.')
        return '\n'.join(lines)
    except Exception:
        return ''
