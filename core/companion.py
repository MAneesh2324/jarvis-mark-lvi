"""JARVIS's heart: its own feelings, and the user at the centre of them.

What it notices (locally, from what the user says plus the voice-tone sensor in core/wellbeing.py)
    low      sad, lonely, hopeless, "I failed", "what's the point"
    setback  a loss, a rejection, a failed test, a trade that hit its stop
    anxious  nervous or worried about something coming up
    unmotivated  "can't focus", "don't feel like it", procrastinating
    win      profit, passed, finished, it works, got it
    crisis   words about ending one's life or self-harm: always handled first and with care

What JARVIS feels in response, and shows on its face
    warm (resting), concerned, proud, determined, playful, calm. A feeling has an intensity and
    fades back to warm over several minutes, so the face and voice move like a person's, not a switch.

What it does with that
    A short private note tells the model how to respond right now: console (acknowledge the feeling
    first, no lecture), steady after a setback (no revenge trading), celebrate a win sincerely,
    motivate (shrink the task, remember why, offer a focus session).

Focus on the user
    - Goals the user states ("my goal is ...", "I want to ...") are remembered and used to motivate.
    - Wins are remembered, so a hard day can be met with what they have already done.
    - Things coming up ("tomorrow I have an interview") become follow-ups: JARVIS asks how it went.
    - Focus sessions: a countdown on the face, non-urgent notifications held, a check at the end, and
      a daily tally of focused minutes and the streak of days.

Only short text snippets the user said about goals, wins and plans are kept (memory/companion.json,
git-ignored, owner-only permissions), never audio.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STATE = BASE / 'memory' / 'companion.json'

FEELINGS = {
    'warm':       {'label': 'WARM',       'color': '#5fd4ff'},
    'concerned':  {'label': 'CONCERNED',  'color': '#8fb8ff'},
    'proud':      {'label': 'PROUD',      'color': '#ffcc00'},
    'determined': {'label': 'DETERMINED', 'color': '#00ff9c'},
    'playful':    {'label': 'PLAYFUL',    'color': '#ff9ee0'},
    'calm':       {'label': 'CALM',       'color': '#7fe7ff'},
}
FADE_SECONDS = 8 * 60            # a strong feeling fades back to warm over about this long
NOTE_GAP = 120                   # at most one companion note per two minutes, except for crisis and wins

_W = r"[\w'’]+"
PATTERNS = {
    'crisis': re.compile(r"\b(kill myself|end (my|it all|my life)|suicid\w*|don'?t want to (live|be alive|exist)|"
                         r"want to die|self[- ]?harm|hurt myself|no reason to live|better off without me)\b", re.I),
    'low': re.compile(r"\b(i'?m|i am|feel(ing)?|so)\s+(really\s+|so\s+|very\s+)?(sad|down|low|lonely|alone|depressed|"
                      r"hopeless|worthless|useless|empty|broken|lost|miserable|heartbroken)\b|\bi('?m| am) (a )?failure\b|"
                      r"\bwhat'?s the point\b|\bnobody (cares|understands)\b|\bhate my life\b|\bcrying\b|\bi give up\b", re.I),
    'setback': re.compile(r"\b(lost|losing) (money|the trade|my trade|again|\d[\d,.]*)|\b(stop ?loss|sl) (hit|got hit)|\bhit my (stop|sl)\b|"
                          r"\b(blew|blown) (up )?(my )?account\b|\b(got )?rejected\b|\bfailed (my |the |an? )?\w+|\bi failed\b|"
                          r"\b(it|this|nothing) (is not|isn'?t|won'?t|doesn'?t) work(ing)?\b|\bbad day\b|\bmessed up\b|\bscrewed up\b", re.I),
    'anxious': re.compile(r"\b(nervous|anxious|scared|afraid|worried|tense|panick\w*)\b", re.I),
    'unmotivated': re.compile(r"\b(can'?t|cannot|unable to) (focus|concentrate|start|get started)\b|\bno motivation\b|"
                              r"\b(un|not )motivated\b|\bdon'?t feel like\b|\bprocrastinat\w*|\bso lazy\b|\bfeel(ing)? lazy\b|"
                              r"\bdistracted\b|\bbored\b|\bwasting (my )?time\b", re.I),
    'win': re.compile(r"\b(i |we )?(did it|nailed it|made it)\b|\b(made|booked|took) (a )?profits?\b|\bin profit\b|\b(hit|reached) (my |the )?(target|tp|goal)\b|"
                      r"\b(i|we) (just )?passed\b|\bpassed (my|the)\b|\bgot (the |a )?(job|offer|selected|admission)\b|\b(finally )?(it )?works( now)?!?$|\bi won\b|\bwe won\b|"
                      r"\b(finished|completed|shipped|launched) (it|the|my)\b", re.I),
}
GOAL = re.compile(r"\b(?:my (?:main |big |real )?goal is (?:to )?|i want to (?:become|be|achieve|learn|build|reach|make|get|crack|master|start)\s|"
                  r"i(?:'m| am) (?:going|planning|trying) to (?:become|learn|build|reach|make|get|crack|master|start)\s|i dream of )"
                  r"(?P<goal>[^.?!]{3,90})", re.I)
WHEN = {'today': 0, 'tonight': 0, 'this evening': 0, 'this afternoon': 0, 'tomorrow': 1, 'day after tomorrow': 2, 'next week': 7}
DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
EVENT = re.compile(r"\b(?P<when>day after tomorrow|tomorrow|today|tonight|this (?:evening|afternoon)|next week|"
                   r"(?:on |this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b"
                   r"[^.?!]{0,40}?\b(?:i have|i've got|i got|there'?s|is|my)\b[^.?!]{0,20}?\b"
                   r"(?P<what>(?:job )?interview|exam|test|presentation|meeting|appointment|surgery|operation|match|"
                   r"game|date|call with \w+|demo|deadline|results?|viva|audition|flight|trip)\b", re.I)
EVENT_REV = re.compile(r"\b(?:my|the|an?)\s+(?P<what>(?:job )?interview|exam|test|presentation|meeting|appointment|match|demo|deadline|results?|viva)\b"
                       r"[^.?!]{0,30}?\b(?:is )?(?P<when>day after tomorrow|tomorrow|today|tonight|next week|"
                       r"(?:on |this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I)

# little face reactions to what the user says (played on JARVIS's face, see core/avatar.py CLIPS)
REACT = [
    (re.compile(r"\b(ha(ha)+|he(he)+|lol|lmao|rofl)\b|😂|🤣", re.I), 'laugh'),
    (re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening))\b", re.I), 'brow_flash'),
    (re.compile(r"\b(thank you|thanks|you'?re (the )?best|good job|well done)\b", re.I), 'smile'),
    (re.compile(r"\b(no way|seriously\?|what\?!|wow|whoa|omg|oh my god)\b", re.I), 'surprise'),
]


def reaction(text: str) -> str | None:
    """The expression JARVIS's face makes on hearing this, or None."""
    for rx, name in REACT:
        if rx.search(text or ''):
            return name
    return None


