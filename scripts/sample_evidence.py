"""見本の実書き出しフレームと配置を記録する。APSC scripts/check_sample.py を参考にした。"""
import base64
from copy import deepcopy
import zlib

from voice_manifest import sha256, write_json


REFERENCE_SIZE = (270, 480)


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
    return result


def save(video, fps, segments, rows):
    write_json(video.with_suffix('.sample-check.json'),
               dict(video_sha256=sha256(video), fps=fps, size=[1080, 1920],
                    reference_size=list(REFERENCE_SIZE), segments=segments, frames=rows))
