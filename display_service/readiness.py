"""Independent, cached real service probes. No phone actions or user recording."""
import json,os,threading,time,urllib.request,wave
from pathlib import Path
from .voice import recognize

def chat_probe():
    # Probe the same configured route as normal conversations, never a separate
    # obsolete model or hard-coded provider URL.
    from .model_routing import chat_routes,request_headers
    for provider,model,config in chat_routes():
        try:
            payload={'model':model,'max_tokens':128,'thinking':{'type':'disabled'},
                     'messages':[{'role':'user','content':'Reply exactly OK'}]}
            req=urllib.request.Request(config['baseUrl'].rstrip('/')+'/chat/completions',
                data=json.dumps(payload).encode(),headers=request_headers(config))
            with urllib.request.urlopen(req,timeout=12) as response:result=json.load(response)
            if result['choices'][0]['message']['content'].strip().upper()=='OK':return
        except (OSError,ValueError,KeyError,IndexError):pass
    raise RuntimeError('chat probe failed')

def asr_probe():
    fixture=Path(os.environ.get('EPAPER_ASR_CHECK_WAV','/opt/phone-controller/assets/asr-check.wav'))
    with wave.open(str(fixture),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise ValueError('invalid fixture')
        raw=wav.readframes(160001)
    text=recognize(raw)
    if '语音' not in text or '测试' not in text:raise ValueError('unexpected recognition')

class Readiness:
    def __init__(self,chat=chat_probe,asr=asr_probe,clock=time.time,ttl=300):
        self.chat,self.asr,self.clock,self.ttl=chat,asr,clock,ttl
        self.lock=threading.Lock();self.result=None
    def snapshot(self):
        result=self.result
        if result and self.clock()-result['checkedAt']<(self.ttl if result['ready'] else 15):return dict(result)
        return {'server':'ok','chat':'pending','asr':'pending','ready':False,'checkedAt':0,
                'phoneControlReady':False,'skill':'cardputer-phone'}
    def run(self):
        with self.lock:
            if self.result and self.clock()-self.result['checkedAt']<(self.ttl if self.result['ready'] else 15):return dict(self.result)
            result=self.snapshot()
            for name,probe in (('chat',self.chat),('asr',self.asr)):
                try:probe();result[name]='ok'
                except Exception:result[name]='error'
            result['ready']=result['chat']=='ok' and result['asr']=='ok'
            result['checkedAt']=self.clock();self.result=dict(result)
            return dict(result)

READINESS=Readiness()
