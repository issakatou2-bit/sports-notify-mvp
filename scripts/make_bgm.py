#!/usr/bin/env python3
"""ショートのBGMの候補を組み立てる（PCだけで動かす道具。Actionsでは動かさない）。

なぜ要るのか:
  10/6、本人「BGMもいい感じだけど主張しすぎない感じにしたい」。読み上げの邪魔を
  しないよう、旋律は控えめ・声の帯域（1.5〜4kHz）を少し空ける・ループの継ぎ目なし。

材料（生成AIは使わない）:
  - 数式の合成（music-compose スキルの部品: C:/Projects/PatchWorkSecure/Tools）
  - 自由に使える録音: VSCO 2 CE（CC0）・Growlybass（CC0）。表記の要る録音（MuldjordKit）は使わない。

使い方（music-compose の Python）:
  C:/Users/issak/Tools/Irodori-TTS/.venv/Scripts/python.exe scripts/make_bgm.py OUT_DIR [名前...]
出力: OUT_DIR/bgm_<名前>.wav（16小節のループ、平均 -14dB）
"""
import importlib.util
import pathlib
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

TOOLS = pathlib.Path("C:/Projects/PatchWorkSecure/Tools")
ARGS = sys.argv[1:]
sys.argv = [sys.argv[0]]
_spec = importlib.util.spec_from_file_location("gs", TOOLS / "Make-Genre-Sketches.py")
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)
ml, bgm = gs.ml, gs.bgm
SR = gs.SR
VS = gs.VS
Bass = gs.Bass
rng = np.random.default_rng(3)


def lp(x, f):
    return sosfilt(butter(2, f, "lowpass", fs=SR, output="sos"), x, axis=0)


def voice_room(x, depth=0.35):
    """声の帯域（1.5〜4kHz）を少し下げる。"""
    band = sosfilt(butter(2, [1500, 4000], "bandpass", fs=SR, output="sos"), x, axis=0)
    return x - depth * band


def loop_finish(mix, loop_len, wet=0.2, sec=2.0, sub_cut=-6):
    """残響をかけ、はみ出た尻尾を頭に重ねて継ぎ目をなくし、平均 -14dB にそろえる。"""
    x = mix.copy()
    for c in range(2):
        x[:, c] = sosfilt(butter(2, 30, "highpass", fs=SR, output="sos"), x[:, c])
    x = gs.shelf(x, 70, sub_cut, "low")
    x = voice_room(x)
    x = ml.reverb(x, sec, wet)
    L = int(loop_len * SR)
    out = x[:L].copy()
    tail = x[L:]
    out[:len(tail)] += tail[:L]
    out = out / (np.sqrt((out ** 2).mean()) + 1e-9) * 10 ** (-14 / 20)
    pk = np.max(np.abs(out))
    if pk > 0.9:
        out = np.tanh(out / pk * 1.4) / np.tanh(1.4) * 0.9
    return out


def organ(note, dur, v=0.6):
    """ドローバーのオルガン（倍音を足すだけ）。"""
    t = np.arange(int((dur + 0.08) * SR)) / SR
    f = 440 * 2 ** ((note - 69) / 12)
    x = sum(a * np.sin(2 * np.pi * f * m * t) for a, m in ((1, 1), (0.6, 2), (0.35, 3), (0.2, 4), (0.12, 6)))
    vib = 1 + 0.004 * np.sin(2 * np.pi * 6 * t)
    x = x * vib
    env = np.ones(len(t))
    env[:200] = np.linspace(0, 1, 200)
    g = int(dur * SR)
    env[g:] = np.linspace(1, 0, len(t) - g)
    return x * env * v * 0.25


def pad(notes, dur, v=0.5):
    """やわらかい和音の下地（のこぎり波を重ねて丸める）。"""
    x = ml.saw_stack(notes, dur, voices=5, detune=0.12)
    if x.ndim == 2:
        x = x.mean(axis=1)
    x = sosfilt(butter(2, 1800, "lowpass", fs=SR, output="sos"), x)
    n = len(x)
    env = np.minimum(np.arange(n) / (0.4 * SR), 1) * np.minimum((n - np.arange(n)) / (0.4 * SR), 1)
    return x * env * v


