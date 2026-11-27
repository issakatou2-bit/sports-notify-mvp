"""1080×1920 のショートに使う文字・顔の安全域。"""

SAFE_TOP = 160
SAFE_RIGHT = 930
SAFE_BOTTOM = 1440
# 11/27 本人「めたずんのサイズ揃えたい」：ずんだもんをめたんと同じ691にし、足を下端に付けると顎が1471まで下がる。
# 左右下隅の胸上の顔だけ下限を1480にする（チャンネル名・題の文字は約1640より下なので顔にかからない）。
CORNER_FACE_BOTTOM = 1480


def outside(box, limit=SAFE_BOTTOM):
    left, top, right, bottom = box
    return not (0 <= left <= right <= SAFE_RIGHT and SAFE_TOP <= top <= bottom <= limit)


def bottom_limit(entry):
    """隅の胸上の顔（corner_face）だけ下限を CORNER_FACE_BOTTOM にする。"""
    return CORNER_FACE_BOTTOM if entry.get("role") == "face" and entry.get("corner_face") else SAFE_BOTTOM


def problems(layout):
    return [
        dict(outside_shorts_safe_area=entry)
        for entry in layout
        if (entry.get("text") or entry["role"] in {"caption", "source", "face", "card", "badge"})
        and outside(entry["box"], bottom_limit(entry))
    ]
