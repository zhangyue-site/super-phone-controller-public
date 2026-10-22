"""Enforce the USB architecture boundary: ADB is input-only."""
import re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AdbBoundaryTests(unittest.TestCase):
 def test_adb_command_type_has_only_keyboard_input(self):
  source=(ROOT/'firmware-epaper/main/adb_command.h').read_text()
  self.assertRegex(source,r'enum class AdbOp \{TYPE_TEXT\}')
  self.assertIn('ADB_INPUT_B64',source)
  for forbidden in ('SCREENSHOT','OBSERVE','TAP','SWIPE','LAUNCH','screencap','input tap','input swipe','am start'):
   self.assertNotIn(forbidden,source)
 def test_adb_transport_has_no_screen_or_touch_commands(self):
  source=(ROOT/'firmware-epaper/main/adb_local.cpp').read_text()
  for forbidden in ('observation_command','uiautomator','dumpsys activity','screencap','input tap','input swipe','am start'):
   self.assertNotIn(forbidden,source)
  self.assertIn('queued_command.op!=AdbOp::TYPE_TEXT',source)
 def test_board_dialogue_accepts_only_type_text(self):
  source=(ROOT/'firmware-epaper/main/dialogue.cpp').read_text()
  self.assertIn('bool valid=!strcmp(op,"type_text")',source)
  for forbidden in ('"screenshot"','"observe"','"tap"','"swipe"','"launch"','"home"','"back"'):
   self.assertNotIn(forbidden,source)
