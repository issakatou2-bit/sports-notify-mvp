"""Briefing motion: cached foreground rows, sequential entry, quiet background."""
from PIL import ImageDraw
from ps_render_template import background
from video_common import ease_out


def prepare(foreground,card):
    splits={'schedule':[570,736,892,1048,1280], 'facts':[570,770,970,1280],
            'bracket':[570,930,1280], 'quote':[570,1280]}[card['layout']]
    ranges=[(210,485),(485,570),*list(zip(splits,splits[1:]))]
    fixed=foreground.copy()
    ImageDraw.Draw(fixed).rectangle((0,210,1079,1279),fill=(0,0,0,0))
    pieces=[(lo,foreground.crop((0,lo,1080,hi)),i*0.16) for i,(lo,hi) in enumerate(ranges)]
    return fixed,pieces


def frame(prepared,seconds):
    fixed,pieces=prepared
    im=background(seconds=seconds);im.paste(fixed,(0,0),fixed)
    for lo,piece,delay in pieces:
        p=max(0,min(1,(seconds-delay)/0.38))
        if p==0:continue
        e=ease_out(p)
        alpha=piece.getchannel('A')
        if p<1:alpha=alpha.point([round(v*e) for v in range(256)])
        im.paste(piece,(-round(56*(1-e)),lo),alpha)
    return im