# ------------------------------------------------------------------ 1
def nighter():
    """ナイター：のんびりしたローファイ。ピアノの和音と、やわらかいリズム。"""
    bpm, nbar = 84, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    piano = gs.Sampler(VS / "Keys/Upright Piano", keymap=lambda s: (
        21 + 2 * int(gs.re.search(r"_(\d{3})\.wav", s).group(1)), int(gs.re.search(r"dyn(\d)", s).group(1)))
        if gs.re.search(r"_(\d{3})\.wav", s) else None)
    shake = [gs._load(f, SR) for f in sorted((VS / "Percussion").glob("Tamb1-Shake*.wav"))]
    # Gmaj7 → F#m7 → Em7 → A7sus（D長調、下がっていく流れ）
    prog = [(43, [59, 62, 66, 69]), (42, [57, 61, 64, 69]), (40, [55, 59, 62, 67]), (45, [57, 62, 64, 67])]
    sw = b / 2 * 0.58
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for j, m in enumerate(ch):
            gs.put(mix, piano.note(m, bar * 0.9, .38, rel=0.8, k=j), t0 + j * 0.02, 0.36, -0.2 + 0.13 * j)
        gs.put(mix, piano.note(ch[1] + 12, b * 0.8, .3), t0 + 2 * b + sw, 0.18, 0.25)
    ev = []
    for bi in range(nbar):
        root = prog[bi % 4][0]
        for st, d, off in [(0, 1.5, 0), (2, 1.0, 0), (3, 0.8, 7)]:
            ev.append((int((bi * bar + st * b) * SR), int(d * b * SR), root + off, 0.5, 0, 0))
    bass = sosfilt(butter(2, 700, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.3)
    for bi in range(nbar):
        t0 = bi * bar
        for st in (0, 2.5):
            gs.put(mix, ml.kick(0.3) * 0.6, t0 + st * b, 0.28)
        for st in (1, 3):
            s = sosfilt(butter(2, 3000, "lowpass", fs=SR, output="sos"), ml.snare())
            gs.put(mix, s, t0 + st * b, 0.16)
        for q in range(4):
            gs.put(mix, shake[q % len(shake)][:int(0.22 * SR)], t0 + q * b + sw, 0.09, 0.35)
    mix = lp(mix, 8500)
    return loop_finish(mix, nbar * bar, wet=0.22), "ナイター", \
        "84 BPM・D長調。ピアノの和音（VSCOの録音）をばらして置き、Gmaj7→F#m7→Em7→A7susと下がる。やわらかいキック・丸めたスネア・シェイカー・低いベース。いちばん控えめ。"


# ------------------------------------------------------------------ 2
def scoreboard():
    """スコアボード：軽い電子音。はじく音の分散和音と、やさしい四つ打ち。"""
    bpm, nbar = 112, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    # Am → F → C → G
    prog = [(45, [57, 60, 64]), (41, [53, 57, 60]), (48, [55, 60, 64]), (43, [55, 59, 62])]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        gs.put(mix, pad(ch, bar), t0, 0.22)
        arp = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[1] + 12]
        for s in range(8):
            if bi < 2 and s % 2:
                continue
            gs.put(mix, bgm.pluck(arp[s % 4], 0.55, bi * 8 + s), t0 + s * b / 2, 0.12, -0.35 if s % 2 else 0.35)
    pumpg = gs.pump(n, b, depth=0.45)
    mix *= pumpg
    ev = []
    for bi in range(nbar):
        root = prog[bi % 4][0]
        for s in range(4):
            ev.append((int((bi * bar + s * b + b / 2) * SR), int(b / 2 * 0.8 * SR), root, 0.55, 0, 0))
    bass = sosfilt(butter(2, 900, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.28)
    for bi in range(nbar):
        t0 = bi * bar
        for q in range(4):
            gs.put(mix, ml.kick(0.25) * 0.7, t0 + q * b, 0.28)
            gs.put(mix, ml.hat(False, 0.6), t0 + q * b + b / 2, 0.07, 0.3)
        if bi >= 4:
            for q in (1, 3):
                gs.put(mix, ml.clap(), t0 + q * b, 0.12)
    return loop_finish(mix, nbar * bar, wet=0.16, sec=1.6), "スコアボード", \
        "112 BPM・イ短調。はじく音の分散和音と、ふくらむ和音の下地、やさしい四つ打ち。Am→F→C→G。ニュースの背景のような軽さ。"


# ------------------------------------------------------------------ 3
def dugout():
    """ダッグアウト：球場のオルガンを思わせる軽いファンク（応援歌は真似しない）。"""
    bpm, nbar = 100, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    tamb = [gs._load(f, SR) for f in sorted((VS / "Percussion").glob("Tamb1-Hit*.wav"))]
    # F → B♭ → F → C
    prog = [(41, [60, 65, 69]), (46, [62, 65, 70]), (41, [60, 65, 69]), (48, [60, 64, 67])]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for st in (0.5, 1.5, 2.5, 3.25):
            for j, m in enumerate(ch):
                gs.put(mix, organ(m, b * 0.32), t0 + st * b, 0.5, -0.3 + 0.3 * j)
    ev = []
    walk = [0, 0, 7, 10]
    for bi in range(nbar):
        root = prog[bi % 4][0]
        for s in range(4):
            ev.append((int((bi * bar + s * b) * SR), int(b * 0.7 * SR), root + walk[s], 0.6, 0, 0))
    bass = sosfilt(butter(2, 900, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.5)
    for bi in range(nbar):
        t0 = bi * bar
        for st in (0, 1.75, 2.5):
            gs.put(mix, ml.kick(0.28) * 0.7, t0 + st * b, 0.4)
        for st in (1, 3):
            gs.put(mix, ml.clap(), t0 + st * b, 0.16)
        for q in range(8):
            gs.put(mix, tamb[q % len(tamb)][:int(0.2 * SR)], t0 + q * b / 2, 0.05 if q % 2 else 0.08, 0.4)
    return loop_finish(mix, nbar * bar, wet=0.2, sec=1.8), "ダッグアウト", \
        "100 BPM・ヘ長調。球場のオルガンを思わせる和音の刻み（合成）、歩くベース、手拍子とタンバリン。F→B♭→F→C。いちばん野球らしい。"


# ------------------------------------------------------------------ 4
def comeback():
    """逆襲：弦の刻みが少しずつ厚くなる映画風。どん底から上がる話に。"""
    bpm, nbar = 96, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    cello = gs.Sampler(VS / "Strings/Cello Section/Spic", pattern=r"_([A-G]#?b?\d)_v(\d)")
    vln = gs.Sampler(VS / "Strings/Violin Section/susVib", pattern=r"_([A-G]#?b?\d)_v(\d)")
    # Dm → B♭ → F → C
    prog = [(38, [62, 65, 69]), (34, [62, 65, 70]), (41, [60, 65, 69]), (36, [60, 64, 67])]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        lvl = 0.5 + 0.5 * (bi / (nbar - 1))
        for s in range(8):
            m = root + 12 + (0 if s % 2 == 0 else 7 if s % 4 == 1 else 12)
            gs.put(mix, cello.note(m, b / 2 * 0.8, .55 + .2 * (s % 2 == 0), rel=0.15, k=s), t0 + s * b / 2,
                   0.32 * lvl, -0.25)
        if bi >= 4:
            for j, m in enumerate(ch):
                gs.put(mix, vln.note(m + 12, bar * 0.98, .5, swell=0.8, rel=0.6, k=j), t0, 0.12 * lvl, 0.25 - 0.1 * j)
        if bi % 4 == 0:
            t = np.arange(int(1.5 * SR)) / SR
            boom = np.sin(2 * np.pi * (55 + 40 * np.exp(-t * 20)) * t) * np.exp(-t * 2.8)
            gs.put(mix, boom, t0, 0.12)
        if bi >= 8:
            for q in (1, 3):
                s = sosfilt(butter(2, 2500, "lowpass", fs=SR, output="sos"), ml.snare())
                gs.put(mix, s, t0 + q * b, 0.12)
    return loop_finish(mix, nbar * bar, wet=0.25, sec=2.4, sub_cut=-10), "逆襲", \
        "96 BPM・ニ短調。チェロの刻み（VSCOの録音）が続き、5小節目からバイオリンの和音がふくらむ。4小節ごとに低い一撃。Dm→B♭→F→C。後半ほど厚くなる。"


ALL = ["nighter", "scoreboard", "dugout", "comeback"]


def main():
    out = pathlib.Path(ARGS[0] if ARGS else "build/bgm")
    out.mkdir(parents=True, exist_ok=True)
    for name in (ARGS[1:] or ALL):
        x, title, desc = globals()[name]()
        wavfile.write(out / f"bgm_{name}.wav", SR, (x * 32767).astype(np.int16))
        (out / f"bgm_{name}.txt").write_text(title + "\n" + desc, encoding="utf-8")
        low = np.abs(np.fft.rfft(x.mean(axis=1)))
        f = np.fft.rfftfreq(len(x), 1 / SR)
        tot = (low ** 2).sum()
        share = lambda a, z: round(float((low[(f >= a) & (f < z)] ** 2).sum() / tot), 2)  # noqa: E731
        print(f"{name}: {len(x) / SR:.1f}s peak {np.max(np.abs(x)):.2f} "
              f"<60Hz {share(0, 60)} 60-250 {share(60, 250)} 250-1k {share(250, 1000)} 1-4k {share(1000, 4000)}")


if __name__ == "__main__":
    main()
