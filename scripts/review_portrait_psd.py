"""ずんだもんのpinch/surpriseを元PSDの表示切替と比較する（ローカル専用）。"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from portrait_parts import compose_parts, load_parts


def main():
    from psd_tools import PSDImage
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    out = root / 'build_reports/portrait_parts_20261027'
    folder = root / 'assets/portraits/ずんだもん'
    data = load_parts(folder)
    catalog = {r['file']: r for r in data['catalog']}
    source = args.source / 'ずんだもん.psd'
    psd = PSDImage.open(source)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == data['source']['sha256']
    items, results = [], []
    for direction in ('正面', '上向き'):
        for name in ('pinch', 'surprise'):
            files = data['presets'][direction]['expressions'][name]['files']
            sources = {s for f in files for s in catalog[f]['source_layers']}

            def walk(node, prefix=()):
                for layer in node:
                    path = prefix + (layer.name,)
                    layer.visible = layer.is_group() or '/'.join(path) in sources
                    if layer.is_group():
                        walk(layer, path)

            walk(psd)
            reference = psd.composite(force=True).convert('RGBA')
            actual = compose_parts(folder, data, files)
            # 透明部の隠れたRGBは表示に無関係なので、同じ地へ合成して比較。
            def flatten(im):
                base = Image.new('RGBA', im.size, '#eeeeee')
                return Image.alpha_composite(base, im).convert('RGB')
            bbox = ImageChops.difference(flatten(reference), flatten(actual)).getbbox()
            face_box = (250, 220, 760, 560)
            face_diff = ImageChops.difference(flatten(reference).crop(face_box),
                                             flatten(actual).crop(face_box))
            results.append(dict(direction=direction, name=name, display_diff_bbox=bbox,
                                face_pixel_equal=face_diff.getbbox() is None,
                                cheek=[f for f in files if catalog[f]['slot'] == 'cheek']))
            for label, im in [('PSD表示', reference), ('parts合成', actual)]:
                items.append((f'{direction} {name} {label}', im.crop(face_box)))
    canvas = Image.new('RGB', (1020, 1520), '#eeeeee')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 18)
    for i, (label, im) in enumerate(items):
        x, y = (i % 2) * 510, (i // 2) * 380
        canvas.paste(im, (x, y + 35), im)
        draw.text((x + 8, y + 4), label, font=font, fill='black')
    canvas.save(out / '青ざめ_PSD比較.png')
    (out / 'psd_comparison.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
