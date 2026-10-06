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


# ------------------------------------------------------------------ 5
# 旋律（16小節、拍で書く）: (小節, 拍, 長さ, MIDI)。既存の曲の写しではない。
_A = [(0, 0, 1, 76), (0, 1.5, .5, 79), (0, 2, 1, 84), (0, 3, 1, 79),
      (1, 0, 1.5, 81), (1, 1.5, .5, 79), (1, 2, 1, 76), (1, 3, 1, 72),
      (2, 0, 1, 77), (2, 1, .5, 81), (2, 1.5, 1.5, 84), (2, 3, 1, 81),
      (3, 0, 1, 79), (3, 1, 1, 74), (3, 2, 2, 71)]
_A2_END = [(3, 0, .5, 79), (3, .5, .5, 81), (3, 1, 1, 83), (3, 2, 2, 86)]
_B = [(0, 0, .5, 79), (0, .5, .5, 76), (0, 1, 1, 79), (0, 2, 1, 84), (0, 3, 1, 88),
      (1, 0, 1, 86), (1, 1, 1, 84), (1, 2, 2, 81),
      (2, 0, .5, 84), (2, .5, .5, 81), (2, 1, 1, 77), (2, 2, 1, 81), (2, 3, 1, 84),
      (3, 0, 1, 83), (3, 1, 1, 79), (3, 2, 2, 74)]
_B2_END = [(3, 0, 1, 79), (3, 1, 1, 77), (3, 2, 1, 74), (3, 3, 1, 71)]


def everyday():
    """日常：軽い音（マリンバと鉄琴）が旋律を奏でる、明るくあっさりした曲。"""
    bpm, nbar = 104, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    marimba = gs.Sampler(VS / "Percussion/Marimba", keymap=lambda s: (
        gs.nn(gs.re.search(r"_([A-G]#?\d)_", s).group(1)), 1) if gs.re.search(r"_([A-G]#?\d)_", s) else None)
    glock = gs.Sampler(VS / "Percussion/Glock", keymap=lambda s: (
        gs.nn(gs.re.search(r"_([A-G]#?\d)\.wav", s).group(1)), 1) if gs.re.search(r"_([A-G]#?\d)\.wav", s) else None)
    pizz = gs.Sampler(VS / "Strings/Violin Section/Pizz", pattern=r"_([A-G]#?b?\d)_v(\d)")
    cello = gs.Sampler(VS / "Strings/Cello Section/pizzT", pattern=r"_([A-G]#?b?\d)_v(\d)")
    shake = [gs._load(f, SR) for f in sorted((VS / "Percussion").glob("Tamb1-Shake*.wav"))]
    # C → Am → F → G（4小節で一回り）
    prog = [(36, [60, 64, 67]), (33, [57, 60, 64]), (29, [57, 60, 65]), (31, [59, 62, 67])]
    melody = []
    for start, part, end in ((0, _A, None), (4, _A, _A2_END), (8, _B, None), (12, _B, _B2_END)):
        body = [x for x in part if not (end and x[0] == 3)] + (end or [])
        melody += [(start + bi, beat, d, m) for bi, beat, d, m in body]
    for bi, beat, d, m in melody:
        t0 = bi * bar + beat * b
        gs.put(mix, marimba.note(m - 12, d * b * 0.95, .7, rel=0.4), t0, 0.5, -0.15)
        if bi >= 8 and beat == 0:
            gs.put(mix, glock.note(m, b, .5), t0, 0.12, 0.4)       # サビだけ鉄琴を重ねる
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for beat in (1, 3):                                         # 2拍目と4拍目に軽い和音
            for j, m in enumerate(ch):
                gs.put(mix, pizz.note(m, b * 0.4, .45, rel=0.2, k=j + beat), t0 + beat * b + j * 0.008,
                       0.16, -0.35 + 0.35 * j)
        for beat in (0, 2):
            gs.put(mix, cello.note(root + 12, b * 0.6, .55, rel=0.3, k=beat), t0 + beat * b, 0.32, 0)
        if bi >= 2:
            for q in range(8):
                gs.put(mix, shake[q % len(shake)][:int(0.18 * SR)], t0 + q * b / 2, 0.05 if q % 2 else 0.035, 0.3)
            for beat in (0, 2):
                gs.put(mix, ml.kick(0.2) * 0.5, t0 + beat * b, 0.18)
            for beat in (1, 3):
                gs.put(mix, ml.clap(), t0 + beat * b, 0.06)
    return loop_finish(mix, nbar * bar, wet=0.18, sec=1.6, sub_cut=-8), "日常",         "104 BPM・ハ長調。マリンバ（VSCOの録音）が旋律を奏で、後半は鉄琴が重なる。弦のピチカートの軽い和音、低いピチカート、シェイカーと小さな手拍子。C→Am→F→G。軽くてあっさり。"


