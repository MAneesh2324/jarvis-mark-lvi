"""Download the version-checked official Google hand model; no camera access."""
from pathlib import Path
import hashlib,sys,urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.hand_gestures import MODEL,MODEL_SHA256
url='https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task'
with urllib.request.urlopen(url,timeout=45) as response:data=response.read(15_000_001)
if len(data)>15_000_000 or hashlib.sha256(data).hexdigest()!=MODEL_SHA256:raise SystemExit('Model changed or download failed; review the official model version before installing.')
MODEL.parent.mkdir(parents=True,exist_ok=True);temporary=MODEL.with_suffix('.download');temporary.write_bytes(data);temporary.replace(MODEL)
print('Installed tested local hand model:',MODEL)
