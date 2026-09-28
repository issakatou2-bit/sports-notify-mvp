"""Shared branding and typography. Importing this never renders or posts."""
import json
from pathlib import Path
from PIL import ImageFont

THEME=json.loads(Path(__file__).with_name('ps-brand-theme.json').read_text(encoding='utf-8'))
TOKENS=THEME['colors']
FONT_CANDIDATES={
    'jp':['C:/Windows/Fonts/meiryob.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'],
    'latin':['C:/Windows/Fonts/bahnschrift.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
    'serif':['C:/Windows/Fonts/georgiab.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf']}
_cache={}
def font(size,latin=False,serif=False):
    role='serif' if serif else 'latin' if latin else 'jp'
    key=(role,size)
    if key not in _cache:
        path=next((p for p in FONT_CANDIDATES[role] if Path(p).exists()),None)
        if not path:raise ValueError('Missing readable font: '+role)
        _cache[key]=ImageFont.truetype(path,size)
    return _cache[key]

def text(draw,xy,value,size,color,width=None,latin=False,serif=False,minimum=24):
    f=font(size,latin,serif)
    if width:
        while draw.textbbox((0,0),value,font=f)[2]>width and size>minimum:
            size-=1;f=font(size,latin,serif)
        if draw.textbbox((0,0),value,font=f)[2]>width:
            raise ValueError('Text needs another line/page, do not squeeze it: '+value)
    draw.text(xy,value,font=f,fill=color)
    return draw.textbbox(xy,value,font=f)