HELPLINES = ('Tele-MANAS 14416 or 1-800-891-4416 (India, free, 24x7), KIRAN 1800-599-0019, '
             'or 112 for immediate danger')

GUIDE = {
    'crisis': ('URGENT — the user may be thinking of harming themselves. Respond with deep, calm care before anything '
               'else: take it seriously, tell them you are glad they said it, ask gently whether they are safe right now, '
               'and encourage them to reach someone they trust or a helpline now: ' + HELPLINES + '. Stay with them, '
               'keep sentences short and kind, no jokes, no changing the subject, no lecturing. Do not call tools unless '
               'they ask for help contacting someone.'),
    'low': ('The user sounds low. You feel genuinely concerned for them. Console first: name what they are feeling in '
            'their own terms in one short sentence and let them know you are with them. No lecture, no quick fixes '
            'unless they ask. Then offer one small kind step, or simply ask if they want to talk about it.{win}'),
    'setback': ('The user has just had a setback. Be steady and on their side: one sentence that it is a hard moment, '
                'then perspective (one result is not the whole story). If it is a trading loss: remind them the plan and '
                'risk rules exist for exactly this, discourage revenge trading, suggest a short pause. Offer one concrete '
                'next step.{win}'),
    'anxious': ('The user is anxious about something. Reassure calmly and specifically, help them prepare in one or two '
                'concrete points, and tell them you will ask how it went.'),
    'unmotivated': ('The user is struggling with motivation or focus. Be determined alongside them, not preachy: shrink the '
                    'task to a first step that takes five minutes, remind them why it matters{goal}, and offer a focus '
                    'session (companion tool, focus_start).'),
    'win': ('The user just had a win. You feel proud of them: say so sincerely in one line and name exactly what they did'
            '{goal}. Then carry on with what they need.'),
}


