import hashlib,hmac,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from display_service import app_ota

class AppOtaTests(unittest.TestCase):
 def setUp(self):
  self.now=[100.0];self.auth=app_ota.Authority(clock=lambda:self.now[0]);self.keys={"one":"secret1","two":"secret2"}
  self.entry={"version":"ci99","sha256":"a"*64,"size":4096}
  self.release=patch.object(app_ota.firmware,"release",return_value=(self.entry,b"x"*4096));self.release.start();self.addCleanup(self.release.stop)
 def challenge(self,device="one"):
  return self.auth.challenge(device,self.keys)
 def proof(self,c,key="secret1"):
  return hmac.new(key.encode(),b"PCFLASH1\n"+c["device"].encode()+b"\n"+bytes.fromhex(c["challenge"]),hashlib.sha256).hexdigest()
 def grant(self,c):return self.auth.authorize(c["device"],c["challenge"],self.proof(c),self.keys)
 def test_proof_download_scope_and_one_use(self):
  c=self.challenge();g=self.grant(c)
  self.assertEqual(g["sha256"],"a"*64)
  self.assertEqual(self.auth.image(g["ticket"])[1],b"x"*4096)
  with self.assertRaises(ValueError):self.grant(c)
  with self.assertRaises(ValueError):self.auth.image("secret1")
 def test_expiry_bad_proof_and_unknown_device(self):
  c=self.challenge();self.now[0]+=121
  with self.assertRaises(ValueError):self.grant(c)
  c=self.challenge()
  with self.assertRaises(ValueError):self.auth.authorize("two",c["challenge"],self.proof(c),self.keys)
  c=self.challenge()
  with self.assertRaises(ValueError):self.auth.authorize("one",c["challenge"],"b"*64,self.keys)
  with self.assertRaises(ValueError):self.challenge("missing")
  c=self.challenge();g=self.grant(c);self.now[0]+=301
  with self.assertRaises(ValueError):self.auth.image(g["ticket"])
 def test_concurrent_replay_has_only_one_winner(self):
  c=self.challenge();results=[]
  def run():
   try:self.grant(c);results.append(True)
   except ValueError:results.append(False)
  ts=[threading.Thread(target=run) for _ in range(8)]
  for t in ts:t.start()
  for t in ts:t.join()
  self.assertEqual(results.count(True),1)
 def test_bounded_challenges_and_grants(self):
  for _ in range(4):self.challenge()
  with self.assertRaises(ValueError):self.challenge()
 def test_immutable_hash_selected_even_after_current_changes(self):
  c=self.challenge();g=self.grant(c)
  self.entry["sha256"]="b"*64
  self.auth.image(g["ticket"])
  self.assertEqual(app_ota.firmware.release.call_args.args,("one","a"*64))

class AppOtaHttpTests(unittest.TestCase):
 def test_real_http_proof_download_and_denied_general_api(self):
  import http.client
  from http.server import ThreadingHTTPServer
  from display_service import app
  with tempfile.TemporaryDirectory() as tmp:
   config=Path(tmp)/"devices.json";config.write_text(json.dumps({"one":"secret1"}))
   server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
   thread=threading.Thread(target=server.serve_forever);thread.start()
   def request(method,path,obj=None,token=None):
    conn=http.client.HTTPConnection(*server.server_address,timeout=5)
    headers={"Authorization":"Bearer "+token} if token else {}
    conn.request(method,path,json.dumps(obj) if obj else None,headers)
    res=conn.getresponse();body=res.read();status=res.status;conn.close();return status,body
   try:
    with patch.object(app,"CONFIG",config),patch.object(app_ota,"AUTHORITY",app_ota.Authority()),patch.object(app_ota.firmware,"release",return_value=({"version":"ci99","size":4096,"sha256":"a"*64},b"x"*4096)):
     code,raw=request("POST","/app-ota/challenge",{"device":"one"});self.assertEqual(code,200);c=json.loads(raw)
     proof=hmac.new(b"secret1",b"PCFLASH1\n"+b"one\n"+bytes.fromhex(c["challenge"]),hashlib.sha256).hexdigest()
     obj=dict(device="one",challenge=c["challenge"],proof=proof)
     code,raw=request("POST","/app-ota/authorize",obj);self.assertEqual(code,200);grant=json.loads(raw)
     self.assertEqual(request("GET","/app-ota/image",token=grant["ticket"]),(200,b"x"*4096))
     self.assertEqual(request("GET","/firmware/image",token=grant["ticket"])[0],401)
     self.assertEqual(request("POST","/app-ota/authorize",obj)[0],403)
     self.assertEqual(request("GET","/app-ota/image")[0],403)
   finally:server.shutdown();server.server_close();thread.join()
