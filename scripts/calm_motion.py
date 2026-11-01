"""動きを「見やすく・静かに」（Opus-32、10/14 本人「一覧→ズームだと無駄。うるさい。喋る内容だけズームしていく方が良い」）。

COLLESPO_MOTION=on のときだけ効く。それ以外では、どの関数を呼んでも今の絵と同じになる。

- 画面全体のカメラの寄りは使わない。画面は動かさない。
- いま読み上げている項目（札）だけを、その場で少し大きく・明るくし、ほかの札は少しだけ暗くする。
  切り替えは0.90秒（前の札を戻してから、次の札を上げる。2枚が同時に上がらない）。
- 数字の弾みと立ち絵の揺れを止め、拡大は小数座標の逆変換で描く。
- 速さと量は下の TUNING の1か所で変える。
"""
import os
import math

TUNING = {
    # --- 読み上げている札 ---
    'focus_scale': 1.04,       # 大きくする割合（1.03〜1.05）
    'focus_bright': 1.035,     # 白飛びと点滅感を抑える
    'rest_dim': 0.94,          # 背景の札も読み続けられる明るさ
    'focus_fade': 0.90,        # 戻す0.45秒＋上げる0.45秒。両端で静止する
    # --- ほかの動き（今の値に対する割合。0.5 で半分） ---
    'slide_distance': 0.5,     # 札が横から入る距離（今 140px）
    'overshoot': 0.0,          # 行き過ぎ・弾みなし
    'background_speed': 0.1,   # 背景の線と光の速さ（ほとんど止まって見える）
    'presenter_bob': 0.0,      # 発話ごとに始まる上下の揺れを止める
    'presenter_period': 2.0,   # 立ち絵の揺れの周期（2倍＝回数が半分）
    # #175の共通部品もこの表を読む。カメラの寄りは使わない。
    'overview': .8, 'stagger': .06, 'entrance': .22, 'rise': 4,
    'pulse_seconds': .48, 'pulse': 0.0, 'light': 0.0,
    'transition': .35, 'drift': 1.5, 'drift_speed': (.14, .11), 'scale': 2,
    'fps': 30,
}


def enabled():
    return os.environ.get('COLLESPO_MOTION') == 'on'


def value(name, default):
    """COLLESPO_MOTION=on なら TUNING の値、そうでなければ default（今の動き）。"""
    return TUNING[name] if enabled() else default


# ------------------------------------------------------------------ どの札の話か
def plan_from_parts(text, parts):
    """読み上げが「項目ごとの文」をつないだものなら、その字数の割合で区切る（いちばん確か）。

    返すのは [(始まりの割合, 終わりの割合, 行の番号)]。ps_program.focus_plan と同じ形。
    つなぎ目が一致しなければ []（推測で強調しない）。"""
    parts = [str(p) for p in parts]
    if not text or not parts or ''.join(parts) != text:
        return []
    total, pos, plan = len(text), 0, []
    for i, p in enumerate(parts):
        plan.append((pos / total, (pos + len(p)) / total, i))
        pos += len(p)
    return plan


def plan_from_markers(text, markers):
    """読み上げの中で、各行の目印（見出し・選手名）が出てくる位置から区切る。

    目印が1つでも見つからない・順番が逆のときは []（推測で強調しない）。
    最初の目印より前（「今シーズンの成績は、」など）はどの行でもない（None）。"""
    if not text or not markers:
        return []
    found, start = [], 0
    for m in markers:
        m = str(m or '')
        at = text.find(m, start) if m else -1
        if at < 0:
            return []
        found.append(at)
        start = at + len(m)
    total, plan = len(text), []
    if found[0] > 0:
        plan.append((0.0, found[0] / total, None))
    for i, at in enumerate(found):
        end = found[i + 1] if i + 1 < len(found) else total
        plan.append((at / total, end / total, i))
    return plan


def focus_at(plan, fraction):
    """ps_program.focus_at と同じ決まり（その割合が入っている区切りの行）。"""
    for lo, hi, idx in plan:
        if lo <= fraction < hi:
            return idx
    return None


def to_seconds(plan, speech_seconds, settle=0.0):
    """割合の区切りを秒に。同じ行が続く区切りはまとめる。札が出そろう settle 秒より前は上げない。"""
    out = []
    for lo, hi, idx in plan:
        a, b = lo * speech_seconds, hi * speech_seconds
        if out and out[-1][2] == idx and abs(out[-1][1] - a) < 1e-9:
            out[-1] = (out[-1][0], b, idx)
        else:
            out.append((a, b, idx))
    result = []
    for a, b, idx in out:
        if idx is None:
            continue
        a = max(a, settle)
        if b > a:
            result.append((a, b, idx))
    return result


