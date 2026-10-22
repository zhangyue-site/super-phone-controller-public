"""Bounded in-memory PCM input; temporary WAV removed after cloud recognition."""
import array,json,math,os,subprocess,tempfile,wave

def validate_pcm(raw):
    if not 12800<=len(raw)<=320000 or len(raw)%2:
        raise ValueError('请录音0.4至10秒')
    samples=array.array('h',raw)
    if math.sqrt(sum(x*x for x in samples)/len(samples))<80:
        raise ValueError('声音太小，请靠近麦克风')
    return raw

def recognize(raw):
    validate_pcm(raw)
    fd,path=tempfile.mkstemp(suffix='.wav')
    try:
        with os.fdopen(fd,'wb') as stream:
            with wave.open(stream,'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(raw)
        result=subprocess.run(['/usr/bin/python3',os.environ.get('EPAPER_ASR','/opt/cardputer-phone/asr.py'),path],
                              capture_output=True,timeout=75,check=True)
        text=json.loads(result.stdout)['text'].strip()[:120]
        if not text:raise ValueError('没有识别到语音')
        return text
    finally:
        os.unlink(path)
