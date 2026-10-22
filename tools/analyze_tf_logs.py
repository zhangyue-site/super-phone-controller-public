#!/usr/bin/env python3
"""Analyze allowlisted board diagnostics; accepts file or USB SDLOGS stdin."""
import argparse,json,sys
KEYS=('usb','peer','adb','adbError','net','online','server','chat','asr','hid','wifi','page','voice','screenError')
REASONS={1:'USB对端没有取得本地地址',2:'ADB端口拒绝连接；确认直连手机及adbd监听状态',3:'ADB连接超时',4:'ADB套接字连接失败',5:'ADB授权或协议握手失败',6:'ADB只读命令验证失败',7:'已建立的ADB连接断开'}
def analyze(text):
 rows=[]
 for line in text.splitlines():
  try:
   r=json.loads(line)
   if not isinstance(r,dict) or r.get('schema')!=1 or not isinstance(r.get('state'),dict):continue
   state={k:v for k,v in r['state'].items() if k in KEYS and type(v) is int and 0<=v<=20}
   if not all(k in state for k in ('usb','peer','adb','online')):continue
   rows.append(state)
  except (ValueError,TypeError):continue
 if not rows:return {'records':0,'finding':'没有完整诊断记录'}
 s=rows[-1]
 if not s['usb']:finding='USB数据连接未建立'
 elif not s['peer']:finding='USB对端尚未取得本地地址'
 elif s['adb']!=3:finding=REASONS.get(s.get('adbError'),'ADB尚未验证通过')
 elif not s['online']:finding='ADB已通过；共享互联网尚未接入'
 elif s.get('server')!=2:finding='服务器检测未通过或尚未完成'
 elif s.get('chat')!=2 or s.get('asr')!=2:finding='AI对话或语音检测未通过或尚未完成'
 else:finding='准备检查通过；手机实际执行仍需独立验收'
 return {'records':len(rows),'lastState':s,'finding':finding}
def main():
 p=argparse.ArgumentParser();p.add_argument('file',nargs='?');a=p.parse_args()
 if a.file:
  with open(a.file,encoding='utf-8',errors='replace') as f:text=f.read(262145)
 else:text=sys.stdin.read(262145)
 if len(text)>262144:raise SystemExit('Diagnostic input exceeds 256 KiB')
 print(json.dumps(analyze(text),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
