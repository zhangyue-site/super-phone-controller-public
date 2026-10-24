from .model_routing import task_model_session
"""App-independent screenshot navigation using the established mailbox fences."""
import base64,re,time,json
from .wechat_nav import WechatNavigator
from .dialogue import PhoneCommandError
from .skill_engine import WorkflowSpec,region,matches,region_matches
from .general_vision import observe
from .dialogue import DENY
WORKFLOW=WorkflowSpec('general.navigate','通用','画面导航',('task',),'general.verified')
def parse_task(text):
 from .store_policy import enabled
 if enabled(text):return text
 if not isinstance(text,str) or not 1<=len(text)<=120 or re.search(r'下载|发送|发消息|转账|支付|付款|删除|卸载|购买|下单|发布|评论|点赞|授权|安装|adb|shell|https?://|[`;$<>\\\n\r]',text,re.I):return None
 return text.strip() if re.fullmatch(r'(?:请|帮我)?(?:打开|进入|搜索|查找|找到|返回|回到).{1,100}',text.strip()) else None
def verification_region(raw,bounds):
 # Final evidence may cover the whole screen. System clock/network counters
 # are not the application result and already excluded by signature().
 if not isinstance(bounds,list) or len(bounds)!=4 or any(type(v)!=int for v in bounds):raise ValueError('结果区域无效')
 x1,y1,x2,y2=bounds
 if not 0<=x1<x2<=1000 or not 0<=y1<y2<=1000:raise ValueError('结果区域无效')
 clipped=[x1,max(y1,45),x2,min(y2,950)]
 if clipped[1]>=clipped[3]:raise ValueError('结果依据只有系统状态栏')
 return region(raw,clipped)

