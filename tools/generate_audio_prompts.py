"""Generate bounded offline Mandarin prompts on macOS (say + afconvert).

Run only when changing phrases; committed PCM needs no TTS service at runtime.
16 kHz, mono, signed little endian PCM, expanded to stereo by the voice worker.
"""
from pathlib import Path
import subprocess, tempfile, wave

ROOT = Path(__file__).resolve().parents[1]
PHRASES = {
    'ready': '连接就绪，请说话',
    'recognized': '已识别，请继续说',
    'failed': '这次未完成，请查看屏幕',
    'stopped': '已停止',
    'test': '这是语音播报试听',
}

def main():
    target = ROOT / 'firmware-epaper/main/audio'
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        for name, text in PHRASES.items():
            aiff, wav = Path(temp)/f'{name}.aiff', Path(temp)/f'{name}.wav'
            subprocess.run(['say', '-v', 'Tingting', '-r', '210', '-o', str(aiff), text], check=True)
            subprocess.run(['afconvert', str(aiff), str(wav), '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1'], check=True)
            with wave.open(str(wav)) as stream:
                assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (1,2,16000)
                pcm = stream.readframes(stream.getnframes())
            assert 0 < len(pcm) <= 96000
            (target/f'{name}.pcm').write_bytes(pcm)
            print(name, len(pcm))

if __name__ == '__main__':
    main()
