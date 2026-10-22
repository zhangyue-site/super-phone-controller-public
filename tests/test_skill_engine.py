import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from display_service.skill_engine import SkillStore,WorkflowSpec,ReplayEngine,signature,region
from test_wechat_nav import frame
class GenericSkillEngineTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=SkillStore(Path(self.temp.name))
  self.job=SimpleNamespace(device="generic-device",done=True,state="done",navigation_verified=True)
  self.spec=WorkflowSpec("browser.read_topic","浏览器","查资料",("topic",),"browser.results")
  self.raw=frame(0)
  self.steps=[{"signature":signature(self.raw),"target":region(self.raw,[50,200,200,300]),"observation":{"screen":"browser_home"},"receipt":{"op":"hid_pointer","id":"a"*32,"ok":True}}]
 def remember(self):
  self.store.remember(self.job,self.spec,{"topic":"天气"},self.steps,(240,480),{"op":"hid_home","id":"b"*32,"ok":True},{"verified":True,"terminal":"browser.results","parameters":{"topic":"天气"}})
 def test_collector_is_generic_and_compiles_separate_specialized_type(self):
  self.assertEqual(self.store.catalog(self.job.device)[0]["kind"],"collector")
  self.remember();self.store.save_last(self.job.device)
  items=self.store.catalog(self.job.device)
  self.assertEqual([i["kind"] for i in items],["collector","specialized"])
  recipe=self.store.find(self.job.device,self.spec,{"topic":"新闻"})
  self.assertEqual(recipe["workflow"],"browser.read_topic")
  self.assertTrue(recipe["requiresFinalVision"])
  self.assertIsNotNone(ReplayEngine.step(recipe,0,self.raw))
  self.assertIsNone(self.store.find("other-device",self.spec,{"topic":"天气"}))
 def test_no_receipt_or_final_proof_cannot_compile(self):
  self.steps[0]["receipt"]["ok"]=False
  with self.assertRaises(ValueError):self.remember()
 def test_failed_terminal_task_cannot_be_saved(self):
  self.remember();self.job.state="error"
  with self.assertRaises(ValueError):self.store.save_last(self.job.device)
 def test_policy_version_or_workflow_change_cannot_reuse_recipe(self):
  self.remember();self.store.save_last(self.job.device)
  changed=WorkflowSpec(self.spec.id,self.spec.group,self.spec.name,self.spec.parameters,self.spec.terminal,version=2)
  self.assertIsNone(self.store.find(self.job.device,changed,{"topic":"天气"}))
 def test_frame_change_returns_to_adapter_instead_of_blind_replay(self):
  self.remember();self.store.save_last(self.job.device)
  recipe=self.store.find(self.job.device,self.spec,{"topic":"天气"})
  self.assertIsNone(ReplayEngine.step(recipe,0,frame(1)))
