"""MiMo online TTS using the existing server-side speech credential; bounded PCM."""
import base64,io,json,os,subprocess,urllib.request,wave
from pathlib import Path
MAX_PCM=960000

def pcm_from_wav(audio):
 if not audio or len(audio)>3000000:raise ValueError('audio size')
 try:
  with wave.open(io.BytesIO(audio),'rb') as wav:
   if wav.getnchannels()==1 and wav.getsampwidth()==2 and wav.getframerate()==16000:
    raw=wav.readframes(480001)
    if not raw or len(raw)>MAX_PCM:raise ValueError('speech too long')
    return raw
 except (wave.Error,EOFError):raise ValueError('invalid wav')
 result=subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-t','30','-f','s16le','-ac','1','-ar','16000','pipe:1'],input=audio,capture_output=True,timeout=8,check=True)
 if not result.stdout or len(result.stdout)>MAX_PCM or len(result.stdout)%2:raise ValueError('speech format')
 return result.stdout

def synthesize(text):
 if not isinstance(text,str) or not 1<=len(text)<=160:raise ValueError('speech length')
 config=json.loads(Path(os.environ.get('EPAPER_SPEECH_CONFIG','/opt/cardputer-phone/asr-config.json')).read_text())
 payload={'model':'mimo-v2.5-tts','messages':[{'role':'user','content':'请用清晰自然的普通话播报，语速略快。'},{'role':'assistant','content':text}], 'audio':{'format':'wav','voice':'mimo_default'}}
 req=urllib.request.Request(config['baseUrl'].rstrip('/')+'/chat/completions',data=json.dumps(payload).encode(),headers={'api-key':config['apiKey'],'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=25) as response:result=json.loads(response.read(4500000))
 audio=base64.b64decode(result['choices'][0]['message']['audio']['data'],validate=True)
 return pcm_from_wav(audio)
