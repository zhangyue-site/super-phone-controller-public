import hashlib,hmac,json,unittest,time
from test_wechat_nav import frame
from unittest.mock import patch
import test_remote_http as http_tests
from display_service import app_control,remote_http,app_screen
from display_service.app_ota import Authority

class AppControlTests(http_tests.RemoteHttpTests):
 # Keep only App cases; parent supplies the real HTTP server/board harness.
 test_both_origins_real_http_flow_and_scoped_verified_result=None
 test_bridge_auth_unknown_peer_cross_confirmation_and_stop=None
 test_remote_stop_blocks_voice_asr_already_in_flight=None
 def setUp(self):
  super().setUp();self.control_auth=Authority()
  self.ap=patch.object(app_control,'AUTHORITY',self.control_auth);self.ap.start()
  self.frames=patch.object(app_screen,'SEQUENCES',{});self.frames.start()
  self.remote.binding_allowed=remote_http.binding_allowed
 def tearDown(self):
  self.frames.stop();self.ap.stop();super().tearDown()
 def grant(self):
  code,c=self.request('/app-control/challenge',{'device':'epaper-01'});self.assertEqual(code,200)
  proof=hmac.new(b'synthetic-device-only',b'PCFLASH1\nepaper-01\n'+bytes.fromhex(c['challenge']),hashlib.sha256).hexdigest()
  with patch('display_service.firmware.release',return_value=({'sha256':'f'*64,'version':'test','size':100},b'')):
   code,g=self.request('/app-control/authorize',{'device':'epaper-01','challenge':c['challenge'],'proof':proof})
  self.assertEqual(code,200);self.assertEqual(g['scope'],'phone-commands');return g['ticket']
 def command(self,ticket,operation,**kw):
  return self.request('/app-control/command',dict(operation=operation,**kw),extra={'Authorization':'Bearer '+ticket})
 def test_preview_confirm_claim_stop_and_private_result(self):
  ticket=self.grant()
  code,plan=self.command(ticket,'prepare',text='打开微信找到张三');self.assertEqual(code,200);self.assertEqual(plan['state'],'pending');self.assertFalse(self.mailbox.jobs)
  self.assertEqual(plan['reply'].count('请在两分钟内点击'),1)
  self.assertNotIn('/phone',self.command(ticket,'status')[1]['reply'])
  self.assertEqual(self.bridge('confirm',task_id=plan['task_id'])[0],409)
  self.assertEqual(self.command(ticket,'confirm',task_id=plan['task_id'])[1]['state'],'queued')
  self.request('/remote/claim',{'ready':True});self.assertEqual(self.request('/remote/claim',{'ready':True})[1]['op'],'start')
  self.assertEqual(self.command(ticket,'stop')[0],200)
  self.assertEqual(self.request('/remote/status')[1]['op'],'cancelled')
  self.assertEqual(self.command(ticket,'status')[1]['state'],'stopped')
 def test_app_command_verified_visual_hid_result(self):
  ticket=self.grant();_,plan=self.command(ticket,'prepare',text='打开微信找到张三')
  self.command(ticket,'confirm',task_id=plan['task_id']);self.request('/remote/claim',{'ready':True})
  self.assertEqual(self.request('/remote/claim',{'ready':True})[1]['op'],'start')
  commands=[];barrier='';number=0;deadline=time.monotonic()+8
  while time.monotonic()<deadline:
   code,event=self.request('/dialogue/poll');self.assertEqual(code,200)
   op=event['op']
   if op=='done':break
   if op!='wait':
    commands.append(op)
    if op=='hid_home':self.stage=0;output='HID_HOME_REPORT_SENT'
    elif op=='hid_pointer':self.stage+=1;output='HID_POINTER_REPORT_SENT'
    elif op=='type_text':self.stage=3;output='__PC_EXIT_0__'
    else:raise AssertionError(op)
    self.assertEqual(self.request('/dialogue/result',{'id':event['id'],'ok':True,'output':output})[0],200)
   number+=1
   code,img=self.request('/app-screen/frame',frame(self.stage),'screen',{'Content-Type':'image/jpeg','X-Screen-Sequence':str(number),'X-Screen-Barrier':barrier})
   self.assertIn(code,(200,202));barrier=img.get('barrier',barrier);time.sleep(.015)
  else:raise AssertionError('timeout')
  code,result=self.command(ticket,'status');self.assertEqual((code,result['state'],result['verified']),(200,'done',True))
  self.assertEqual(commands,['hid_home','hid_pointer','hid_pointer','type_text'])
  self.assertEqual(self.command(ticket,'save',task_id=plan['task_id'])[0],200)
 def test_scope_expiry_supersession_and_revocation(self):
  ticket=self.grant();_,plan=self.command(ticket,'prepare',text='打开微信找到张三')
  self.assertEqual(self.command(self.ticket,'confirm',task_id=plan['task_id'])[0],403)
  newer=self.grant()
  self.assertEqual(self.command(ticket,'confirm',task_id=plan['task_id'])[0],403)
  self.assertEqual(self.command(newer,'confirm',task_id=plan['task_id'])[0],409)
  self.assertEqual(self.command(newer,'status')[1]['state'],'idle')
  self.assertEqual(self.remote.records[plan['task_id']]['state'],'error')
  self.control_auth.tickets[newer]=(0,'epaper-01','f'*64)
  self.assertEqual(self.command(newer,'status')[0],403)
 def test_no_injected_shell_or_owner(self):
  ticket=self.grant()
  self.assertEqual(self.command(ticket,'prepare',text='adb shell input tap 1 2')[0],409)
  self.assertEqual(self.command(ticket,'confirm')[0],409)
  self.assertEqual(self.command(ticket,'prepare',text='打开微信找到张三',device='other')[0],409)
  self.assertEqual(self.request('/app-control/authorize',{'device':'epaper-01','challenge':'0'*64,'proof':'0'*64})[0],409)
if __name__=='__main__':unittest.main()
