import unittest
from display_service.renewal import collect_with_renewal

class RenewalTest(unittest.TestCase):
 def test_healthy_session_not_rotated(self):
  calls=[]
  self.assertEqual(collect_with_renewal(lambda:{'ok':True},lambda:calls.append(1)),{'ok':True})
  self.assertEqual(calls,[])
 def test_auth_failures_renew_once_and_retry(self):
  for reason in ('http_401','http_403','session_expired'):
   attempts=[];renewed=[]
   def fetch():
    attempts.append(1)
    if len(attempts)==1:raise RuntimeError(reason)
    return {'ok':True}
   self.assertTrue(collect_with_renewal(fetch,lambda:renewed.append(1))['ok'])
   self.assertEqual((len(attempts),len(renewed)),(2,1))
 def test_network_error_not_treated_as_auth(self):
  renewed=[]
  def fetch():raise RuntimeError('network_unavailable')
  with self.assertRaisesRegex(RuntimeError,'network_unavailable'):
   collect_with_renewal(fetch,lambda:renewed.append(1))
  self.assertEqual(renewed,[])
 def test_rejected_session_does_not_loop(self):
  calls=[]
  def fetch():raise RuntimeError('http_401')
  with self.assertRaisesRegex(RuntimeError,'http_401'):
   collect_with_renewal(fetch,lambda:calls.append(1))
  self.assertEqual(len(calls),1)
