import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave
import numpy as np
from core.recording_echo import echo_filter,finalize,ffmpeg_path

class RecordingEchoTests(unittest.TestCase):
    def test_reduces_delayed_echo_and_preserves_independent_voice(self):
        rate=16000;size=rate*6;rng=np.random.default_rng(42)
        reference=rng.normal(0,.05,size).astype('float32')
        voice=rng.normal(0,.025,size).astype('float32');voice[:rate*3]=0
        mic=voice.copy();delay=rate//10;mic[delay:]+=.6*reference[:-delay]
        with tempfile.TemporaryDirectory() as folder:
            paths=[]
            for name,data in [('system',reference),('microphone',mic)]:
                path=Path(folder)/(name+'.wav');paths.append(path)
                with wave.open(str(path),'wb') as out:
                    out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes((data*32767).astype('int16').tobytes())
            graph=echo_filter('0:a:0','1:a:0').replace('[direct][clean]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95:level=0:latency=1[mixed]','[direct]anullsink;[clean]anull[mixed]')
            result=subprocess.run([ffmpeg_path(),'-v','error','-i',str(paths[0]),'-i',str(paths[1]),'-filter_complex',graph,'-map','[mixed]','-f','f32le','pipe:1'],capture_output=True,check=True,timeout=20)
            cleaned=np.frombuffer(result.stdout,dtype='float32')[:size]
            residual=np.sqrt(np.mean(cleaned[rate:rate*3]**2))/np.sqrt(np.mean(mic[rate:rate*3]**2))
            self.assertLess(residual,.25)
            self.assertGreater(np.corrcoef(cleaned[rate*4:],voice[rate*4:len(cleaned)])[0,1],.85)
    def test_finalizer_validates_tracks_and_preserves_source_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.mp4'
            subprocess.run([ffmpeg_path(),'-v','error','-f','lavfi','-i','color=s=64x48:r=5:d=1','-f','lavfi','-i','sine=frequency=400:duration=1','-map','0:v','-map','1:a','-c:v','libx264','-c:a','aac',str(path)],check=True,capture_output=True,timeout=10)
            before=path.read_bytes()
            with self.assertRaisesRegex(RuntimeError,'separate system and microphone'):finalize(path)
            self.assertEqual(before,path.read_bytes())
    def test_two_track_video_becomes_one_track_private_playable_result(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.mp4'
            subprocess.run([ffmpeg_path(),'-v','error','-f','lavfi','-i','color=s=64x48:r=5:d=2','-f','lavfi','-i','sine=frequency=400:duration=2','-f','lavfi','-i','sine=frequency=700:duration=2','-map','0:v','-map','1:a','-map','2:a','-c:v','libx264','-c:a','aac',str(path)],check=True,capture_output=True,timeout=10)
            finalize(path)
            result=subprocess.run([str(Path(ffmpeg_path()).with_name('ffprobe')),'-v','error','-show_entries','stream=codec_type','-of','json',str(path)],capture_output=True,text=True,check=True,timeout=10)
            types=[s['codec_type'] for s in json.loads(result.stdout)['streams']]
            self.assertEqual(types.count('audio'),1);self.assertIn('video',types)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
