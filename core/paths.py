"""Find the file the user means, the way a person would.

The model passes what it heard: "~/Desktop/report.py", "Desktop/make_twilio_call.py", "solve.py",
"Desktop report gen py". Tools used to take that literally — relative to the app's folder, with '~'
unexpanded — and answered "File not found" while the file sat on the Desktop. In one session that
happened eleven times in a row.

find(name) tries, in order:
  1. the path as given, with ~ and $VARS expanded
  2. relative to the usual places: home, Desktop, Desktop/JARVIS Code, Documents, Downloads
  3. the same file name anywhere a few levels under those places (case-insensitive; spaces,
     dashes and underscores treated alike; a missing extension allowed)
  4. Spotlight (mdfind) for the file name in the home folder
The newest match wins. Nothing here creates, moves or deletes anything.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def home() -> Path:
    return Path(os.path.expanduser('~'))


def places() -> list[Path]:
    h = home()
    return [h / 'Desktop', h / 'Desktop' / 'JARVIS Code', h / 'Documents', h / 'Downloads', h]


def expand(raw) -> Path:
    text = str(raw or '').strip().strip('"').strip("'")
    return Path(os.path.expandvars(os.path.expanduser(text)))


def _key(name: str) -> str:
    return re.sub(r'[\s_\-]+', '', name.lower())


SKIP = {'Library', 'node_modules', '.git', '.venv', 'venv', '__pycache__', '.Trash', 'Applications'}


def _walk(root: Path, depth: int):
    if depth < 0 or not root.is_dir():
        return
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for e in entries:
        if e.name.startswith('.') or e.name in SKIP:
            continue
        yield Path(e.path)
        if e.is_dir(follow_symlinks=False):
            yield from _walk(Path(e.path), depth - 1)


def _spotlight(name: str, limit: int = 20) -> list[Path]:
    try:
        out = subprocess.run(['mdfind', '-onlyin', str(home()), '-name', name], capture_output=True, text=True,
                             timeout=4).stdout
    except Exception:
        return []
    return [Path(line) for line in out.splitlines()[:limit] if line and '/Library/' not in line]


def find(raw, *, want_dir: bool | None = None, spotlight: bool = True) -> Path | None:
    """The existing file or folder the user most likely means, or None."""
    if not str(raw or '').strip():
        return None
    p = expand(raw)
    ok = (lambda q: q.exists() and (want_dir is None or q.is_dir() == want_dir))
    if p.is_absolute():
        if ok(p):
            return p
        rel = None
    else:
        rel = p
    if rel is not None:
        parts = rel.parts
        for base in places():
            q = base / rel
            if ok(q):
                return q
            # "Desktop/x.py" when base is already Desktop
            if parts and parts[0].lower() == base.name.lower() and len(parts) > 1:
                q = base / Path(*parts[1:])
                if ok(q):
                    return q
    name = p.name
    if not name:
        return None
    want = _key(name)
    stem_only = not Path(name).suffix
    hits: list[Path] = []
    for base in places():
        for q in _walk(base, 0 if base == home() else 3):
            k = _key(q.name)
            if (k == want or (stem_only and _key(q.stem) == want)) and ok(q):
                hits.append(q)
    if not hits and spotlight:
        hits = [q for q in _spotlight(name) if (_key(q.name) == want or (stem_only and _key(q.stem) == want)) and ok(q)]
    if not hits:
        return None
    return max(dict.fromkeys(hits), key=lambda q: q.stat().st_mtime)


def resolve(raw, **kw) -> Path:
    """find(), or the expanded path itself when nothing exists yet (for messages and for new files)."""
    return find(raw, **kw) or expand(raw)
