"""Android command capability: BLE proof, explicit confirmation, no long-lived key."""
import hashlib,json,os,re
from .app_ota import Authority
from . import remote_http
AUTHORITY=Authority()
def owner(ticket):
 if not isinstance(ticket,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',ticket):raise PermissionError('ticket')
 with AUTHORITY.lock:
  AUTHORITY._prune(AUTHORITY.clock());item=AUTHORITY.tickets.get(ticket)
  if item is None:raise PermissionError('expired')
  device=item[1]
 principal=hashlib.sha256(ticket.encode()).hexdigest()
 return ('android-app',principal,principal,device)
def binding_allowed(identity):
 # No authority lock is ever held while calling RemoteControl/mailbox.
 with AUTHORITY.lock:
  AUTHORITY._prune(AUTHORITY.clock())
  return any(item[1]==identity[3] and hashlib.sha256(ticket.encode()).hexdigest()==identity[1]==identity[2] for ticket,item in AUTHORITY.tickets.items())
def handle(handler,config):
 path=handler.path
 if path not in ('/app-control/challenge','/app-control/authorize','/app-control/command'):return False
 try:
  if handler.command!='POST':handler.reply(405,b'{}');return True
  if os.environ.get('EPAPER_REMOTE_CONTROL')!='1':handler.reply(503,b'{}');return True
  obj=remote_http.body(handler,2048)
  if path.endswith('/challenge'):
   if set(obj)!={'device'}:raise ValueError('fields')
   result=AUTHORITY.challenge(obj['device'],json.loads(config.read_text()))
  elif path.endswith('/authorize'):
   if set(obj)!={'device','challenge','proof'}:raise ValueError('fields')
   grant=AUTHORITY.authorize(obj['device'],obj['challenge'],obj['proof'],json.loads(config.read_text()))
   # A new BLE-authorized controller supersedes the previous App session.
   with AUTHORITY.lock:
    for ticket,item in list(AUTHORITY.tickets.items()):
     if item[1]==obj['device'] and ticket!=grant['ticket']:AUTHORITY.tickets.pop(ticket,None)
   result={'ticket':grant['ticket'],'expiresIn':grant['expiresIn'],'scope':'phone-commands'}
  else:
   header=handler.headers.get('Authorization','')
   if not header.startswith('Bearer '):raise PermissionError('auth')
   identity=owner(header[7:])
   if set(obj)-{'operation','text','task_id'}:raise ValueError('fields')
   operation=obj.get('operation');remote=remote_http.REMOTE
   if operation=='prepare':
    result=remote.prepare(identity,obj.get('text'))
   elif operation=='confirm':
    ident=obj.get('task_id')
    if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('请重新生成计划，再点击确认执行。')
    result=remote.confirm(identity,ident)
   elif operation=='status':result=remote.status(identity,obj.get('task_id'))
   elif operation=='stop':result=remote.stop(identity)
   elif operation=='save':result=remote.save(identity,obj.get('task_id'))
   else:raise ValueError('operation')
  if result.get('state')=='pending':result['reply']=result['reply'].split('回复 /phone 确认 ')[0]+'请在两分钟内点击“确认执行”。'
  handler.reply(200,json.dumps(result,ensure_ascii=False).encode())
 except PermissionError:handler.reply(403,json.dumps({'reply':'控制授权已失效，请重新连接授权。'},ensure_ascii=False).encode())
 except (ValueError,TypeError,KeyError) as error:
  message='授权未完成，请检查蓝牙连接后重试。' if not path.endswith('/command') else str(error)
  handler.reply(409,json.dumps({'reply':message},ensure_ascii=False).encode())
 except OSError:handler.reply(503,b'{}')
 return True
