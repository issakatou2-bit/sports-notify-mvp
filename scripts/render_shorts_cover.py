"""Render the approved simple 9:16 daily cover from the actual narration hook."""
import argparse
import json
import os
from pathlib import Path
import re

from PIL import Image, ImageDraw
import video_common as vc
from daily_focus import cover_metadata


# 新しい見た目（COLLESPO_STYLE=v2）：濃紺の地・黄1色・数字は Oswald。既定は今のまま。
OLD = dict(ground='#0c1520', line='#172b36', gold='#ffbe36', tag='#183a39', teal='#48c8b4', white='#faf8f1', grey='#b4becb', rule='#3b495a')
NEW = dict(ground=None, line='#14213d', gold='#d6fa46', tag='#1e293b', teal='#d6fa46', white='#f4f6fa', grey='#96a2ba', rule='#2e3a56')


def render_cover(meta):
    v2 = os.environ.get('COLLESPO_STYLE') == 'v2'
    c = NEW if v2 else OLD
    if v2:
        import style_v2
        im = style_v2.background(0).convert('RGB')
    else:
        im = Image.new('RGB', (1080, 1920), c['ground'])
    draw = ImageDraw.Draw(im)

    def label(y, value, size, color=c['white'], minimum=54, number=False):
        face = (lambda s: style_v2.num(s)) if number and v2 else vc.font
        while size >= minimum and draw.textlength(value, font=face(size)) > 920:
            size -= 2
        if size < minimum:
            raise ValueError('Cover text exceeds readable safe width: ' + value)
        draw.text((80, y), value, font=face(size), fill=color, anchor='lt')

    if not v2:
        draw.line([(540, 1550), (940, 1150), (540, 750), (140, 1150), (540, 1550)],
                  fill=c['line'], width=3)
    draw.rectangle((0, 0, 1080, 18 if not v2 else 8), fill=c['gold'])
    if v2:
        draw.rectangle((62, 145, 440, 219), fill=c['tag'])
        draw.rectangle((62, 145, 68, 219), fill=c['gold'])
    else:
        draw.rounded_rectangle((76, 145, 440, 219), radius=18, fill=c['tag'])
    label(163, 'MLB・注目試合', 39, c['teal'], 39)
    label(300, meta['subject'], 133, minimum=92)
    fact = meta['fact']
    magic = re.fullmatch(r'地区優勝マジック([0-9]+)', fact)
    streak = re.fullmatch(r'([0-9]+)連勝中', fact)
    if magic:
        label(482, '地区優勝', 80)
        label(610, 'マジック', 96, c['gold'])
        label(750, magic[1], 435, c['gold'], 180, number=True)
    elif streak:
        label(540, streak[1], 360, c['gold'], 180, number=True)
        label(980, '連勝中', 133, c['gold'])
    else:
        # Short phrases only. Long or unstructured hooks fall back to a frame.
        label(540, fact, 125, c['gold'], 70)
        if meta['team'] and meta['team'] != meta['subject']:
            label(820, meta['team'], 85)
    draw.line((80, 1250, 1000, 1250), fill=c['rule'], width=3)
    label(1310, meta['matchup'], 69)
    label(1430, meta['time'], 56, c['grey'], 48)
    label(1590, '注目試合を理由つきで', 51, c['grey'], 51)
    if v2:
        draw.text((80, 1750), 'コレスポ', font=vc.font(43), fill=c['white'], anchor='lt')
        return im
    draw.rectangle((82, 1744, 132, 1755), fill=c['gold'])
    draw.rectangle((122, 1744, 133, 1798), fill=c['gold'])
    draw.rectangle((82, 1787, 132, 1798), fill=c['gold'])
    draw.ellipse((75, 1764, 90, 1779), fill=c['teal'])
    draw.text((157, 1750), 'コレスポ', font=vc.font(43), fill=c['grey'], anchor='lt')
    return im


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', required=True)
    parser.add_argument('--narration', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.games).read_text(encoding='utf-8'))
    narration = json.loads(Path(args.narration).read_text(encoding='utf-8'))
    games = [g for g in data.get('games', []) if g.get('is_notable')][:3]
    hook = next(((s.get('meta') or {}).get('hook') or {}
                 for s in narration.get('segments', []) if s.get('kind') == 'intro'), {})
    meta = cover_metadata(games, hook)
    # A stale narration must not create today's cover using yesterday's hook.
    if narration.get('date_label') != (games[0].get('start_time_jst') or '').split(' ')[0]:
        raise ValueError('Narration date differs from daily games')
    im = render_cover(meta)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, optimize=True)
    path.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[info] Dedicated daily Shorts cover: ' + str(path))


if __name__ == '__main__':
    main()
