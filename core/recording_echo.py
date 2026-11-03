"""Local post-recording adaptive echo reduction before mixing microphone + system."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def ffmpeg_path():
    path=shutil.which('ffmpeg')
    if not path and Path('/opt/homebrew/bin/ffmpeg').exists():path='/opt/homebrew/bin/ffmpeg'
    if not path:raise RuntimeError('FFmpeg is required for microphone echo reduction. Install FFmpeg or record audio=system.')
    return path


def echo_filter(system='0:a:0',microphone='0:a:1'):
    # Both tracks use the same media timeline. Do not independently reset PTS:
    # that would erase the measured system/microphone timing relationship.
    return (f'[{system}]aresample=16000,aformat=channel_layouts=mono,asplit=2[reference][direct];'
            f'[{microphone}]aresample=16000,aformat=channel_layouts=mono[mic];'
            '[reference][mic]anlms=order=8192:mu=0.5:eps=0.001:leakage=0:out_mode=o[clean];'
            '[direct][clean]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95:level=0:latency=1[mixed]')


def finalize(path):
    """Atomically replace a two-track native recording; preserve raw file on failure."""
    path=Path(path);ffmpeg=ffmpeg_path()
    probe=Path(ffmpeg).with_name('ffprobe')
    result=subprocess.run([str(probe),'-v','error','-show_entries','stream=codec_type','-of','json',str(path)],capture_output=True,text=True,timeout=15,check=True)
    if sum(s.get('codec_type')=='audio' for s in json.loads(result.stdout)['streams'])!=2:
        raise RuntimeError('Expected separate system and microphone tracks; original recording retained without echo processing.')
    # Private directory keeps the incomplete encoded result out of other users' reach.
    with tempfile.TemporaryDirectory(prefix='.echo-',dir=path.parent) as folder:
        output=Path(folder)/'processed.mp4'
        result=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(path),
            '-filter_complex',echo_filter(),'-map','0:v:0','-map','[mixed]','-c:v','copy','-c:a','aac','-b:a','128k',
            '-movflags','+faststart',str(output)],capture_output=True,text=True,timeout=600)
        if result.returncode or not output.exists() or output.stat().st_size==0:
            raise RuntimeError('Echo processing failed; the original two-track recording is retained. '+result.stderr[-400:])
        os.chmod(output,0o600)
        checked=subprocess.run([str(probe),'-v','error','-show_entries','stream=codec_type','-of','json',str(output)],capture_output=True,text=True,timeout=15,check=True)
        streams=json.loads(checked.stdout)['streams']
        if not any(s.get('codec_type')=='video' for s in streams) or sum(s.get('codec_type')=='audio' for s in streams)!=1:
            raise RuntimeError('Processed tracks failed verification; original recording retained.')
        os.replace(output,path)
