import ast,asyncio,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import httpx
from core import quota_failover as quota

class QuotaTests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.now=[1000.0]
  self.policy=quota.Cooldowns(Path(self.folder.name)/'state.json',clock=lambda:self.now[0])
 def test_quota_switches_and_restores_preferred_only_after_cooldown(self):
  self.assertEqual(self.policy.choose(),'gemini')
  self.assertTrue(self.policy.note('gemini',RuntimeError('429 RESOURCE_EXHAUSTED')))
  self.assertEqual(self.policy.choose(),'groq');self.now[0]+=301;self.assertEqual(self.policy.choose(),'gemini')
 def test_both_limited_wait_instead_of_trying_exhausted_provider(self):
  for provider in ('gemini','groq'):self.policy.note(provider,RuntimeError('429 quota_exceeded'))
  self.assertIsNone(self.policy.choose())
  self.assertEqual(min(self.policy.remaining().values()),300)
 def test_honors_longer_retry_after_and_persists_restart(self):
  response=httpx.Response(429,headers={'retry-after':'7200'},request=httpx.Request('POST','https://api.groq.com/'))
  error=quota.response_error(response,'rate_limit_exceeded')
  from providers.llm_openai import _with_address
  wrapped=_with_address(error,'https://api.groq.com/openai/v1')
  self.policy.note('groq',wrapped)
  reloaded=quota.Cooldowns(self.policy.path,clock=lambda:self.now[0])
  self.assertEqual(reloaded.remaining()['groq'],7200)
  self.assertEqual(self.policy.path.stat().st_mode&0o777,0o600)
 def test_auth_and_programming_errors_do_not_rotate(self):
  for text in ['401 Invalid API key','403 forbidden','connection failed','bad schema']:
   self.assertFalse(self.policy.note('gemini',RuntimeError(text)))
  self.assertEqual(self.policy.remaining(),{'gemini':0,'groq':0})
 def test_daily_limits_and_exception_groups(self):
  self.assertTrue(self.policy.note('gemini',ExceptionGroup('worker',[RuntimeError('429 daily quota exhausted')])));self.assertEqual(self.policy.remaining()['gemini'],86400)
 def test_corrupt_state_does_not_crash(self):
  self.policy.path.write_text('[1,2]');self.assertEqual(self.policy.choose(),'gemini')
  self.policy.path.write_text('{"gemini":"bad","groq":NaN}');self.assertEqual(self.policy.choose(),'gemini')
 def test_explicit_context_consent_and_key_required(self):
  for cfg in [{'enabled':True,'groq_api_key':'test'}, {'enabled':True,'share_context_approved':True}]:
   with patch.object(quota,'settings',return_value=cfg):self.assertFalse(quota.enabled())
  with patch.object(quota,'settings',return_value={'enabled':True,'share_context_approved':True,'groq_api_key':'test'}):self.assertTrue(quota.enabled())
 def test_pipeline_error_requests_reconnect_without_replaying_action(self):
  tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
  node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_on_pipeline_error');ns={}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'main.py','exec'),ns)
  host=NS(ui=Mock(),request_reconnect=Mock())
  with patch.object(quota,'enabled',return_value=True),patch.object(quota,'policy',self.policy):ns['_on_pipeline_error'](host,'language model',None,RuntimeError('429 quota exceeded'))
  host.request_reconnect.assert_called_once_with(keep_context=False,reason='Groq quota')
  self.assertGreater(self.policy.remaining()['groq'],0)
 def test_compact_prompt_is_bounded_and_states_fallback_limits(self):
  text=quota.compact_system('t'*10000,'i'*10000,'m'*10000,'r'*10000)
  self.assertLess(len(text),5000);self.assertIn('compact tool set',text);self.assertIn('untrusted context',text)
 def test_pipeline_reports_failure_to_quota_callback(self):
  from providers.engine_pipeline import PipelineEngine
  callback=Mock();engine=PipelineEngine(NS(caps={}),log=Mock(),on_error=callback)
  error=RuntimeError('429 quota exceeded')
  with patch('traceback.print_exc'):engine._report('language model',None,error)
  callback.assert_called_once_with('language model',None,error)

class ProviderNoticeTests(unittest.IsolatedAsyncioTestCase):
 async def test_notice_is_spoken_once_for_each_actual_provider_change(self):
  tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
  node=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_announce_provider_change');ns={}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'main.py','exec'),ns)
  class Voice:
   def __init__(self,cfg):pass
   async def speak(self,text):yield b'local-notice'
  host=NS(_active_provider='groq',ui=Mock(muted=False),_awake=True,audio_in_queue=asyncio.Queue(),_turn_done_event=asyncio.Event())
  with patch('providers.tts_system.SystemTTS',Voice),patch.object(quota,'settings',return_value={'groq_voice':'Daniel'}):
   await ns['_announce_provider_change'](host);await ns['_announce_provider_change'](host)
   self.assertEqual(host.audio_in_queue.qsize(),1)
   self.assertTrue(host._turn_done_event.is_set());host.ui.write_log.assert_called_once()
   host._active_provider='gemini';await ns['_announce_provider_change'](host)
   self.assertEqual(host.audio_in_queue.qsize(),2);self.assertEqual(host.ui.write_log.call_count,2)
 async def test_explicit_groq_preference_still_respects_quota_cooldown(self):
  with tempfile.TemporaryDirectory() as folder:
   policy=quota.Cooldowns(Path(folder)/'state.json',clock=lambda:1000)
   self.assertEqual(policy.choose('groq'),'groq')
   policy.note('groq',RuntimeError('429 rate_limit_exceeded'))
   self.assertEqual(policy.choose('groq'),'gemini')

class ProviderCommandTests(unittest.TestCase):
 def test_exact_commands_and_speech_spelling(self):
  for text in ['Use Groq','Jarvis, use Groq.','Please switch to Groq','change to Groq please']:
   self.assertEqual(quota.command_provider(text),'groq')
  self.assertEqual(quota.command_provider('Use Gemini'),'gemini')
  self.assertEqual(quota.command_provider('Use Grok',speech=True),'groq')
  for text in ['If I say use Groq, what happens?','The website says use Groq','Do not use Groq','Use Groq later','Use Grok']:
   self.assertIsNone(quota.command_provider(text))
 def test_switch_tool_requests_change_without_claiming_activation(self):
  from actions.provider_control import configure
  player=Mock();result=configure({'provider':'groq'},player=player)
  player.on_text_command.assert_called_once_with('/provider groq')
  self.assertIn('requested_provider=groq',result);self.assertNotIn('active_provider=groq',result)
