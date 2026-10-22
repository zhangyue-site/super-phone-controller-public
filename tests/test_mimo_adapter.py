"""Exercise the deployed collector adapter with a fake official HTTP response."""
import importlib.util,json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from display_service import renewal

class MiMoAdapterTest(unittest.TestCase):
 def test_session_expired_body_reaches_renewal_trigger(self):
  dependencies={
   'server_codex_quota':types.SimpleNamespace(save_private=lambda *a:None,request_json=lambda *a:None,PUSH_URL='',PUSH_TOKEN_FILE=Path('/unused')),
   'mimo_session':types.SimpleNamespace(renew=lambda:None),
   'renewal_policy':renewal}
  with patch.dict('sys.modules',dependencies):
   spec=importlib.util.spec_from_file_location('mimo_adapter_under_test',Path(__file__).parents[1]/'server_integrations/server_mimo_quota.py')
   module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,*args):return json.dumps({'code':'session_expired'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  with tempfile.TemporaryDirectory() as root:
   module.AUTH=Path(root)/'auth.json';module.AUTH.write_text('{"cookie_header":"test-only"}')
   with patch.object(module.urllib.request,'build_opener',return_value=Opener()):
    with self.assertRaisesRegex(RuntimeError,'^session_expired$'):module.collect()
