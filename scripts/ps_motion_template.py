"""Briefing motion: cached foreground rows, sequential entry, quiet background.

10/3 改善案C: 入場のあと、読み上げ中の行を明るく、他の行を少し沈める
（focus）。止まった絵が10秒続くと、耳と目が別の所を追う。
沈めた版は prepare で一度だけ作る（毎コマ作り直すと重い）。
"""
from PIL import ImageDraw
from ps_render_template import background
from video_common import ease_out

ENTRY_SECONDS = 1.2      # 全行が出そろうまで（0.16秒ずつ × 行数 + 0.38秒）
DIM = 0.45               # 読み上げていない行の濃さ


def visible_layout(rows, top, bottom, dx=0):
    """切り出して貼る実際の範囲と移動量を配置記録にも使う。"""
    return [dict(row, box=[left + dx, max(y0, top), right + dx, min(y1, bottom)])
            for row in rows for left, y0, right, y1 in [row['box']]
            if y0 < bottom and top < y1]


def prepare(foreground,card):
    splits={'schedule':[570,736,892,1048,1280], 'facts':[570,770,970,1280],
            'bracket':[570,930,1280], 'quote':[570,1280]}[card['layout']]
    ranges=[(210,485),(485,570),*list(zip(splits,splits[1:]))]
    fixed=foreground.copy()
    ImageDraw.Draw(fixed).rectangle((0,210,1079,1279),fill=(0,0,0,0))
    layout = foreground.info.get('v3_layout', [])
    fixed.info['v3_layout'] = visible_layout(layout, 0, 210) + visible_layout(layout, 1280, fixed.height)
    pieces=[]
    for i,(lo,hi) in enumerate(ranges):
        piece=foreground.crop((0,lo,1080,hi))
        piece.info['v3_layout'] = visible_layout(layout, lo, hi)
        dim=piece.copy()
        dim.putalpha(piece.getchannel('A').point([round(v*DIM) for v in range(256)]))
        pieces.append((lo,piece,i*0.16,dim))
    return fixed,pieces


def frame(prepared,seconds,focus=None,style='stadium',team_id=None):
    """focus は読み上げ中の行（items の何番目か）。None なら全行そのまま。"""
    fixed,pieces=prepared
    im=background(style=style,seconds=seconds,team_id=team_id);im.paste(fixed,(0,0),fixed)
    layout = im.info['v3_layout'] = list(fixed.info['v3_layout'])
    lit = focus is not None and seconds >= ENTRY_SECONDS
    for j,(lo,piece,delay,dim) in enumerate(pieces):
        p=max(0,min(1,(seconds-delay)/0.38))
        if p==0:continue
        e=ease_out(p)
        if lit and j>=2:
            src=piece if j-2==focus else dim
            im.paste(src,(0,lo),src.getchannel('A'))
            layout.extend(piece.info['v3_layout'])
            if j-2==focus:
                ImageDraw.Draw(im).rectangle((50,lo+6,58,lo+piece.height-16),fill='#ffd16c')
            continue
        alpha=piece.getchannel('A')
        if p<1:alpha=alpha.point([round(v*e) for v in range(256)])
        dx = -round(56*(1-e))
        im.paste(piece,(dx,lo),alpha)
        layout.extend(visible_layout(piece.info['v3_layout'], lo, lo + piece.height, dx))
    return im

def cues(prepared,duration):
    """実際の札の入場時刻と同じ時刻表。時間内のものだけを鳴らす。"""
    return [(0.0,'transition','b',-10)] if duration>0 else []
