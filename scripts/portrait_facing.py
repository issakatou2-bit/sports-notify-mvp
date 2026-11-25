"""立ち絵の頭にある肌の重心から向きを調べる。散歩 sanpo/facing.py を参照。"""
import numpy as np


def source_facing(image):
    pixels = np.asarray(image.convert("RGBA"), dtype=np.int16)
    head = pixels[:round(image.height * .35)]
    red, green, blue, alpha = np.moveaxis(head, 2, 0)
    opaque = alpha > 128
    skin = opaque & (red > 215) & (green > 170) & (blue > 140) & (
        red - blue > 25) & (red - blue < 90)
    if skin.sum() < 500:
        return None
    offset = (np.nonzero(skin)[1].mean() - np.nonzero(opaque)[1].mean()) / image.width
    if abs(offset) < .012:
        return None
    return "left" if offset < 0 else "right"
