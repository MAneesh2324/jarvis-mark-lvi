import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch
from core.voice_health import enqueue_latest, microphone_stalled, playback_drained, has_answer_progress


def method(name):
    tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
    module=ast.Module(body=[node],type_ignores=[])
    namespace={'asyncio':asyncio,'types':NS(Blob=lambda **kw:kw),'has_answer_progress':has_answer_progress}
    exec(compile(ast.fix_missing_locations(module),'main.py','exec'),namespace)
    return namespace[name]


class VoiceHealthTests(unittest.TestCase):
    def test_congestion_keeps_latest_audio_without_queuefull(self):
        queue=asyncio.Queue(maxsize=2)
        for item in range(100):enqueue_latest(queue,item)
        self.assertEqual([queue.get_nowait(),queue.get_nowait()],[98,99])
    def test_microphone_checks_callbacks_even_when_driver_claims_active(self):
        self.assertFalse(microphone_stalled(True,10,11))
        self.assertTrue(microphone_stalled(True,10,14))
        self.assertTrue(microphone_stalled(False,10,10))
    def test_missing_completion_releases_only_drained_playback(self):
        self.assertTrue(playback_drained(True,True,12,10,.25))
        self.assertFalse(playback_drained(True,False,12,10,.25))
        self.assertFalse(playback_drained(True,True,10.5,10,.25))
        self.assertFalse(playback_drained(False,True,12,10,.25))
    def test_input_and_keepalive_do_not_mask_unanswered_question(self):
        self.assertFalse(has_answer_progress(NS()))
        self.assertFalse(has_answer_progress(NS(server_content=NS(input_transcription=NS(text='question')))))
        self.assertTrue(has_answer_progress(NS(data=b'audio')))
        self.assertTrue(has_answer_progress(NS(tool_call=NS())))
        self.assertTrue(has_answer_progress(NS(server_content=NS(turn_complete=True))))


class VoiceTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_goaway_requests_context_preserving_reconnect(self):
        response=NS(go_away=NS(),session_resumption_update=NS(resumable=True,new_handle='test-handle'),data=None)
        async def receive():yield response
        obj=NS(session=NS(receive=receive),ui=Mock(),request_reconnect=Mock(),_clear_stall=Mock(),_resume_handle=None)
        await method('_receive_audio')(obj)
        self.assertEqual(obj._resume_handle,'test-handle')
        obj.request_reconnect.assert_called_once_with(keep_context=True,reason='server session expiry')
        obj._clear_stall.assert_not_called()
    async def test_audio_send_has_timeout_and_new_audio_field(self):
        queue=asyncio.Queue();queue.put_nowait({'data':b'pcm'})
        obj=NS(out_queue=queue,_local_voice=NS(enabled=False),session=NS(send_realtime_input=AsyncMock()))
        original=asyncio.wait_for
        async def bounded(awaitable,timeout):
            self.assertEqual(timeout,8)
            await awaitable
            raise TimeoutError('simulated blocked socket')
        with patch.object(asyncio,'wait_for',bounded):
            with self.assertRaises(TimeoutError):await method('_send_realtime')(obj)
        obj.session.send_realtime_input.assert_awaited_once_with(audio={'data':b'pcm','mime_type':'audio/pcm'})
