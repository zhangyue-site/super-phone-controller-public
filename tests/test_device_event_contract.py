import json,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from display_service import events
class DeviceEventContract(unittest.TestCase):
 def test_firmware_event_names_are_accepted(self):
  names=set()
  for path in (Path(__file__).parents[1]/'firmware-epaper/main').glob('*.cpp'):
   names.update(re.findall(r'controller_event\("([a-z_]+)"',path.read_text()))
  self.assertTrue(names)
  self.assertEqual(names-events.EVENTS,set())
 def test_mixed_numeric_batch_is_ingested_and_deduplicated(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(events.control,'ROOT',Path(tmp)):
   names=['boot','touch_down','touch_up','hid','voice_finish','ai_home','stop']
   raw='\n'.join(json.dumps(dict(boot=7,seq=i,ms=i*20,event=name,page=5,a=1,b=0,result=1)) for i,name in enumerate(names)).encode()
   self.assertEqual(events.ingest('test-board',raw),len(names))
   self.assertEqual(events.ingest('test-board',raw),0)
   self.assertEqual([r['event'] for r in events.tail('test-board')],names)
 def test_unknown_event_cannot_enter_numeric_log(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(events.control,'ROOT',Path(tmp)):
   raw=json.dumps(dict(boot=7,seq=1,ms=20,event='private_text',page=5,a=1,b=0,result=1)).encode()
   with self.assertRaises(ValueError):events.ingest('test-board',raw)
   self.assertEqual(events.tail('test-board'),[])
if __name__=='__main__':unittest.main()
