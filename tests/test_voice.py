import array,unittest
from display_service.voice import validate_pcm
class VoiceTests(unittest.TestCase):
 def test_valid_audio(self):
  raw=array.array('h',[600,-600]*4000).tobytes()
  self.assertEqual(validate_pcm(raw),raw)
 def test_rejects_empty_short_odd_and_long(self):
  for raw in (b'',b'\0'*100,b'\1'*12801,b'\1'*320002):
   with self.assertRaises(ValueError):validate_pcm(raw)
 def test_rejects_silence(self):
  with self.assertRaises(ValueError):validate_pcm(b'\0'*16000)
