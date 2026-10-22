import io,json,hmac,hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from display_service import app_screen
from display_service.app_ota import Authority
from display_service.dialogue import Mailbox
class Handler:
 command='POST'
 def __init__(self,path,data=b'',ticket='',seq='1'):
  self.path=path;self.rfile=io.BytesIO(data);self.headers={'Content-Length':str(len(data)),'Content-Type':'image/jpeg','X-Screen-Sequence':seq,'Authorization':'Bearer '+ticket}
 def reply(self,code,body,kind=None):self.code=code;self.body=json.loads(body)
class ScreenTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.config=Path(self.temp.name)/'config';self.config.write_text(json.dumps({'test-board':'synthetic-key'}));self.auth=Authority();self.patch=patch.object(app_screen,'AUTHORITY',self.auth);self.patch.start();app_screen.SEQUENCES.clear()
 def tearDown(self):self.patch.stop();self.temp.cleanup()
 def grant(self):
  c=self.auth.challenge('test-board',{'test-board':'synthetic-key'});proof=hmac.new(b'synthetic-key',b'PCFLASH1\ntest-board\n'+bytes.fromhex(c['challenge']),hashlib.sha256).hexdigest()
  with patch('display_service.app_ota.firmware.release',return_value=({'version':'test','size':4096,'sha256':'a'*64},b'')):
   h=Handler('/app-screen/authorize',json.dumps(dict(device='test-board',challenge=c['challenge'],proof=proof)).encode());app_screen.handle(h,self.config)
  self.assertEqual(h.code,200);self.assertEqual(h.body['scope'],'screen-frames');self.assertNotIn('sha256',h.body);return h.body['ticket']
 def test_no_device_bearer_in_capability_response(self):self.grant()
 def test_firmware_ticket_cannot_upload_frames(self):
  h=Handler('/app-screen/frame',b'fake','a'*43);app_screen.handle(h,self.config);self.assertEqual(h.code,403)
 def test_no_active_task_drops_frame(self):
  ticket=self.grant()
  with patch.object(app_screen.CONVERSATION,'mailbox',Mailbox()):
   h=Handler('/app-screen/frame',b'fake',ticket);app_screen.handle(h,self.config);self.assertEqual(h.code,202);self.assertFalse(h.body["accepted"]);self.assertRegex(h.body["barrier"],r"^[0-9a-f]{32}$")
 def test_replayed_frame_rejected(self):
  ticket=self.grant()
  with patch.object(app_screen.CONVERSATION,'mailbox',Mailbox()):
   for code in (202,403):
    h=Handler('/app-screen/frame',b'fake',ticket);app_screen.handle(h,self.config);self.assertEqual(h.code,code)
 def test_stop_revokes_ticket_and_cancels_active_task(self):
  ticket=self.grant();m=Mailbox();j=m.create('test-board','a'*16,1)
  with patch.object(app_screen.CONVERSATION,'mailbox',m):
   h=Handler('/app-screen/stop',ticket=ticket);app_screen.handle(h,self.config);self.assertEqual(h.code,200);self.assertTrue(j.cancelled)
  with self.assertRaises(ValueError):app_screen.subject(ticket)
 def test_expired_ticket_rejected(self):
  ticket=self.grant();self.auth.clock=lambda:10**15
  with self.assertRaises(ValueError):app_screen.subject(ticket)
 def test_active_task_accepts_real_jpeg_without_phone_actions(self):
  from PIL import Image
  out=io.BytesIO();Image.new('RGB',(64,128)).save(out,format='JPEG');ticket=self.grant();m=Mailbox();j=m.create('test-board','b'*16,1)
  with patch.object(app_screen.CONVERSATION,'mailbox',m):
   h=Handler('/app-screen/frame',out.getvalue(),ticket);app_screen.handle(h,self.config);self.assertEqual(h.code,200);self.assertTrue(j.video);self.assertFalse(h.body['phone_execution'])
 def test_revoked_during_body_read_cannot_bind_new_task(self):
  ticket=self.grant();m=Mailbox();j=m.create('test-board','c'*16,1)
  h=Handler('/app-screen/frame',b'fake',ticket)
  def read(size):
   self.auth.tickets.pop(ticket,None)
   return b'fake'
  h.rfile.read=read
  with patch.object(app_screen.CONVERSATION,'mailbox',m):app_screen.handle(h,self.config)
  self.assertEqual(h.code,403);self.assertFalse(j.video);self.assertFalse(j.screen_session)
 def test_stale_stop_does_not_cancel_new_task(self):
  ticket=self.grant();m=Mailbox();j=m.create('test-board','d'*16,1)
  def revoked_subject(value):
   self.auth.tickets.pop(value,None)
   return 'test-board'
  with patch.object(app_screen.CONVERSATION,'mailbox',m),patch.object(app_screen,'subject',revoked_subject):
   h=Handler('/app-screen/stop',ticket=ticket);app_screen.handle(h,self.config)
  self.assertEqual(h.code,403);self.assertFalse(j.cancelled)
if __name__=='__main__':unittest.main()
