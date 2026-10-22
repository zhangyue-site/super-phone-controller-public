import os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ImeRestoreTests(unittest.TestCase):
 def run_script(self,fail=False,existing=False,interrupt=False):
  with tempfile.TemporaryDirectory() as td:
   t=pathlib.Path(td);src=t/'script.cpp';exe=t/'generator'
   src.write_text('#include "adb_command.h"\n#include <cstdio>\nint main(){controller::AdbCommand c{controller::AdbOp::TYPE_TEXT};strcpy(c.text_b64,"5p2O5rSL");char b[4096];if(!controller::adb_command(c,b,sizeof(b)))return 1;puts(b);}')
   subprocess.run(['c++','-std=c++17','-I',str(ROOT/'firmware-epaper/main'),str(src),'-o',str(exe)],check=True)
   script=subprocess.check_output([str(exe)]).decode().replace('/data/local/tmp/controller-ime.restore',str(t/'restore'))
   for name,body in {'settings':'echo com.example.original/.IME','ime':'echo "$*" >> "$TRACE"','am':'if [ "$INTERRUPT" = 1 ]; then kill -TERM "$PPID"; exit 0; fi; if [ "$FAIL" = 1 ]; then exit 1; fi'}.items():
    f=t/name;f.write_text('#!/bin/sh\n'+body+'\n');f.chmod(0o700)
   if existing:(t/'restore').write_text('com.old/.IME')
   env=dict(os.environ,PATH=str(t)+':'+os.environ['PATH'],TRACE=str(t/'trace'),FAIL='1' if fail else '0',INTERRUPT='1' if interrupt else '0')
   p=subprocess.run(['sh','-c',script],env=env,capture_output=True)
   return p.returncode,(t/'trace').read_text() if (t/'trace').exists() else '',(t/'restore').exists()
 def test_success_restores_original_immediately(self):
  rc,trace,mark=self.run_script();self.assertEqual(rc,0);self.assertIn('set com.android.adbkeyboard/.AdbIME',trace);self.assertTrue(trace.strip().endswith('set com.example.original/.IME'));self.assertFalse(mark)
 def test_broadcast_failure_restores_original(self):
  rc,trace,mark=self.run_script(fail=True);self.assertNotEqual(rc,0);self.assertTrue(trace.strip().endswith('set com.example.original/.IME'));self.assertFalse(mark)
 def test_unrecovered_marker_blocks_new_switch(self):
  rc,trace,mark=self.run_script(existing=True);self.assertNotEqual(rc,0);self.assertFalse(trace);self.assertTrue(mark)

 def test_interruption_restores_original(self):
  rc,trace,mark=self.run_script(interrupt=True);self.assertNotEqual(rc,0);self.assertTrue(trace.strip().endswith('set com.example.original/.IME'));self.assertFalse(mark)
