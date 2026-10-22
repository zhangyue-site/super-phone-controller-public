"""Real HTTP confirmation->mailbox->synthetic HID/input->fresh visual result."""
import http.client,json,tempfile,threading,time,unittest,subprocess,re
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from display_service import app,app_screen,remote_http
from display_service.app_ota import Authority
from display_service.dialogue import Mailbox
from display_service.conversation import Conversation
from display_service.remote_control import RemoteControl
from display_service.wechat_nav import SkillStore,WechatNavigator
from test_wechat_nav import frame,observation
class RemoteHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.owner={'channel':'openclaw-weixin','sender':'synthetic@im.wechat','conversation':'["wx-account","synthetic@im.wechat"]','device':'epaper-01'};self.tg=dict(self.owner,channel='telegram',sender='123456789',conversation='["default","123456789"]')
  self.token='b'*48;self.config=self.root/'bridge.json';self.config.write_text(json.dumps({'token':self.token,'bindings':[self.owner,self.tg]}));self.devices=self.root/'devices.json';self.devices.write_text(json.dumps({'epaper-01':'synthetic-device-only'}))
  self.lease='';self.claim_sequence=0;self.turn=1
  self.stage=0;self.calls=[];self.mailbox=Mailbox();self.skills=SkillStore(self.root/'skills')
  def vision(raw,query,verify=False):self.calls.append(verify);return observation(3 if verify else self.stage)
  nav=WechatNavigator(self.mailbox,self.skills,vision=vision,frame_timeout=2)
  self.c=Conversation(self.mailbox,model=lambda _:(_ for _ in ()).throw(AssertionError('wrong runner')),tts=lambda _:b'\x01\x02'*100,status=lambda *a:None,navigator=nav,skills=self.skills)
  self.auth=Authority();self.ticket='s'*43;self.auth.tickets[self.ticket]=(self.auth.clock()+300,'epaper-01','f'*64)
  self.remote=RemoteControl(self.c,self.root/'remote.json',screen_ready=lambda _:True)
  self.remote.runtime_lock=app.LOCK;self.remote.voice_busy=lambda d:d in app.VOICE_BUSY;self.remote.cancel_voice=app._remote_cancel_voice;self.remote.turn_allowed=lambda d,s,q:q>app.VOICE_CANCELLED.get(d,{}).get(s,0)
  self.patches=[patch.object(app,'VOICE_BUSY',set()),patch.object(app,'VOICE_GENERATION',{}),patch.object(app,'VOICE_CANCELLED',{}),patch.dict('os.environ',{'EPAPER_REMOTE_CONTROL':'1','EPAPER_WECHAT_NAV':'1'}),patch.object(app,'CONFIG',self.devices),patch.object(app,'CONVERSATION',self.c),patch.object(app_screen,'CONVERSATION',self.c),patch.object(app_screen,'AUTHORITY',self.auth),patch.object(app_screen,'STORE',self.skills),patch.object(remote_http,'REMOTE',self.remote),patch.object(remote_http,'CONFIG',self.config),patch.object(app,'write_interaction',lambda *a:None)]
  for p in self.patches:p.start()
  self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
 def tearDown(self):
  self.mailbox.cancel('epaper-01');self.server.shutdown();self.thread.join();self.server.server_close()
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def request(self,path,obj=None,kind='board',extra=None):
  data=obj if isinstance(obj,bytes) else json.dumps(obj).encode() if obj is not None else b''
  headers={'Authorization':'Bearer '+(self.token if kind=='bridge' else self.ticket if kind=='screen' else 'synthetic-device-only'),'X-Voice-Session':'a'*16,'X-Voice-Sequence':str(self.turn),'X-HID-Pointer':'absolute-v1'}
  if path=='/remote/claim':
   self.claim_sequence+=1;headers['X-Voice-Sequence']=str(self.claim_sequence);headers['X-Remote-Lease']=self.lease
  if isinstance(obj,bytes):data=obj
  if extra:headers.update(extra)
  conn=http.client.HTTPConnection(*self.server.server_address,timeout=4);conn.request('POST',path,data,headers);r=conn.getresponse();out=(r.status,json.loads(r.read()));conn.close()
  if path=='/remote/claim':
   self.lease=out[1].get('lease',self.lease)
   if out[1].get('op')=='start':self.turn=self.claim_sequence
  return out
 def bridge(self,op,owner=None,**values):return self.request('/bridge/phone',dict(owner or self.owner,operation=op,**values),'bridge')
 def adapter(self,args='',owner=None,poll=False):
  owner=owner or self.owner;account,peer=json.loads(owner['conversation'])
  ctx=dict(channel=owner['channel'],channelId=owner['channel'],senderId=owner['sender'],from_=peer,to=peer,accountId=account,isAuthorizedSender=True,args=args)
  ctx['from']=ctx.pop('from_')
  value=dict(base='http://127.0.0.1:'+str(self.server.server_address[1]),config=dict(token=self.token,bindings=[self.owner,self.tg]),statePath=str(self.root/'watchers.json'),ctx=ctx,poll=poll)
  p=subprocess.run(['node',str(Path(__file__).resolve().parents[1]/'integrations/openclaw-phone/http-harness.mjs')],input=json.dumps(value),capture_output=True,text=True,timeout=15,check=True)
  return json.loads(p.stdout)
 def test_both_origins_real_http_flow_and_scoped_verified_result(self):
  for owner in (self.owner,self.tg):
   with self.subTest(channel=owner['channel']):
    self.stage=0;plan=self.adapter('打开微信找到张三',owner)['result'];ident=re.search('[a-f0-9]{32}',plan['text']).group()
    self.assertFalse(self.mailbox.jobs);self.assertEqual(self.request('/remote/claim',{'ready':True})[1]['op'],'wait')
    confirmed=self.adapter('确认 '+ident,owner)['result'];self.assertIn('已确认',confirmed['text'])
    code,claim=self.request('/remote/claim',{'ready':True});self.assertEqual(code,200);self.assertEqual(claim['op'],'start')
    self.assertEqual(self.request('/remote/claim',{'ready':True})[1]['op'],'wait')
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
    code,result=self.bridge('status',owner,task_id=ident);self.assertEqual((code,result['state'],result['verified']),(200,'done',True));self.assertEqual(commands,['hid_home','hid_pointer','hid_pointer','type_text'])
    feedback=self.adapter(poll=True)['messages'];self.assertEqual(len(feedback),1);self.assertEqual(feedback[0]['channel'],owner['channel']);self.assertEqual(feedback[0]['conversation'],owner['conversation']);self.assertIn('张三',feedback[0]['text'])
    other=self.tg if owner==self.owner else self.owner
    self.assertEqual(self.bridge('status',other,task_id=ident)[0],409)
    self.assertEqual(self.bridge('save',owner,task_id=ident)[0],200)
    self.mailbox.jobs.clear();self.mailbox.high.clear();app_screen.SEQUENCES.clear()
 def test_bridge_auth_unknown_peer_cross_confirmation_and_stop(self):
  self.assertEqual(self.request('/bridge/phone',dict(self.owner,operation='prepare',text='打开微信找到张三'))[0],403)
  self.assertEqual(self.bridge('prepare',dict(self.owner,sender='stranger'),text='打开微信找到张三')[0],403)
  plan=self.adapter('打开微信找到张三')['result'];ident=re.search('[a-f0-9]{32}',plan['text']).group()
  self.assertEqual(self.bridge('confirm',self.tg,task_id=ident)[0],409)
  self.assertEqual(self.request('/remote/claim',{'ready':True})[1]['op'],'wait')
  self.adapter('确认 '+ident);self.request('/remote/claim',{'ready':True})
  self.assertIn('停止',self.adapter('停止',self.tg)['result']['text'])
  messages=self.adapter(poll=True)['messages'];self.assertEqual(len(messages),1);self.assertEqual(messages[0]['channel'],self.owner['channel']);self.assertIn('停止',messages[0]['text'])
  self.assertEqual(self.request('/remote/status')[1]['op'],'cancelled');self.assertEqual(self.bridge('status',task_id=ident)[1]['state'],'stopped')
 def test_remote_stop_blocks_voice_asr_already_in_flight(self):
  import array
  entered=threading.Event();release=threading.Event();out=[]
  def recognize(raw):entered.set();release.wait(3);return '打开微信找到张三'
  with patch.object(app,'recognize',recognize):
   t=threading.Thread(target=lambda:out.append(self.request('/voice',array.array('h',[600,-600]*4000).tobytes(),extra={'X-Voice-Dialogue':'1'})));t.start()
   try:
    self.assertTrue(entered.wait(2));_,plan=self.bridge('prepare',text='打开微信找到张三')
    self.assertEqual(self.bridge('confirm',task_id=plan['task_id'])[0],409)
    self.assertEqual(self.bridge('stop')[0],200)
   finally:release.set();t.join(4)
  self.assertEqual(out[0][0],409);self.assertFalse(self.mailbox.jobs)
if __name__=='__main__':unittest.main()
