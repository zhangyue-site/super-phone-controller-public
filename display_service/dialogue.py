"""Per-device turn mailbox. No cloud process gets an ADB socket or arbitrary shell."""
import json,re,threading,time,uuid,xml.etree.ElementTree as ET
from dataclasses import dataclass,field
DENY=re.compile(r'发送|支付|付款|转账|购买|充值|删除|清空|授权|权限|登录|退出|保存|提交|开启|关闭|修改|重置|卸载|安装|send|pay|buy|delete|remove|confirm|allow|permission|sign.?in|save|submit|install|reset',re.I)
NAV=re.compile(r'打开|进入|查看|返回|列表|详情|账单|设置|菜单|分类|首页|明细|记录|关于|帮助|搜索|home|settings|menu|details|list|back|help',re.I)

COMMAND_ERRORS=frozenset(('adb_unavailable','cancelled','busy','invalid_command','observe_failed','screen_changed','app_unavailable','input_failed'))
class PhoneCommandError(ValueError):
 def __init__(self,code):
  if code not in COMMAND_ERRORS:raise ValueError('unknown phone command error')
  self.code=code;super().__init__(code)

def parse_observation(raw):
 if not isinstance(raw,str) or len(raw.encode())>48000:raise ValueError('observation size')
 start=raw.find('<?xml');start=start if start>=0 else raw.find('<hierarchy');end=raw.rfind('</hierarchy>')
 if start<0 or end<0:raise ValueError('incomplete UI')
 header=raw[:start];footer=raw[end+12:]
 focus=re.search(r'^FOCUS ([A-Za-z0-9_.]+)/([^\s]+)',header,re.M)
 size=re.search(r'^SIZE (\d+)x(\d+)',header,re.M)
 if not focus or not size or not re.search(r'^LOCKED false$',header,re.M):raise ValueError('phone locked or no foreground')
 if not re.search(r'^END_LOCKED false$',footer,re.M) or not re.search(r'^END_FOCUS '+re.escape(focus[1]+'/'+focus[2])+r'$',footer,re.M):raise ValueError('phone changed while observing')
 root=ET.fromstring(raw[start:end+12]);nodes=[]
 for n in root.iter('node'):
  a=n.attrib
  if a.get('password')=='true':continue
  bounds=[int(v) for v in re.findall(r'\d+',a.get('bounds',''))]
  if len(bounds)!=4 or not 0<=bounds[0]<bounds[2]<=int(size[1]) or not 0<=bounds[1]<bounds[3]<=int(size[2]):continue
  if a.get('package') and a['package']!=focus[1]:raise ValueError('mixed foreground UI')
  label=' '.join((c.get('text','')+' '+c.get('content-desc','')).strip() for c in n.iter('node') if c.get('password')!='true')[:1000]
  if not label and a.get('clickable')!='true' and a.get('scrollable')!='true':continue
  nodes.append({'id':len(nodes),'own_label':(a.get('text','')+' '+a.get('content-desc','')).strip(),'class':a.get('class',''),'resource_id':a.get('resource-id',''),'label':label,'bounds':bounds,'clickable':a.get('clickable')=='true','scrollable':a.get('scrollable')=='true','enabled':a.get('enabled','true')=='true','editable':a.get('class','').endswith('EditText'),'focused':a.get('focused')=='true','password':a.get('password')=='true'})
 if not nodes:raise ValueError('no UI nodes')
 apps=[]
 block=re.search(r'^APPS_BEGIN\n(.*?)^APPS_END$',header,re.M|re.S)
 if block:apps=re.findall(r'^([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)$',block[1],re.M)[:128]
 return {'size':[int(size[1]),int(size[2])],'apps':apps,'package':focus[1],'activity':focus[2],'launcher':bool(re.search(r'^LAUNCHER '+re.escape(focus[1])+r'/',header,re.M)),'nodes':nodes}

