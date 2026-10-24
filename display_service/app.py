"""Private e-paper endpoint. Bind loopback behind TLS; each device has its own token."""
from collections import OrderedDict
import re
import hashlib,hmac,io,json,os,threading,time,subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from . import events,firmware,app_ota,app_screen
from .conversation import CONVERSATION
from . import remote_http,app_control
from .audio_stream import EarlyDisconnect,read_chunks,read_chunks_tolerant
from .model import quota_rows
from .voice import validate_pcm,recognize
from .readiness import READINESS
from .render import render,render_dialogue,render_voice_ui
from .control import read as read_interaction, write as write_interaction

CONFIG=Path(os.environ.get('EPAPER_CONFIG','/etc/phone-controller/devices.json'))
QUOTAS=Path(os.environ.get('EPAPER_QUOTAS','/root/.local/state/quota-reporter'))
LOCK=threading.Lock()
INTERACTIONS={}
VOICE_BUSY=set()
VOICE_GENERATION={}
VOICE_CANCELLED={}

def _remote_cancel_voice(device):
    VOICE_GENERATION[device]=VOICE_GENERATION.get(device,0)+1
remote_http.REMOTE.runtime_lock=LOCK
remote_http.REMOTE.voice_busy=lambda device:device in VOICE_BUSY
remote_http.REMOTE.cancel_voice=_remote_cancel_voice
remote_http.REMOTE.turn_allowed=lambda device,session,seq:seq>VOICE_CANCELLED.get(device,{}).get(session,0)


