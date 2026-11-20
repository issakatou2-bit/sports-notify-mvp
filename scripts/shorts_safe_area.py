"""1080×1920 のショートに使う文字・顔の安全域。"""

SAFE_TOP = 160
SAFE_RIGHT = 930
SAFE_BOTTOM = 1440


def outside(box):
    left, top, right, bottom = box
    return not (0 <= left <= right <= SAFE_RIGHT and SAFE_TOP <= top <= bottom <= SAFE_BOTTOM)


def problems(layout):
    return [
        dict(outside_shorts_safe_area=entry)
        for entry in layout
        if (entry.get("text") or entry["role"] in {"caption", "source", "face", "card", "badge"})
        and outside(entry["box"])
    ]