def action_command(d,obs):
 action=d.get('action')
 if action in ('home','back','open_settings'):return {'op':action}
 if action=='launch':
  component=d.get('component')
  if not isinstance(component,str) or component not in obs.get('apps',[]) or len(component)>159:raise ValueError('unobserved launcher activity')
  return {'op':'launch','component':component}
 if action not in ('tap','scroll'):raise ValueError('unsupported action')
 i=d.get('node')
 if type(i)!=int or not 0<=i<len(obs['nodes']):raise ValueError('unknown node')
 n=obs['nodes'][i]
 if not n['enabled'] or not n['clickable' if action=='tap' else 'scrollable'] or DENY.search(n['label']):raise ValueError('node rejected')
 x1,y1,x2,y2=n['bounds'];x=(x1+x2)//2
 if action=='tap':
  if not NAV.search(n['label']):raise ValueError('only navigation controls allowed')
  return {'op':'tap','x':x,'y':(y1+y2)//2}
 direction=d.get('direction','up')
 if direction not in ('up','down'):raise ValueError('scroll direction')
 top=y1+(y2-y1)*3//10;bottom=y1+(y2-y1)*8//10
 return {'op':'swipe','x':x,'y':bottom if direction=='up' else top,'x2':x,'y2':top if direction=='up' else bottom}

def verify_done(task,d,obs):
 evidence=d.get('evidence')
 if not isinstance(evidence,str) or not evidence.strip() or not any(evidence in n['label'] for n in obs['nodes']):return False
 if '打开' in task and obs['launcher']:return False
 if re.search(r'打开.*设置',task) and obs['package']!='com.android.settings':return False
 if re.search(r'(回到|返回|回).*桌面|手机首页',task) and not obs['launcher']:return False
 return True

@dataclass
class Job:
 device:str
 session:str
 sequence:int
 created:float
 touched:float
 max_age:float=180
 cancelled:bool=False
 command:dict|None=None
 delivered:bool=False
 result:tuple|None=None
 audio:bytes=b''
 reply:str=''
 video:bytes=b''
 video_source:str=''
 video_barrier:str=field(default_factory=lambda:uuid.uuid4().hex)
 screen_session:str=''
 pointer_protocol:str=''
 fenced:bool=False
 navigation_verified:bool=False
 last_receipt:dict=field(default_factory=dict)
 video_sequence:int=0
 video_received:float=0
 video_width:int=0
 video_height:int=0
 ui_protocol:str=''
 ui_revision:int=0
 ui_seen_revision:int=0
 ui_heard:str=''
 ui_plan:list=field(default_factory=list)
 ui_event:threading.Event=field(default_factory=threading.Event)
 speech_error:bool=False
 state:str='thinking'
 done:bool=False
 event:threading.Event=field(default_factory=threading.Event)

class Mailbox:
 def __init__(self,clock=time.monotonic):self.clock=clock;self.lock=threading.RLock();self.jobs={};self.high={}
 def _live(self,j):
  if j.cancelled or self.clock()-j.created>j.max_age or self.clock()-j.touched>45:
   j.cancelled=True;j.video=b'';j.event.set();raise ValueError('turn cancelled or expired')
 def _job(self,device,session,seq):
  j=self.jobs.get(device)
  if not j or (j.session,j.sequence)!=(session,seq):raise ValueError('unknown turn')
  self._live(j);return j
 def create(self,device,session,seq):
  with self.lock:
   key=(device,session)
   if seq<=self.high.get(key,0):raise ValueError('duplicate turn')
   old=self.jobs.get(device)
   if old and not old.done and not old.cancelled and self.clock()-old.touched<=15:raise ValueError('turn busy')
   if old:old.cancelled=True;old.video=b'';old.event.set()
   self.high[key]=seq
   if len(self.high)>256:self.high.pop(next(iter(self.high)))
   now=self.clock();j=Job(device,session,seq,now,now);self.jobs[device]=j;return j
 def offer(self,j,command):
  with self.lock:
   self._live(j)
   if j.command:raise ValueError('command busy')
   j.result=None;j.delivered=False;j.command=dict(command,id=uuid.uuid4().hex);j.event.clear()
   print('PHONE_COMMAND device=%s turn=%d id=%s op=%s'%(j.device,j.sequence,j.command['id'][:8],command['op']),flush=True)
 def poll(self,device,session,seq,pointer_protocol=None):
  with self.lock:
   j=self._job(device,session,seq);j.touched=self.clock()
   if pointer_protocol=='absolute-v1':j.pointer_protocol=pointer_protocol
   ui={'uiRevision':j.ui_revision} if j.ui_protocol=='plan-v1' else {}
   if j.command and not j.delivered:
    # Pointer packets have a strict firmware key allowlist; UI metadata belongs to status packets.
    j.delivered=True;return dict(j.command,**({} if j.command['op']=='hid_pointer' else ui))
   return dict({'op':'done' if j.done else 'wait','state':j.state,'reply':j.reply,'audio':bool(j.audio),'speechError':j.speech_error},**ui)
 def ui_seen(self,device,session,seq,revision):
  with self.lock:
   j=self._job(device,session,seq)
   if j.ui_protocol!='plan-v1' or type(revision)!=int or revision<1 or revision!=j.ui_revision:raise ValueError('stale UI revision')
   j.ui_seen_revision=revision;j.touched=self.clock();j.ui_event.set()
   print('VOICE_UI_SEEN '+json.dumps({'turn':seq,'revision':revision}),flush=True)
   return {'accepted':True}

 def ack(self,device,session,seq,ident,ok,output,error=''):
  if error and error not in COMMAND_ERRORS:raise ValueError('unknown phone command error')
  with self.lock:
   j=self._job(device,session,seq)
   if not j.command or not j.delivered or ident!=j.command['id']:raise ValueError('stale acknowledgement')
   if not isinstance(output,str) or len(output.encode())>(786432 if j.command['op']=='screenshot' else 48000):raise ValueError('command output size')
   print('PHONE_RECEIPT device=%s turn=%d id=%s ok=%s err=%s'%(device,seq,ident[:8],ok,error or '-'),flush=True)
   j.last_receipt={'id':ident,'op':j.command['op'],'ok':ok,'barrier_before':j.video_barrier}
   j.result=(ok,output,error);j.command=None;j.touched=self.clock()
   if j.fenced:j.video_barrier=uuid.uuid4().hex;j.video=b''
   j.event.set()
 def execute(self,j,command):
  self.offer(j,command)
  until=self.clock()+60
  while self.clock()<until:
   j.event.wait(.2)
   with self.lock:
    self._live(j)
    if j.result is not None:
     ok,out,error=j.result;j.result=None
     if not ok:raise PhoneCommandError(error or 'input_failed')
     return out
  raise TimeoutError('phone acknowledgement timeout; not retried')
 def cancel(self,device,session=None,sequence=None):
  with self.lock:
   j=self.jobs.get(device)
   if j and (session is None or (j.session==session and j.sequence<=sequence)):
    j.cancelled=True;j.audio=b'';j.video=b'';j.event.set()
 def ingest_video(self,device,session,seq,frame_sequence,payload,codec,decoder=None,expected_barrier=None,source='bridge_declared'):
  from .bridge_video import decode
  if type(frame_sequence)!=int or not 1<=frame_sequence<=2147483647:raise ValueError('frame sequence')
  with self.lock:
   j=self._job(device,session,seq)
   if j.fenced and expected_barrier!=j.video_barrier:raise ValueError('capture barrier required')
   if expected_barrier is not None and expected_barrier!=j.video_barrier:raise ValueError('capture superseded')
   if j.done or frame_sequence<=j.video_sequence:raise ValueError('stale video')
   j.video_sequence=frame_sequence;j.video=b'';received=self.clock();barrier=j.video_barrier
  jpeg,width,height=(decoder or decode)(payload,codec)
  with self.lock:
   if self._job(device,session,seq) is not j or j.done or j.video_sequence!=frame_sequence or j.video_barrier!=barrier or self.clock()-received>8:raise ValueError('video superseded')
   j.video=jpeg;j.video_source=source;j.video_width=width;j.video_height=height;j.video_received=received;j.touched=self.clock()
   return dict(accepted=True,frame=frame_sequence,width=width,height=height,source='bridge_declared',phone_execution=False)
 def latest_video(self,j,max_age=2):
  with self.lock:
   self._live(j)
   if j.done or not j.video or self.clock()-j.video_received>max_age:raise ValueError('fresh video required')
   return j.video,j.video_sequence,j.video_width,j.video_height
 def audio(self,device,session,seq):
  with self.lock:return self._job(device,session,seq).audio