def _now() -> float:
    return time.time()


class Companion:
    def __init__(self, path: Path | None = None):
        self.path = path or STATE
        self._lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}
        for k, v in (('goals', []), ('wins', []), ('followups', []), ('focus', None), ('focus_log', {})):
            self.data.setdefault(k, v)
        self.feeling, self.intensity, self.why, self.felt_at = 'warm', 0.4, 'here with you', _now()
        self.last_note = 0.0
        self.listeners: list = []          # fn(feeling, intensity, focus) — the HUD

    # ── storage ─────────────────────────────────────────────────────────────
    def save(self):
        from core.mission_store import write_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_file(self.path, json.dumps(self.data, ensure_ascii=False))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ── feelings ────────────────────────────────────────────────────────────
    def feel(self, name: str, intensity: float, why: str):
        self.feeling, self.intensity, self.why, self.felt_at = name, max(0.0, min(1.0, intensity)), why, _now()
        self._tell()

    def current(self) -> dict:
        """The feeling as it is now: strong feelings fade back toward warm with time."""
        age = _now() - self.felt_at
        if self.feeling != 'warm' and age > FADE_SECONDS:
            self.feeling, self.intensity, self.why, self.felt_at = 'warm', 0.4, 'here with you', _now()
            age = 0
        k = max(0.0, 1 - age / FADE_SECONDS) if self.feeling != 'warm' else 1.0
        level = round(self.intensity * (0.35 + 0.65 * k), 3)
        if self.focus_active():
            return {'feeling': 'determined' if self.feeling in ('warm', 'calm') else self.feeling,
                    'intensity': max(level, 0.5), 'why': 'you are focusing on ' + self.data['focus']['task']}
        return {'feeling': self.feeling, 'intensity': level, 'why': self.why}

    def _tell(self):
        state, focus = self.current(), self.focus_status()
        for fn in list(self.listeners):
            try:
                fn(state['feeling'], state['intensity'], focus)
            except Exception as exc:
                print(f'[Companion] listener failed: {exc}')

    # ── what the user said ──────────────────────────────────────────────────
    @staticmethod
    def signals(text: str) -> list[str]:
        t = ' ' + (text or '').strip() + ' '
        return [k for k, rx in PATTERNS.items() if rx.search(t)]

    def on_user_turn(self, text: str, mood: str | None = None) -> str | None:
        """After each user turn: update feelings, remember goals/wins/plans; return a private note or None."""
        text = (text or '').strip()
        with self._lock:
            sig = self.signals(text)
            changed = self._remember(text, sig)
            kind = next((k for k in ('crisis', 'low', 'setback', 'anxious', 'unmotivated', 'win') if k in sig), None)
            if kind is None and mood in ('stressed', 'tired'):
                kind = 'mood:' + mood
            if kind is None:
                if mood == 'excited':
                    self.feel('playful', 0.55, 'you sound upbeat')
                if changed:
                    self.save()
                return None
            feeling = {'crisis': 'concerned', 'low': 'concerned', 'setback': 'concerned', 'anxious': 'concerned',
                       'unmotivated': 'determined', 'win': 'proud', 'mood:stressed': 'calm', 'mood:tired': 'concerned'}[kind]
            strength = {'crisis': 1.0, 'low': 0.9, 'setback': 0.75, 'anxious': 0.65, 'unmotivated': 0.7, 'win': 0.85}.get(kind, 0.5)
            self.feel(feeling, strength, {'crisis': 'I am worried about you', 'low': 'you sound low', 'setback': 'you had a setback',
                                          'anxious': 'you are worried', 'unmotivated': 'you need a push', 'win': 'you did it',
                                          'mood:stressed': 'you sound stressed', 'mood:tired': 'you sound tired'}[kind])
            if changed:
                self.save()
            if kind.startswith('mood:'):
                return None                     # the wellbeing sensor already sent its own tone note
            if kind not in ('crisis', 'win') and _now() - self.last_note < NOTE_GAP:
                return None
            self.last_note = _now()
            return self.note(kind, text)

    def note(self, kind: str, said: str) -> str:
        wins = [w['text'] for w in self.data['wins'][-3:]]
        goals = [g['text'] for g in self.data['goals'][-3:]]
        guide = GUIDE[kind].format(
            win=(f' If it helps, remind them of something they already did: "{wins[-1]}".' if wins and kind in ('low', 'setback') else ''),
            goal=(f' (their goal: "{goals[-1]}")' if goals else ''))
        quote = said[:160].replace('"', "'")
        return (f'[Private context from JARVIS\'s companion sense, not spoken by the user. They said: "{quote}". '
                f'{guide} Your own feeling right now: {self.current()["feeling"]}. Speak from it naturally; never say '
                'you "detected" anything.]')

    def _remember(self, text: str, sig: list[str]) -> bool:
        changed = False
        m = GOAL.search(text)
        if m:
            goal = m.group('goal').strip(' ,')
            if goal and not any(g['text'].lower() == goal.lower() for g in self.data['goals']):
                self.data['goals'] = (self.data['goals'] + [{'text': goal, 'added': date.today().isoformat()}])[-12:]
                changed = True
        if 'win' in sig and 'crisis' not in sig:
            self.data['wins'] = (self.data['wins'] + [{'text': text[:140], 'at': date.today().isoformat()}])[-30:]
            changed = True
        ev = EVENT.search(text) or EVENT_REV.search(text)
        if ev:
            due = self._due(ev.group('when'))
            what = ev.group('what').lower()
            if due and not any(f['what'] == what and f['due'] == due for f in self.data['followups']):
                self.data['followups'] = (self.data['followups'] + [{'what': what, 'due': due, 'said': text[:140], 'asked': False}])[-20:]
                changed = True
        return changed

    @staticmethod
    def _due(when: str, today: date | None = None) -> str | None:
        today = today or date.today()
        w = when.lower().replace('on ', '').replace('this ', '').strip()
        if when.lower() in WHEN:
            return (today + timedelta(days=WHEN[when.lower()])).isoformat()
        w = w.replace('next ', '')
        if w in DAYS:                                    # the coming one ("friday", "on friday", "next friday")
            return (today + timedelta(days=(DAYS.index(w) - today.weekday()) % 7 or 7)).isoformat()
        return None

    # ── goals and follow-ups ────────────────────────────────────────────────
    def add_goal(self, text: str) -> dict:
        with self._lock:
            text = str(text).strip()[:120]
            if text and not any(g['text'].lower() == text.lower() for g in self.data['goals']):
                self.data['goals'].append({'text': text, 'added': date.today().isoformat()})
                self.save()
        return {'goals': self.data['goals']}

    def remove_goal(self, text: str) -> dict:
        with self._lock:
            key = str(text).lower().strip()
            self.data['goals'] = [g for g in self.data['goals'] if key not in g['text'].lower()]
            self.save()
        return {'goals': self.data['goals']}

    def due_followups(self, today: date | None = None) -> list[dict]:
        today = (today or date.today()).isoformat()
        return [f for f in self.data['followups'] if not f['asked'] and f['due'] < today
                or (not f['asked'] and f['due'] == today and datetime.now().hour >= 18)]

    def mark_asked(self):
        with self._lock:
            for f in self.due_followups():
                f['asked'] = True
            self.data['followups'] = [f for f in self.data['followups'] if not f['asked'] or f['due'] >= (date.today() - timedelta(days=7)).isoformat()]
            self.save()

    # ── focus sessions ──────────────────────────────────────────────────────
    def focus_start(self, task: str, minutes: int = 25) -> dict:
        minutes = max(5, min(int(minutes or 25), 180))
        with self._lock:
            self.data['focus'] = {'task': (str(task or 'deep work').strip()[:80] or 'deep work'), 'minutes': minutes,
                                  'started': _now(), 'ends': _now() + minutes * 60}
            self.save()
        self.feel('determined', 0.75, 'you are focusing')
        return self.focus_status()

    def focus_active(self) -> bool:
        f = self.data.get('focus')
        return bool(f and _now() < f['ends'])

    def focus_status(self) -> dict | None:
        f = self.data.get('focus')
        if not f:
            return None
        left = max(0, int(f['ends'] - _now()))
        return {'task': f['task'], 'minutes': f['minutes'], 'seconds_left': left, 'active': left > 0,
                'progress': round(1 - left / (f['minutes'] * 60), 3)}

    def focus_stop(self, completed: bool | None = None) -> dict:
        with self._lock:
            f = self.data.get('focus')
            if not f:
                return {'stopped': False, 'note': 'No focus session is running.'}
            done_min = round(min(_now(), f['ends']) - f['started']) // 60
            day = date.today().isoformat()
            self.data['focus_log'][day] = self.data['focus_log'].get(day, 0) + int(done_min)
            self.data['focus_log'] = dict(sorted(self.data['focus_log'].items())[-60:])
            self.data['focus'] = None
            self.save()
        full = completed if completed is not None else done_min >= f['minutes'] - 1
        if full:
            self.feel('proud', 0.8, f'you focused on {f["task"]} for {done_min} minutes')
        else:
            self._tell()
        return {'stopped': True, 'task': f['task'], 'focused_minutes': int(done_min), 'completed': bool(full), **self.focus_totals()}

    def focus_totals(self) -> dict:
        log = self.data['focus_log']
        streak, d = 0, date.today()
        if not log.get(d.isoformat()):
            d -= timedelta(days=1)                       # today not started yet: the streak runs to yesterday
        while log.get(d.isoformat()):
            streak += 1
            d -= timedelta(days=1)
        return {'today_minutes': log.get(date.today().isoformat(), 0), 'streak_days': streak,
                'week_minutes': sum(v for k, v in log.items() if k >= (date.today() - timedelta(days=6)).isoformat())}

    def tick(self) -> str | None:
        """Once a minute: finish a focus session that ran out. Returns something to say, or None."""
        f = self.data.get('focus')
        if f and _now() >= f['ends']:
            r = self.focus_stop(completed=True)
            return (f'Focus session complete: {r["focused_minutes"]} minutes on {r["task"]}. '
                    f'{r["today_minutes"]} focused minutes today' + (f', a {r["streak_days"]}-day streak' if r['streak_days'] > 1 else '')
                    + '. Take five minutes away from the screen before the next one.')
        self._tell()                                     # keeps the face's countdown and fading feeling current
        return None

    # ── what the model knows at the start of a conversation ─────────────────
    def context_block(self) -> str:
        lines = []
        goals = [g['text'] for g in self.data['goals'][-5:]]
        wins = [f'{w["text"]} ({w["at"]})' for w in self.data['wins'][-3:]]
        due = self.due_followups()
        if goals:
            lines.append('Their goals: ' + '; '.join(goals) + '.')
        if wins:
            lines.append('Recent wins of theirs: ' + '; '.join(wins) + '.')
        if due:
            lines.append('Ask how these went, warmly and early in the conversation (one at a time): '
                         + '; '.join(f'{f["what"]} on {f["due"]} ("{f["said"][:80]}")' for f in due) + '.')
        fs = self.focus_status()
        if fs and fs['active']:
            lines.append(f'They are in a focus session on "{fs["task"]}" ({fs["seconds_left"] // 60} min left): keep replies '
                         'very short and kindly steer back to the task if they drift.')
        t = self.focus_totals()
        if t['today_minutes'] or t['streak_days'] > 1:
            lines.append(f'Focused today: {t["today_minutes"]} min; streak: {t["streak_days"]} day(s).')
        if not lines:
            return ''
        return '[ABOUT THE USER — from JARVIS\'s companion memory]\n' + '\n'.join(lines) + '\n'

    def status(self) -> dict:
        return {'jarvis_feels': self.current(), 'goals': self.data['goals'], 'recent_wins': self.data['wins'][-5:],
                'followups': [f for f in self.data['followups'] if not f['asked']], 'focus': self.focus_status(),
                **self.focus_totals()}


_instance: Companion | None = None


def instance() -> Companion:
    global _instance
    if _instance is None:
        _instance = Companion()
    return _instance
