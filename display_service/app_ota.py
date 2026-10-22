"""BLE possession proof grants only short-lived, immutable firmware downloads."""
import hashlib,hmac,re,secrets,threading,time
from . import firmware
HEX=re.compile(r"[0-9a-f]{64}\Z")
class Authority:
 def __init__(self,clock=time.monotonic):
  self.clock=clock;self.lock=threading.Lock();self.challenges={};self.tickets={};self.rates={}
 def _prune(self,now):
  for entries in (self.challenges,self.tickets):
   for key in list(entries):
    if entries[key][0]<=now:del entries[key]
  for key in list(self.rates):
   if self.rates[key][0]+60<=now:del self.rates[key]
 def challenge(self,device,keys):
  if not isinstance(device,str) or device not in keys or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",device):raise ValueError("device")
  with self.lock:
   now=self.clock();self._prune(now)
   count=sum(v[1]==device for v in self.challenges.values())
   rate=self.rates.get(device,(now,0))
   if count>=4 or len(self.challenges)>=256 or len(self.tickets)>=256 or rate[1]>=12:raise ValueError("rate")
   self.rates[device]=(rate[0],rate[1]+1)
   nonce=secrets.token_hex(32);self.challenges[nonce]=(now+120,device)
  return {"device":device,"challenge":nonce,"expiresIn":120}
 def authorize(self,device,nonce,proof,keys):
  if not isinstance(nonce,str) or not HEX.fullmatch(nonce) or not isinstance(proof,str) or not HEX.fullmatch(proof):raise ValueError("proof")
  with self.lock:
   now=self.clock();self._prune(now)
   item=self.challenges.pop(nonce,None)
   if item is None or item[1]!=device or device not in keys:raise ValueError("challenge")
   message=b"PCFLASH1\n"+device.encode()+b"\n"+bytes.fromhex(nonce)
   expected=hmac.new(keys[device].encode(),message,hashlib.sha256).hexdigest()
   if not hmac.compare_digest(proof,expected) or len(self.tickets)>=256:raise ValueError("proof")
   entry,_=firmware.release(device)
   ticket=secrets.token_urlsafe(32)
   self.tickets[ticket]=(now+300,device,entry["sha256"])
   return dict(version=entry["version"],size=entry["size"],sha256=entry["sha256"],ticket=ticket,expiresIn=300)
 def image(self,ticket):
  if not isinstance(ticket,str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}",ticket):raise ValueError("ticket")
  with self.lock:
   self._prune(self.clock());item=self.tickets.get(ticket)
   if item is None:raise ValueError("ticket")
  return firmware.release(item[1],item[2])
AUTHORITY=Authority()

def handle(handler,config):
 """Only these isolated endpoints bypass the general device bearer check."""
 path=handler.path
 if path not in ("/app-ota/challenge","/app-ota/authorize","/app-ota/image"):return False
 import json
 try:
  if path=="/app-ota/image" and handler.command=="GET":
   header=handler.headers.get("Authorization","")
   if not header.startswith("Bearer "):raise ValueError("auth")
   _,data=AUTHORITY.image(header[7:]);handler.reply(200,data,"application/octet-stream");return True
  if handler.command!="POST":handler.reply(405,b"{}");return True
  size=int(handler.headers.get("Content-Length","0"))
  if not 1<=size<=1024:raise ValueError("size")
  obj=json.loads(handler.rfile.read(size));keys=json.loads(config.read_text())
  if not isinstance(obj,dict):raise ValueError("body")
  if path=="/app-ota/challenge":
   if set(obj)!={"device"}:raise ValueError("fields")
   result=AUTHORITY.challenge(obj["device"],keys)
  else:
   if set(obj)!={"device","challenge","proof"}:raise ValueError("fields")
   result=AUTHORITY.authorize(obj["device"],obj["challenge"],obj["proof"],keys)
  handler.reply(200,json.dumps(result).encode())
 except (ValueError,TypeError,KeyError,OSError):handler.reply(403,b"{\"error\":\"authorization failed or expired\"}")
 return True
