"""Find anything on this Mac through Spotlight: by name, content, kind, date or where it came from.

Spotlight already indexes the whole disk, so a query answers in well under a
second, where walking folders takes minutes. Results are sorted newest first
and skip caches, system folders and source-control internals.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

KINDS = {
    'pdf': ['com.adobe.pdf'], 'image': ['public.image'], 'photo': ['public.image'], 'video': ['public.movie'],
    'audio': ['public.audio'], 'music': ['public.audio'], 'app': ['com.apple.application'],
    'folder': ['public.folder'], 'document': ['public.composite-content', 'public.text', 'com.adobe.pdf'],
    'word': ['org.openxmlformats.wordprocessingml.document', 'com.microsoft.word.doc'],
    'spreadsheet': ['public.spreadsheet', 'org.openxmlformats.spreadsheetml.sheet'],
    'presentation': ['public.presentation'], 'text': ['public.plain-text'], 'code': ['public.source-code'],
    'archive': ['public.archive', 'public.zip-archive'],
    'installer': ['com.apple.disk-image', 'com.apple.installer-package-archive'],
}
_SKIP = re.compile(r'/(Library/(Caches|Containers|Group Containers|Application Support/[^/]+/Cache)|\.git|node_modules|'
                   r'\.venv|__pycache__|\.Trash|System/|private/var)/')


def _esc(s: str) -> str:
    return str(s).replace('\\', '\\\\').replace('"', '\\"')


def build_query(text: str = '', kind: str = '', days: float | None = None, downloaded: bool = False,
                content: bool = True) -> str:
    parts = []
    if text:
        t = _esc(text.strip())
        name = f'kMDItemDisplayName == "*{t}*"cd'
        parts.append(f'({name} || kMDItemTextContent == "*{t}*"cd)' if content else name)
    if kind:
        types = KINDS.get(kind.lower())
        if not types:
            raise ValueError('kind must be one of: ' + ', '.join(sorted(KINDS)))
        parts.append('(' + ' || '.join(f'kMDItemContentTypeTree == "{x}"' for x in types) + ')')
    if days:
        field = 'kMDItemDateAdded' if downloaded else 'kMDItemFSContentChangeDate'
        parts.append(f'{field} >= $time.today(-{int(max(0, days))})')
    if downloaded:
        parts.append('kMDItemWhereFroms == "*"')
    if not parts:
        raise ValueError('Give something to search for: words, a kind or a time window.')
    return ' && '.join(parts)


def _size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def find(text: str = '', kind: str = '', days: float | None = None, folder: str = '', downloaded: bool = False,
         content: bool = True, limit: int = 15) -> dict:
    query = build_query(text, kind, days, downloaded, content)
    cmd = ['mdfind']
    if folder:
        f = Path(os.path.expanduser(folder)).resolve()
        if not f.is_dir():
            raise ValueError(f'Folder not found: {f}')
        cmd += ['-onlyin', str(f)]
    cmd.append(query)
    t0 = time.monotonic()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError('Spotlight took too long; narrow the search with a kind, folder or date.')
    paths = [p for p in out.splitlines() if p and not _SKIP.search(p + '/')][:600]
    rows = []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        rows.append((st.st_mtime, p, st.st_size, os.path.isdir(p)))
    rows.sort(reverse=True)
    limit = max(1, min(int(limit or 15), 50))
    items = [{'name': os.path.basename(p), 'path': p, 'folder': os.path.dirname(p).replace(str(Path.home()), '~'),
              'size': '' if is_dir else _size(size), 'modified': datetime.fromtimestamp(m).strftime('%Y-%m-%d %H:%M'),
              'type': 'folder' if is_dir else (Path(p).suffix.lower().lstrip('.') or 'file')}
             for m, p, size, is_dir in rows[:limit]]
    return {'query': {'text': text, 'kind': kind or None, 'days': days, 'folder': folder or None, 'downloaded': downloaded},
            'found': len(rows), 'showing': len(items), 'seconds': round(time.monotonic() - t0, 2), 'results': items,
            'note': 'Newest first. Spotlight covers indexed locations; external drives may need indexing.'}
