"""Separate authenticated OpenClaw bridge and device-only remote-claim endpoints."""
import hmac,json,os,re
from pathlib import Path
from .remote_control import RemoteControl
from .conversation import CONVERSATION
CONFIG=Path(os.environ.get('EPAPER_OPENCLAW_CONFIG','/etc/phone-controller/openclaw-bridge.json'))
def screen_ready(device):
 from . import app_screen
 with app_screen.AUTHORITY.lock:
  app_screen.AUTHORITY._prune(app_screen.AUTHORITY.clock())
  return any(item[1]==device for item in app_screen.AUTHORITY.tickets.values())
def binding_allowed(owner):
 if owner[0]=='android-app':
  from . import app_control
  return app_control.binding_allowed(owner)
 try:
  config=json.loads(CONFIG.read_text())
  return any(list(owner)==[b.get(k) for k in ('channel','sender','conversation','device')] for b in config.get('bindings',[]))
 except (OSError,ValueError,TypeError):return False
REMOTE=RemoteControl(CONVERSATION,screen_ready=screen_ready)
REMOTE.binding_allowed=binding_allowed
def body(handler,limit):
 size=int(handler.headers.get('Content-Length','0'))
 if not 0<=size<=limit:raise ValueError('size')
 raw=handler.rfile.read(size)
 if len(raw)!=size:raise ValueError('truncated')
 obj=json.loads(raw) if raw else {}
 if not isinstance(obj,dict):raise ValueError('body')
 return obj
def handle(handler,device_config):
 path=handler.path
 if path not in ('/bridge/phone','/remote/claim','/remote/status'):return False
 try:
  if handler.command!='POST':handler.reply(405,b'{}');return True
  if os.environ.get('EPAPER_REMOTE_CONTROL')!='1':handler.reply(503,b'{"error":"remote control disabled"}');return True
  if path=='/bridge/phone':
   config=json.loads(CONFIG.read_text());token=config.get('token')
   if not isinstance(token,str) or len(token)<43 or not hmac.compare_digest(handler.headers.get('Authorization',''),'Bearer '+token):raise PermissionError('bridge auth')
   obj=body(handler,2048)
   if set(obj)-{'operation','channel','sender','conversation','device','text','task_id'}:raise ValueError('unknown fields')
   owner=tuple(obj.get(k,'') for k in ('channel','sender','conversation','device'));REMOTE._owner(owner)
   if not any(list(owner)==[b.get(k) for k in ('channel','sender','conversation','device')] for b in config.get('bindings',[])):raise PermissionError('binding')
   operation=obj.get('operation')
   if operation=='prepare':result=REMOTE.prepare(owner,obj.get('text'))
   elif operation=='confirm':result=REMOTE.confirm(owner,obj.get('task_id'))
   elif operation=='status':result=REMOTE.status(owner,obj.get('task_id'))
   elif operation=='stop':result=REMOTE.stop(owner)
   elif operation=='save':result=REMOTE.save(owner,obj.get('task_id'))
   else:raise ValueError('operation')
  else:
   device=handler.device()
   if device is None:raise PermissionError('device auth')
   session=handler.headers.get('X-Voice-Session','');seq=int(handler.headers.get('X-Voice-Sequence','0'))
   if not re.fullmatch('[0-9a-f]{16}',session) or not 1<=seq<=2147483647:raise ValueError('turn')
   obj=body(handler,128)
   if path=='/remote/claim':
    if set(obj)-{'ready'} or ('ready' in obj and type(obj['ready']) is not bool):raise ValueError('claim shape')
    result=REMOTE.claim(device,session,seq,obj.get('ready',False),handler.headers.get('X-HID-Pointer'),handler.headers.get('X-Remote-Lease'))
   else:
    if obj:raise ValueError('status shape')
    result=REMOTE.board_status(device,session,seq)
  handler.reply(200,json.dumps(result,ensure_ascii=False).encode())
 except PermissionError:handler.reply(403,b'{"error":"authorization failed"}')
 except (ValueError,TypeError,KeyError):handler.reply(409,json.dumps({'state':'rejected','reply':'请求无效、确认已失效或控制板忙；请查询状态后重试。'},ensure_ascii=False).encode())
 except OSError:handler.reply(503,b'{"error":"bridge unavailable"}')
 return True
