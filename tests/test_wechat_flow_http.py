"""Synthetic HTTP end-to-end: App frames, real mailbox, simulated board only."""
import array,http.client,json,tempfile,threading,time,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from display_service import app,app_screen
from display_service.app_ota import Authority
from display_service.conversation import Conversation
from display_service.dialogue import Mailbox
from display_service.wechat_nav import SkillStore,WechatNavigator
from test_wechat_nav import frame,observation

class WechatHttpTests(unittest.TestCase):
 def test_voice_to_hid_to_chinese_to_verified_result_and_voice_save(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);config=root/"devices.json";config.write_text(json.dumps({"sim-board":"synthetic-only"}))
   mailbox=Mailbox();store=SkillStore(root/"skills");stage=[0];calls=[]
   def vision(raw,query,verify=False):calls.append(verify);return observation(3 if verify else stage[0])
   nav=WechatNavigator(mailbox,store,vision=vision,frame_timeout=2)
   def forbidden(_):raise AssertionError("Wechat task must use bounded navigator, not text tools")
   conversation=Conversation(mailbox,model=forbidden,tts=lambda _:b"\0\1"*100,status=lambda *a:None,navigator=nav,skills=store)
   authority=Authority();ticket="t"*43;authority.tickets[ticket]=(authority.clock()+300,"sim-board","a"*64)
   server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
   session="e"*16;turn=1;commands=[];barrier="";frame_number=0
   def request(path,body=b"",screen=False,extra=None):
    conn=http.client.HTTPConnection(*server.server_address,timeout=3)
    headers={"Authorization":"Bearer "+(ticket if screen else "synthetic-only"),"X-Voice-Session":session,"X-Voice-Sequence":str(turn),"X-HID-Pointer":"absolute-v1"}
    if extra:headers.update(extra)
    conn.request("POST",path,body,headers);response=conn.getresponse();status=response.status;raw=response.read();conn.close()
    return status,json.loads(raw)
   try:
    with patch.dict("os.environ",{"EPAPER_WECHAT_NAV":"1"}),patch.object(app,"CONFIG",config),patch.object(app,"CONVERSATION",conversation),patch.object(app_screen,"CONVERSATION",conversation),patch.object(app_screen,"AUTHORITY",authority),patch.object(app_screen,"STORE",store),patch.object(app,"recognize",lambda _:"打开微信找到张三"),patch.object(app,"write_interaction",lambda *a:None):
     status,_=request("/voice",array.array("h",[600,-600]*4000).tobytes(),extra={"X-Voice-Dialogue":"1"});self.assertEqual(status,200)
     until=time.monotonic()+8
     while time.monotonic()<until:
      status,result=request("/dialogue/poll");self.assertEqual(status,200)
      op=result["op"]
      if op=="done":break
      if op!="wait":
       commands.append(op)
       if op=="hid_home":stage[0]=0;output="HID_HOME_REPORT_SENT"
       elif op=="hid_pointer":stage[0]+=1;output="HID_POINTER_REPORT_SENT"
       elif op=="type_text":stage[0]=3;output="__PC_EXIT_0__"
       else:raise AssertionError("Forbidden command "+op)
       status,_=request("/dialogue/result",json.dumps({"id":result["id"],"ok":True,"output":output}).encode());self.assertEqual(status,200)
      frame_number+=1
      status,response=request("/app-screen/frame",frame(stage[0]),screen=True,extra={"Content-Type":"image/jpeg","X-Screen-Sequence":str(frame_number),"X-Screen-Barrier":barrier})
      self.assertIn(status,(200,202))
      barrier=response.get("barrier",barrier)
      time.sleep(.015)
     self.assertEqual(result.get("op"),"done");self.assertEqual(result["state"],"done")
     self.assertIn("搜索结果页",result["reply"]);self.assertIn("没有发送消息",result["reply"])
     self.assertEqual(commands,["hid_home","hid_pointer","hid_pointer","type_text"])
     self.assertEqual(len(calls),4)
     status,_=request("/app-screen/status",screen=True);self.assertEqual(status,200)
     turn=2
     status,_=request("/dialogue/text",json.dumps({"text":"存为技能"}).encode());self.assertEqual(status,200)
     until=time.monotonic()+2
     while time.monotonic()<until:
      _,result=request("/dialogue/poll")
      if result["op"]=="done":break
      time.sleep(.01)
     self.assertEqual(result["state"],"done");self.assertEqual(store.list("sim-board")[0]["group"],"微信")
   finally:server.shutdown();server.server_close();thread.join()

 def test_receipt_rotates_capture_barrier_and_blocks_old_frame(self):
  m=Mailbox();j=m.create("sim-board","a"*16,1);j.fenced=True
  m.offer(j,{"op":"type_text","text_b64":"5p2O5rSL"});cmd=m.poll(j.device,j.session,j.sequence);before=j.video_barrier
  m.ack(j.device,j.session,j.sequence,cmd["id"],True,"__PC_EXIT_0__")
  self.assertNotEqual(j.video_barrier,before);self.assertFalse(j.video)

 def test_old_capture_cannot_cross_ack_between_handler_and_decoder(self):
  import io
  m=Mailbox();j=m.create("sim-board","f"*16,1);j.fenced=True
  m.offer(j,{"op":"type_text","text_b64":"5p2O5rSL"});command=m.poll(j.device,j.session,j.sequence);old=j.video_barrier
  auth=Authority();ticket="u"*43;auth.tickets[ticket]=(auth.clock()+300,j.device,"a"*64)
  raw=frame(2)
  class Handler:
   path="/app-screen/frame";command="POST"
   headers={"Content-Length":str(len(raw)),"Content-Type":"image/jpeg","Authorization":"Bearer "+ticket,"X-Screen-Sequence":"1","X-Screen-Barrier":old}
   rfile=io.BytesIO(raw)
   def reply(self,code,body,kind=None):self.code=code
  original=m.ingest_video
  def delayed(*args,**kwargs):
   m.ack(j.device,j.session,j.sequence,command["id"],True,"__PC_EXIT_0__")
   return original(*args,**kwargs)
  handler=Handler()
  with patch.object(app_screen,"AUTHORITY",auth),patch.object(app_screen.CONVERSATION,"mailbox",m),patch.object(m,"ingest_video",delayed):
   app_screen.handle(handler,Path("/unused"))
  self.assertEqual(handler.code,403);self.assertFalse(j.video);self.assertNotEqual(j.video_barrier,old)
