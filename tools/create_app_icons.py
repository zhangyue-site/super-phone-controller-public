"""Rebuild Android launcher + store icons from one control-board glyph."""
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
RES=ROOT/"app/android/app/src/main/res"
BG="#0B171B";PAPER="#EDEADC";ACCENT="#8DE6C2"
def icon(size):
 scale=8
 im=Image.new("RGBA",(108*scale,108*scale),(0,0,0,0));d=ImageDraw.Draw(im)
 def box(coords,fill,r=0):
  c=tuple(round(v*scale) for v in coords)
  if r:d.rounded_rectangle(c,radius=r*scale,fill=fill)
  else:d.rectangle(c,fill=fill)
 box((0,0,108,108),BG,22)
 box((31,27,77,81),PAPER,7)
 box((36,33,72,66),BG,3)
 d.polygon([(x*scale,y*scale) for x,y in [(54,39),(44,49),(50,49),(50,59),(58,59),(58,49),(64,49)]],fill=ACCENT)
 box((48,72,60,75),BG,1)
 return im.resize((size,size),Image.Resampling.LANCZOS)
for density,size in [("mdpi",48),("hdpi",72),("xhdpi",96),("xxhdpi",144),("xxxhdpi",192)]:
 icon(size).save(RES/f"mipmap-{density}/ic_launcher.png")
assets=ROOT/"app/assets";assets.mkdir(exist_ok=True)
icon(512).save(assets/"store-icon.png")
glyph='M38,27 L70,27 Q77,27 77,34 L77,74 Q77,81 70,81 L38,81 Q31,81 31,74 L31,34 Q31,27 38,27 Z M39,33 Q36,33 36,36 L36,63 Q36,66 39,66 L69,66 Q72,66 72,63 L72,36 Q72,33 69,33 Z M48,72 L60,72 L60,75 L48,75 Z'
arrow='M54,39 L44,49 L50,49 L50,59 L58,59 L58,49 L64,49 Z'
def vector(monochrome=False):
 return f'''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
 <path android:fillColor="{PAPER if not monochrome else '#FFFFFF'}" android:fillType="evenOdd" android:pathData="{glyph}"/>
 <path android:fillColor="{ACCENT if not monochrome else '#FFFFFF'}" android:pathData="{arrow}"/>
</vector>
'''
(RES/"drawable/ic_launcher_foreground.xml").write_text(vector())
(RES/"drawable/ic_launcher_monochrome.xml").write_text(vector(True))
(RES/"values/icon_colors.xml").write_text(f'<resources><color name="launcher_background">{BG}</color></resources>\n')
for directory,mono in [("mipmap-anydpi-v26",False),("mipmap-anydpi-v33",True)]:
 p=RES/directory;p.mkdir(exist_ok=True)
 p.joinpath("ic_launcher.xml").write_text('''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
 <background android:drawable="@color/launcher_background"/>
 <foreground android:drawable="@drawable/ic_launcher_foreground"/>
'''+(' <monochrome android:drawable="@drawable/ic_launcher_monochrome"/>\n' if mono else '')+'</adaptive-icon>\n')
p=RES.parent/"AndroidManifest.xml";s=p.read_text()
if "android:roundIcon" not in s:s=s.replace('android:icon="@mipmap/ic_launcher"','android:icon="@mipmap/ic_launcher"\n        android:roundIcon="@mipmap/ic_launcher"')
p.write_text(s)