# ------------------------------------------------------------------ おしゃれ・ライト（10/7）
# 本人「かわいすぎる。YouTubeで聞くフリーBGMみたいな、おしゃれでライトで、邪魔をしない感じ」。
# 共通: 7th・9th の和音（エレピ）で色を出し、旋律は短い合いの手だけ。鈴・口笛・鉄琴は使わない。

def _st(x):
    """(2, n) のステレオを (n, 2) に。"""
    return x.T if x.ndim == 2 and x.shape[0] == 2 else x


def mute_guitar(notes, dur, v=0.6, seed=0):
    """カッティングのギター（はじく計算・短く止める）。"""
    n = int((dur + 0.05) * SR)
    out = np.zeros(n)
    r = np.random.default_rng(seed)
    for k, m in enumerate(notes):
        f = 440 * 2 ** ((m - 69) / 12)
        L = max(int(SR / f), 2)
        buf = r.uniform(-1, 1, L)
        y = np.zeros(n)
        for i in range(n):
            y[i] = buf[i % L]
            buf[i % L] = 0.5 * (buf[i % L] + buf[(i + 1) % L]) * 0.985
        d = int(k * 0.004 * SR)
        out[d:] += y[:n - d]
    env = np.exp(-np.arange(n) / (0.045 * SR))
    out = sosfilt(butter(2, [250, 3500], "bandpass", fs=SR, output="sos"), out * env)
    return out / (np.max(np.abs(out)) + 1e-9) * v


def ep_chord(notes, dur, v=0.5):
    return sum(bgm.rhodes(m, dur, v) for m in notes) / len(notes)


