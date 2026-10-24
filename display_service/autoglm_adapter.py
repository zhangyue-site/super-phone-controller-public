"""Open-AutoGLM planner with board-owned, typed execution; no server ADB socket."""
import base64,contextlib,io,json,os,re,time
from pathlib import Path
from PIL import Image
from .dialogue import parse_observation,DENY,NAV

MAX_SCREEN=786432

def screenshot(raw):
 if not isinstance(raw,str) or len(raw)>MAX_SCREEN:raise ValueError('screenshot size')
 try:
  data=base64.b64decode(''.join(raw.split()),validate=True)
  with Image.open(io.BytesIO(data)) as im:
   w,h=im.size
   if im.format!='PNG' or not 1<=w<=5000 or not 1<=h<=5000 or w*h>16000000:raise ValueError('screenshot format')
   im.load();im=im.convert('RGB');im.thumbnail((720,1280));out=io.BytesIO();im.save(out,format='JPEG',quality=75)
  return base64.b64encode(out.getvalue()).decode(),w,h
 except Exception as e:raise ValueError('invalid screenshot') from e

def target_name(task):
 m=re.search(r'(?:搜索|查找|找到|找)\s*[“\"\']?([\w\u4e00-\u9fff]{2,20})',task)
 return m[1] if m else ''

def search_result_verified(obs,target):
 # A name in an input, a suggestion or a no-results message is not a contact.
 if not target:return False
 nodes=obs['nodes']
 if any(re.search(r'未找到|没有找到|无结果|暂无结果|没有搜索到',n.get('own_label','')) for n in nodes):return False
 fields=[n for n in nodes if n.get('editable') and n.get('own_label','').strip()==target]
 if not fields:return False
 if not any(re.search(r'联系人|通讯录|好友',n.get('own_label','')) for n in nodes):return False
 return any(not n.get('editable') and n.get('own_label','').strip()==target for n in nodes)

def translate(action,obs,task):
 name=action.get('action')
 if name=='Launch':
  from phone_agent.config.apps import APP_PACKAGES
  package=APP_PACKAGES.get(action.get('app'))
  choices=[c for c in obs.get('apps',[]) if c.split('/')[0]==package]
  if not choices:raise ValueError('app unavailable')
  return {'op':'launch','component':choices[0]}
 if name in ('Home','Back'):return {'op':name.lower()}
 if name in ('Type','Type_Name'):
  text=action.get('text');focused=[n for n in obs['nodes'] if n.get('editable') and n.get('focused') and n.get('enabled') and not n.get('password')]
  if len(focused)!=1 or not re.search(r'搜索|查找|search',focused[0]['label'],re.I):raise ValueError('not a search field')
  if not isinstance(text,str) or not 1<=len(text)<=120 or text not in task or any(ord(c)<32 for c in text):raise ValueError('unrequested search text')
  if len(text.encode())>384:raise ValueError('text size')
  return {'op':'type_text','text_b64':base64.b64encode(text.encode()).decode()}
 if name in ('Tap','Swipe'):
  def point(v):
   if not isinstance(v,list) or len(v)!=2 or any(type(x)!=int or not 0<=x<=999 for x in v):raise ValueError('coordinate range')
   w,h=obs['size'];return v[0]*w//1000,v[1]*h//1000
  x,y=point(action.get('element') if name=='Tap' else action.get('start'))
  ns=[n for n in obs['nodes'] if n['enabled'] and n['bounds'][0]<=x<n['bounds'][2] and n['bounds'][1]<=y<n['bounds'][3] and n['clickable' if name=='Tap' else 'scrollable']]
  ns.sort(key=lambda n:(n['bounds'][2]-n['bounds'][0])*(n['bounds'][3]-n['bounds'][1]))
  if not ns:raise ValueError('unobserved input target')
  n=ns[0];label=n['label'];target=target_name(task)
  if DENY.search(label) or action.get('message'):raise ValueError('sensitive control')
  if name=='Tap':
   if not NAV.search(label) and not(target and target in label):raise ValueError('not navigation')
   return {'op':'tap','x':x,'y':y}
  x2,y2=point(action.get('end'));return {'op':'swipe','x':x,'y':y,'x2':x2,'y2':y2}
 raise ValueError('unsupported phone action')

