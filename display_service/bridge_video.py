"""Cloud-only decoding of bounded compressed bridge uploads; no phone or ADB access."""
import io,json,re,subprocess,threading
from PIL import Image
MAX_UPLOAD=2*1024*1024
DECODE_SLOTS=threading.BoundedSemaphore(1)

def decode(payload,codec):
 if not isinstance(payload,bytes) or not 1<=len(payload)<=MAX_UPLOAD:raise ValueError("video size")
 if codec not in ("jpeg","h264-annexb"):raise ValueError("video codec")
 if not DECODE_SLOTS.acquire(blocking=False):raise ValueError("decoder busy")
 try:
  if codec=="h264-annexb":
   units=re.split(b"\x00\x00(?:\x00)?\x01",payload)
   kinds={u[0]&31 for u in units[1:] if u}
   if units[0] or not {5,7,8}<=kinds:raise ValueError("independent IDR with SPS/PPS required")
   try:
    probe=subprocess.run(["ffprobe","-v","error","-f","h264","-i","pipe:0","-show_entries","stream=width,height","-of","json"],input=payload,capture_output=True,timeout=3,check=True)
    streams=json.loads(probe.stdout)["streams"]
    if len(streams)!=1:raise ValueError("video stream count")
    w,h=streams[0]["width"],streams[0]["height"]
    if not 1<=w<=4096 or not 1<=h<=4096 or w*h>4194304:raise ValueError("video dimensions")
    result=subprocess.run(["ffmpeg","-nostdin","-v","error","-threads","1","-filter_threads","1","-max_alloc","33554432","-protocol_whitelist","pipe","-f","h264","-i","pipe:0","-frames:v","1","-vf","scale=w=720:h=1280:force_original_aspect_ratio=decrease","-f","image2pipe","-c:v","mjpeg","pipe:1"],input=payload,capture_output=True,timeout=4,check=True)
    payload=result.stdout
   except (OSError,subprocess.SubprocessError,KeyError,TypeError,json.JSONDecodeError) as error:raise ValueError("video decode failed") from error
  try:
   with Image.open(io.BytesIO(payload)) as image:
    w,h=image.size
    if image.format!="JPEG" or not 1<=w<=4096 or not 1<=h<=4096 or w*h>4194304:raise ValueError("JPEG dimensions")
    image.load();image=image.convert("RGB");image.thumbnail((720,1280));out=io.BytesIO();image.save(out,format="JPEG",quality=80)
    jpeg=out.getvalue()
    if len(jpeg)>MAX_UPLOAD:raise ValueError("JPEG size")
    return jpeg,image.width,image.height
  except (OSError,Image.DecompressionBombError) as error:raise ValueError("invalid JPEG") from error
 finally:DECODE_SLOTS.release()
