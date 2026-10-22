import threading,unittest,time
from unittest.mock import patch
from display_service.dialogue import Mailbox
from display_service.conversation import Conversation
class RunnerTests(unittest.TestCase):
 def run_turn(self,decision,backend='hid_pending'):
  m=Mailbox();j=m.create('d','a'*16,1)
  def forbidden(*a,**kw):raise AssertionError('phone action must stay disabled')
  m.execute=forbidden
  with patch.dict('os.environ',{'EPAPER_PHONE_BACKEND':backend}):
   Conversation(m,lambda messages:decision,lambda text:b'\1\0'*16000,lambda *a,**kw:None).run(j,'打开微信找到张三')
  return j
 def test_chat_runs_without_phone_actions_and_keeps_memory(self):
  m=Mailbox();j=m.create('d','a'*16,1)
  c=Conversation(m,lambda messages:{'action':'reply','reply':'你好'},lambda text:b'\1\0'*16000,lambda *a,**kw:None)
  c.run(j,'你好')
  self.assertTrue(j.done);self.assertEqual(j.reply,'你好');self.assertTrue(j.audio)
 def test_phone_action_is_blocked_without_executing_any_mailbox_command(self):
  for backend in ('hid_pending','autoglm','legacy',''):
   with self.subTest(backend=backend):
    j=self.run_turn({'action':'observe'},backend)
    self.assertEqual(j.state,'error');self.assertIn('尚未接入',j.reply);self.assertTrue(j.audio)
 def test_done_action_cannot_claim_phone_result_without_video(self):
  j=self.run_turn({'action':'done','reply':'已找到张三','evidence':'张三'})
  self.assertEqual(j.state,'error');self.assertIn('当前没有执行',j.reply)
 def test_stop_is_spoken(self):
  j=self.run_turn({'action':'stop','reply':'操作已停止'})
  self.assertEqual(j.state,'done');self.assertEqual(j.reply,'操作已停止')
 def test_speech_failure_does_not_claim_spoken_completion(self):
  m=Mailbox();j=m.create('d','a'*16,1)
  def failed(text):raise RuntimeError('tts unavailable')
  Conversation(m,lambda m:{'action':'reply','reply':'测试结果'},failed,lambda *a,**kw:None).run(j,'你好')
  self.assertEqual(j.state,'error');self.assertTrue(j.speech_error);self.assertEqual(j.reply,'测试结果')
 def test_active_turn_survives_expiry_sweep(self):
  now=[0];m=Mailbox(clock=lambda:now[0]);j=m.create('d','a'*16,1);c=Conversation(m,status=lambda *a,**kw:None)
  now[0]=10;c.expire();self.assertFalse(j.cancelled)
  now[0]=46;c.expire();self.assertTrue(j.cancelled)

class AiHidHomeTests(unittest.TestCase):
 def run_home(self,text,enabled='1',receipt='HID_HOME_REPORT_SENT',failure=False):
  m=Mailbox();j=m.create('d','b'*16,1);calls=[]
  def execute(job,command):
   calls.append(command)
   if failure:raise TimeoutError('no acknowledgement')
   return receipt
  m.execute=execute
  with patch.dict('os.environ',{'EPAPER_AI_HID_HOME':enabled}):
   Conversation(m,lambda messages:{'action':'home'},lambda text:b'\1\0'*100,lambda *a,**kw:None).run(j,text)
  return j,calls
 def test_explicit_home_dispatches_only_hid_and_waits_for_human_verification(self):
  j,calls=self.run_home('回到手机桌面')
  self.assertEqual(calls,[{'op':'hid_home'}]);self.assertEqual(j.state,'waiting')
  self.assertIn('没有画面回传',j.reply);self.assertNotIn('已回到桌面',j.reply)
 def test_feature_off_never_dispatches(self):
  j,calls=self.run_home('回到手机桌面',enabled='0');self.assertFalse(calls);self.assertEqual(j.state,'error')
 def test_model_home_does_not_convert_wechat_task_to_blind_navigation(self):
  j,calls=self.run_home('打开微信找到李阳');self.assertFalse(calls);self.assertEqual(j.state,'error')
 def test_missing_or_invalid_receipt_never_claims_report_sent(self):
  for kwargs in ({'failure':True},{'receipt':'queued'}):
   j,calls=self.run_home('返回手机桌面',**kwargs)
   self.assertEqual(j.state,'error');self.assertNotIn('已发出',j.reply);self.assertEqual(len(calls),1)

 def test_negated_home_or_stop_does_not_dispatch_even_if_model_returns_home(self):
  for text in ('不要回到手机桌面','停止返回手机桌面','取消回到手机桌面'):
   j,calls=self.run_home(text);self.assertFalse(calls);self.assertEqual(j.state,'error')
