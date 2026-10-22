import io,tempfile,threading,time,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from display_service.dialogue import Mailbox
from display_service.wechat_nav import WechatNavigator,SkillStore,parse_task
def frame(stage):
 im=Image.new("RGB",(240,480),["#16202b","#e4e4e4","#fff8e0","#e2ffee"][stage]);d=ImageDraw.Draw(im)
 d.rectangle((20+stage*12,100,90,165),fill=["green","black","red","blue"][stage])
 out=io.BytesIO();im.save(out,format="JPEG");return out.getvalue()
def observation(stage,query="张三"):
 return [{"screen":"launcher","target":"wechat_app","bounds":[80,200,240,360],"confidence":.99},
 {"screen":"wechat_home","target":"global_search","bounds":[820,40,950,140],"confidence":.99},
 {"screen":"wechat_search","input_focused":True,"query":"","confidence":.99},
 {"screen":"wechat_results","query":query,"contacts":[query],"result_page":True,"query_bounds":[10,40,300,100],"contact_bounds":[10,180,400,320],"confidence":.99}][stage]
class NavigationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=SkillStore(Path(self.temp.name));self.calls=[]
 def run_flow(self,replay=False,bad_result=False,cancel_after=None,fail_input=False,cancel_in_vision=False,drop_after_input=False,changed=False,query='张三'):
  m=Mailbox();j=m.create("test-board","a"*16,1);j.pointer_protocol="absolute-v1";j.video_source="user-consented-app-screen"
  stop=threading.Event();commands=[];stage=[0]
  def feed():
   while not stop.is_set() and not j.done and not j.cancelled:
    try:
     cmd=m.poll(j.device,j.session,j.sequence,pointer_protocol="absolute-v1")
     if cmd["op"] not in ("wait","done"):
      commands.append(cmd["op"])
      if cancel_after==len(commands):m.cancel(j.device);continue
      if cmd["op"]=="hid_home":stage[0]=0;output="HID_HOME_REPORT_SENT"
      elif cmd["op"]=="hid_pointer":stage[0]+=1;output="HID_POINTER_REPORT_SENT"
      elif cmd["op"]=="type_text":
       if fail_input:m.ack(j.device,j.session,j.sequence,cmd["id"],False,"","input_failed");continue
       import base64
       self.assertEqual(base64.b64decode(cmd["text_b64"]).decode(),query)
       stage[0]=3;output="__PC_EXIT_0__"
      else:raise AssertionError(cmd)
      m.ack(j.device,j.session,j.sequence,cmd["id"],True,output)
     if drop_after_input and stage[0]==3:continue
     m.ingest_video(j.device,j.session,j.sequence,j.video_sequence+1,frame(stage[0]),"jpeg",expected_barrier=j.video_barrier,source="user-consented-app-screen")
     j.video_source="user-consented-app-screen"
    except ValueError:pass
    time.sleep(.01)
  def vision(raw,query,verify=False):
   self.calls.append(verify);s=stage[0]
   if cancel_in_vision:m.cancel(j.device)
   if verify:return observation(3,"李阳" if bad_result else query)
   return observation(s)
  t=threading.Thread(target=feed);t.start()
  nav=WechatNavigator(m,self.store,vision=vision,frame_timeout=.8)
  try:result=nav.run(j,query);j.done=True;j.state="done"
  finally:stop.set();t.join()
  return result,commands,j
 def test_simulated_full_flow_and_explicit_save_replay_uses_less_ai(self):
  result,commands,j=self.run_flow()
  self.assertEqual(commands,["hid_home","hid_pointer","hid_pointer","type_text"])
  self.assertIn("搜索结果",result);self.assertEqual(len(self.calls),4)
  self.assertFalse(self.store.list("test-board"))
  self.store.save_last("test-board")
  self.assertEqual(self.store.list("test-board")[0]["group"],"微信")
  self.calls.clear();result,commands,j=self.run_flow(replay=True)
  self.assertEqual(len(self.calls),1);self.assertTrue(self.calls[0])
  self.assertNotIn("send",commands)
 def test_wrong_contact_cannot_verify_or_save(self):
  with self.assertRaises(ValueError):self.run_flow(bad_result=True)
  with self.assertRaises(ValueError):self.store.save_last("test-board")
 def test_stop_no_further_action_or_save(self):
  with self.assertRaises(ValueError):self.run_flow(cancel_after=2)
  with self.assertRaises(ValueError):self.store.save_last("test-board")
 def test_failed_chinese_input_never_claims_result_or_saves(self):
  with self.assertRaises(ValueError):self.run_flow(fail_input=True)
  with self.assertRaises(ValueError):self.store.save_last("test-board")
 def test_device_scope_and_unsupported_board(self):
  self.run_flow();self.store.save_last("test-board");self.assertEqual(self.store.list("other"),[])
  m=Mailbox();j=m.create("old","a"*16,1)
  with self.assertRaises(ValueError):WechatNavigator(m,self.store,vision=lambda *a:None,frame_timeout=.05).run(j,"张三")
 def test_task_parser_never_accepts_message_or_unrelated_actions(self):
  self.assertEqual(parse_task("打开微信找到张三"),"张三")
  self.assertEqual(parse_task("回放技能 打开微信找到张三"),"张三")
  for text in ["给张三发送你好","打开微信找到张三然后发消息","不要打开微信找到张三","打开支付宝"]:
   self.assertIsNone(parse_task(text))

 def test_stop_during_model_response_cannot_emit_next_command(self):
  with self.assertRaises(ValueError):self.run_flow(cancel_in_vision=True)
  with self.assertRaises(ValueError):self.store.save_last("test-board")
 def test_no_fresh_capture_after_chinese_input_fails_without_skill(self):
  with self.assertRaises(ValueError):self.run_flow(drop_after_input=True)
  with self.assertRaises(ValueError):self.store.save_last("test-board")
 def test_failed_terminal_state_is_not_saved(self):
  _,_,j=self.run_flow();j.state="error"
  with self.assertRaises(ValueError):self.store.save_last("test-board")

 def test_target_change_forces_vision_even_when_small_scene_hash_matches(self):
  from display_service.wechat_nav import signature,matches,region,region_matches
  im=Image.new("RGB",(600,1200),"white")
  before=io.BytesIO();im.save(before,format="JPEG")
  ImageDraw.Draw(im).rectangle((50,100,55,110),fill="black")
  after=io.BytesIO();im.save(after,format="JPEG")
  self.assertTrue(matches(signature(before.getvalue()),signature(after.getvalue())))
  self.assertFalse(region_matches(region(before.getvalue(),[70,70,110,110]),after.getvalue()))

 def test_specialized_skill_rebinds_contact_instead_of_replaying_old_name(self):
  self.run_flow();self.store.save_last("test-board")
  self.calls.clear();result,commands,j=self.run_flow(query="李华")
  self.assertEqual(len(self.calls),1);self.assertIn("李华",result)
  self.assertNotIn("张三",result)