class GeneralNavigator(WechatNavigator):
 def __init__(self,mailbox,store,vision=observe,frame_timeout=15):super().__init__(mailbox,store,vision,frame_timeout)
 def _log(self,j,stage,**metadata):
  if stage=='dispatch':
   j.state='running';j.reply={'hid_home':'正在回到手机桌面','hid_pointer':'正在按画面定位导航目标','type_text':'正在输入搜索词并恢复原输入法'}.get(metadata.get('op'),'正在导航')
  elif stage=='vision' and metadata.get('verify'):j.state='verifying';j.reply='正在独立核验目标画面'
  print("GENERAL_NAV "+json.dumps(dict(device=j.device,turn=j.sequence,stage=stage,**metadata),separators=(",",":")),flush=True)
 def _action(self,j,command,sig):
  try:return super()._action(j,command,sig)
  except PhoneCommandError as e:
   # input_failed means the HID report never reached the USB endpoint:
   # resubmitting once is safe (firmware dedupes by command id).
   if e.code!='input_failed' or command.get('op') not in ('hid_pointer','hid_home'):raise
   self._log(j,'input_retry',op=command.get('op'))
   return super()._action(j,command,sig)
 def _command(self,o,task):
  action=o.get('action')
  label=o.get('target_label')
  if not isinstance(label,str) or not label.strip() or len(label)>120 or DENY.search(label):raise ValueError('导航目标标签无法确认或属于受限动作')
  if o.get('safe') is not True:raise ValueError('画面目标不属于安全导航范围')
  box=o.get('bounds')
  if not isinstance(box,list) or len(box)!=4 or any(type(v)!=int for v in box):raise ValueError('导航目标缺少坐标')
  x1,y1,x2,y2=box
  if not 0<=x1<x2<=1000 or not 0<=y1<y2<=1000 or x2-x1>950 or y2-y1>400:raise ValueError('导航目标区域无效')
  if action=='type_text':
   text=o.get('text')
   if not isinstance(text,str) or not 1<=len(text)<=60 or text not in task or o.get('input_focused') is not True or o.get('input_role')!='search':raise ValueError('输入内容或焦点无法确认')
   return {'op':'type_text','text_b64':base64.b64encode(text.encode()).decode()}
  if action not in ('click','drag'):raise ValueError('无法识别可支持的导航动作')
  command={'op':'hid_pointer','kind':action,'x':(x1+x2)*32767//2000,'y':(y1+y2)*32767//2000}
  if action=='drag':
   end=o.get('end')
   if not isinstance(end,list) or len(end)!=2 or any(type(v)!=int or not 0<=v<=1000 for v in end):raise ValueError('拖动终点无效')
   command.update(x2=end[0]*32767//1000,y2=end[1]*32767//1000,duration_ms=600)
  return command
 def _matches_action_frame(self,expected,sig,current):
  if super()._matches_action_frame(expected,sig,current):return True
  if not (expected.get('_blank_launcher') is True or expected.get('_launcher_settings') is True):return False
  from .launcher_guard import structure_metrics,quantized_core_matches
  from .jev_vision import clear_swipe_region
  shape=structure_metrics(expected,sig)
  target_same=('settings_core' in expected and quantized_core_matches(expected['settings_core'],current)) if expected.get('_launcher_settings') is True else clear_swipe_region(current)
  core_delta=None
  if expected.get('_launcher_settings') and not target_same and 'settings_core' in expected:
   from .launcher_guard import core_difference
   core_delta=core_difference(expected['settings_core'],current)
  print('LAUNCHER_FENCE '+json.dumps(dict(shape=shape,target_same=target_same,core_delta=core_delta,kind='settings' if expected.get('_launcher_settings') else 'blank')),flush=True)
  if shape and shape['same'] and target_same:return True
  if expected.get('_blank_launcher') is True and target_same and (expected.get('w'),expected.get('h'))==(sig.get('w'),sig.get('h')):
   # A drawer swipe depends on the current launcher + clear swipe patch,
   # not on the positions or pixels of unrelated home icons.
   from .jev_vision import observe_launcher
   gate=observe_launcher(current)
   accepted=bool(gate and gate.get('_trusted_launcher_blank') is True and gate.get('screen')=='launcher' and gate.get('bounds')==[450,630,550,670] and gate.get('end')==[500,250])
   print('LAUNCHER_SEMANTIC_FENCE '+json.dumps({'accepted':accepted,'scope':'blank_swipe'}),flush=True)
   return accepted
  return False
 def _receipt_frame_floor(self,j,sequence):
  with self.m.lock:
   self.m._live(j)
   return max(sequence,j.video_sequence)
 def _validate_final(self,final,task):
  if final.get('complete') is not True or final.get('verified') is not True or final.get('task')!=task or final.get('safe') is not True or not isinstance(final.get('evidence'),str) or not final['evidence'].strip():raise ValueError('最终画面未通过独立核验')
  goal=re.fullmatch(r'(?:请|帮我)?(?:打开|进入)(.+?)(?:(?:搜索|查找|找到)(.+))?',task)
  if goal:
   if final.get('application')!=goal[1]:raise ValueError('最终画面没有核验到目标应用')
   if goal[2] and (final.get('query')!=goal[2] or goal[2] not in final['evidence']):raise ValueError('最终画面没有核验到完整搜索词')
 @task_model_session
 def run(self,j,task):
  if parse_task(task) is None:raise ValueError('仅支持打开、查找和搜索，不支持发送、支付或删除')
  from .store_policy import enabled,run as run_store
  if enabled(task):return run_store(self,j,task)
  self.store.invalidate(j.device);j.fenced=True
  deadline=time.monotonic()+self.timeout
  while j.pointer_protocol!='absolute-v1' and time.monotonic()<deadline:self.m._live(j);time.sleep(.025)
  if j.pointer_protocol!='absolute-v1':raise ValueError('控制板尚未提供鼠标协议')
  raw,seq,sig=self._frame(j);geometry=(sig['w'],sig['h']);entry=self._action(j,{'op':'hid_home'},sig)
  trace=[];last=self._receipt_frame_floor(j,seq);complete=False;final=None
  frame_replans=1
  for index in range(9):
   raw,seq,sig=self._frame(j,after=last);last=seq
   if (sig['w'],sig['h'])!=geometry:raise ValueError('共享画面尺寸改变')
   # A saved skill is a method: every run locates its target in the current frame.
   o=self._observe(j,raw,task)
   if o.get('complete') is True:complete=True;break
   if o.get('action')=='unknown' and o.get('safe') is True:
    # Missing completion fields must never turn into an extra action.
    final=self._observe(j,raw,task,verify=True)
    self._validate_final(final,task)
    complete=True;break
   if index==8:break
   command=self._command(o,task)
   stored={'signature':sig,'observation':o,'target':region(raw,o['bounds'])}
   if o.get('_trusted_launcher_blank') is True and o.get('screen')=='launcher' and o.get('action')=='drag' and o.get('bounds')==[450,630,550,670] and o.get('end')==[500,250]:sig['_blank_launcher']=True
   if o.get('_trusted_launcher_settings') is True and o.get('action')=='click' and o.get('target_label') in ('设置','系统设置'):
    from .launcher_guard import settings_icon_core
    sig['settings_core']=settings_icon_core(raw,o['bounds']);sig['_launcher_settings']=True
   sig['target']=stored['target']
   from .wechat_nav import ActionFrameChanged
   try:stored['receipt']=self._action(j,command,sig)
   except ActionFrameChanged:
    if not frame_replans or not (sig.get('_launcher_settings') or sig.get('_blank_launcher')):raise
    # Nothing was dispatched: discard coordinates and inspect a newer frame once.
    frame_replans-=1;last=self._receipt_frame_floor(j,last)
    self._log(j,'frame_replan',remaining=frame_replans)
    continue
   trace.append(stored)
   last=self._receipt_frame_floor(j,last)
  if not complete:raise ValueError('导航超出八步限制或未识别到目标')
  final=final or self._observe(j,raw,task,verify=True)
  self._validate_final(final,task)
  target=verification_region(raw,final.get('bounds'));latest,_,latest_sig=self._frame(j,after=seq)
  scene_same=matches(sig,latest_sig);target_same=region_matches(target,latest)
  self._log(j,'result_stability',scene_same=scene_same,target_same=target_same,box=target['box'])
  stable=scene_same and target_same
  if not stable:
   # Read-only result validation: independently inspect the newer frame.
   # Action precondition fences remain strict; dynamic results are not cached.
   if latest_sig.get('w')!=geometry[0] or latest_sig.get('h')!=geometry[1]:raise ValueError('共享画面尺寸改变')
   refreshed=self._observe(j,latest,task,verify=True)
   self._validate_final(refreshed,task)
   verification_region(latest,refreshed.get('bounds'))
   self._log(j,'result_reverified',verified=True,coordinate_replay_saved=False)
  with self.m.lock:
   self.m._live(j);j.navigation_verified=True
   self.store.remember(j,WORKFLOW,{'task':task},trace,geometry,entry,{'verified':True,'terminal':WORKFLOW.terminal,'parameters':{'task':task},'frame':seq,'executionMode':'semantic'})
  return '已通过画面核验完成：'+task+'。已保留结果页。'

