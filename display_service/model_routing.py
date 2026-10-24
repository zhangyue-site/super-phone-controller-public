"""Resolve only currently configured providers; scope model routing per task."""
import contextlib,contextvars,functools,hashlib,json,os,uuid
from pathlib import Path
_SESSION=contextvars.ContextVar('phone_model_session',default=None)

def providers():
 return json.loads(Path(os.environ.get('EPAPER_MODEL_CONFIG','/root/.openclaw/openclaw.json')).read_text())['models']['providers']

def vision_route():
 config=providers();pinned=os.environ.get('EPAPER_VISION_PROVIDER')
 provider=pinned or next((p for p in ('xiaomi','opencode-go') if p in config),None)
 if provider not in config:raise ValueError('Vision provider is not configured')
 return provider,os.environ.get('EPAPER_VISION_MODEL','mimo-v2.6-flash'),config[provider]

def chat_routes():
 config=providers()
 choices=[('deepseek','deepseek-flash'),('zai','glm-5.3-flash'),('opencode-go','deepseek-v4.1-flash'),('opencode-go','glm-5.3-flash')]
 return [(p,m,config[p]) for p,m in choices if p in config and
         (not config[p].get('models') or m in [v.get('id') for v in config[p]['models']])]

def request_headers(config):
 session=_SESSION.get()
 if session is None:session='pc-'+uuid.uuid4().hex;_SESSION.set(session)
 return {'Authorization':'Bearer '+config['apiKey'],'Content-Type':'application/json',
         'User-Agent':'phone-controller/1.0','x-opencode-session':session}

@contextlib.contextmanager
def task_scope(device,session,sequence):
 identity=json.dumps([device,session,sequence],ensure_ascii=True,separators=(',',':')).encode()
 token=_SESSION.set('pc-'+hashlib.sha256(identity).hexdigest()[:32])
 try:yield
 finally:_SESSION.reset(token)

def task_model_session(function):
 @functools.wraps(function)
 def run(self,job,*args,**kwargs):
  with task_scope(job.device,job.session,job.sequence):return function(self,job,*args,**kwargs)
 return run
