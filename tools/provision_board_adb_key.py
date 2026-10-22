"""Generate a new board-only ADB identity, never copy the Mac's private key."""
import base64,os,struct
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
root=Path(__file__).resolve().parents[1]
backup=root/'private-backups/board-adb.pem'
backup.parent.mkdir(mode=0o700,exist_ok=True)
if backup.exists():key=serialization.load_pem_private_key(backup.read_bytes(),None)
else:
 key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
 pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
 fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'wb') as out:out.write(pem)
num=key.public_key().public_numbers();n=num.n
wire=struct.pack('<II',64,(-pow(n,-1,1<<32))&0xffffffff)+n.to_bytes(256,'little')+((1<<4096)%n).to_bytes(256,'little')+struct.pack('<I',num.e)
pub=base64.b64encode(wire).decode()+' epaper@controller'
pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
path=root/'firmware-epaper/main/device_adb_keys.h'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as out:out.write('#pragma once\nstatic const char board_adb_private[]=R"KEY('+pem+')KEY";\nstatic const char board_adb_public[]="'+pub+'";\n')
print('Board-specific ADB identity prepared in ignored files; no credentials printed.')
