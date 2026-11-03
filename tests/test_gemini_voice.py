import asyncio,io,wave,unittest
from unittest.mock import AsyncMock,Mock,patch
from providers.tts_gemini import GeminiTTS
from providers import tts_gemini
class GeminiVoiceTests(unittest.IsolatedAsyncioTestCase):
 async def test_remote_pcm_uses_gemini_voice_and_does_not_invoke_local_voice(self):
  voice=GeminiTTS({'on_voice':Mock()});voice._remote=AsyncMock(return_value=b'\0\0'*100);voice.fallback=Mock()
  with patch.object(tts_gemini,'_cooldown_until',0):result=b''.join([part async for part in voice.speak('Ready, sir.')])
  self.assertEqual(result,b'\0\0'*100);voice.fallback.speak.assert_not_called();voice.on_voice.assert_called_once_with('gemini')
 async def test_quota_uses_local_voice_and_cools_only_speech_path(self):
  voice=GeminiTTS({'on_voice':Mock(),'log':Mock()});error=RuntimeError('quota');error.code=429;voice._remote=AsyncMock(side_effect=error)
  class Local:
   async def speak(self,text):yield b'local'
  voice.fallback=Local()
  with patch.object(tts_gemini,'_cooldown_until',0):
   self.assertEqual(b''.join([p async for p in voice.speak('Ready')]),b'local')
   self.assertEqual(b''.join([p async for p in voice.speak('Again')]),b'local')
   voice._remote.assert_awaited_once();self.assertGreater(tts_gemini._cooldown_until,0)
  self.assertEqual(voice.log.call_count,1)
 async def test_cancellation_never_speaks_fallback(self):
  voice=GeminiTTS();voice._remote=AsyncMock(side_effect=asyncio.CancelledError());voice.fallback=Mock()
  with patch.object(tts_gemini,'_cooldown_until',0):
   with self.assertRaises(asyncio.CancelledError):[p async for p in voice.speak('Ready')]
  voice.fallback.speak.assert_not_called()
 def test_audio_formats_are_checked_before_playback(self):
  data=b'\0\0'*100;self.assertEqual(GeminiTTS.pcm(data,'audio/L16;codec=pcm;rate=24000'),data)
  with self.assertRaises(RuntimeError):GeminiTTS.pcm(b'x','audio/L16;rate=24000')
  with self.assertRaises(RuntimeError):GeminiTTS.pcm(data,'application/json')
  out=io.BytesIO()
  with wave.open(out,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(data)
  self.assertEqual(GeminiTTS.pcm(out.getvalue(),'audio/wav'),data)
