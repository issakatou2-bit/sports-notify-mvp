#!/usr/bin/env python3
"""画面の動きに合わせる効果音（数式の合成だけ。録音・生成AIは使わない）。

なぜ要るのか:
  10/6、本人「効果音は画面の動きに連動する感じで」。新デザイン（札が飛び込む・
  数字が回って止まる・○が付く・マーカーが引かれる）に、動きごとの音を当てる。

  どれも numpy だけで作るので、GitHub Actions でも同じ音が毎回できる
  （音の素材ファイルをリポジトリに置かない。権利の表記も要らない）。

使い方:
  import sfx; y = sfx.make("swish", variant="a")   # 44100Hz・モノラル・-1〜1
  python scripts/sfx.py out_dir                     # 全部を wav で書き出す（試聴用）
"""
import pathlib
import sys

import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100
_RNG = np.random.default_rng(7)


def _n(sec):
    return int(sec * SR)


def _t(sec):
    return np.arange(_n(sec)) / SR


def _noise(sec, seed=0):
    return np.random.default_rng(seed).standard_normal(_n(sec))


def _band(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "bandpass", fs=SR, output="sos"), x)


def _lp(x, f, order=2):
    return sosfilt(butter(order, f, "lowpass", fs=SR, output="sos"), x)


def _hp(x, f, order=2):
    return sosfilt(butter(order, f, "highpass", fs=SR, output="sos"), x)


def _sweep_filter(x, f0, f1, q_width=0.6, blocks=48):
    """帯域を f0→f1 へ動かしながら通す（風切り音）。"""
    out = np.zeros_like(x)
    edges = np.linspace(0, len(x), blocks + 1).astype(int)
    for i in range(blocks):
        a, b = edges[i], edges[i + 1]
        f = f0 * (f1 / f0) ** (i / max(blocks - 1, 1))
        lo, hi = f * (1 - q_width / 2), min(f * (1 + q_width / 2), SR / 2 - 100)
        seg = _band(x[max(0, a - 512):b], lo, hi)
        out[a:b] = seg[-(b - a):]
    return out


def _env(n, attack, release, curve=2.0):
    e = np.ones(n)
    a = max(1, _n(attack))
    e[:a] = np.linspace(0, 1, a)
    r = max(1, min(n, _n(release)))
    e[-r:] *= np.linspace(1, 0, r) ** curve
    return e


def _norm(x, peak=0.8):
    return x / (np.max(np.abs(x)) + 1e-9) * peak


# ---------------------------------------------------------------- 札が飛び込む
def swish(variant="a"):
    """札・行が横から入る。a＝軽い風、b＝鋭く短い。"""
    if variant == "b":
        d = 0.18
        x = _sweep_filter(_noise(d, 1), 6000, 1800, 0.5)
        return _norm(x * _env(len(x), 0.01, 0.12, 3), 0.7)
    d = 0.32
    x = _sweep_filter(_noise(d, 2), 900, 4200, 0.8)
    e = np.sin(np.pi * np.linspace(0, 1, len(x))) ** 1.5
    return _norm(x * e, 0.6)


# ---------------------------------------------------------------- 数字が回って止まる
def roll(variant="a", sec=1.2):
    """スロットのように数字が回り、だんだん遅くなって止まる。a＝機械のカチカチ、b＝電子音。"""
    y = np.zeros(_n(sec + 0.4))
    # だんだん間が空く
    times, t, gap = [], 0.0, 0.035
    while t < sec:
        times.append(t)
        t += gap
        gap *= 1.09
    for i, t0 in enumerate(times):
        if variant == "b":
            f = 1400 + 30 * (i % 3)
            k = np.sin(2 * np.pi * f * _t(0.03)) * _env(_n(0.03), 0.001, 0.025, 2)
            g = 0.25
        else:
            k = _band(_noise(0.02, 10 + i), 2500, 7000) * _env(_n(0.02), 0.0005, 0.018, 4)
            g = 0.5
        a = _n(t0)
        y[a:a + len(k)] += g * k
    return _norm(y, 0.55)


def stop(variant="a"):
    """回っていた数字が止まる一撃。a＝ガチャン（低い胴鳴り）、b＝電子のピコン。"""
    if variant == "b":
        t = _t(0.35)
        f = 880 * np.where(t < 0.06, 1, 1.5)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(len(t), 0.002, 0.3, 3)
        return _norm(x, 0.6)
    t = _t(0.45)
    body = np.sin(2 * np.pi * (110 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 9)
    click = _band(_noise(0.45, 3), 1500, 6000) * np.exp(-t * 60)
    return _norm(body + 0.6 * click, 0.85)


# ---------------------------------------------------------------- ○が付く・項目が出る
def pop(variant="a"):
    """○が付く・吹き出しが出る。a＝ポン（泡）、b＝チーン（小さな鐘）。"""
    if variant == "b":
        t = _t(0.9)
        x = sum(a * np.sin(2 * np.pi * 1318.5 * m * t) * np.exp(-t * d)
                for a, m, d in ((1, 1, 5), (0.5, 2.76, 9), (0.25, 5.4, 14)))
        return _norm(x * _env(len(t), 0.002, 0.2), 0.45)
    t = _t(0.16)
    f = 380 + 900 * (t / 0.16) ** 0.6
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 28)
    return _norm(x, 0.6)


