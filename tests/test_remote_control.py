import tempfile,threading,unittest
from pathlib import Path
from display_service.dialogue import Mailbox
from display_service.remote_control import RemoteControl
class FakeConversation:
 def __init__(self):self.mailbox=Mailbox();self.started=[]
 def start(self,device,session,sequence,text):
  self.started.append(text);return self.mailbox.create(device,session,sequence)
class RemoteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=FakeConversation();self.now=[100.];self.path=Path(self.tmp.name)/'state.json';self.r=RemoteControl(self.c,self.path,clock=lambda:self.now[0],screen_ready=lambda d:True)
  self.lease=None;self.counter=0
  self.wx=('openclaw-weixin','owner-wx','owner-wx','board');self.tg=('telegram','owner-tg','owner-tg','board')
 def tearDown(self):self.tmp.cleanup()
 def prepare(self,owner=None):return self.r.prepare(owner or self.wx,'打开微信找到张三')['task_id']
 def claim(self,seq=None):
  self.counter=seq if seq is not None else self.counter+1
  if self.lease is None:self.lease=self.r.claim('board','a'*16,self.counter,False,'absolute-v1')['lease']
  return self.r.claim('board','a'*16,self.counter,True,'absolute-v1',self.lease)
 def test_prepare_and_cross_channel_confirm_never_dispatch(self):
  ident=self.prepare();self.assertEqual(self.c.started,[])
  with self.assertRaises(ValueError):self.r.confirm(self.tg,ident)
  self.assertEqual(self.claim()['op'],'wait');self.assertEqual(self.c.started,[])
 def test_confirm_claim_exactly_once_and_two_channels_share_device_lock(self):
  ident=self.prepare();self.r.confirm(self.wx,ident);self.r.confirm(self.wx,ident)
  other=self.prepare(self.tg)
  with self.assertRaises(ValueError):self.r.confirm(self.tg,other)
  out=self.claim();self.assertEqual(out['op'],'start');self.assertEqual(out['task_id'],ident)
  self.assertEqual(self.claim(2)['op'],'wait');self.assertEqual(len(self.c.started),1)
 def test_pending_and_queued_expire_without_execution(self):
  ident=self.prepare();self.now[0]+=121
  with self.assertRaises(ValueError):self.r.confirm(self.wx,ident)
  ident=self.prepare();self.r.confirm(self.wx,ident);self.now[0]+=61
  self.assertEqual(self.claim()['op'],'wait');self.assertEqual(self.c.started,[])
 def test_stop_before_claim_and_during_running(self):
  ident=self.prepare();self.r.confirm(self.wx,ident);self.r.stop(self.tg)
  self.assertEqual(self.claim()['op'],'wait')
  ident=self.prepare();self.r.confirm(self.wx,ident);self.claim(2);j=self.c.mailbox.jobs['board'];self.r.stop(self.tg)
  self.assertTrue(j.cancelled);self.assertEqual(self.r.board_status('board','a'*16,2)['op'],'cancelled')
  self.assertEqual(self.r.status(self.wx,ident)['state'],'stopped')
 def test_result_only_origin_and_only_verified_done_is_success(self):
  ident=self.prepare();self.r.confirm(self.wx,ident);self.claim();j=self.c.mailbox.jobs['board'];j.done=True;j.state='done';j.reply='找到了';j.navigation_verified=True
  self.assertEqual(self.r.status(self.wx,ident)['state'],'done');self.assertTrue(self.r.status(self.wx,ident)['verified'])
  with self.assertRaises(ValueError):self.r.status(self.tg,ident)
 def test_unverified_done_and_failed_are_not_success(self):
  ident=self.prepare();self.r.confirm(self.wx,ident);self.claim();j=self.c.mailbox.jobs['board'];j.done=True;j.state='done';j.reply='fake'
  self.assertEqual(self.r.status(self.wx,ident)['state'],'error')
 def test_no_start_without_hid_protocol_ready_or_screen(self):
  ident=self.prepare();self.r.confirm(self.wx,ident)
  self.assertEqual(self.r.claim('board','a'*16,1,False,'absolute-v1')['op'],'wait')
  self.assertEqual(self.r.claim('board','a'*16,1,True,'old')['op'],'wait')
  self.r.screen_ready=lambda _:False;self.assertEqual(self.claim()['op'],'wait');self.assertFalse(self.c.started)
 def test_restart_never_replays_confirmed_plan(self):
  ident=self.prepare();self.r.confirm(self.wx,ident)
  other=RemoteControl(self.c,self.path,clock=lambda:self.now[0],screen_ready=lambda _:True)
  self.assertEqual(other.claim('board','a'*16,1,True,'absolute-v1')['op'],'wait');self.assertEqual(other.status(self.wx,ident)['state'],'error')
 def test_voice_conflict_and_concurrent_confirm(self):
  ident=self.prepare();self.r.confirm(self.wx,ident);self.c.start('board','b'*16,1,'ordinary voice')
  self.assertEqual(self.claim()['op'],'wait');self.assertEqual(len(self.c.started),1)
 def test_replace_pending_invalidates_old_and_rejects_unsupported(self):
  old=self.prepare();new=self.prepare()
  with self.assertRaises(ValueError):self.r.confirm(self.wx,old)
  with self.assertRaises(ValueError):self.r.prepare(self.wx,'发消息给张三')
  self.assertNotEqual(old,new)
 def test_inflight_asr_rejected_and_stop_invalidates_voice_generation(self):
  busy=[True];cancelled=[];self.r.voice_busy=lambda _:busy[0];self.r.cancel_voice=lambda d:cancelled.append(d)
  ident=self.prepare()
  with self.assertRaises(ValueError):self.r.confirm(self.wx,ident)
  busy[0]=False;self.r.confirm(self.wx,ident);busy[0]=True
  self.assertEqual(self.claim()['op'],'wait');self.assertFalse(self.c.started)
  self.r.stop(self.wx);self.assertEqual(cancelled,['board'])
 def test_stale_claim_sequence_and_old_boot_lease_cannot_execute(self):
  self.claim(10);old=self.lease
  ident=self.prepare();self.r.confirm(self.wx,ident)
  self.assertEqual(self.r.claim('board','a'*16,9,True,'absolute-v1',old)['op'],'wait');self.assertFalse(self.c.started)
  lease=self.r.claim('board','b'*16,1,False,'absolute-v1')['lease']
  self.assertEqual(self.r.claim('board','b'*16,2,False,'absolute-v1',lease)['op'],'wait')
  self.assertEqual(self.r.claim('board','a'*16,11,True,'absolute-v1',old)['op'],'wait');self.assertFalse(self.c.started)
  self.assertEqual(self.r.claim('board','b'*16,3,True,'absolute-v1',lease)['op'],'start')
 def test_revoking_binding_cancels_queued_and_running_task(self):
  ident=self.prepare();self.r.confirm(self.wx,ident);self.r.binding_allowed=lambda _:False
  self.assertEqual(self.claim()['op'],'wait');self.assertEqual(self.r.status(self.wx,ident)['state'],'error');self.assertFalse(self.c.started)
  self.r.binding_allowed=lambda _:True;ident=self.prepare();self.r.confirm(self.wx,ident);self.claim();self.r.binding_allowed=lambda _:False
  self.assertEqual(self.r.board_status('board','a'*16,self.counter)['op'],'cancelled');self.assertTrue(self.c.mailbox.jobs['board'].cancelled)
 def test_two_channel_confirmation_race_has_only_one_winner(self):
  a=self.prepare();b=self.prepare(self.tg);barrier=threading.Barrier(3);results=[]
  def confirm(owner,ident):
   barrier.wait()
   try:self.r.confirm(owner,ident);results.append('ok')
   except ValueError:results.append('busy')
  threads=[threading.Thread(target=confirm,args=p) for p in ((self.wx,a),(self.tg,b))]
  for t in threads:t.start()
  barrier.wait()
  for t in threads:t.join()
  self.assertCountEqual(results,['ok','busy']);self.assertEqual(self.claim()['op'],'start');self.assertEqual(len(self.c.started),1)
 def test_physical_stop_cancels_queue_before_first_handshake(self):
  ident=self.prepare();self.r.confirm(self.wx,ident)
  first=self.r.claim('board','a'*16,1,False,'absolute-v1')
  self.r.stop_board('board','a'*16,2)
  self.assertEqual(self.r.claim('board','a'*16,3,True,'absolute-v1',first['lease'])['op'],'wait');self.assertFalse(self.c.started)
  self.assertEqual(self.r.status(self.wx,ident)['state'],'stopped')
 def test_screen_snapshot_never_holds_mailbox_lock(self):
  available=[]
  def screen(_):
   result=[]
   def probe():
    acquired=self.c.mailbox.lock.acquire(timeout=.2);result.append(acquired)
    if acquired:self.c.mailbox.lock.release()
   thread=threading.Thread(target=probe);thread.start();thread.join();available.extend(result);return True
  self.r.screen_ready=screen;self.claim();self.assertTrue(all(available))
 def test_reboot_stop_before_any_new_heartbeat_cancels_queued(self):
  self.claim();ident=self.prepare();self.r.confirm(self.wx,ident)
  self.r.stop_board('board','b'*16,1)
  lease=self.r.claim('board','b'*16,2,True,'absolute-v1')['lease']
  self.assertEqual(self.r.claim('board','b'*16,3,True,'absolute-v1',lease)['op'],'wait');self.assertFalse(self.c.started)
  self.assertEqual(self.r.status(self.wx,ident)['state'],'stopped')
 def test_idle_status_is_readable_on_both_origins(self):
  for owner in (self.wx,self.tg):self.assertEqual(self.r.status(owner)['state'],'idle')
if __name__=='__main__':unittest.main()
