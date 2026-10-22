"""Raw ADB identity check via Mac localhost USB forwarding, never via Wi-Fi.
Diagnostic only, not proof the board USB network works.
Prepare on authorized USB phone: adb -P5038 -s SERIAL tcpip 5555;
then adb -P5038 -s SERIAL forward tcp:15555 tcp:5555.
Remove forwarding and restore `adb usb` after the test.
"""
import socket,struct,time
from pathlib import Path
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import padding,utils

CNXN=0x4e584e43;AUTH=0x48545541;OPEN=0x4e45504f;OKAY=0x59414b4f;WRTE=0x45545257;CLSE=0x45534c43
root=Path(__file__).resolve().parents[1]
key=serialization.load_pem_private_key((root/'private-backups/board-adb.pem').read_bytes(),None)
# Rebuild public identity without exposing a private header in diagnostic output.
import base64
num=key.public_key().public_numbers();n=num.n
raw=struct.pack('<II',64,(-pow(n,-1,1<<32))&0xffffffff)+n.to_bytes(256,'little')+((1<<4096)%n).to_bytes(256,'little')+struct.pack('<I',num.e)
pub=base64.b64encode(raw)+b' epaper@controller\0'
with socket.create_connection(('127.0.0.1',15555),timeout=3) as sock:
 sock.settimeout(30)
 def exact(size):
  out=b''
  while len(out)<size:
   part=sock.recv(size-len(out))
   if not part:raise RuntimeError('ADB disconnected')
   out+=part
  return out
 def send(cmd,a,b,data=b''):
  sock.sendall(struct.pack('<6I',cmd,a,b,len(data),sum(data)&0xffffffff,cmd^0xffffffff)+data)
 def receive():
  cmd,a,b,size,check,magic=struct.unpack('<6I',exact(24))
  if size>4096 or magic!=(cmd^0xffffffff):raise RuntimeError('Invalid ADB header')
  data=exact(size)
  if sum(data)&0xffffffff!=check:raise RuntimeError('Invalid ADB checksum')
  return cmd,a,b,data
 send(CNXN,0x01000000,4096,b'host::\0');signed=False;public=False
 while True:
  cmd,a,b,data=receive()
  if cmd==CNXN:break
  if cmd!=AUTH or a!=1 or len(data)!=20:raise RuntimeError('Unsupported ADB authentication')
  if not signed:
   send(AUTH,2,0,key.sign(data,padding.PKCS1v15(),utils.Prehashed(hashes.SHA1())));signed=True
  elif not public:
   send(AUTH,3,0,pub);public=True;print('Waiting for phone authorization of board identity.',flush=True)
  else:raise RuntimeError('Phone rejected board identity')
 send(OPEN,1,0,b'shell:echo __CONTROLLER_ADB_OK__\0');result=b''
 while True:
  cmd,a,b,data=receive()
  if cmd==OKAY and b==1:continue
  if cmd==WRTE and b==1:
   result=(result+data)[-4096:];send(OKAY,1,a)
  elif cmd==CLSE and b==1:
   send(CLSE,1,a);break
  else:raise RuntimeError('Unexpected ADB stream')
 if b'__CONTROLLER_ADB_OK__' not in result:raise RuntimeError('Read-only ADB probe failed')
 print('Board RSA identity and read-only shell verified through USB forwarding.')
