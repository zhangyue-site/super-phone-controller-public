"""200x200 monochrome view shared by firmware and PNG previews."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont


def render(rows, interaction, page=0, now=None, connected=True):
    font_path=os.environ.get('EPAPER_FONT','/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc')
    if not os.path.isfile(font_path):
        font_path='/System/Library/Fonts/Supplemental/Songti.ttc'
    font=ImageFont.truetype(font_path,12)
    small=ImageFont.truetype(font_path,10)
    title=ImageFont.truetype(font_path,16)
    im=Image.new('1',(200,200),1)
    d=ImageDraw.Draw(im)
    def text(x,y,s,f=font):
        s=str(s)
        while s and d.textlength(s,font=f)>192-x:
            s=s[:-1]
        d.text((x,y),s,font=f,fill=0)
    text(8,3,'模型额度' if page==0 else '当前交互',title)
    text(145,8,'106 在线' if connected else '未连接',small)
    d.line((7,27,192,27),fill=0)
    if page==0:
        text(8,31,'剩余额度 · 旧值标记 *',small)
        for i,row in enumerate(rows[:5]):
            y=49+i*25
            text(8,y,row['label'])
            value=row['value']+('*' if row['status']!='ok' else '')
            w=d.textlength(value,font=font)
            text(max(90,191-w),y,value)
            if row['remaining'] is not None:
                d.rectangle((8,y+18,191,y+20),outline=0)
                width=int(181*row['remaining']/100)
                if width:d.rectangle((9,y+19,9+width,y+19),fill=0)
    else:
        state=interaction.get('state','idle')
        labels={'idle':'待命','listening':'正在录音','thinking':'正在思考','running':'正在执行',
                'waiting':'等待确认','done':'已完成','error':'执行失败','stopped':'已停止'}
        text(8,34,labels.get(state,'未知状态'),title)
        text(8,61,'设备：'+interaction.get('phone','尚未绑定'))
        task=interaction.get('task') or '尚无手机控制任务'
        for i in range(3):text(8,85+i*19,task[i*14:(i+1)*14])
        text(8,149,'步骤：'+str(interaction.get('step',0)),small)
        text(8,164,'投屏 / HID 尚未接通',small)
    d.line((7,178,192,178),fill=0)
    stamp=datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).strftime('%H:%M') if now else '--:--'
    text(8,182,stamp+' 更新',small)
    text(91,182,'短按翻页 长按停止',small)
    return im


def render_dialogue(reply,state,speech_error=False):
    """Large result text; the central bottom area matches the board STOP hit target."""
    font_path=os.environ.get('EPAPER_FONT','/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc')
    if not os.path.isfile(font_path):font_path='/System/Library/Fonts/STHeiti Medium.ttc'
    title=ImageFont.truetype(font_path,24);font=ImageFont.truetype(font_path,17)
    im=Image.new('1',(200,200),1);d=ImageDraw.Draw(im)
    label='播报不可用' if speech_error else '本轮结果' if state=='done' else '请核对手机' if state=='waiting' else '本轮未完成'
    d.text((8,5),label,font=title,fill=0)
    lines=[];line=''
    for c in reply:
        if c=='\n' or d.textlength(line+c,font=font)>180:
            lines.append(line);line=''
            if c=='\n':continue
        line+=c
    if line:lines.append(line)
    for i,line in enumerate(lines[:4]):d.text((8,39+i*21),line,font=font,fill=0)
    if len(lines)>4:d.text((170,103),'…',font=font,fill=0)
    d.rectangle((8,132,191,154),outline=0,width=2);d.text((47,134),'点此停止',font=font,fill=0)
    return im

def render_voice_ui(job):
    """Heard text + bounded plan, with the same visible STOP hit area as firmware."""
    path=os.environ.get('EPAPER_FONT','/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc')
    if not os.path.isfile(path):path='/System/Library/Fonts/STHeiti Medium.ttc'
    title=ImageFont.truetype(path,22);heard=ImageFont.truetype(path,13);body=ImageFont.truetype(path,14);button=ImageFont.truetype(path,17)
    im=Image.new('1',(200,200),1);d=ImageDraw.Draw(im)
    labels={'planning':'我听到了','plan':'准备这样做','running':'正在执行','verifying':'核对结果','done':'已完成','error':'本轮未完成','stopped':'已停止'}
    d.text((8,3),labels.get(job.state,'正在处理'),font=title,fill=0)
    def wrap(text,font,width):
        lines=[];line=''
        for c in text:
            if c=='\n' or d.textlength(line+c,font=font)>width:
                lines.append(line);line=''
                if c=='\n':continue
            line+=c
        if line:lines.append(line)
        return lines
    lines=wrap('你说：'+job.ui_heard,heard,184)
    for i,line in enumerate(lines[:2]):
        if i==1 and len(lines)>2:line=line[:-1]+'…'
        d.text((8,31+i*15),line,font=heard,fill=0)
    if getattr(job,'done',False):
        reply_lines=wrap(job.reply,body,184)
        for i,line in enumerate(reply_lines[:4]):
            if i==3 and len(reply_lines)>4:line=line[:-1]+'…'
            d.text((8,65+i*16),line,font=body,fill=0)
    elif job.ui_plan:
        for i,step in enumerate(job.ui_plan[:4]):
            text=str(i+1)+'. '+step
            while d.textlength(text,font=body)>184:text=text[:-2]+'…'
            d.text((8,65+i*16),text,font=body,fill=0)
    else:
        d.text((8,78),'正在理解，先不操作手机',font=body,fill=0)
        d.text((8,101),'稍后在这里显示计划',font=body,fill=0)
    d.rectangle((8,132,191,154),outline=0,width=2)
    d.text((47,133),'点此停止',font=button,fill=0)
    return im
