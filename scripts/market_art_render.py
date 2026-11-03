"""市場の挿絵だけの描画。元画像を変えず、比率を保って空いた上段へ置く。"""
from functools import lru_cache
from PIL import Image, ImageOps


@lru_cache(maxsize=24)
def bitmap(path, digest):
    with Image.open(path) as source:
        if source.width * source.height > 24_000_000:
            raise ValueError('挿絵が大きすぎます。縮小した素材を用意してください')
        return ImageOps.contain(ImageOps.exif_transpose(source).convert('RGBA'), (360, 246))


def draw(im, row, elapsed):
    import review_render_v3 as r3
    art = bitmap(str(row['path']), row['digest']).copy()
    fade = .75 + .25 * min(1.0, max(0.0, elapsed/.7))
    art.putalpha(art.getchannel('A').point(lambda value: round(value*fade)))
    x = round((r3.LEFT+r3.SAFE_RIGHT-260-art.width)/2)
    y = 340 + (270-art.height)//2
    im.paste(art, (x,y), art)
    r3.record_box(im, 'illustration', (x,y,x+art.width,y+art.height), row['filename'])
    im.info['market_art'] = dict(filename=row['filename'], box=[x,y,x+art.width,y+art.height], fade=fade)


def check_layout(im):
    entries = im.info.get('v3_layout', [])
    pictures = [e for e in entries if e['role'] == 'illustration']
    errors = []
    for art in pictures:
        a,b,c,d = art['box']
        for entry in entries:
            if entry is art or entry['role'] == 'illustration':
                continue
            x,y,r,s = entry['box']
            if max(a,x) < min(c,r) and max(b,y) < min(d,s):
                errors.append({'illustration': art['box'], 'overlap': entry})
    if pictures:
        for portrait in im.info.get('duo_portraits', []):
            a,b,c,d = portrait['box']
            for entry in entries:
                if entry['role'] != 'text':
                    continue
                x,y,r,s = entry['box']
                if max(a,x) < min(c,r) and max(b,y) < min(d,s):
                    errors.append({'portrait': portrait['box'], 'overlap': entry})
    return errors
