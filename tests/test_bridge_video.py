import io,shutil,subprocess,unittest
from PIL import Image
from display_service.bridge_video import decode,MAX_UPLOAD
from display_service.dialogue import Mailbox

def jpeg():
 out=io.BytesIO();Image.new("RGB",(1200,1600),"blue").save(out,format="JPEG");return out.getvalue()

class BridgeVideoTests(unittest.TestCase):
 def test_jpeg_decoded_on_cloud_and_bounded(self):
  raw,w,h=decode(jpeg(),"jpeg")
  self.assertEqual((w,h),(720,960))
  with Image.open(io.BytesIO(raw)) as im:self.assertEqual(im.format,"JPEG")
 def test_unsupported_invalid_and_oversize_input(self):
  for payload,codec in ((b"bad","jpeg"),(b"bad","h264-annexb"),(jpeg(),"adb"),(b"x"*(MAX_UPLOAD+1),"jpeg")):
   with self.subTest(codec=codec):
    with self.assertRaises(ValueError):decode(payload,codec)
 @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"ffmpeg required for real H264 test")
 def test_real_h264_is_decoded_without_board_decoding(self):
  from pathlib import Path
  fixture=(Path(__file__).parent/"fixtures/bridge-blue-320x240.h264").read_bytes()
  raw,w,h=decode(fixture,"h264-annexb")
  self.assertGreater(len(raw),0);self.assertGreater(w,0);self.assertGreater(h,0)
 def test_cancel_replay_new_turn_and_freshness(self):
  now=[0];m=Mailbox(clock=lambda:now[0]);j=m.create("d","a"*16,1)
  result=m.ingest_video("d","a"*16,1,1,jpeg(),"jpeg")
  self.assertFalse(result["phone_execution"]);self.assertEqual(m.latest_video(j)[1],1)
  with self.assertRaises(ValueError):m.ingest_video("d","a"*16,1,1,jpeg(),"jpeg")
  now[0]=3
  with self.assertRaises(ValueError):m.latest_video(j)
  m.cancel("d");self.assertEqual(j.video,b"")
  with self.assertRaises(ValueError):m.ingest_video("d","a"*16,1,2,jpeg(),"jpeg")
  m.create("d","a"*16,2)
  with self.assertRaises(ValueError):m.ingest_video("d","a"*16,1,3,jpeg(),"jpeg")
 def test_stop_during_decode_discards_result(self):
  m=Mailbox();j=m.create("d","a"*16,1)
  def interrupted(payload,codec):m.cancel("d");return b"jpeg",10,10
  with self.assertRaises(ValueError):m.ingest_video("d","a"*16,1,1,b"x","jpeg",decoder=interrupted)
  self.assertEqual(j.video,b"")

class BridgeVideoHttpTests(unittest.TestCase):
 def test_authenticated_current_turn_only(self):
  import http.client,json,tempfile,threading
  from pathlib import Path
  from http.server import ThreadingHTTPServer
  from unittest.mock import patch
  from display_service import app
  from display_service.conversation import Conversation
  mailbox=Mailbox();job=mailbox.create("one","a"*16,1);conversation=Conversation(mailbox)
  with tempfile.TemporaryDirectory() as temp:
   config=Path(temp)/"devices.json";config.write_text(json.dumps(dict(one="token1",two="token2")))
   server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
   def post(token="token1",session="a"*16,frame="1"):
    connection=http.client.HTTPConnection(*server.server_address,timeout=5)
    connection.request("POST","/dialogue/video",jpeg(),{"Authorization":"Bearer "+token,"X-Voice-Session":session,"X-Voice-Sequence":"1","X-Video-Sequence":frame,"X-Video-Codec":"jpeg"})
    response=connection.getresponse();result=response.status,response.read();connection.close();return result
   try:
    with patch.object(app,"CONFIG",config),patch.object(app,"CONVERSATION",conversation):
     self.assertEqual(post(token="invalid")[0],401)
     self.assertEqual(post(token="token2")[0],409)
     self.assertEqual(post(session="b"*16)[0],409)
     status,body=post();self.assertEqual(status,200);self.assertFalse(json.loads(body)["phone_execution"])
     self.assertEqual(post()[0],409)
     mailbox.cancel("one")
     self.assertEqual(post(frame="2")[0],409);self.assertEqual(job.video,b"")
   finally:server.shutdown();server.server_close();thread.join()
