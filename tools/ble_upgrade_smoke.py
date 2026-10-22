#!/usr/bin/env python3
"""Real BLE OTA smoke test. No ADB; no long-lived credentials on this client."""
import argparse,asyncio,hashlib,json,subprocess,time
from pathlib import Path
from bleak import BleakClient
SVC="6f6f7461-2d6f-7461-0000-000000000001"
CTRL=SVC[:-1]+"2";STAT=SVC[:-1]+"3";INFO=SVC[:-1]+"4";AUTH=SVC[:-1]+"5"
BASE="https://erweima.zhangyue.site/phone-controller/app-ota/"
def http(path,obj=None,ticket=None):
 args=["curl","--max-time","120","-fsS","--config","-",BASE+path]
 cfg=""
 if ticket:cfg='header = "Authorization: Bearer '+ticket+'"\n'
 if obj is not None:args+=["-H","Content-Type: application/json","--data-binary",json.dumps(obj)]
 p=subprocess.run(args,input=cfg.encode(),capture_output=True)
 if p.returncode:raise RuntimeError("HTTP failed curl code "+str(p.returncode))
 return p.stdout
def target(data):
 assert data[0]==0xe9 and data[12:14]==b"\x09\x00" and len(data)<=0x340000
 return data[48:80].split(b"\0")[0].decode(),data[176:208].hex()
async def read_info(client):
 return json.loads(bytes(await client.read_gatt_char(INFO)))
async def main(args):
 old=None
 disconnected=asyncio.Event()
 async with BleakClient(args.address,disconnected_callback=lambda _:disconnected.set(),timeout=20) as client:
  if client.services.get_characteristic(INFO):old=await read_info(client)
  if args.image:
   data=Path(args.image).read_bytes()
  else:
   if old is None:raise RuntimeError("Bootstrap firmware required")
   challenge=json.loads(await asyncio.to_thread(http,"challenge",{"device":old["device"]}))
   await client.write_gatt_char(AUTH,bytes.fromhex(challenge["challenge"]),response=True)
   proof=bytes(await client.read_gatt_char(AUTH)).hex()
   grant=json.loads(await asyncio.to_thread(http,"authorize",dict(device=old["device"],challenge=challenge["challenge"],proof=proof)))
   data=await asyncio.to_thread(http,"image",None,grant["ticket"])
   assert len(data)==grant["size"] and hashlib.sha256(data).hexdigest()==grant["sha256"]
   print("REAL_BOARD_AUTH_DOWNLOAD_PASS",grant["version"],len(data),flush=True)
  if args.download_only:
   print("DOWNLOAD_ONLY_NO_FLASH",flush=True);return
  version,elf=target(data)
  state=[0,0,0,0];terminal=[];ready=asyncio.Event();receiving=asyncio.Event();began=time.monotonic();last_status=[None,None]
  def notify(_,raw):
   state[:]=raw
   key=(raw[0],raw[1]//10)
   if key!=tuple(last_status) or raw[2]:
    print("BLE_STATUS",list(raw),"elapsed",round(time.monotonic()-began,1),flush=True);last_status[:]=key
   if raw[0]==1:receiving.set()
   if raw[0] in (3,4) and not terminal:terminal[:]=raw;ready.set()
  await client.start_notify(STAT,notify)
  await client.write_gatt_char(CTRL,b"\x01"+len(data).to_bytes(4,"little")+hashlib.sha256(data).digest(),response=True)
  await asyncio.wait_for(receiving.wait(),10)
  chunk=min(511,client.mtu_size-4);last=-1;started=time.monotonic()
  print("BLE_MTU",client.mtu_size,"chunk",chunk,flush=True)
  try:
   for offset in range(0,len(data),chunk):
    if state[0]==4:raise RuntimeError("Board transfer error "+str(state[2]))
    await client.write_gatt_char(CTRL,b"\x02"+data[offset:offset+chunk],response=True)
    pct=(offset+chunk)*100//len(data)
    if pct//10!=last:
     last=pct//10;print("BLE_TRANSFER",min(100,pct),flush=True)
   await client.write_gatt_char(CTRL,b"\x03",response=True)
   await asyncio.wait_for(ready.wait(),25)
   if not terminal or terminal[0]!=3 or terminal[2]!=0:raise RuntimeError("Board verification failed "+str(terminal))
   print("BLE_IMAGE_VERIFIED",version,"seconds",round(time.monotonic()-started,1),flush=True)
  except BaseException:
   try:await client.write_gatt_char(CTRL,b"\x04",response=True)
   except Exception:pass
   raise
  await asyncio.wait_for(disconnected.wait(),20)
 for attempt in range(20):
  await asyncio.sleep(2)
  try:
   async with BleakClient(args.address,timeout=10) as client:
    current=await read_info(client)
    assert current["version"]==version and current["elfSha256"]==elf
    assert current["imageState"]==2
    if old:assert current["device"]==old["device"] and current["boot"]!=old["boot"]
    print("REAL_REBOOT_CONFIRMED",current["version"],"state",current["imageState"],"new_boot",old is not None,flush=True)
    return
  except Exception as error:
   print("WAIT_REBOOT",attempt,type(error).__name__,flush=True)
 raise RuntimeError("Reboot confirmation timed out")
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--address",required=True);p.add_argument("--image");p.add_argument("--download-only",action="store_true")
 asyncio.run(main(p.parse_args()))
