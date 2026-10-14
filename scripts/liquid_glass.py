"""リキッドグラス風の板（Apple の Liquid Glass の考え方を借りた自前の描画。Apple の素材は使っていない）。

使い方: im = liquid_glass(im, box=(x0,y0,x1,y1), radius=40, tint=(255,255,255), tint_alpha=0.10, dark_text=False)
- 後ろの景色を板の中でぼかし、縁の近くだけレンズのように内側へ曲げて見せる（屈折）。
- 縁に沿った光の線（上と左が明るく、下と右は淡い）、上半分のつや、縁のごく弱い色のにじみ。
- 文字の読みやすさのため、中はわずかに暗く（明るい背景なら明るく）整える。
依存: Pillow・numpy。2026-10-14 コレスポ（Claude）。PWS などでも使える。
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _sdf_rounded(w, h, r):
    """角の丸い長方形の内側までの距離（縁で0、中へ行くほど大きい）。"""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    qx = np.abs(xs - cx) - (w / 2 - r)
    qy = np.abs(ys - cy) - (h / 2 - r)
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    return -outside, xs, ys, cx, cy


def liquid_glass(im, box, radius=40, bezel=34, refract=26, blur=10, tint=(255, 255, 255), tint_alpha=0.10,
                 darken=0.0, shadow=True):
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    base = im.convert("RGB")
    pad = refract + blur * 2
    src = base.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad)).filter(ImageFilter.GaussianBlur(blur))
    arr = np.asarray(src).astype(np.float32)
    d, xs, ys, cx, cy = _sdf_rounded(w, h, radius)
    inside = d >= 0
    # 縁から bezel の幅の中だけ、中心へ向けて曲げる（縁ほど強い）。
    t = np.clip(1 - d / bezel, 0, 1) ** 2
    vx, vy = xs - cx, ys - cy
    n = np.hypot(vx, vy) + 1e-6
    ox, oy = -vx / n * refract * t, -vy / n * refract * t

    def sample(shift):
        sx = np.clip(xs + pad + ox * shift, 0, arr.shape[1] - 1).astype(np.int32)
        sy = np.clip(ys + pad + oy * shift, 0, arr.shape[0] - 1).astype(np.int32)
        return arr[sy, sx]
    # 色のにじみ：赤と青を少しずらす（縁だけ）
    out = sample(1.0)
    out[..., 0] = sample(1.10)[..., 0]
    out[..., 2] = sample(0.90)[..., 2]
    # 明るさ・鮮やかさを少し上げ、薄く色を乗せる
    out = out * 1.12 + 6
    gray = out.mean(axis=2, keepdims=True)
    out = gray + (out - gray) * 1.25
    out = out * (1 - tint_alpha) + np.array(tint, np.float32) * tint_alpha
    out = out * (1 - darken)
    # 上半分のつや（ゆるい白のグラデーション）
    gloss = np.clip(1 - ys / (h * 0.55), 0, 1) ** 2 * 26
    out = out + gloss[..., None]
    # 縁の光：上・左が明るい。縁から数ピクセルだけ。
    rim = np.clip(1 - np.abs(d - 1.5) / 2.2, 0, 1)
    light = 0.55 + 0.45 * (-(vy / n) * 0.8 + -(vx / n) * 0.35)
    out = out + (rim * np.clip(light, 0.15, 1) * 150)[..., None]
    inner = np.clip(1 - np.abs(d - 7) / 5, 0, 1) * 0.25
    out = out + (inner * 40)[..., None]
    out = np.clip(out, 0, 255).astype(np.uint8)
    glass = Image.fromarray(out, "RGB")
    mask = Image.fromarray((np.clip(d + 0.5, 0, 1) * 255).astype(np.uint8), "L")
    res = base.convert("RGBA")
    if shadow:
        sh = Image.new("RGBA", res.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((x0 + 2, y0 + 14, x1 + 2, y1 + 14), radius=radius, fill=(0, 0, 0, 110))
        res.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    res.paste(glass, (x0, y0), mask)
    return res.convert(im.mode)
