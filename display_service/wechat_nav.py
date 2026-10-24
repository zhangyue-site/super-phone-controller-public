"""Bounded WeChat navigation and explicit per-device verified replay skills."""
from .model_routing import task_model_session
import base64,hashlib,io,json,math,os,re,threading,time,zlib
from pathlib import Path
from PIL import Image
from .wechat_vision import observe
from .skill_engine import SkillStore,WorkflowSpec,ReplayEngine,signature,matches,region,region_matches
WORKFLOW=WorkflowSpec('wechat.search_contact','微信','微信找联系人',('contact',),'wechat.search_results')

def parse_task(text):
 text=re.sub(r"^(回放技能|运行技能)\s*","",text.strip())
 match=re.fullmatch(r"(?:请|帮我)?(?:打开|进入)微信(?:然后|并|，|,)?(?:找到|搜索|查找)([\u4e00-\u9fffA-Za-z0-9·]{1,24})",text)
 if not match or re.search(r"发送|发消息|不要|停止|取消|然后|转账|删除|支付",match[1]):return None
 return match[1]

class ActionFrameChanged(ValueError):
 """Pre-dispatch frame fence rejection; no actuator command was sent."""

class WechatNavigator:
 def __init__(self,mailbox,store,vision=observe,frame_timeout=15):
  self.m=mailbox;self.store=store;self.vision=vision;self.timeout=frame_timeout
 def _log(self,j,stage,**metadata):
  if stage=='dispatch':
   j.state='running';j.reply={'hid_home':'正在回到手机桌面','hid_pointer':'正在定位并点击微信导航','type_text':'正在输入联系人并恢复原输入法'}.get(metadata.get('op'),'正在操作')
  elif stage=='vision' and metadata.get('verify'):j.state='verifying';j.reply='正在核验搜索结果'
  print("WECHAT_NAV "+json.dumps(dict(device=j.device,turn=j.sequence,stage=stage,**metadata),separators=(",",":")),flush=True)
 def _frame(self,j,after=0):
  deadline=time.monotonic()+self.timeout
  while time.monotonic()<deadline:
   with self.m.lock:
    self.m._live(j)
    if j.video and j.video_sequence>after and self.m.clock()-j.video_received<=2:
     if j.video_source!="user-consented-app-screen":raise ValueError("请在App里共享整个手机屏幕")
     if j.video_width>=j.video_height:raise ValueError("请保持手机竖屏并重新共享")
     return j.video,j.video_sequence,signature(j.video)
   time.sleep(.025)
  raise ValueError("未收到新的手机画面，请在App中共享整个屏幕")
 def _observe(self,j,raw,query,verify=False):
  start=time.monotonic();barrier=j.video_barrier;session=j.screen_session
  result=self.vision(raw,query,verify)
  with self.m.lock:
   self.m._live(j)
   if barrier!=j.video_barrier or session!=j.screen_session:raise ValueError("画面会话已经改变")
  confidence=result.get("confidence")
  if type(confidence) not in (int,float) or not math.isfinite(confidence) or confidence<(.95 if verify else .9):raise ValueError("画面识别置信度不足")
  self._log(j,"vision",verify=verify,ms=round((time.monotonic()-start)*1000))
  return result
 def _matches_action_frame(self,expected,sig,current):
  return matches(expected,sig) and ('target' not in expected or region_matches(expected['target'],current))
 def _action(self,j,command,expected):
  self.m._live(j);current,_,sig=self._frame(j)
  if not self._matches_action_frame(expected,sig,current):raise ActionFrameChanged("手机页面已变化，本次停止以避免点错")
  self._log(j,"dispatch",op=command["op"])
  output=self.m.execute(j,command)
  good=("HID_HOME_REPORT_SENT" if command["op"]=="hid_home" else "HID_POINTER_REPORT_SENT" if command["op"]=="hid_pointer" else "__PC_EXIT_0__")
  if output.strip()!=good:raise ValueError("板端没有确认动作完成")
  self._log(j,"receipt",op=command["op"],confirmed=True)
  return dict(j.last_receipt)
 def _command(self,observation,query):
  screen=observation.get("screen")
  if screen=="launcher":target="wechat_app"
  elif screen=="wechat_home":target="global_search"
  elif screen=="wechat_search":
   if observation.get("input_focused") is True:
    return {"op":"type_text","text_b64":base64.b64encode(query.encode()).decode()},"wechat_search"
   target="search_input"
  else:raise ValueError("当前不是支持的微信导航页面")
  bounds=observation.get("bounds")
  if observation.get("target")!=target or not isinstance(bounds,list) or len(bounds)!=4 or any(type(n)!=int for n in bounds):raise ValueError("没有找到可信的导航目标")
  x1,y1,x2,y2=bounds
  if not 0<=x1<x2<=1000 or not 0<=y1<y2<=1000 or x2-x1>(950 if target=='search_input' else 400) or y2-y1>250:raise ValueError("导航坐标超出范围")
  return {"op":"hid_pointer","kind":"click","x":(x1+x2)*32767//2000,"y":(y1+y2)*32767//2000},screen
 @task_model_session
 def run(self,j,query):
  self.store.invalidate(j.device);j.fenced=True
  deadline=time.monotonic()+self.timeout
  while j.pointer_protocol!="absolute-v1" and time.monotonic()<deadline:
   self.m._live(j);time.sleep(.025)
  if j.pointer_protocol!="absolute-v1":raise ValueError("请先升级支持AI鼠标协议的控制板固件")
  raw,seq,sig=self._frame(j)
  geometry=(sig["w"],sig["h"]);entry_receipt=self._action(j,{"op":"hid_home"},sig)
  entry=self.store.find(j.device,WORKFLOW,{"contact":query});cached=entry.get("steps",[]) if entry else []
  trace=[];ai_calls=0;typed=False;last_seq=seq;expected_screen='launcher'
  self._log(j,"start",replay=bool(cached))
  for step in range(8):
   raw,seq,sig=self._frame(j,after=last_seq);last_seq=seq
   if (sig["w"],sig["h"])!=geometry:raise ValueError("共享画面尺寸改变，请重新开始")
   replay_step=ReplayEngine.step({"steps":cached},step,raw)
   if replay_step is not None:
    stored=replay_step
    command,stage=self._command(stored.get("observation",{}),query)
    self._log(j,"cache_hit",step=step)
   else:
    if cached:self._log(j,"cache_miss",step=step)
    cached=[]
    observation=self._observe(j,raw,query);ai_calls+=1
    command,stage=self._command(observation,query)
    stored={"signature":sig,"observation":observation}
    stored["target"]=region(raw,observation["bounds"] if command["op"]=="hid_pointer" else [0,45,1000,250])
   if stored.get('observation',{}).get('screen')!=expected_screen:raise ValueError('页面顺序不符，停止导航')
   trace.append(stored)
   sig["target"]=stored["target"]
   stored["receipt"]=self._action(j,command,sig)
   if command["op"]=="type_text":typed=True;break
   expected_screen='wechat_home' if stage=='launcher' else 'wechat_search'
  if not typed:raise ValueError("微信导航步骤超出限制")
  raw,seq,sig=self._frame(j,after=last_seq)
  if (sig["w"],sig["h"])!=geometry:raise ValueError("共享画面尺寸改变")
  final=self._observe(j,raw,query,verify=True);ai_calls+=1
  if final.get("screen")!="wechat_results" or final.get("result_page") is not True or final.get("query")!=query or not isinstance(final.get("contacts"),list) or query not in final["contacts"]:raise ValueError("未在微信搜索结果页核验到完整联系人姓名")
  for box in (final.get("query_bounds"),final.get("contact_bounds")):
   if not isinstance(box,list) or len(box)!=4 or any(type(v)!=int for v in box) or not 5<=box[2]-box[0]<=400 or not 4<=box[3]-box[1]<=140:raise ValueError("结果姓名定位区域不准确")
  query_region=region(raw,final["query_bounds"]);contact_region=region(raw,final["contact_bounds"])
  latest,_,latest_sig=self._frame(j)
  if not matches(sig,latest_sig) or not region_matches(query_region,latest) or not region_matches(contact_region,latest):raise ValueError("结果页面已变化，请重新核验")
  with self.m.lock:
   self.m._live(j);j.navigation_verified=True;self.store.remember(j,WORKFLOW,{"contact":query},trace,geometry,entry_receipt,{"verified":True,"terminal":WORKFLOW.terminal,"parameters":{"contact":query},"frame":seq})
  self._log(j,"verified",frame=seq,ai_calls=ai_calls,actions=len(trace)+1)
  return "已在微信搜索结果页找到"+query+"，已保留结果页，没有发送消息。"
STORE=SkillStore()
