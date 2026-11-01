"""保存ESPN材料からv6/v4の4場面を静止再描画（音声・通信・公開なし）。"""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault('COLLESPO_SHORT_LOOK', 'v4')
import review_render_v3 as r3
import soccer_results as results
import soccer_results_render as render
from preview_soccer_readability import caption
from visual_capture import renderer_layout, layout_issues, sheet, write_json

ROOT = Path(__file__).resolve().parents[1]


def material():
    directory = ROOT / 'scripts/fixtures/soccer-results'
    read = lambda name: json.loads((directory / name).read_text(encoding='utf-8'))
    return results.build(read('scoreboards.json'), read('summaries.json'), '2026-09-20')


def frames(look):
    os.environ.update(COLLESPO_SOCCER_LOOK=look, COLLESPO_SHORT_LOOK='v4',
                      COLLESPO_BUBBLE='slant', COLLESPO_DUO='off', COLLESPO_SOLO_HOST='metan')
    data = material()
    clubs = render.resolve_clubs(data)
    narration = render.narration(data)
    for kind in ('intro', 'result', 'roster', 'outro'):
        segment = next(s for s in narration['segments'] if s['kind'] == kind)
        caption(segment)
        image = render.frame(3, segment, data, clubs)
        yield kind, image, render.validate_frame(image, data, clubs)
    r3.set_program_clock(None)
    r3.set_caption('', 0, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/visual-fixes/soccer')
    args = parser.parse_args()
    records = []
    for look in ('v6', 'v4'):
        items = []
        for kind, image, errors in frames(look):
            path = args.out/look/(kind+'.png')
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path)
            items.append((look+' '+kind+' / saved 2026-09-20 / 3s', path))
            geometry = renderer_layout(image.info)
            records.append(dict(look=look, kind=kind, image=str(path), errors=errors,
                                geometry=geometry, layout_issues=layout_issues(geometry),
                                portraits=image.info.get('duo_portraits', [])))
        sheet(items, args.out/(look+'-contact.jpg'), columns=4, cell=(360,680))
    write_json(args.out/'manifest.json', dict(material='saved ESPN 2026-09-20',
        scope='settled stills at 3s; no completed video/audio/publication', records=records))
    print([(r['look'], r['kind'], len(r['errors'])) for r in records])
    return int(any(r['errors'] for r in records))


if __name__ == '__main__':
    raise SystemExit(main())
