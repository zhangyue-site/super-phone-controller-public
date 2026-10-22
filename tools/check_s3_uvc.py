"""Offline USB configuration inspection; never opens a device or invokes ADB.
Descriptor candidacy is not proof of HDMI/screen capture or working streaming.
"""
import argparse,json,struct
from pathlib import Path

def inspect(raw,speed):
 if speed not in ("full","high","low"):raise ValueError("invalid speed")
 if len(raw)<9 or raw[0]!=9 or raw[1]!=2:raise ValueError("configuration header")
 total=int.from_bytes(raw[2:4],"little")
 if total!=len(raw):raise ValueError("configuration length")
 interface=None;video=False;fmt=False;mjpeg=set();frames=[];endpoints=[]
 offset=0
 while offset<len(raw):
  size=raw[offset]
  if size<2 or offset+size>len(raw):raise ValueError("truncated descriptor")
  d=raw[offset:offset+size];kind=d[1]
  if kind==4:
   if size<9:raise ValueError("interface descriptor")
   interface=d[2];video=d[5:7]==bytes((14,2));fmt=False
  elif kind==0x24 and video:
   if size<3:raise ValueError("video descriptor")
   if d[2]==6:
    if size<11:raise ValueError("MJPEG format descriptor")
    fmt=True;mjpeg.add(interface)
   elif d[2] in (4,10,12,16):fmt=False
   elif d[2]==7 and fmt:
    if size<26:raise ValueError("MJPEG frame descriptor")
    w,h=struct.unpack_from("<HH",d,5);buffer=struct.unpack_from("<I",d,17)[0]
    count=d[25]
    if size<26+(count*4 if count else 12):raise ValueError("frame intervals")
    intervals=list(struct.unpack_from("<"+"I"*(count or 3),d,26))
    if not w or not h or not buffer or any(x==0 for x in (intervals if count else intervals[:2])):raise ValueError("frame values")
    if not count and intervals[0]>intervals[1]:raise ValueError("interval range")
    frames.append(dict(interface=interface,width=w,height=h,max_frame_bytes=buffer,intervals_100ns=intervals,continuous=not bool(count)))
  elif kind==5 and video:
   if size<7:raise ValueError("endpoint descriptor")
   address=d[2];transfer=d[3]&3;packet=int.from_bytes(d[4:6],"little")
   if address&128 and transfer in (1,2):
    # S3 UVC driver has a 512-byte isochronous payload limit.
    limit=512 if transfer==1 else 64
    endpoints.append(dict(interface=interface,address=address,transfer="isoc" if transfer==1 else "bulk",packet_bytes=packet,full_speed_candidate=0<packet<=limit))
  offset+=size
 suitable=[e for e in endpoints if e["interface"] in mjpeg and e["full_speed_candidate"]]
 candidate=speed=="full" and bool(frames) and bool(suitable)
 return dict(status="descriptor_candidate" if candidate else "not_qualified",speed=speed,frames=frames,endpoints=endpoints,screen_source_verified=False,streaming_verified=False,
             note="Requires real Full-Speed MJPEG streaming, screen-source verification, USB role/power and AOA concurrency tests. High-Speed descriptors cannot prove Full-Speed fallback.")

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument("descriptor",type=Path,help="One complete raw USB configuration descriptor")
 parser.add_argument("--speed",required=True,choices=("full","high","low"),help="Actual speed at descriptor collection")
 args=parser.parse_args()
 try:result=inspect(args.descriptor.read_bytes(),args.speed)
 except (OSError,ValueError) as error:parser.error(str(error))
 print(json.dumps(result,ensure_ascii=False,indent=2))
 return 0 if result["status"]=="descriptor_candidate" else 2

if __name__=="__main__":raise SystemExit(main())
