import struct,unittest
from tools.check_s3_uvc import inspect
def fixture(packet=512,transfer=1):
 interface=bytes((9,4,1,0,0,14,2,0,0))
 fmt=bytes((11,0x24,6,1,1,0,1,0,0,0,0))
 frame=bytearray(30);frame[:5]=bytes((30,0x24,7,1,0))
 struct.pack_into("<HH",frame,5,640,480);struct.pack_into("<I",frame,17,100000);frame[25]=1;struct.pack_into("<I",frame,26,2000000)
 alt=bytes((9,4,1,1,1,14,2,0,0))
 endpoint=bytes((7,5,0x81,transfer,packet&255,packet>>8,1))
 body=interface+fmt+frame+alt+endpoint
 return bytes((9,2,(9+len(body))&255,(9+len(body))>>8,1,1,0,128,50))+body
class S3UvcTests(unittest.TestCase):
 def test_full_speed_mjpeg_is_only_a_candidate(self):
  result=inspect(fixture(),"full")
  self.assertEqual(result["status"],"descriptor_candidate")
  self.assertFalse(result["screen_source_verified"]);self.assertFalse(result["streaming_verified"])
  self.assertEqual(result["frames"][0]["width"],640)
 def test_high_speed_and_oversize_packet_are_not_qualified(self):
  self.assertEqual(inspect(fixture(),"high")["status"],"not_qualified")
  self.assertEqual(inspect(fixture(1024),"full")["status"],"not_qualified")
  self.assertEqual(inspect(fixture(512,2),"full")["status"],"not_qualified")
  self.assertEqual(inspect(fixture(64,2),"full")["status"],"descriptor_candidate")
 def test_missing_format_or_truncated_configuration_rejected(self):
  raw=fixture()
  with self.assertRaises(ValueError):inspect(raw[:-1],"full")
  with self.assertRaises(ValueError):inspect(raw[:9]+bytes((0,4))+raw[11:],"full")
  raw=raw.replace(bytes((11,0x24,6)),bytes((11,0x24,4)))
  self.assertEqual(inspect(raw,"full")["status"],"not_qualified")