def chillhouse():
    """チルハウス：エレピの裏打ちと、ふくらむ下地、やわらかい四つ打ち。"""
    bpm, nbar = 118, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    # B♭maj9 → Am7 → Gm9 → C9sus4（ヘ長調）
    prog = [(46, [57, 60, 62, 65]), (45, [55, 60, 64, 67]), (43, [57, 58, 62, 65]), (48, [58, 62, 65, 67])]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        gs.put(mix, pad(ch, bar), t0, 0.12)
        for st in (0.5, 1.5, 2.5, 3.0, 3.5):
            gs.put(mix, ep_chord(ch, b * 0.35, .55), t0 + st * b, 0.30, -0.2 if st % 1 else 0.2)
        if bi % 2 == 1 and bi >= 4:                               # 2小節に1度、短い合いの手
            for k, m in enumerate((ch[-1] + 5, ch[-1] + 7, ch[-1] + 3)):
                gs.put(mix, _st(bgm.synth_arp(m, b * 0.4, .6, bi * 3 + k)), t0 + (2 + k * 0.5) * b, 0.10)
    mix *= gs.pump(n, b, depth=0.35)
    ev = []
    for bi in range(nbar):
        root = prog[bi % 4][0]
        for st, d in ((0, 0.75), (1.5, 0.4), (2, 0.75), (3.5, 0.4)):
            ev.append((int((bi * bar + st * b) * SR), int(d * b * SR), root, 0.5, 0, 0))
    bass = sosfilt(butter(2, 700, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.26)
    for bi in range(nbar):
        t0 = bi * bar
        for q in range(4):
            if bi >= 2:
                gs.put(mix, ml.kick(0.22) * 0.6, t0 + q * b, 0.22)
            gs.put(mix, ml.hat(False, 0.5), t0 + q * b + b / 2, 0.06, 0.3)
        if bi >= 4:
            for q in (1, 3):
                gs.put(mix, ml.clap(), t0 + q * b, 0.07)
    return loop_finish(mix, nbar * bar, wet=0.2, sec=1.8, sub_cut=-8), "チルハウス", \
        "118 BPM・ヘ長調。エレピの7th・9thの和音を裏打ちで刻み、下地がキックに合わせてふわっと沈む。やわらかい四つ打ち。合いの手は2小節に1度だけ。おしゃれ系フリーBGMの定番の方向。"


def jazzhop():
    """ジャズホップ：エレピの和音、ゆるく跳ねるドラム、少しのレコードの音。"""
    bpm, nbar = 86, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    sw = b / 2 * 0.6
    # E♭maj9 → Dm7 → Gm9 → C13（変ロ長調）
    prog = [(39, [55, 58, 62, 65]), (38, [57, 60, 62, 65]), (43, [57, 58, 62, 65]), (36, [58, 62, 64, 69])]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        gs.put(mix, ep_chord(ch, b * 1.8, .5), t0, 0.42, -0.15)
        gs.put(mix, ep_chord(ch[1:], b * 0.6, .4), t0 + 2 * b + sw, 0.28, 0.15)
        if bi % 4 == 3:                                           # 4小節ごとの短いフレーズ
            for k, m in enumerate((ch[-1] + 2, ch[-1], ch[-2] + 2)):
                gs.put(mix, bgm.rhodes(m + 12, b * 0.4, .45), t0 + 3 * b + k * sw * 0.8, 0.18, 0.3)
    ev = []
    for bi in range(nbar):
        root = prog[bi % 4][0]
        for st, d, off in ((0, 1.4, 0), (1.5 + 0.1, 0.4, 0), (2.5 + 0.1, 0.9, 7)):
            ev.append((int((bi * bar + st * b) * SR), int(d * b * SR), root + off, 0.5, 0, 0))
    bass = sosfilt(butter(2, 650, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.3)
    for bi in range(nbar):
        t0 = bi * bar
        for st in (0, 1.5 + 0.1, 2.5):
            gs.put(mix, ml.kick(0.25) * 0.6, t0 + st * b, 0.25)
        for st in (1, 3):
            s_ = sosfilt(butter(2, 3200, "lowpass", fs=SR, output="sos"), ml.snare())
            gs.put(mix, s_, t0 + st * b, 0.13)
        for q in range(4):
            gs.put(mix, ml.hat(False, 0.5), t0 + q * b, 0.045, 0.25)
            gs.put(mix, ml.hat(False, 0.35), t0 + q * b + sw, 0.03, 0.25)
    cr = np.zeros(n)
    idx = rng.integers(0, n, int(n / SR * 4))
    cr[idx] = rng.standard_normal(len(idx)) * 0.5
    cr = sosfilt(butter(2, [1500, 7000], "bandpass", fs=SR, output="sos"), cr)
    mix += gs.stereo(cr, 0) * 0.08
    return loop_finish(mix, nbar * bar, wet=0.22, sec=2.0, sub_cut=-8), "ジャズホップ", \
        "86 BPM・変ロ長調。エレピのジャズっぽい和音（E♭maj9→Dm7→Gm9→C13）、ゆるく跳ねるドラム、丸いベース、ほんの少しのレコードの音。落ち着いた話の回に。"


def funklight():
    """ファンクライト：ギターのカッティングと、はずむベース。軽いシティポップ寄り。"""
    bpm, nbar = 108, 16
    b = 60 / bpm
    bar = 4 * b
    s16 = b / 4
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    # Dmaj9 → Bm11 → Em9 → A13（ニ長調）
    prog = [(38, [57, 61, 64, 66], [66, 69, 73]), (35, [57, 62, 64, 69], [64, 69, 74]),
            (40, [55, 59, 62, 66], [62, 66, 71]), (45, [55, 61, 66, 67], [61, 66, 67])]
    cut = [2, 6, 7, 10, 14]
    for bi in range(nbar):
        root, ch, top = prog[bi % 4]
        t0 = bi * bar
        gs.put(mix, ep_chord(ch, b * 3.6, .35), t0, 0.22, -0.3)
        for k, st in enumerate(cut):
            gs.put(mix, mute_guitar([m - 12 for m in top], s16 * 0.9, .7, bi * 16 + k), t0 + st * s16, 0.16, 0.35)
    ev = []
    pat = [(0, 0), (3, 12), (6, 0), (8, 0), (10, 12), (11, 0), (14, 7)]
    for bi in range(nbar):
        root = prog[bi % 4][0]
        for st, off in pat:
            ev.append((int((bi * bar + st * s16) * SR), int(s16 * 1.6 * SR), root + off, 0.6, 0, 0))
    bass = sosfilt(butter(2, 1100, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.3)
    for bi in range(nbar):
        t0 = bi * bar
        for st in (0, 1.75, 2.5):
            gs.put(mix, ml.kick(0.22) * 0.6, t0 + st * b, 0.22)
        for st in (1, 3):
            gs.put(mix, ml.clap(), t0 + st * b, 0.1)
        for q in range(16):
            gs.put(mix, ml.hat(False, 0.5 if q % 2 else 0.3), t0 + q * s16, 0.03, 0.3)
    return loop_finish(mix, nbar * bar, wet=0.16, sec=1.5, sub_cut=-8), "ファンクライト", \
        "108 BPM・ニ長調。きれいな音のギターのカッティング（16分の裏）、はずむベース、エレピの和音、手拍子。軽いシティポップ寄りで、スポーツの話題に勢いが出る。"


def futurepop():
    """フューチャーポップ：沈む和音のシンセと、軽いスネア。明るく今っぽい。"""
    bpm, nbar = 100, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 4) * SR)
    mix = np.zeros((n, 2))
    # Fmaj7 → G6 → Em7 → Am9（ハ長調）
    prog = [(41, [57, 60, 64, 65]), (43, [59, 62, 64, 67]), (40, [55, 59, 62, 64]), (45, [55, 59, 60, 64])]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for st in (0, 0.75, 1.5, 2.5, 3.25):
            gs.put(mix, _st(bgm.supersaw(ch, b * 0.5, .8, bi * 8 + int(st * 4))), t0 + st * b, 0.7)
        if bi >= 8 and bi % 2 == 0:
            for k, m in enumerate((ch[-1] + 12, ch[-2] + 12, ch[-1] + 10)):
                gs.put(mix, bgm.pluck(m - 12, .5, bi * 3 + k), t0 + (1 + k * 0.5) * b, 0.08, 0.3 - 0.3 * k)
    mix *= gs.pump(n, b, depth=0.6)
    t = np.arange(n) / SR
    sub = np.zeros(n)
    for bi in range(nbar):
        root = prog[bi % 4][0]
        a, z = int(bi * bar * SR), int((bi + 1) * bar * SR)
        sub[a:z] = np.sin(2 * np.pi * 440 * 2 ** ((root - 69) / 12) * t[a:z])
    gs.put(mix, sub * gs.pump(n, b, depth=0.8)[:, 0], 0, 0.12)
    for bi in range(nbar):
        t0 = bi * bar
        for q in range(4):
            gs.put(mix, ml.kick(0.2) * 0.6, t0 + q * b, 0.2)
            gs.put(mix, ml.hat(False, 0.45), t0 + q * b + b / 2, 0.05, 0.3)
        for q in (1, 3):
            gs.put(mix, ml.snare(), t0 + q * b, 0.1)
            gs.put(mix, ml.clap(), t0 + q * b, 0.06)
    return loop_finish(mix, nbar * bar, wet=0.2, sec=1.6, sub_cut=-8), "フューチャーポップ", \
        "100 BPM・ハ長調。キックに合わせて沈むシンセの和音（Fmaj7→G6→Em7→Am9）、軽いスネアと手拍子、後半だけ短いはじく音の合いの手。明るく今っぽい。"


ALL = ["chillhouse", "jazzhop", "funklight", "futurepop", "everyday", "nighter", "scoreboard", "dugout", "comeback"]


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
