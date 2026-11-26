"""見本の実書き出しフレームと配置を記録する。APSC scripts/check_sample.py を参考にした。"""
import base64
from copy import deepcopy
import zlib

from PIL import ImageDraw

from voice_manifest import sha256, write_json


REFERENCE_SIZE = (270, 480)


class LayoutDraw(ImageDraw.ImageDraw):
    """既存の Pillow 描画に、同じフォント・引数で測った文字の箱を付ける。"""

    def text(self, xy, text, fill=None, font=None, anchor=None, *, role='text', **kwargs):
        super().text(xy, text, fill=fill, font=font, anchor=anchor, **kwargs)
        if not text or '\n' in text:
            return
        measured = {k: v for k, v in kwargs.items() if k in (
            'spacing', 'align', 'direction', 'features', 'language', 'stroke_width',
            'embedded_color', 'font_size')}
        box = self.textbbox(xy, text, font=font, anchor=anchor, **measured)
        self._image.info.setdefault('v3_layout', []).append(dict(role=role, box=list(box), text=text))


def record(image, raw, index, layout, portraits, transition=False):
    """実際にエンコーダへ渡した画素を、小さい照合用の画像にする。"""
    frame = image.convert('RGB')
    frame.frombytes(raw)
    pixels = frame.convert('L').resize(REFERENCE_SIZE, 2).tobytes()
    reference = base64.b64encode(zlib.compress(pixels)).decode('ascii')
    return dict(frame=index, layout=deepcopy(layout), portraits=portraits, reference=reference, transition=transition)


def portraits(info):
    layers = {row['who']: row for row in info.get('duo_layer', [])}
    faces = [row['box'] for row in info.get('v3_layout', []) if row['role'] == 'face']
    result = []
    drawn = info.get('duo_portraits') or [
        dict(who=row['who'], box=[*row['at'], row['at'][0], row['at'][1]],
             active=row.get('active', False))
        for row in layers.values()
    ]
    for row in drawn:
        layer = layers.get(row['who'], {})
        x, y = row['box'][:2]
        face = row.get('face') or next((box for box in faces if box[:2] == [x, y]), None)
        result.append(dict(who=row['who'], box=row['box'], face=face,
                           active=row.get('active', layer.get('active', False)),
                           side=layer.get('side'), facing=layer.get('facing'),
                           dy=layer.get('dy', 0), ink=row.get('ink'), expression=layer.get('face'),
                           corner=bool(layer.get('corner')), origin=layer.get('at')))
        if 'floor' in row:
            result[-1]['floor'] = row['floor']
    return result


def save(video, fps, segments, rows, *, size=(1080, 1920), stride=3):
    write_json(video.with_suffix('.sample-check.json'),
               dict(video_sha256=sha256(video), fps=fps, size=list(size), stride=stride,
                    reference_size=list(REFERENCE_SIZE), segments=segments, frames=rows))
