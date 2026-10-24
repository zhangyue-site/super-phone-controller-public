"""Generic collection/compilation Skill plus reusable specialized Skill templates."""
import base64,hashlib,io,json,os,re,threading,time,zlib
from pathlib import Path
from PIL import Image
def signature(raw):
 with Image.open(io.BytesIO(raw)) as im:
  w,h=im.size
  small=im.convert("L").crop((0,int(h*.045),w,int(h*.95))).resize((96,160))
  return {"w":w,"h":h,"pixels":base64.b64encode(zlib.compress(small.tobytes())).decode()}
def matches(a,b):
 if not isinstance(a,dict) or (a.get("w"),a.get("h"))!=(b.get("w"),b.get("h")):return False
 try:
  x=zlib.decompress(base64.b64decode(a["pixels"]));y=zlib.decompress(base64.b64decode(b["pixels"]))
  if len(x)!=15360 or len(y)!=15360:return False
  differences=[abs(v-w) for v,w in zip(x,y)]
  return sum(differences)/len(differences)<=1.0 and sum(v>12 for v in differences)/len(differences)<.002
 except (ValueError,KeyError,zlib.error):return False

def region(raw,bounds):
 if not isinstance(bounds,list) or len(bounds)!=4 or any(type(v)!=int for v in bounds):raise ValueError("需要准确目标区域")
 x1,y1,x2,y2=bounds
 if not 0<=x1<x2<=1000 or not 0<=y1<y2<=1000:raise ValueError("目标区域无效")
 with Image.open(io.BytesIO(raw)) as im:
  w,h=im.size
  box=(x1*w//1000,y1*h//1000,max(x1*w//1000+1,x2*w//1000),max(y1*h//1000+1,y2*h//1000))
  crop=im.convert("RGB").crop(box)
  return {"box":bounds,"w":crop.width,"h":crop.height,"pixels":base64.b64encode(zlib.compress(crop.tobytes())).decode()}
def region_matches(reference,raw):
 if not isinstance(reference,dict):return False
 try:
  current=region(raw,reference["box"])
  if (current["w"],current["h"])!=(reference["w"],reference["h"]):return False
  a=zlib.decompress(base64.b64decode(reference["pixels"]));b=zlib.decompress(base64.b64decode(current["pixels"]))
  if len(a)!=len(b) or not a:return False
  diff=[abs(x-y) for x,y in zip(a,b)]
  return sum(diff)/len(diff)<=.5 and sum(v>8 for v in diff)/len(diff)<.001
 except (ValueError,KeyError,zlib.error,TypeError):return False

from dataclasses import dataclass
import copy

NAVIGATION_METHOD={'version':1,'entry':'android.home','parameter':'task','steps':['read_current_screen','locate_visible_target','check_fresh_frame','execute_once','verify_goal_from_new_screen'],'coordinateReplay':False}
COLLECTOR={"id":"collect-and-compile","kind":"collector","group":"通用技能","name":"采集与固化"}
@dataclass(frozen=True)
class WorkflowSpec:
 id:str
 group:str
 name:str
 parameters:tuple
 terminal:str
 version:int=1
 def bind(self,values):
  if not isinstance(values,dict) or set(values)!=set(self.parameters):raise ValueError("专项技能参数不符")
  if any(not isinstance(v,str) or not 1<=len(v)<=120 for v in values.values()):raise ValueError("专项技能参数无效")
  return dict(values)
class SkillStore:
 """Generic collector/compiler; app policy and result verification stay in adapters."""
 def __init__(self,root=None,clock=time.monotonic):
  self.root=Path(root or os.environ.get("EPAPER_SKILLS","/var/lib/phone-controller/skills"))
  self.clock=clock;self.lock=threading.RLock();self.last={}
 def _path(self,device):
  if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",device):raise ValueError("device")
  return self.root/(device+".json")
 def _read(self,device):
  try:
   p=self._path(device)
   if p.stat().st_size>3000000:return {}
   data=json.loads(p.read_text())
   return data if isinstance(data,dict) and data.get("schema")==2 else {}
  except (OSError,ValueError):return {}
 def invalidate(self,device):
  with self.lock:self.last.pop(device,None)
 def remember(self,job,spec,parameters,steps,geometry,entry_receipt,verification):
  parameters=spec.bind(parameters)
  if not isinstance(entry_receipt,dict) or entry_receipt.get("op")!="hid_home" or entry_receipt.get("ok") is not True:raise ValueError("缺少桌面入口回执")
  if not verification.get("verified") or verification.get("terminal")!=spec.terminal or verification.get("parameters")!=parameters:raise ValueError("缺少专项结果核验")
  if not (0 if spec.id=="general.navigate" else 1)<=len(steps)<=8:raise ValueError("技能步骤无效")
  for step in steps:
   receipt=step.get("receipt",{})
   if receipt.get("ok") is not True or receipt.get("op") not in ("hid_pointer","type_text"):raise ValueError("缺少动作成功回执")
   if not re.fullmatch(r"[0-9a-f]{32}",receipt.get("id","")):raise ValueError("动作关联ID无效")
   if "signature" not in step or "target" not in step:raise ValueError("缺少画面与目标检查条件")
  print('SKILL_COLLECT device=%s workflow=%s turn=%s verified=true'%(job.device,spec.id,getattr(job,'sequence',0)),flush=True)
  with self.lock:self.last[job.device]=(self.clock(),job,spec,parameters,copy.deepcopy(steps),geometry,copy.deepcopy(entry_receipt),copy.deepcopy(verification))
 def save_last(self,device):
  with self.lock:
   item=self.last.get(device)
   if not item or self.clock()-item[0]>900:raise ValueError("没有最近核验成功的操作可保存")
   _,job,spec,parameters,steps,geometry,entry,proof=item
   if not job.done or job.state!="done" or not job.navigation_verified:raise ValueError("操作尚未成功完成，不能固化")
   data=self._read(device);entries=data.get("skills",{})
   key=hashlib.sha256((spec.id+json.dumps(parameters,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()[:24]
   name=spec.name+"（"+"、".join(parameters.values())+"）"
   entries[key]={"kind":"specialized","workflow":spec.id,"policyVersion":spec.version,"group":spec.group,"name":name,
    "parameterNames":list(spec.parameters),"parameters":parameters,"entry":"desktop","entryReceipt":entry,"steps":steps,
    "geometry":geometry,"context":{"device":job.device,"turn":getattr(job,"sequence",0),"screenSession":hashlib.sha256(getattr(job,"screen_session","").encode()).hexdigest()[:16]},"terminal":spec.terminal,"verification":proof,"requiresFinalVision":True}
   if spec.id=='general.navigate':
    entry=entries[key]
    entry['executionMode']='semantic';entry['method']=copy.deepcopy(NAVIGATION_METHOD)
    entry['evidence']=[{'target_label':step.get('observation',{}).get('target_label'),'receipt':copy.deepcopy(step['receipt'])} for step in steps]
    entry.pop('steps',None);entry.pop('geometry',None)
   if len(entries)>32:raise ValueError("专项技能已满，请先整理")
   self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
   path=self._path(device);tmp=path.with_suffix(".tmp")
   encoded=json.dumps({"schema":2,"collector":COLLECTOR["id"],"skills":entries},ensure_ascii=False)
   if len(encoded.encode())>3000000:raise ValueError("技能数据已满")
   tmp.write_text(encoded);tmp.chmod(0o600);os.replace(tmp,path)
   print("SKILL_COMPILE device=%s kind=specialized workflow=%s parameters=%s"%(device,spec.id,",".join(spec.parameters)),flush=True)
   return name
 def find(self,device,spec,parameters):
  parameters=spec.bind(parameters)
  with self.lock:
   entries=[e for e in self._read(device).get("skills",{}).values() if isinstance(e,dict)]
   # Exact instance first; a workflow template may bind a new contact/parameter.
   entries.sort(key=lambda e:e.get("parameters")!=parameters)
   for entry in entries:
    if not isinstance(entry,dict):continue
    if not isinstance(entry,dict) or entry.get("kind")!="specialized" or entry.get("workflow")!=spec.id or entry.get("policyVersion")!=spec.version:continue
    if entry.get("parameterNames")!=list(spec.parameters) or entry.get("terminal")!=spec.terminal or entry.get("entry")!="desktop":continue
    if not entry.get("requiresFinalVision"):continue
    if spec.id=='general.navigate':
     from .general_nav import parse_task
     if parse_task(parameters.get('task')) is None:continue
     bound=copy.deepcopy(entry);bound.pop('steps',None);bound['executionMode']='semantic';bound['method']=copy.deepcopy(NAVIGATION_METHOD);bound['boundParameters']=parameters
     return bound
    if not isinstance(entry.get("steps"),list) or not 1<=len(entry["steps"])<=8:continue
    bound=copy.deepcopy(entry);bound["boundParameters"]=parameters;return bound
   return None
 def list(self,device):
  with self.lock:return [{k:v.get(k,"") for k in ("kind","workflow","group","name")} for v in self._read(device).get("skills",{}).values() if isinstance(v,dict)]
 def cards(self,device):
  with self.lock:
   result=[]
   for ident,entry in self._read(device).get("skills",{}).items():
    if not isinstance(entry,dict):continue
    result.append({"id":ident,"name":entry.get("name",""),"group":entry.get("group",""),"description":("从桌面识别当前画面并定位目标，图标换位时重新寻找，结束后独立核验" if entry.get("workflow")=="general.navigate" else "从桌面回放已核验的导航，结束后独立画面核验"),"requirements":["手机解锁","整屏共享","板端HID许可"],"parameters":[{"name":k,"label":k,"value":v} for k,v in entry.get("parameters",{}).items()]})
   return result
 def resolve(self,device,ident,parameters):
  if not isinstance(ident,str) or not re.fullmatch("[0-9a-f]{24}",ident):raise ValueError("技能ID无效")
  with self.lock:entry=self._read(device).get("skills",{}).get(ident)
  if not isinstance(entry,dict) or entry.get("requiresFinalVision") is not True:raise ValueError("当前设备没有该技能")
  if not isinstance(parameters,dict):raise ValueError("技能参数无效")
  values=parameters or entry.get("parameters",{})
  if entry.get("workflow")=="wechat.search_contact":
   spec=WorkflowSpec("wechat.search_contact","微信","微信找联系人",("contact",),"wechat.search_results")
   values=spec.bind(values);text="打开微信找到"+values["contact"]
  elif entry.get("workflow")=="general.navigate":
   spec=WorkflowSpec("general.navigate","通用","画面导航",("task",),"general.verified")
   values=spec.bind(values)
   from .general_nav import parse_task
   if parse_task(values["task"]) is None:raise ValueError("通用方法只支持安全导航目标")
   text=values["task"]
  else:raise ValueError("不支持的技能")
  return text
 def catalog(self,device):return [dict(COLLECTOR),*self.list(device)]
class ReplayEngine:
 """Reusable visual guards; adapters retain action allowlists and final verifier."""
 @staticmethod
 def step(recipe,index,raw):
  steps=recipe.get("steps",[]) if recipe else []
  if index>=len(steps):return None
  step=steps[index]
  if not matches(step.get("signature"),signature(raw)) or not region_matches(step.get("target"),raw):return None
  return copy.deepcopy(step)
