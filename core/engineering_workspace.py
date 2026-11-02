"""Bounded local project inspection. Never executes project code or follows symlinks."""
from pathlib import Path
import ast, json, os, re
SKIP={'.git','.venv','venv','node_modules','vendor','__pycache__','models','recordings','memory','config','.aws','.ssh','.codex'}
EXT={'.py','.js','.ts','.tsx','.jsx','.md','.txt','.json','.svg','.html','.css','.pdf'}
PRIVATE=re.compile(r'(secret|credential|api.?key|token|password|\.env|id_rsa|id_ed25519)',re.I)
def files(root):
    root=Path(root).expanduser().resolve()
    if not root.is_dir():raise ValueError('Select an existing project folder.')
    rows=[]
    for base,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d not in SKIP and not d.startswith('.') and not (Path(base)/d).is_symlink())
        for name in sorted(names):
            path=Path(base)/name
            if name.startswith('.') or PRIVATE.search(name) or path.is_symlink() or path.suffix.lower() not in EXT:continue
            if path.stat().st_size>512_000:continue
            rows.append(path)
            if len(rows)>=250:return root,rows
    return root,rows

def read(root,relative):
    root=Path(root).expanduser().resolve();candidate=root/relative
    if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents if parent!=root and root in parent.parents):raise ValueError('Symlink files are excluded.')
    path=candidate.resolve()
    if root not in path.parents or any(p in SKIP or p.startswith('.') for p in path.relative_to(root).parts) or PRIVATE.search(path.name):raise ValueError('This file is outside the permitted project selection or is a private configuration.')
    if path.suffix.lower() not in EXT or path.stat().st_size>512_000:raise ValueError('Choose a supported file below 512 KB.')
    if path.suffix.lower()=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(path)
        if reader.is_encrypted:raise ValueError('Encrypted PDFs are not read.')
        return '\n'.join((page.extract_text() or '')[:12000] for page in reader.pages[:8])[:40000]
    return path.read_text(encoding='utf-8',errors='replace')[:40000]

def inspect(root,cancel=lambda:None):
    root,paths=files(root);inventory=[];diagnostics=[];notes=[]
    for path in paths:
        cancel();relative=str(path.relative_to(root));text=read(root,relative) if path.suffix.lower()=='.pdf' else path.read_text(encoding='utf-8',errors='replace')
        row={'file':relative,'bytes':path.stat().st_size}
        if path.suffix=='.py':
            try:
                tree=ast.parse(text,filename=relative)
                row['symbols']=[node.name for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))][:30]
            except SyntaxError as exc:diagnostics.append({'file':relative,'line':exc.lineno,'message':exc.msg,'check':'Python AST parse'})
        elif path.suffix=='.json':
            try:json.loads(text)
            except ValueError as exc:diagnostics.append({'file':relative,'message':str(exc),'check':'JSON parse'})
        for line,value in enumerate(text.splitlines(),1):
            if re.search(r'\b(TODO|FIXME)\b',value) and len(notes)<60:notes.append({'file':relative,'line':line,'text':value.strip()[:200]})
        inventory.append(row)
    return {'root':str(root),'files':inventory,'diagnostics':diagnostics,'notes':notes,'checks':'Python syntax and JSON structure only. Does not execute files/tests, prove behavior or perform a security audit.','bounded':len(paths)>=250,'sharing':'Read locally; no project content was sent to an AI service.'}
