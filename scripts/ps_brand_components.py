"""Shared branding and typography. Importing this never renders or posts."""
import json
from pathlib import Path
from PIL import ImageFont

THEME=json.loads(Path(__file__).with_name('ps-brand-theme.json').read_text(encoding='utf-8'))
TOKENS=THEME['colors']
# Paired uniform accents, shared by PS cover and detail cards. Primary colors
# remain in notability_engine.MLB_TEAM_COLOR. These are screen design tokens.
TEAM_SECONDARY_COLORS={
    '108':'#003263','109':'#30CED8','110':'#FFFFFF','111':'#0C2340',
    '112':'#CC3433','113':'#FFFFFF','114':'#E31937','115':'#C4CED4',
    '116':'#FA4616','117':'#EB6E1F','118':'#BD9B60','119':'#FFFFFF',
    '120':'#14225A','121':'#FF5910','133':'#EFB21E','134':'#27251F',
    '135':'#FFC425','136':'#005C5C','137':'#27251F','138':'#0C2340',
    '139':'#8FBCE6','140':'#C0111F','141':'#E8291C','142':'#D31145',
    '143':'#284898','144':'#13274F','145':'#C4CED4','146':'#EF3340',
    '147':'#FFFFFF','158':'#FFC52F'}
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
    bounds=draw.textbbox((0,0),value,font=f)
    if width:
        while bounds[2]-bounds[0]>width and size>minimum:
            size-=1;f=font(size,latin,serif)
            bounds=draw.textbbox((0,0),value,font=f)
        if bounds[2]-bounds[0]>width:
            raise ValueError('Text needs another line/page, do not squeeze it: '+value)
    # xy marks the ink's left edge. Noto CJK gives some Latin capitals a
    # negative bearing (e.g. AJ), even when the full name fits the row.
    # Align the measured glyphs; retain the existing font size and safety gate.
    position=(xy[0]-bounds[0],xy[1])
    draw.text(position,value,font=f,fill=color)
    return draw.textbbox(position,value,font=f)
