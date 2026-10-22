#!/usr/bin/env python3
"""Synthetic phone + real configured vision model. Never connects to a phone."""
import base64,io,json,sys,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
from display_service.dialogue import Mailbox
from display_service.wechat_nav import WechatNavigator,SkillStore
from display_service.wechat_vision import observe
FONT="/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"
def picture(stage):
 im=Image.new("RGB",(600,1200),"#f4f4f4");d=ImageDraw.Draw(im)
 font=ImageFont.truetype(FONT,30);small=ImageFont.truetype(FONT,23)
 d.text((25,10),"9:41                 5G   100%",font=small,fill="black")
 if stage==0:
  d.rectangle((0,45,599,1199),fill="#dce7f0")
  d.rounded_rectangle((65,200,170,305),radius=22,fill="#07c160")
  d.ellipse((80,220,143,263),fill="white");d.ellipse((109,243,158,279),fill="white")
  d.text((85,320),"微信",font=font,fill="black")
  d.text((50,800),"相册        设置        浏览器",font=small,fill="black")
 else:
  d.text((24,65),"微信" if stage==1 else "搜索",font=font,fill="black")
  if stage==1:
   d.ellipse((490,68,522,100),outline="black",width=3);d.line((518,97,535,114),fill="black",width=3)
   d.text((35,180),"微信团队",font=font,fill="black");d.text((35,230),"欢迎使用微信",font=small,fill="#555555")
   d.text((25,1120),"微信    通讯录    发现    我",font=font,fill="black")
  else:
   d.rounded_rectangle((25,125,535,190),radius=10,fill="white")
   if stage==2:
    d.text((48,139),"| 搜索",font=font,fill="#666666")
    d.text((35,240),"搜索指定内容",font=small,fill="#888888")
    d.rectangle((0,785,599,1199),fill="#d0d4da")
    d.text((30,820),"q w e r t y u i o p",font=font,fill="#333333")
    d.text((45,895),"a s d f g h j k l",font=font,fill="#333333")
    d.text((80,970),"z x c v b n m",font=font,fill="#333333")
    d.text((450,1090),"搜索",font=font,fill="black")
   else:
    d.text((48,139),"张三",font=font,fill="black")
    d.text((35,240),"联系人",font=small,fill="#888888")
    d.rounded_rectangle((28,300,575,430),radius=8,fill="white")
    d.rectangle((45,320,115,390),fill="#07c160");d.text((140,315),"张三",font=font,fill="black")
    d.text((140,365),"微信号：test_contact",font=small,fill="#888888")
    d.text((30,500),"搜索 张三 的其他内容",font=small,fill="#888888")
 out=io.BytesIO();im.save(out,format="JPEG",quality=90);return out.getvalue()
def run(store,turn):
 m=Mailbox();j=m.create("simulation-only","c"*16,turn);stage=[0];quit=threading.Event();commands=[];ai=[0]
 def model(raw,query,verify=False):
  ai[0]+=1;return observe(raw,query,verify)
 def phone():
  while not quit.is_set() and not j.done and not j.cancelled:
   try:
    command=m.poll(j.device,j.session,j.sequence,pointer_protocol="absolute-v1");op=command["op"]
    if op not in ("wait","done"):
     commands.append(op)
     if op=="hid_home":stage[0]=0;output="HID_HOME_REPORT_SENT"
     elif op=="hid_pointer":stage[0]=min(2,stage[0]+1);output="HID_POINTER_REPORT_SENT"
     elif op=="type_text":
      assert base64.b64decode(command["text_b64"]).decode()=="张三";stage[0]=3;output="__PC_EXIT_0__"
     else:raise AssertionError("forbidden "+op)
     m.ack(j.device,j.session,j.sequence,command["id"],True,output)
    m.ingest_video(j.device,j.session,j.sequence,j.video_sequence+1,picture(stage[0]),"jpeg",expected_barrier=j.video_barrier,source="user-consented-app-screen")
   except ValueError:pass
   time.sleep(.2)
 t=threading.Thread(target=phone);t.start()
 try:
  result=WechatNavigator(m,store,vision=model).run(j,"张三");j.done=True;j.state="done"
  print(json.dumps({"simulation_only":True,"turn":turn,"commands":commands,"ai_calls":ai[0],"result":result},ensure_ascii=False),flush=True)
 finally:quit.set();t.join()
 return ai[0]
if __name__=="__main__":
 with tempfile.TemporaryDirectory() as temp:
  store=SkillStore(Path(temp));cold=run(store,1);store.save_last("simulation-only");replay=run(store,2)
  print("REAL_VISION_SYNTHETIC_FLOW_PASS","cold_ai",cold,"replay_ai",replay,flush=True)
