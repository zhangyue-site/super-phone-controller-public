import json,unittest
from tools.analyze_tf_logs import analyze
class TfDiagnosticsTests(unittest.TestCase):
 def test_incomplete_power_loss_tail_and_no_private_echo(self):
  row={'schema':1,'state':{'usb':1,'peer':1,'adb':5,'adbError':2,'online':0,'secret':'do-not-echo'}}
  result=analyze('--- USB ---\n'+json.dumps(row)+'\n{"broken":')
  self.assertEqual(result['records'],1)
  self.assertIn('拒绝',result['finding']);self.assertNotIn('do-not-echo',str(result))
 def test_ip_or_adb_not_internet_success(self):
  row={'schema':1,'state':{'usb':1,'peer':1,'adb':3,'online':0}}
  self.assertIn('尚未接入',analyze(json.dumps(row))['finding'])
 def test_no_valid_records(self):self.assertEqual(analyze('garbage')['records'],0)
