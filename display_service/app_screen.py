"""Opt-in screen frames authorized by a separate BLE-possession capability.
No phone actions, device bearer keys, screenshots on disk, or ADB access.
"""
import json,re,threading,os
from .app_ota import Authority
from .conversation import CONVERSATION
from .wechat_nav import STORE
AUTHORITY=Authority()
LOCK=threading.Lock()
SEQUENCES={}

def extend_diagnostic_ticket(device,grant):
 if device!='epaper-01' or os.environ.get('EPAPER_SCREEN_DIAG_LONG')!='epaper-01':return
 item=AUTHORITY.tickets.get(grant['ticket'])
 if item is None or item[1]!=device:raise ValueError('ticket')
 AUTHORITY.tickets[grant['ticket']]=(AUTHORITY.clock()+1200,item[1],item[2]);grant['expiresIn']=1200

def subject(ticket):
 if not isinstance(ticket,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',ticket):raise ValueError('ticket')
 with AUTHORITY.lock:
  AUTHORITY._prune(AUTHORITY.clock());item=AUTHORITY.tickets.get(ticket)
  if item is None:raise ValueError('ticket')
  return item[1]

def handle(handler,config):
 path=handler.path
 if path not in ('/app-screen/challenge','/app-screen/authorize','/app-screen/frame','/app-screen/stop','/app-screen/status'):return False
 try:
  if handler.command!='POST':handler.reply(405,b'{}');return True
  size=int(handler.headers.get('Content-Length','0'))
  if path in ('/app-screen/challenge','/app-screen/authorize'):
   if not 1<=size<=1024:raise ValueError('size')
   raw=handler.rfile.read(size)
   if len(raw)!=size:raise ValueError('truncated')
   obj=json.loads(raw);keys=json.loads(config.read_text())
   if not isinstance(obj,dict):raise ValueError('body')
   if path.endswith('/challenge'):
    if set(obj)!={'device'}:raise ValueError('fields')
    result=AUTHORITY.challenge(obj['device'],keys)
   else:
    if set(obj)!={'device','challenge','proof'}:raise ValueError('fields')
    grant=AUTHORITY.authorize(obj['device'],obj['challenge'],obj['proof'],keys)
    with AUTHORITY.lock:
     extend_diagnostic_ticket(obj['device'],grant)
     for old,item in list(AUTHORITY.tickets.items()):
      if item[1]==obj['device'] and old!=grant['ticket']:AUTHORITY.tickets.pop(old,None)
     CONVERSATION.mailbox.cancel(obj['device'])
    result={'ticket':grant['ticket'],'expiresIn':grant['expiresIn'],'scope':'screen-frames'}
   handler.reply(200,json.dumps(result).encode());return True
  header=handler.headers.get('Authorization','')
  if not header.startswith('Bearer '):raise ValueError('auth')
  ticket=header[7:];device=subject(ticket)
  mailbox=CONVERSATION.mailbox
  if path.endswith('/status'):
   if size!=0:raise ValueError('size')
   with mailbox.lock:
    j=mailbox.jobs.get(device)
    result={'state':j.state if j and not j.cancelled else 'idle','reply':j.reply if j and not j.cancelled else '',
     'frame':j.video_sequence if j else 0,'pointerReady':bool(j and j.pointer_protocol=='absolute-v1'),
     'skills':STORE.catalog(device),'barrier':j.video_barrier if j else ''}
   handler.reply(200,json.dumps(result,ensure_ascii=False).encode());return True
  if path.endswith('/stop'):
   if size!=0:raise ValueError('size')
   with AUTHORITY.lock:
    if ticket not in AUTHORITY.tickets:raise ValueError('revoked')
    AUTHORITY.tickets.pop(ticket,None)
    with LOCK:SEQUENCES.pop(ticket,None)
    mailbox.cancel(device);STORE.invalidate(device)
   handler.reply(200,b'{}');return True
  if handler.headers.get('Content-Type')!='image/jpeg' or not 1<=size<=524288:raise ValueError('size')
  sequence=int(handler.headers.get('X-Screen-Sequence','0'))
  if not 1<=sequence<=2147483647:raise ValueError('sequence')
  payload=handler.rfile.read(size)
  if len(payload)!=size:raise ValueError('truncated')
  with AUTHORITY.lock:
   AUTHORITY._prune(AUTHORITY.clock())
   if ticket not in AUTHORITY.tickets:raise ValueError('revoked')
   with LOCK:
    for key in list(SEQUENCES):
     if key not in AUTHORITY.tickets:SEQUENCES.pop(key,None)
    if sequence<=SEQUENCES.get(ticket,0):raise ValueError('stale frame')
    SEQUENCES[ticket]=sequence
   with mailbox.lock:
    j=mailbox.jobs.get(device)
    if j is None or j.done or j.cancelled:
     handler.reply(202,b'{"accepted":false,"reason":"no active voice task","barrier":"00000000000000000000000000000000"}');return True
    if j.screen_session and j.screen_session!=ticket:raise ValueError('screen session changed')
    j.screen_session=ticket
    if j.fenced and handler.headers.get('X-Screen-Barrier','')!=j.video_barrier:
     handler.reply(202,json.dumps({'accepted':False,'reason':'capture barrier required','barrier':j.video_barrier}).encode());return True
    capture_barrier=j.video_barrier
    voice_session,voice_sequence,frame_sequence=j.session,j.sequence,j.video_sequence+1
   try:
    result=mailbox.ingest_video(device,voice_session,voice_sequence,frame_sequence,payload,'jpeg',expected_barrier=capture_barrier,source='user-consented-app-screen')
   except ValueError:
    with mailbox.lock:
     if mailbox.jobs.get(device) is j and (j.done or j.cancelled):
      handler.reply(202,b'{"accepted":false,"reason":"no active voice task","barrier":"00000000000000000000000000000000"}');return True
    raise
   with mailbox.lock:
    if mailbox.jobs.get(device) is j and (j.done or j.cancelled):
     handler.reply(202,b'{"accepted":false,"reason":"no active voice task","barrier":"00000000000000000000000000000000"}');return True
    if mailbox._job(device,voice_session,voice_sequence) is not j or j.done or j.video_barrier!=capture_barrier:raise ValueError('superseded')
    j.video_source='user-consented-app-screen'
    result['barrier']=j.video_barrier
  result['source']='user-consented-app-screen'
  if frame_sequence==1 or frame_sequence%10==0:print('APP_SCREEN frame device=%s turn=%d frame=%d width=%d height=%d'%(device,voice_sequence,frame_sequence,result['width'],result['height']),flush=True)
  handler.reply(200,json.dumps(result).encode())
 except (ValueError,TypeError,KeyError,OSError):handler.reply(403,b'{"error":"screen session invalid or expired"}')
 return True