def _smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def weights(timeline, t, rows):
    """その時刻の、行ごとの「上がり具合」（0〜1）。

    上げるのは区切りの始まりから fade/2 秒、戻すのは終わりの fade/2 秒前から。
    だから前の札が戻りきってから次の札が上がる（2枚が同時に上がらない）。"""
    half = max(1e-6, TUNING['focus_fade'] / 2)
    out = [0.0] * rows
    for a, b, idx in timeline:
        if idx is None or not 0 <= idx < rows:
            continue
        w = _smooth((t - a) / half) * _smooth((b - t) / half)
        out[idx] = max(out[idx], w)
    return out


def focus_for(t, text, speech_seconds, rows, parts=None, markers=None, settle=0.0):
    """読み上げ（text・秒）から、時刻 t の行ごとの上がり具合。決められなければ None。"""
    if not enabled() or not speech_seconds or rows < 2:
        return None
    plan = plan_from_parts(text, parts) if parts else []
    if not plan and markers:
        plan = plan_from_markers(text, markers)
    if not plan:
        return None
    return weights(to_seconds(plan, speech_seconds, settle), t, rows)


# ------------------------------------------------------------------ 札の描き方
def _brightness(card, k):
    """RGB だけを明るく・暗く（透明度は変えない）。"""
    if abs(k - 1.0) < 1e-3:
        return card
    from PIL import ImageEnhance
    rgb = card.convert('RGB')
    out = ImageEnhance.Brightness(rgb).enhance(k).convert('RGBA')
    out.putalpha(card.getchannel('A'))
    out.info.update(card.info)
    return out


def styled(card, own, others, anchor='center'):
    """札を、自分の上がり具合 own・ほかの札の上がり具合 others で描き直す。

    返すのは (札, 大きくなった幅, 大きくなった高さ)。own=others=0 なら元の札そのもの。"""
    if own <= 0 and others <= 0:
        return card, 0, 0
    bright = 1 + (TUNING['focus_bright'] - 1) * own
    dim = 1 - (1 - TUNING['rest_dim']) * max(0.0, others - own)
    out = _brightness(card, bright * dim)
    scale = 1 + (TUNING['focus_scale'] - 1) * own
    if scale == 1:
        return out, 0, 0
    from PIL import Image
    w, h = card.size
    # 出力枠の寸法を固定し、逆変換の小数座標で拡大する。
    # 毎フレームのroundと//2による1pxの寸法・中心の段差を作らない。
    nw = w + 2 * math.ceil(w * (TUNING['focus_scale'] - 1) / 2)
    nh = h + 2 * math.ceil(h * (TUNING['focus_scale'] - 1) / 2)
    dx = nw - w * scale if anchor == 'right' else (nw - w * scale) / 2
    dy = (nh - h * scale) / 2
    layout = out.info.get('v3_layout', [])
    big = out.transform((nw, nh), Image.Transform.AFFINE,
                        (1 / scale, 0, -dx / scale, 0, 1 / scale, -dy / scale),
                        Image.Resampling.BICUBIC)
    big.info.update(out.info)
    big.info['v3_layout'] = [dict(e, box=[e['box'][0] * scale + dx, e['box'][1] * scale + dy,
                                       e['box'][2] * scale + dx, e['box'][3] * scale + dy]) for e in layout]
    return big, nw - w, nh - h


# ------------------------------------------------------------------ 検査
def check_sync(render, timeline, rows, heads=()):
    """読み上げている行と、大きくなっている札が一致しているか。

    render(t) は1枚描いて返す関数（v3_slot_render.frame が im.info['v3_focus'] に記録する）。
    各区切りの真ん中の時刻で、上がっている札が1枚だけで、その行であることを確かめる。
    heads があれば、上がっている札の中の文字にその行の見出しが入っていることも確かめる。"""
    errors = []
    for a, b, idx in timeline:
        if idx is None:
            continue
        t = (a + b) / 2
        im = render(t)
        focus = im.info.get('v3_focus') or []
        lifted = [f for f in focus if f['weight'] > 0.5]
        if len(lifted) != 1 or lifted[0]['row'] != idx:
            errors.append({'t': round(t, 2), 'want': idx, 'got': [f['row'] for f in lifted]})
            continue
        if heads:
            head = str(heads[idx])
            words = ''.join(lifted[0].get('text', []))
            if head and head not in words:
                errors.append({'t': round(t, 2), 'want': idx, 'missing': head})
    return errors
