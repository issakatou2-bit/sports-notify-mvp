"""公式の雨衣部品を選んで重ねる。素材の加工・生成はしない。"""
import functools
import json
import os
from pathlib import Path

from PIL import Image


def state(mood, line, elapsed, clock, duration, level, fan=None, silent=False):
    """同じ時計から口・瞬き・控えめな一度の身ぶりを選ぶ。"""
    speaking = bool(line) and elapsed < max(.1, duration - .25)
    mouth = 0 if silent or not speaking else (level if level is not None else 0)
    # 笑顔でも無音・文末は閉口。発声中だけ公式の笑い口を使う。
    if mouth and any(word in line for word in ('ふふ', 'うふふ', 'あはは')):
        mouth = '笑'
    blink = (clock % 4.3) >= 4.14
    arm = '基本'
    # 急な連打を避け、文中で一度だけ出して基本に戻す。
    if speaking and .6 <= elapsed < min(3.4, duration - .25):
        if '?' in line or '？' in line:
            arm = '考え'
        elif fan and fan[0] == 'pose-smile':
            arm = '上げ'
        else:
            arm = '指'
    return f'{mood}:mouth{mouth}:arm{arm}:blink{int(blink)}'


@functools.lru_cache(maxsize=4)
def assets(directory):
    folder = Path(directory)
    spec = json.loads((folder/'parts.json').read_text(encoding='utf8'))
    # 目・腕が変わっても全レイヤーは同じ原点・大きさ。
    parts = {}
    names = [spec['体']] + [v for k in ('右腕', '左腕', '眉', '目', '口') for v in spec[k].values()]
    for name in names:
        with Image.open(folder/name) as part:
            parts[name] = part.convert('RGBA')
    return spec, parts


def portrait(face, height):
    import characters
    directory = os.getenv('COLLESPO_UI_PORTRAIT_DIR')
    if not directory:
        raise ValueError('雨衣の既存立ち絵を COLLESPO_UI_PORTRAIT_DIR で指定してください')
    spec, parts = assets(directory)
    mood, *options = face.split(':')
    opts = {key: next((v[len(key):] for v in options if v.startswith(key)), None)
            for key in ('mouth', 'arm', 'blink')}
    brow, eye, lips = characters.FACE_PARTS.get(mood, characters.FACE_PARTS['base'])
    if opts['mouth'] is not None:
        lips = '笑' if opts['mouth'] == '笑' else ('閉', '開', '大')[int(opts['mouth'])]
    if opts['blink'] == '1':
        eye = '閉'
    arm = opts['arm'] or '基本'
    left = '上げ' if arm == '上げ' else '基本'
    names = [spec['体'], spec['右腕'][arm], spec['左腕'][left], spec['眉'][brow], spec['目'][eye], spec['口'][lips]]
    art = Image.new('RGBA', tuple(spec['size']))
    for name in names:
        art = Image.alpha_composite(art, parts[name])
    art = art.crop(tuple(spec['crop']))
    art = art.crop((0, 0, art.width, round(art.height*.62)))
    return art.resize((round(art.width*(height/2)/art.height), height//2), Image.Resampling.LANCZOS)


def head_box(box):
    # parts.json のcrop=[155,145,860,1010]、頭の既存部品の範囲。
    x, y, right, bottom = box
    scale = (bottom-y)/round((1010-145)*.62)
    return [x+(267-155)*scale, y+(148-145)*scale,
            x+(793-155)*scale, y+(540-145)*scale]