# ---------------------------------------------------------------- 大きな数字がドン
def impact(variant="a"):
    """大きな数字・見出しが出る。a＝ドン（低い一撃＋残響）、b＝バシッ（明るい一撃）。"""
    t = _t(1.4)
    if variant == "b":
        x = _hp(_noise(1.4, 4), 1200) * np.exp(-t * 14) + 0.6 * np.sin(2 * np.pi * 70 * t) * np.exp(-t * 10)
        return _norm(x, 0.8)
    sub = np.sin(2 * np.pi * (48 + 60 * np.exp(-t * 18)) * t) * np.exp(-t * 3.2)
    hit = _lp(_noise(1.4, 5), 2500) * np.exp(-t * 22)
    tail = _band(_noise(1.4, 6), 200, 1500) * np.exp(-t * 2.5) * 0.15
    return _norm(sub + 0.5 * hit + tail, 0.9)


# ---------------------------------------------------------------- マーカーが引かれる
def marker(variant="a"):
    """大事な語に色が入る。a＝シャッ（明るいこすれ）、b＝キラッ（上がる音）。"""
    if variant == "b":
        t = _t(0.5)
        x = sum(np.sin(2 * np.pi * f * t) * np.exp(-((t - k * 0.05) * 30) ** 2)
                for k, f in enumerate((1568, 1976, 2349, 3136)))
        return _norm(x * _env(len(t), 0.005, 0.3), 0.4)
    x = _sweep_filter(_noise(0.35, 7), 2500, 7000, 0.4)
    return _norm(x * _env(len(x), 0.04, 0.15, 2), 0.45)


# ---------------------------------------------------------------- 場面が切り替わる
def transition(variant="a"):
    """場面・画面の切り替え。a＝逆回しのシンバル（吸い込む）、b＝シュッと下がる。"""
    if variant == "b":
        d = 0.4
        x = _sweep_filter(_noise(d, 8), 5000, 400, 0.7)
        return _norm(x * _env(len(x), 0.01, 0.3, 2), 0.6)
    d = 0.9
    t = _t(d)
    x = _hp(_noise(d, 9), 3000) * (t / d) ** 3
    x[-_n(0.01):] *= np.linspace(1, 0, _n(0.01))
    return _norm(x, 0.5)


# ---------------------------------------------------------------- 棒・線が伸びる
def rise(variant="a", sec=0.8):
    """棒グラフ・線が伸びる。a＝やわらかく上がる音、b＝カウントの電子音。"""
    t = _t(sec)
    if variant == "b":
        y = np.zeros(len(t))
        for i, t0 in enumerate(np.arange(0, sec - 0.05, 0.06)):
            f = 600 + i * 45
            k = np.sin(2 * np.pi * f * _t(0.04)) * _env(_n(0.04), 0.001, 0.03)
            a = _n(t0)
            y[a:a + len(k)] += k
        return _norm(y, 0.35)
    f = 220 * 2 ** (t / sec * 1.5)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * np.sin(2 * np.pi * np.cumsum(2 * f) / SR)
    return _norm(x * _env(len(t), 0.05, 0.2), 0.35)


# ---------------------------------------------------------------- コメントが届く
def notify(variant="a"):
    """コメントの吹き出しが出る。a＝ポロン（2音）、b＝コトッ（木を叩く）。"""
    if variant == "b":
        t = _t(0.25)
        x = np.sin(2 * np.pi * 620 * t) * np.exp(-t * 35) + 0.4 * np.sin(2 * np.pi * 1730 * t) * np.exp(-t * 60)
        return _norm(x, 0.55)
    y = np.zeros(_n(0.6))
    for t0, f in ((0, 1046.5), (0.09, 1568)):
        t = _t(0.45)
        k = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)) * np.exp(-t * 9)
        a = _n(t0)
        y[a:a + len(k)] += k[:len(y) - a]
    return _norm(y * _env(len(y), 0.002, 0.1), 0.4)


KINDS = {
    "swish": ("札が飛び込む", swish),
    "roll": ("数字が回る", roll),
    "stop": ("数字が止まる", stop),
    "pop": ("○が付く・項目が出る", pop),
    "impact": ("大きな数字がドン", impact),
    "marker": ("マーカーが引かれる", marker),
    "transition": ("場面が切り替わる", transition),
    "rise": ("棒・線が伸びる", rise),
    "notify": ("コメントが出る", notify),
}


def make(kind: str, variant: str = "a") -> np.ndarray:
    return KINDS[kind][1](variant)


def place(track: np.ndarray, sig: np.ndarray, at: float, gain: float = 1.0) -> None:
    """track（モノラル）の at 秒に sig を足す。はみ出たぶんは切る。"""
    a = _n(at)
    if a >= len(track):
        return
    m = min(len(sig), len(track) - a)
    track[a:a + m] += gain * sig[:m]


def main(out: str) -> int:
    from scipy.io import wavfile
    d = pathlib.Path(out)
    d.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        for v in ("a", "b"):
            y = make(kind, v)
            wavfile.write(d / f"sfx_{kind}_{v}.wav", SR, (np.clip(y, -1, 1) * 32767).astype(np.int16))
    print(f"[info] {len(KINDS) * 2}個 -> {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "build/sfx"))
