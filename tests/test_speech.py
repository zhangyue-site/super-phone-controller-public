import unittest,io,wave
from unittest.mock import patch
from display_service.speech import pcm_from_wav
class SpeechTests(unittest.TestCase):
 def test_pcm_bounds_and_format(self):
  out=io.BytesIO()
  with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\1\0'*1600)
  self.assertEqual(pcm_from_wav(out.getvalue()),b'\1\0'*1600)
  with self.assertRaises(ValueError):pcm_from_wav(b'bad')
 def test_dialogue_bitmap_has_large_stop_area(self):
  from display_service.render import render_dialogue
  im=render_dialogue('这是聊天回答和手机执行结果。','done')
  self.assertEqual(im.size,(200,200));self.assertEqual(len(im.tobytes()),5000)
  self.assertEqual(im.getpixel((8,132)),0)