def model_client():
 from phone_agent.model import ModelConfig,ModelClient
 config=json.loads(Path(os.environ.get('EPAPER_MODEL_CONFIG','/root/.openclaw/openclaw.json')).read_text())['models']['providers']
 provider=os.environ.get('EPAPER_AUTOGLM_PROVIDER','xiaomi');model=os.environ.get('EPAPER_AUTOGLM_MODEL','mimo-v2.6-flash');c=config[provider]
 return ModelClient(ModelConfig(base_url=c['baseUrl'],api_key=c['apiKey'],model_name=model,max_tokens=1200,extra_body={'thinking':{'type':'disabled'}}))

def run(mailbox,job,task,status,client=None):
 from phone_agent.config.prompts_zh import SYSTEM_PROMPT
 from phone_agent.actions.handler import parse_action
 client=client or model_client()
 messages=[{'role':'system','content':SYSTEM_PROMPT+'\n本轮只允许打开、查看、搜索；不得发送消息/支付/删除/授权。只搜索用户原话中的名字。找到结果即finish，保留结果页，不返回桌面。每次Type后原输入法会立即恢复。'}]
 for step in range(12):
  mailbox._live(job);status(job.device,'running','正在读取手机界面',step=step+1)
  raw=mailbox.execute(job,{'op':'observe'});obs=parse_observation(raw)
  encoded,w,h=screenshot(mailbox.execute(job,{'op':'screenshot'}))
  if obs['size']!=[w,h] or mailbox.execute(job,{'op':'observe'})!=raw:raise ValueError('phone changed while observing')
  # Keep a bounded history without retaining prior screenshots.
  for m in messages:
   if isinstance(m.get('content'),list):m['content']=[x for x in m['content'] if x.get('type')!='image_url']
  messages.append({'role':'user','content':[{'type':'text','text':('任务：'+task if step==0 else '最新真实界面，检查上一操作结果')+'\n当前应用：'+obs['package']},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+encoded}}]})
  with contextlib.redirect_stdout(io.StringIO()):response=client.request(messages);action=parse_action(response.action)
  mailbox._live(job);print('PHONE step=%d action=%s'%(step+1,action.get('action',action.get('_metadata'))),flush=True)
  messages.append({'role':'assistant','content':response.action})
  if mailbox.execute(job,{'op':'observe'})!=raw:raise ValueError('phone changed during inference; no input sent')
  if action.get('_metadata')=='finish':
   target=target_name(task)
   if target and not search_result_verified(obs,target):raise ValueError('search result not verified')
   if '微信' in task and obs['package']!='com.tencent.mm':raise ValueError('target app not foreground')
   return ('已在微信找到“'+target+'”，手机保留在结果页。' if target and '微信' in task else str(action.get('message','操作完成'))[:120]),'done'
  if action.get('action')=='Wait':time.sleep(.5);continue
  if action.get('action') in ('Take_over','Interact'):return '需要你在手机上确认或选择，本次操作已暂停。','error'
  cmd=translate(action,obs,task)
  # Revalidate after inference. Board also verifies immediately before input.
  if mailbox.execute(job,{'op':'observe'})!=raw:raise ValueError('phone changed during inference; no input sent')
  status(job.device,'running',{'launch':'正在打开应用','type_text':'正在输入搜索文字，随后恢复输入法','tap':'正在点击并验证','swipe':'正在滑动并验证'}.get(cmd['op'],'正在操作手机'),step=step+1)
  mailbox.execute(job,cmd)
 raise ValueError('phone step budget exceeded')
