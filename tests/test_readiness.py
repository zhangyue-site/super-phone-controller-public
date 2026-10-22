import unittest
from display_service.readiness import Readiness
class ReadinessTests(unittest.TestCase):
 def test_actual_probes_required_and_cached(self):
  calls=[];clock=[1000]
  r=Readiness(lambda:calls.append('chat'),lambda:calls.append('asr'),clock=lambda:clock[0])
  self.assertFalse(r.snapshot()['ready'])
  self.assertTrue(r.run()['ready']);self.assertEqual(calls,['chat','asr'])
  r.run();self.assertEqual(len(calls),2)
  clock[0]+=301;self.assertFalse(r.snapshot()['ready']);r.run();self.assertEqual(len(calls),4)
 def test_chat_failure_not_server_or_voice_success(self):
  def fail():raise RuntimeError('secret must not be exposed')
  r=Readiness(fail,lambda:None)
  result=r.run();self.assertEqual(result['server'],'ok');self.assertEqual(result['chat'],'error');self.assertEqual(result['asr'],'ok')
  self.assertFalse(result['ready']);self.assertNotIn('secret',str(result))
 def test_no_phone_control_claim(self):
  r=Readiness(lambda:None,lambda:None)
  self.assertFalse(r.run()['phoneControlReady'])
