"""Render the approved simple 9:16 daily cover from the actual narration hook."""
import argparse
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw
import video_common as vc
from daily_focus import cover_metadata


def render_cover(meta):
    im = Image.new('RGB', (1080, 1920), '#0c1520')
    draw = ImageDraw.Draw(im)

    def label(y, value, size, color='#faf8f1', minimum=54):
        while size >= minimum and draw.textlength(value, font=vc.font(size)) > 920:
            size -= 2
        if size < minimum:
            raise ValueError('Cover text exceeds readable safe width: ' + value)
        draw.text((80, y), value, font=vc.font(size), fill=color, anchor='lt')

    draw.line([(540, 1550), (940, 1150), (540, 750), (140, 1150), (540, 1550)],
              fill='#172b36', width=3)
    draw.rectangle((0, 0, 1080, 18), fill='#ffbe36')
    draw.rounded_rectangle((76, 145, 440, 219), radius=18, fill='#183a39')
    label(163, 'MLB・注目試合', 39, '#48c8b4', 39)
    label(300, meta['subject'], 133, minimum=92)
    fact = meta['fact']
    magic = re.fullmatch(r'地区優勝マジック([0-9]+)', fact)
    streak = re.fullmatch(r'([0-9]+)連勝中', fact)
    if magic:
        label(482, '地区優勝', 80)
        label(610, 'マジック', 96, '#ffbe36')
        label(750, magic[1], 435, '#ffbe36', 180)
    elif streak:
        label(540, streak[1], 360, '#ffbe36', 180)
        label(980, '連勝中', 133, '#ffbe36')
    else:
        # Short phrases only. Long or unstructured hooks fall back to a frame.
        label(540, fact, 125, '#ffbe36', 70)
        if meta['team'] and meta['team'] != meta['subject']:
            label(820, meta['team'], 85)
    draw.line((80, 1250, 1000, 1250), fill='#3b495a', width=3)
    label(1310, meta['matchup'], 69)
    label(1430, meta['time'], 56, '#b4becb', 48)
    label(1590, '注目試合を理由つきで', 51, '#b4becb', 51)
    draw.rectangle((82, 1744, 132, 1755), fill='#ffbe36')
    draw.rectangle((122, 1744, 133, 1798), fill='#ffbe36')
    draw.rectangle((82, 1787, 132, 1798), fill='#ffbe36')
    draw.ellipse((75, 1764, 90, 1779), fill='#48c8b4')
    draw.text((157, 1750), 'コレスポ', font=vc.font(43), fill='#b4becb', anchor='lt')
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