def snapshot():
    data={}
    for provider in ('codex','cursor','jev','mimo'):
        try:
            obj=json.loads((QUOTAS/(provider+'.json')).read_text())
            if isinstance(obj,dict):data[provider]=obj
        except (OSError,ValueError):pass
    return quota_rows(data,time.time())


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,code,body,kind='application/json'):
        self.send_response(code)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(body)
    def device(self):
        try:devices=json.loads(CONFIG.read_text())
        except (OSError,ValueError):return None
        header=self.headers.get('Authorization','')
        for name,token in devices.items():
            if hmac.compare_digest(header,'Bearer '+token):return name
        return None
    def do_GET(self):
        self.connection.settimeout(10)
        if app_ota.handle(self,CONFIG):return
        if app_screen.handle(self,CONFIG):return
        if remote_http.handle(self,CONFIG):return
        if app_control.handle(self,CONFIG):return
        device=self.device()
        if device is None:return self.reply(401,b'{}')
        parsed=urlparse(self.path)
        if parsed.path in ('/firmware/manifest','/firmware/image'):
            try:
                if parsed.path.endswith('/manifest'):return self.reply(200,firmware.manifest(device),'text/plain')
                sha=parse_qs(parsed.query).get('sha',[''])[0]
                return self.reply(200,firmware.release(device,sha)[1],'application/octet-stream')
            except (OSError,ValueError,KeyError,TypeError):return self.reply(404,b'{}')
        if parsed.path=='/events':return self.reply(200,json.dumps(events.tail(device)).encode())
        if parsed.path=='/checks':return self.reply(200,json.dumps(READINESS.snapshot()).encode())
        if parsed.path not in ('/screen.bin','/screen.png','/status'):return self.reply(404,b'{}')
        rows=snapshot()
        with LOCK:interaction=read_interaction(device)
        if parsed.path=='/status':
            return self.reply(200,json.dumps({'quota':rows,'interaction':interaction},ensure_ascii=False).encode())
        page=1 if parse_qs(parsed.query).get('page')==['1'] else 0
        im=render(rows,interaction,page,time.time())
        if parsed.path=='/screen.png':
            out=io.BytesIO();im.save(out,format='PNG')
            return self.reply(200,out.getvalue(),'image/png')
        return self.reply(200,im.tobytes(),'application/octet-stream')
    def do_POST(self):
        self.connection.settimeout(10)
        if app_ota.handle(self,CONFIG):return
        if app_screen.handle(self,CONFIG):return
        if remote_http.handle(self,CONFIG):return
        if app_control.handle(self,CONFIG):return
        device=self.device()
        if device is None:return self.reply(401,b'{}')
        if self.path=='/firmware/report':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 1<=size<=1024:raise ValueError('size')
                raw=self.rfile.read(size)
                if len(raw)!=size:raise ValueError('truncated')
                return self.reply(200,json.dumps(firmware.report(device,raw)).encode())
            except (ValueError,TypeError):return self.reply(400,b'{}')
        if self.path=='/events':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 1<=size<=16384:raise ValueError('invalid size')
                raw=self.rfile.read(size)
                if len(raw)!=size:raise ValueError('truncated batch')
                count=events.ingest(device,raw)
                return self.reply(200,json.dumps({'accepted':count}).encode())
            except (ValueError,UnicodeError,TypeError):return self.reply(400,b'{}')
        if self.path in ('/checks','/checks.bin'):
            result=READINESS.run()
            if self.path=='/checks.bin':
                data=''.join('1' if result[k]=='ok' else '2' for k in ('server','chat','asr')).encode()
                return self.reply(200,data,'application/octet-stream')
            return self.reply(200,json.dumps(result).encode())
        session=self.headers.get('X-Voice-Session','')
        seq=self.headers.get('X-Voice-Sequence','')
        valid_session=bool(re.fullmatch(r'[0-9a-f]{16}',session) and re.fullmatch(r'[0-9]{1,10}',seq))
        sequence=int(seq) if valid_session else 0
        if self.path.startswith('/dialogue/'):
            if not valid_session or sequence<1:return self.reply(400,b'{}')
            try:
                if self.path=='/dialogue/video':
                    from .bridge_video import MAX_UPLOAD
                    size=int(self.headers.get('Content-Length','0'))
                    frame_sequence=int(self.headers.get('X-Video-Sequence','0'))
                    codec=self.headers.get('X-Video-Codec','')
                    if not 1<=size<=MAX_UPLOAD:raise ValueError('video body size')
                    with CONVERSATION.mailbox.lock:
                        j=CONVERSATION.mailbox._job(device,session,sequence)
                        if j.done:raise ValueError('completed turn')
                    raw=self.rfile.read(size)
                    if len(raw)!=size:raise ValueError('truncated video')
                    result=CONVERSATION.mailbox.ingest_video(device,session,sequence,frame_sequence,raw,codec)
                    return self.reply(200,json.dumps(result).encode())
                if self.path=='/dialogue/poll':
                    return self.reply(200,json.dumps(CONVERSATION.mailbox.poll(device,session,sequence,pointer_protocol=self.headers.get('X-HID-Pointer')),ensure_ascii=False).encode())
                if self.path=='/dialogue/screen':
                    size=int(self.headers.get('Content-Length','0'));requested=None
                    if size:
                        if not 1<=size<=128:raise ValueError('screen revision size')
                        body=json.loads(self.rfile.read(size))
                        if set(body)!={'revision'} or type(body['revision'])!=int:raise ValueError('screen revision fields')
                        requested=body['revision']
                    with CONVERSATION.mailbox.lock:
                        j=CONVERSATION.mailbox._job(device,session,sequence)
                        if requested is not None and requested!=j.ui_revision:raise ValueError('stale screen revision')
                        frame=(render_voice_ui(j) if j.ui_protocol=='plan-v1' else render_dialogue(j.reply,j.state,j.speech_error)).tobytes()
                    return self.reply(200,frame,'application/octet-stream')
                if self.path=='/dialogue/seen':
                    size=int(self.headers.get('Content-Length','0'))
                    if not 1<=size<=128:raise ValueError('UI ack size')
                    body=json.loads(self.rfile.read(size))
                    if set(body)!={'revision'}:raise ValueError('UI ack fields')
                    return self.reply(200,json.dumps(CONVERSATION.mailbox.ui_seen(device,session,sequence,body['revision'])).encode())
                if self.path=='/dialogue/audio':
                    return self.reply(200,CONVERSATION.mailbox.audio(device,session,sequence),'application/octet-stream')
                if self.path in ('/dialogue/result','/dialogue/text'):
                    size=int(self.headers.get('Content-Length','0'))
                    if not 1<=size<=850000:raise ValueError('body size')
                    raw=self.rfile.read(size)
                    if len(raw)!=size:raise ValueError('truncated')
                    body=json.loads(raw)
                    if self.path=='/dialogue/text':
                        text=body['text']
                        if not isinstance(text,str) or not 1<=len(text)<=120:raise ValueError('text length')
                        with LOCK:
                            if sequence<=VOICE_CANCELLED.get(device,{}).get(session,0):raise ValueError('cancelled turn')
                            CONVERSATION.start(device,session,sequence,text,ui_protocol=self.headers.get('X-Voice-UI',''))
                    else:
                        if type(body['ok']) is not bool or not isinstance(body['output'],str) or len(body['output'].encode())>786432:raise ValueError('result shape')
                        CONVERSATION.mailbox.ack(device,session,sequence,body['id'],body['ok'],body['output'],body.get('error',''))
                    return self.reply(200,b'{"accepted":true}')
                return self.reply(404,b'{}')
            except (ValueError,KeyError,TypeError):return self.reply(409,b'{"error":"turn rejected"}')
        if self.path in ('/voice','/voice/stream'):
            if not valid_session or sequence<1:return self.reply(400,b'{}')
            with LOCK:
                if sequence<=VOICE_CANCELLED.get(device,{}).get(session,0):return self.reply(409,b'{}')
                if device in VOICE_BUSY:return self.reply(409,b'{}')
                VOICE_BUSY.add(device)
                generation=VOICE_GENERATION.get(device,0)
            try:
                started=time.monotonic();first=[None]
                def progress(size):
                    if first[0] is None:
                        first[0]=time.monotonic()
                        print('VOICE first_chunk bytes=%d delay_ms=%d'%(size,(first[0]-started)*1000),flush=True)
                if self.path=='/voice/stream':
                    if self.headers.get('Transfer-Encoding','').lower()!='chunked':raise ValueError('chunked required')
                    if self.headers.get('Content-Length') is not None:raise ValueError('ambiguous length')
                    tolerated=False
                    try:
                        raw=read_chunks_tolerant(self.rfile,progress)
                    except EarlyDisconnect as disc:
                        # Board aborts short/no-voice takes by dropping the upload.
                        # Tolerate what arrived instead of erroring the screen.
                        tolerated=True
                        raw=disc.args[0] if disc.args else b''
                        if len(raw)>=12800:print('VOICE early-disconnect-tolerated bytes=%d'%len(raw),flush=True)
                    if len(raw)<12800:
                        # Short take, clean terminator or hang-up alike: quiet
                        # no-capture. Cancelled turns stay completely silent.
                        print('VOICE no-capture bytes=%d'%len(raw),flush=True)
                        with LOCK:
                            if sequence<=VOICE_CANCELLED.get(device,{}).get(session,0):
                                return self.reply(200,b'{"recognized":false,"nocapture":true}')
                            if generation==VOICE_GENERATION.get(device,0):
                                write_interaction(device,'idle','\u672a\u5f55\u5230\u8bf4\u8bdd\uff0c\u8bf7\u9760\u8fd1\u9ea6\u514b\u98ce\u518d\u8bf4')
                        return self.reply(200,b'{"recognized":false,"nocapture":true}')
                    if tolerated:
                        # Aborted takes with enough bytes must still sound like
                        # speech; VAD-timeout silence stays a quiet no-capture.
                        try:
                            raw=validate_pcm(raw)
                        except ValueError:
                            print('VOICE no-capture bytes=%d rejected'%len(raw),flush=True)
                            with LOCK:
                                if generation==VOICE_GENERATION.get(device,0):
                                    write_interaction(device,'idle','\u672a\u5f55\u5230\u8bf4\u8bdd\uff0c\u8bf7\u9760\u8fd1\u9ea6\u514b\u98ce\u518d\u8bf4')
                            return self.reply(200,b'{"recognized":false,"nocapture":true}')
                else:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 12800<=size<=320000:raise ValueError('invalid length')
                    raw=self.rfile.read(size)
                    if len(raw)!=size:raise ValueError('truncated audio')
                received=time.monotonic()
                print('VOICE received bytes=%d receive_ms=%d'%(len(raw),(received-started)*1000),flush=True)
                validate_pcm(raw)
                with LOCK:
                    if generation!=VOICE_GENERATION.get(device,0):return self.reply(409,b'{}')
                    write_interaction(device,'thinking','语音已上传，正在云端识别')
                text=recognize(raw)
                print("VOICE recognized asr_ms=%d text=%s"%((time.monotonic()-received)*1000,json.dumps(text,ensure_ascii=False)),flush=True)
                with LOCK:
                    if generation!=VOICE_GENERATION.get(device,0):return self.reply(409,b'{}')
                    if self.headers.get('X-Voice-Dialogue')=='1':
                        if sequence<=VOICE_CANCELLED.get(device,{}).get(session,0):raise ValueError('cancelled turn')
                        CONVERSATION.start(device,session,sequence,text,ui_protocol=self.headers.get('X-Voice-UI',''))
                    else:write_interaction(device,'waiting',text+'（仅识别模式）')
                return self.reply(200,b'{"recognized":true,"actuatorConnected":false}')
            except (ValueError,OSError,TimeoutError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
                if isinstance(error,(BrokenPipeError,ConnectionResetError)):
                    # Board aborts by hanging up; outcome was already written (or is moot).
                    print('VOICE client-gone',flush=True);return None
                intake_errors={'chunked required','ambiguous length','recording timed out','invalid chunk header','invalid chunk size','audio too large','trailers unsupported','truncated audio','invalid length'}
                reason=str(error) if isinstance(error,ValueError) and str(error) in intake_errors else type(error).__name__
                print('VOICE failure='+reason,flush=True)
                with LOCK:
                    if generation==VOICE_GENERATION.get(device,0):write_interaction(device,'error','语音识别失败，请靠近麦克风重试')
                return self.reply(422,b'{"recognized":false}')
            finally:
                with LOCK:VOICE_BUSY.discard(device)
        if self.path!='/stop':return self.reply(404,b'{}')
        CONVERSATION.mailbox.cancel(device,session,sequence)
        if os.environ.get('EPAPER_REMOTE_CONTROL')=='1':remote_http.REMOTE.stop_board(device,session,sequence)
        with LOCK:
            VOICE_GENERATION[device]=VOICE_GENERATION.get(device,0)+1
            if valid_session:
                history=VOICE_CANCELLED.setdefault(device,OrderedDict())
                history[session]=max(sequence,history.get(session,0));history.move_to_end(session)
                while len(history)>16:history.popitem(last=False)
            write_interaction(device,'stopped','对话任务已取消；板端停止会撤销本地ADB操作')
        return self.reply(200,b'{"recorded":true,"actuatorConnected":false}')


def main():
    def expire():
        while True:
            time.sleep(5);CONVERSATION.expire()
    threading.Thread(target=expire,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',18943),Handler).serve_forever()

if __name__=='__main__':main()
