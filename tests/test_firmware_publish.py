import hashlib,json,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from display_service import firmware

def image(version='2026.10.21-cmd1',project='phone_controller_epaper'):
 header=bytearray(24);header[0]=0xe9;header[1]=1;header[12:14]=struct.pack('<H',9);header[23]=1
 desc=bytearray(256);desc[:4]=struct.pack('<I',0xabcd5432);desc[16:16+len(version)]=version.encode();desc[48:48+len(project)]=project.encode()
 payload=desc+b'\x12'*1000
 checksum=0xef
 for byte in payload:checksum^=byte
 blob=bytes(header)+struct.pack('<II',0x3c000020,len(payload))+payload
 blob+=b'\0'*((15-len(blob)%16)%16)+bytes([checksum])
 return blob+hashlib.sha256(blob).digest()

class PublishTests(unittest.TestCase):
 def test_stage_then_activate_immutable_private_artifact(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(firmware,'ROOT',Path(temp)):
   blob=image();entry=firmware.publish('epaper-01',blob,'a'*40)
   folder=Path(temp)/'epaper-01'
   self.assertFalse((folder/'current.json').exists())
   self.assertEqual(firmware.release('epaper-01',entry['sha256'])[1],blob)
   firmware.publish('epaper-01',blob,'a'*40,activate=True)
   self.assertEqual(firmware.manifest('epaper-01').splitlines()[-1],b'2026.10.21-cmd1')
   self.assertEqual((folder/(entry['sha256']+'.bin')).stat().st_mode&0o777,0o600)
 def test_corrupt_and_wrong_target_images_never_change_current(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(firmware,'ROOT',Path(temp)):
   firmware.publish('epaper-01',image(),'a'*40,activate=True)
   current=(Path(temp)/'epaper-01/current.json').read_bytes()
   bad=bytearray(image());bad[-1]^=1
   for blob in (bytes(bad),image(project='other_project'),b'bad'*400):
    with self.assertRaises(ValueError):firmware.publish('epaper-01',blob,'a'*40,activate=True)
   self.assertEqual((Path(temp)/'epaper-01/current.json').read_bytes(),current)
 def test_activation_keeps_previous_release(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(firmware,'ROOT',Path(temp)):
   old=firmware.publish('epaper-01',image(),'a'*40,activate=True)
   firmware.publish('epaper-01',image('2026.10.21-cmd2'),'b'*40,activate=True)
   self.assertEqual(json.loads((Path(temp)/'epaper-01/previous.json').read_text())['sha256'],old['sha256'])

 def test_old_cloud_build_cannot_replace_newer_current(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(firmware,'ROOT',Path(temp)):
   new=firmware.publish('epaper-01',image('2026.10.21-new'),'b'*40,activate=True,generation=20)
   with self.assertRaises(ValueError):firmware.publish('epaper-01',image('2026.10.21-old'),'a'*40,activate=True,generation=19)
   self.assertEqual(firmware.release('epaper-01')[0]['sha256'],new['sha256'])
