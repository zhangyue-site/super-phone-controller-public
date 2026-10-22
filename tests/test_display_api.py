import http.client,json,tempfile,threading,unittest,array,secrets
from unittest.mock import patch
from pathlib import Path
from http.server import ThreadingHTTPServer
from display_service import app,control

class DisplayApiTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  root=Path(cls.tmp.name)
  cls.old=(app.CONFIG,app.QUOTAS,control.ROOT)
  app.CONFIG=root/'devices.json';app.QUOTAS=root/'quota';control.ROOT=root/'state'
  app.QUOTAS.mkdir()
  app.CONFIG.write_text(json.dumps({'phone-a':'a'*64,'phone-b':'b'*64}))
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown();cls.server.server_close();cls.thread.join()
  app.CONFIG,app.QUOTAS,control.ROOT=cls.old
  cls.tmp.cleanup()
 def request(self,path,token=None,method='GET',body=None,extra=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
  headers={'Authorization':'Bearer '+token} if token else {}
  if path=='/voice':headers.update({'X-Voice-Session':secrets.token_hex(8),'X-Voice-Sequence':'1'})
  if extra:headers.update(extra)
  c.request(method,path,body=body,headers=headers)
  r=c.getresponse();result=(r.status,r.read());c.close();return result
 def test_anonymous_and_wrong_token_rejected(self):
  self.assertEqual(self.request('/status')[0],401)
  self.assertEqual(self.request('/status','incorrect')[0],401)
 def test_server_originated_state_isolated_by_device(self):
  control.write('phone-a','waiting','等待手机连接')
  a=json.loads(self.request('/status','a'*64)[1])
  b=json.loads(self.request('/status','b'*64)[1])
  self.assertEqual(a['interaction']['task'],'等待手机连接')
  self.assertNotIn('task',b['interaction'])
 def test_stop_does_not_claim_actuator_execution(self):
  status,raw=self.request('/stop','b'*64,'POST')
  self.assertEqual(status,200)
  self.assertEqual(json.loads(raw),{'recorded':True,'actuatorConnected':False})
 def test_fixed_size_monochrome_frame(self):
  status,raw=self.request('/screen.bin','a'*64)
  self.assertEqual(status,200)
  self.assertEqual(len(raw),5000)
 def test_arbitrary_file_routes_not_available(self):
  self.assertEqual(self.request('/../../etc/passwd','a'*64)[0],404)

 def test_voice_auth_and_invalid_audio(self):
  self.assertEqual(self.request('/voice',method='POST',body=b'bad')[0],401)
  self.assertEqual(self.request('/voice','b'*64,'POST',b'bad')[0],422)
 def test_voice_recognizes_without_claiming_execution(self):
  raw=array.array('h',[600,-600]*4000).tobytes()
  with patch.object(app,'recognize',return_value='打开设置'):
   status,body=self.request('/voice','b'*64,'POST',raw)
  self.assertEqual(status,200)
  self.assertFalse(json.loads(body)['actuatorConnected'])
  state=control.read('phone-b')
  self.assertEqual(state['state'],'waiting')
  self.assertIn('打开设置',state['task'])
 def test_stop_wins_over_inflight_recognition(self):
  entered=threading.Event();finish=threading.Event();result=[]
  def recognize(raw):
   entered.set();finish.wait(3);return '迟到的识别'
  raw=array.array('h',[600,-600]*4000).tobytes()
  with patch.object(app,'recognize',side_effect=recognize):
   worker=threading.Thread(target=lambda:result.append(self.request('/voice','b'*64,'POST',raw)))
   worker.start();self.assertTrue(entered.wait(2))
   self.assertEqual(self.request('/stop','b'*64,'POST')[0],200)
   finish.set();worker.join(3)
  self.assertEqual(result[0][0],409)
  self.assertEqual(control.read('phone-b')['state'],'stopped')

 def test_stop_before_upload_admission_rejects_old_recording(self):
  session=secrets.token_hex(8)
  self.assertEqual(self.request('/stop','b'*64,'POST',extra={'X-Voice-Session':session,'X-Voice-Sequence':'2'})[0],200)
  raw=array.array('h',[600,-600]*4000).tobytes()
  with patch.object(app,'recognize') as cloud:
   self.assertEqual(self.request('/voice','b'*64,'POST',raw,{'X-Voice-Session':session,'X-Voice-Sequence':'1'})[0],409)
   cloud.assert_not_called()
  self.assertEqual(control.read('phone-b')['state'],'stopped')
  with patch.object(app,'recognize',return_value='新录音'):
   self.assertEqual(self.request('/voice','b'*64,'POST',raw,{'X-Voice-Session':session,'X-Voice-Sequence':'3'})[0],200)
