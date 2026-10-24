"""Structure fence only for a certified blank-launcher upward gesture."""
import base64,zlib
from PIL import Image,ImageFilter,ImageChops
def structure_metrics(a,b):
 if (a.get('w'),a.get('h'))!=(b.get('w'),b.get('h')):return None
 try:
  def edges(sig):
   raw=zlib.decompress(base64.b64decode(sig['pixels']))
   if len(raw)!=15360:raise ValueError('signature size')
   im=Image.frombytes('L',(96,160),raw).filter(ImageFilter.GaussianBlur(1)).filter(ImageFilter.FIND_EDGES).crop((2,2,94,158))
   return bytes(1 if v>=32 else 0 for v in im.getdata())
  x,y=edges(a),edges(b);fraction=sum(v!=w for v,w in zip(x,y))/len(x);anchors=min(sum(x),sum(y))
  return dict(same=anchors>=100 and fraction<.002,changed_fraction=round(fraction,6),anchors=anchors)
 except (KeyError,ValueError,TypeError,zlib.error):return None
def same_launcher_structure(a,b):
 result=structure_metrics(a,b)
 return bool(result and result['same'])

def settings_icon_core(raw,bounds):
 from .skill_engine import region
 if not isinstance(bounds,list) or len(bounds)!=4 or any(type(v)!=int for v in bounds):raise ValueError('设置图标区域无效')
 x1,y1,x2,y2=bounds;w=x2-x1;h=y2-y1
 if not 24<=w<=250 or not 24<=h<=180:raise ValueError('设置图标区域大小无效')
 return region(raw,[x1+w//4,y1+h//4,x2-w//4,y2-h//4])

def core_difference(reference,raw):
 from .skill_engine import region
 import os,json,time
 from pathlib import Path
 try:
  current=region(raw,reference['box']);a=zlib.decompress(base64.b64decode(reference['pixels']));b=zlib.decompress(base64.b64decode(current['pixels']))
  if (reference['w'],reference['h'])!=(current['w'],current['h']) or len(a)!=len(b) or not a:return None
  delta=[abs(x-y) for x,y in zip(a,b)];result=dict(mean=sum(delta)/len(delta),large_fraction=round(sum(v>8 for v in delta)/len(delta),6),max=max(delta),box=reference['box'])
  location=os.environ.get('EPAPER_ICON_DIAGNOSTIC_DIR')
  if location:
   dest=Path(location);dest.mkdir(mode=0o700,parents=True,exist_ok=True)
   try:
    with (dest/'capture.json').open('x') as f:json.dump(result,f)
   except FileExistsError:pass
   else:
    Image.frombytes('RGB',(reference['w'],reference['h']),a).save(dest/'reference.png')
    Image.frombytes('RGB',(current['w'],current['h']),b).save(dest/'current.png')
  return result
 except (ValueError,KeyError,TypeError,zlib.error,OSError):return None

def quantized_core_matches(reference,raw):
 # This branch is only used for a certified desktop Settings icon and is
 # combined with the full-screen strong-edge fence by GeneralNavigator.
 difference=core_difference(reference,raw)
 return bool(difference and difference['mean']<=1.0 and difference['max']<=8)
