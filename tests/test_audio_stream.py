import io,unittest
from display_service.audio_stream import read_chunks
class AudioStreamTests(unittest.TestCase):
 def test_proxy_can_coalesce_small_board_chunks(self):
  raw=b'\1\0'*26357
  stream=io.BytesIO(('%x\r\n'%len(raw)).encode()+raw+b'\r\n0\r\n\r\n')
  self.assertEqual(read_chunks(stream),raw)
 def test_total_recording_limit_is_enforced_for_single_or_multiple_chunks(self):
  for stream in [io.BytesIO(b'4e201\r\n'),io.BytesIO(b'4e200\r\n'+b'\0'*320000+b'\r\n1\r\na\r\n0\r\n\r\n')]:
   with self.assertRaises(ValueError):read_chunks(stream)
 def test_truncated_or_invalid_framing_is_rejected(self):
  for raw in [b'bad\n',b'2\r\na',b'0\r\nTrailer: x\r\n\r\n']:
   with self.assertRaises(ValueError):read_chunks(io.BytesIO(raw))
