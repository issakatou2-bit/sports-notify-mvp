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


# ------------------------------------------------------------------ 乾いた・軽い（10/7夕）
# 本人「質は下げないで、でも音の響きが広すぎる。もっと軽くていい。エコーなし。
#   電子音か、メロディなしの伴奏だけ。ハイハットのトラップ（ﾁﾁﾁﾁﾀﾁﾁﾁﾁﾁﾁﾁﾀﾁﾁﾁ）のドラムだけも」。
# 共通: 残響なし・左右の広がりは小さく・音数を減らす。

def dry_finish(mix, loop_len, sub_cut=-6):
    """残響をかけずに仕上げる（継ぎ目は尻尾を頭に重ねるだけ）。"""
    x = mix.copy()
    for c in range(2):
        x[:, c] = sosfilt(butter(2, 30, "highpass", fs=SR, output="sos"), x[:, c])
    x = gs.shelf(x, 70, sub_cut, "low")
    x = voice_room(x, 0.25)
    mid = x.mean(axis=1, keepdims=True)
    x = mid + (x - mid) * 0.6                               # 左右の広がりを狭く
    L = int(loop_len * SR)
    out = x[:L].copy()
    tail = x[L:]
    out[:len(tail)] += tail[:L]
    out = out / (np.sqrt((out ** 2).mean()) + 1e-9) * 10 ** (-14 / 20)
    pk = np.max(np.abs(out))
    if pk > 0.9:
        out = np.tanh(out / pk * 1.4) / np.tanh(1.4) * 0.9
    return out


def _hat16(mix, t0, b, bars_i, roll=True, vel=(0.55, 0.35), g=0.16):
    """16分のハイハット。2小節に1度、最後の拍を32分で詰める（チキチキ）。"""
    s16 = b / 4
    for q in range(16):
        if roll and bars_i % 2 == 1 and q >= 12:
            for r in range(2):
                gs.put(mix, ml.hat(False, 0.45), t0 + (q + r * 0.5) * s16, g * 0.8, 0.1)
            continue
        if q in (4, 12):
            continue                                           # 「タ」の所はハイハットを抜く
        gs.put(mix, ml.hat(False, vel[0] if q % 2 == 0 else vel[1]), t0 + q * s16, g, 0.1)


def trap_hats():
    """ﾁﾁﾁﾁﾀﾁﾁﾁﾁﾁﾁﾁﾀﾁﾁﾁ：ハイハットと手拍子と軽いキックだけ。音程のある楽器なし。"""
    bpm, nbar = 96, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 2) * SR)
    mix = np.zeros((n, 2))
    for bi in range(nbar):
        t0 = bi * bar
        _hat16(mix, t0, b, bi)
        for q in (1, 3):                                       # 「タ」＝2拍目と4拍目
            gs.put(mix, ml.clap(), t0 + q * b, 0.22)
        for st in (0, 2.5 if bi % 2 == 0 else 2.25):
            gs.put(mix, ml.kick(0.25) * 0.7, t0 + st * b, 0.2)
    return dry_finish(mix, nbar * bar), "トラップ・ハイハット", \
        "96 BPM。ﾁﾁﾁﾁﾀﾁﾁﾁﾁﾁﾁﾁﾀﾁﾁﾁ の注文どおり、16分のハイハットに2拍目・4拍目の手拍子、軽いキックだけ。2小節に1度、最後の拍を細かく詰める。音程のある楽器なし・残響なし。"


def trap_808():
    """トラップ・ハイハットに、808の低音（すべる）を足す。旋律なし。"""
    bpm, nbar = 96, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 2) * SR)
    mix = np.zeros((n, 2))
    roots = [36, 33, 29, 31]                                   # C → A → F → G（長調の流れ）
    notes, times = [], []
    for bi in range(nbar):
        t0 = bi * bar
        _hat16(mix, t0, b, bi)
        for q in (1, 3):
            gs.put(mix, ml.clap(), t0 + q * b, 0.2)
        r = roots[bi % 4]
        for st, off in ((0, 0), (1.75, 0), (2.5, 7 if bi % 2 else 0)):
            notes.append(r + 12 + off)
            times.append(t0 + st * b)
            gs.put(mix, ml.kick(0.2) * 0.6, t0 + st * b, 0.18)
    bass = ml.k808(notes, times, n, decay=0.45, drive=1.6, glide=0.05)
    bass = sosfilt(butter(2, 70, "highpass", fs=SR, output="sos"), bass)
    gs.put(mix, bass, 0, 0.10)
    return dry_finish(mix, nbar * bar, sub_cut=-4), "トラップ808", \
        "96 BPM。トラップ・ハイハットに、すべる808の低音（C→A→F→G）を足した。旋律なし・残響なし。"


def _pulse(note, dur, v=0.5, width=0.25):
    """やわらかい矩形波（電子音）。"""
    n = int((dur + 0.02) * SR)
    t = np.arange(n) / SR
    f = 440 * 2 ** ((note - 69) / 12)
    x = np.where((f * t) % 1 < width, 1.0, -1.0)
    x = sosfilt(butter(2, 2600, "lowpass", fs=SR, output="sos"), x)
    env = np.minimum(t / 0.004, 1) * np.exp(-t / max(dur * 0.6, 0.05))
    return x * env * v


def dry_electro():
    """ドライ・エレクトロ：短い電子音の和音と、ぽこぽこした低音、乾いたドラム。"""
    bpm, nbar = 112, 16
    b = 60 / bpm
    bar = 4 * b
    s16 = b / 4
    n = int((nbar * bar + 2) * SR)
    mix = np.zeros((n, 2))
    # C → Am → F → G（ハ長調）、和音は短く切る
    prog = [(36, [60, 64, 67]), (33, [57, 60, 64]), (29, [57, 60, 65]), (31, [59, 62, 67])]
    stab = [2, 6, 10, 11, 14]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for st in stab:
            for m in ch:
                gs.put(mix, _pulse(m, s16 * 0.8, .35), t0 + st * s16, 0.12)
        for st, off in ((0, 0), (3, 12), (8, 0), (11, 12), (14, 7)):
            gs.put(mix, _pulse(root + 12 + off, s16 * 1.2, .6, 0.5), t0 + st * s16, 0.22)
        if bi >= 8 and bi % 2 == 1:                            # 後半だけ、2小節に1度の短い電子音
            for k, m in enumerate((ch[-1] + 12, ch[-2] + 12, ch[-1] + 12, ch[0] + 12)):
                gs.put(mix, _pulse(m, s16 * 0.9, .4, 0.125), t0 + (8 + k * 2) * s16, 0.08)
        for q in range(4):
            gs.put(mix, ml.kick(0.2) * 0.6, t0 + q * b, 0.22)
            gs.put(mix, ml.hat(False, 0.5), t0 + q * b + b / 2, 0.12)
        for q in (1, 3):
            gs.put(mix, ml.clap(), t0 + q * b, 0.12)
    return dry_finish(mix, nbar * bar), "ドライ・エレクトロ", \
        "112 BPM・ハ長調。短く切った電子音（矩形波）の和音の刻み、ぽこぽこ跳ねる低音、乾いたドラム。後半だけ2小節に1度、短い電子音の合いの手。残響なし。"


def dry_backing():
    """伴奏だけ：エレピの和音の刻みとベースと軽いドラム。旋律なし・残響なし。"""
    bpm, nbar = 104, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 2) * SR)
    mix = np.zeros((n, 2))
    # Fmaj7 → Em7 → Dm7 → Cmaj7（ハ長調、下がっていく）
    prog = [(41, [57, 60, 64]), (40, [55, 59, 62]), (38, [53, 57, 60]), (36, [55, 59, 64])]
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for st in (0.5, 1.5, 2.5, 3.5):
            gs.put(mix, ep_chord(ch, b * 0.3, .5), t0 + st * b, 0.32)
    ev = []
    for bi in range(nbar):
        root = prog[bi % 4][0]
        for st, d in ((0, 0.9), (1.5, 0.4), (2, 0.9), (3.5, 0.4)):
            ev.append((int((bi * bar + st * b) * SR), int(d * b * SR), root, 0.55, 0, 0))
    bass = sosfilt(butter(2, 800, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.3)
    for bi in range(nbar):
        t0 = bi * bar
        for st in (0, 2.5):
            gs.put(mix, ml.kick(0.22) * 0.6, t0 + st * b, 0.24)
        for q in (1, 3):
            gs.put(mix, ml.clap(), t0 + q * b, 0.09)
        for q in range(8):
            gs.put(mix, ml.hat(False, 0.45 if q % 2 == 0 else 0.3), t0 + q * b / 2, 0.08)
    return dry_finish(mix, nbar * bar), "伴奏だけ", \
        "104 BPM・ハ長調。エレピの和音の裏打ち（Fmaj7→Em7→Dm7→Cmaj7）、ベース、軽いドラムだけ。旋律なし・残響なし。"


# ------------------------------------------------------------------ 伴奏だけ・和音の流れの違い（10/7夜）
# 本人「伴奏だけが良さげ。コード進行のバリエーションがいくつか欲しい」。
# 音の作り（エレピ・ベース・軽いドラム・残響なし）は「伴奏だけ」と同じで、和音の流れと刻み方だけ変える。
# どれもよく使われる一般的な流れ。特定の曲の和音の並びは写さない。

RHYTHMS = {
    "ura": [(0.5, 0.3), (1.5, 0.3), (2.5, 0.3), (3.5, 0.3)],              # 裏打ち
    "sync": [(0, 0.4), (0.75, 0.25), (1.5, 0.4), (2.5, 0.3), (3.25, 0.5)],  # はねる刻み
    "long": [(0, 1.6), (2, 0.4), (2.75, 1.0)],                             # 長め・ゆったり
}


def _backing(bpm, prog, rhythm, bass_pat=((0, 0.9), (1.5, 0.4), (2, 0.9), (3.5, 0.4))):
    b = 60 / bpm
    bar = 4 * b
    nbar = 16
    n = int((nbar * bar + 2) * SR)
    mix = np.zeros((n, 2))
    chords = [prog[(bi * len(prog)) // nbar % len(prog)] if len(prog) > 4 else prog[bi % len(prog)]
              for bi in range(nbar)]
    for bi, (root, ch) in enumerate(chords):
        t0 = bi * bar
        for st, d in RHYTHMS[rhythm]:
            gs.put(mix, ep_chord(ch, b * d, .5), t0 + st * b, 0.32)
    ev = []
    for bi, (root, ch) in enumerate(chords):
        for st, d in bass_pat:
            ev.append((int((bi * bar + st * b) * SR), int(d * b * SR), root, 0.55, 0, 0))
    bass = sosfilt(butter(2, 800, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.3)
    for bi in range(nbar):
        t0 = bi * bar
        for st in (0, 2.5):
            gs.put(mix, ml.kick(0.22) * 0.6, t0 + st * b, 0.24)
        for q in (1, 3):
            gs.put(mix, ml.clap(), t0 + q * b, 0.09)
        for q in range(8):
            gs.put(mix, ml.hat(False, 0.45 if q % 2 == 0 else 0.3), t0 + q * b / 2, 0.08)
    return dry_finish(mix, nbar * bar)


def backing_pop():
    """C → G/B → Am7 → Fmaj7：いちばん素直で明るい流れ。"""
    prog = [(36, [55, 60, 64]), (35, [55, 59, 62]), (33, [55, 60, 64]), (29, [57, 60, 64])]
    return _backing(108, prog, "ura"), "伴奏・王道", \
        "108 BPM・ハ長調。C→G/B→Am7→Fmaj7。いちばん素直で明るい流れ。裏打ち。"


def backing_jpop():
    """Fmaj7 → G7 → Em7 → Am7：日本のポップスでよく使われる、少し切なさのある流れ。"""
    prog = [(41, [57, 60, 64]), (43, [55, 59, 65]), (40, [55, 59, 62]), (45, [55, 60, 64])]
    return _backing(104, prog, "sync"), "伴奏・切なめ", \
        "104 BPM・ハ長調。Fmaj7→G7→Em7→Am7。少し切なさのある、日本のポップスでよく使われる流れ。はねる刻み。"


def backing_jazz():
    """Dm9 → G13 → Cmaj9 → A7：ジャズっぽい ii-V-I。"""
    prog = [(38, [57, 60, 64, 65]), (43, [53, 59, 64]), (36, [55, 59, 62, 64]), (33, [55, 61, 64])]
    return _backing(96, prog, "long"), "伴奏・ジャズ", \
        "96 BPM・ハ長調。Dm9→G13→Cmaj9→A7。ジャズでよく使う ii-V-I の流れ。長めにゆったり。"


def backing_vamp():
    """Fmaj7 ⇄ G6 の2つだけ：いちばん主張しない。"""
    prog = [(41, [57, 60, 64]), (43, [59, 62, 64])]
    return _backing(110, prog, "sync"), "伴奏・2つの和音", \
        "110 BPM・ハ長調。Fmaj7とG6を行き来するだけ。いちばん主張しない、ずっと流しても飽きにくい形。"


def backing_sixties():
    """C6 → Am7 → Dm7 → G7sus：昔のポップスのような、ほのぼのした一回り。"""
    prog = [(36, [57, 60, 64]), (33, [55, 60, 64]), (38, [57, 60, 65]), (43, [57, 60, 65])]
    return _backing(112, prog, "ura"), "伴奏・ほのぼの", \
        "112 BPM・ハ長調。C6→Am7→Dm7→G7sus。昔のポップスのような一回り。裏打ち。"


def backing_bright():
    """D → A/C# → Bm7 → G → Em7 → A7sus（6つ、長め）：明るく前に進む。"""
    prog = [(38, [57, 62, 66]), (37, [57, 61, 64]), (35, [57, 62, 66]), (43, [55, 59, 62]),
            (40, [55, 59, 62]), (45, [57, 62, 64])]
    return _backing(116, prog, "sync"), "伴奏・前向き", \
        "116 BPM・ニ長調。D→A/C#→Bm7→G→Em7→A7sus。ベースが下がっていき、最後に前へ戻る。はねる刻み。"


# ------------------------------------------------------------------ 今っぽく（10/7夜2）
# 本人「ドゥンってやつ、最近の曲でわざと伸ばして音程つけるやつ」＝音程のある長い808。
# 「伴奏・切なめ、ジャズを、もっと現代っぽく、質を上げて」。
# 質の上げ方: 和音を9th・11th・13thまで重ねる、強さと時間を少しずつ揺らす（人の手の感じ）、
# ゴーストノート（ごく小さい音）、ハイハットの3連の詰め、808の低音、軽いテープのひずみ。残響なし。

_HR = np.random.default_rng(42)


def _hum(t, ms=6):
    """時間を少し揺らす（±ms）。"""
    return max(0.0, t + _HR.uniform(-ms, ms) / 1000)


def _tape(x, drive=1.2):
    """軽いテープのひずみ（角を丸める）。"""
    pk = np.max(np.abs(x)) + 1e-9
    return np.tanh(drive * x / pk) / np.tanh(drive) * pk


def _modern_drums(mix, t0, b, bi, trap=True):
    """今っぽいドラム: 16分のハイハット（強弱つき・ときどき3連の詰め）、2・4拍のリムとスナップ、ゴースト。"""
    s16 = b / 4
    for q in range(16):
        if trap and bi % 4 == 3 and q in (14, 15):
            for r in range(3):                                   # 3連で詰める
                gs.put(mix, ml.hat(False, 0.4), _hum(t0 + (14 + r * 2 / 3) * s16, 3), 0.1, 0.1)
            break
        vel = (0.5, 0.25, 0.38, 0.25)[q % 4] * _HR.uniform(0.85, 1.1)
        gs.put(mix, ml.hat(False, vel), _hum(t0 + q * s16, 4), 0.14, 0.1)
    for q in (1, 3):
        gs.put(mix, ml.clap(), _hum(t0 + q * b, 3), 0.12)
        s_ = sosfilt(butter(2, [700, 5000], "bandpass", fs=SR, output="sos"), ml.snare())
        gs.put(mix, s_, _hum(t0 + q * b, 3), 0.08)
    for gq in (7, 13):                                           # ゴーストノート
        s_ = sosfilt(butter(2, 3000, "lowpass", fs=SR, output="sos"), ml.snare())
        gs.put(mix, s_, _hum(t0 + gq * s16, 5), 0.025)


def _ep_rich(notes, dur, v=0.5):
    """エレピの和音（1音ずつ強さを揺らし、ほんの少しずらして弾く）。"""
    n = int((dur + 0.6) * SR)
    out = np.zeros(n)
    for k, m in enumerate(notes):
        s = bgm.rhodes(m, dur, v * _HR.uniform(0.8, 1.0))
        d = int(k * 0.006 * SR)
        out[d:d + len(s)] += s[:n - d]
    return out / len(notes)


def trap_808_long():
    """音程のある長い808（ドゥーン）が低音の旋律をなぞる。上はハイハットと手拍子だけ。"""
    bpm, nbar = 96, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 3) * SR)
    mix = np.zeros((n, 2))
    # 808 の線（C → A → F → G、ときどきオクターブ上へすべる）。(拍, MIDI)
    line = {0: [(0, 36), (1.75, 36), (2.5, 43)], 1: [(0, 33), (1.5, 45), (2.5, 40)],
            2: [(0, 29), (1.75, 29), (2.5, 41)], 3: [(0, 31), (1.5, 38), (2.75, 43), (3.5, 31)]}
    notes, times = [], []
    for bi in range(nbar):
        t0 = bi * bar
        _hat16(mix, t0, b, bi, g=0.14)
        for q in (1, 3):
            gs.put(mix, ml.clap(), t0 + q * b, 0.18)
        for st, m in line[bi % 4]:
            notes.append(m)
            times.append(t0 + st * b)
            gs.put(mix, ml.kick(0.18) * 0.6, t0 + st * b, 0.12)
    bass = ml.k808(notes, times, n, decay=1.3, drive=2.4, glide=0.09)
    bass = sosfilt(butter(2, 45, "highpass", fs=SR, output="sos"), bass)
    gs.put(mix, bass, 0, 0.16)
    return dry_finish(mix, nbar * bar, sub_cut=-3), "トラップ・長い808", \
        "96 BPM。音程のある長い808（ドゥーン）が C→A→F→G の低音をなぞり、ときどきオクターブ上へすべる。上はハイハットと手拍子だけ。旋律なし・残響なし。"


def modern_setsuna():
    """切なめを今っぽく: 9th・11thの和音、808の低音、強弱のついたハイハット。"""
    bpm, nbar = 88, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 3) * SR)
    mix = np.zeros((n, 2))
    # Fmaj9 → G13 → Em9 → Am11（ハ長調）
    prog = [(41, [57, 60, 64, 67]), (43, [53, 59, 64, 69]), (40, [55, 59, 62, 66]), (45, [55, 60, 62, 67])]
    notes, times = [], []
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for st, d in ((0, 1.2), (1.75, 0.5), (2.5, 0.9), (3.5, 0.4)):
            gs.put(mix, _ep_rich(ch, b * d, .55), _hum(t0 + st * b), 0.34, -0.1)
        if bi >= 4:
            _modern_drums(mix, t0, b, bi)
        for st in (0, 2.5) if bi % 2 == 0 else (0, 1.75, 2.75):
            notes.append(root - 12 + 12)
            times.append(t0 + st * b)
            gs.put(mix, ml.kick(0.18) * 0.5, t0 + st * b, 0.14)
    bass = ml.k808(notes, times, n, decay=0.7, drive=1.8, glide=0.05)
    bass = sosfilt(butter(2, 40, "highpass", fs=SR, output="sos"), bass)
    gs.put(mix, bass, 0, 0.1)
    mix = _tape(mix, 1.15)
    return dry_finish(mix, nbar * bar, sub_cut=-4), "切なめ・今っぽく", \
        "88 BPM・ハ長調。Fmaj9→G13→Em9→Am11 のエレピ（1音ずつ強さを揺らす）、808の低音、強弱のついた16分のハイハットと3連の詰め、ゴーストノート、軽いテープのひずみ。残響なし。"


def modern_jazz():
    """ジャズを今っぽく（ネオソウル寄り）: 跳ねる16分、リム、丸い低音、豊かな和音。"""
    bpm, nbar = 84, 16
    b = 60 / bpm
    bar = 4 * b
    s16 = b / 4
    sw = 0.17                                                    # 16分の跳ね（裏を遅らせる割合）
    n = int((nbar * bar + 3) * SR)
    mix = np.zeros((n, 2))
    # Dm9 → G13 → Cmaj9 → A7(♭13)（ハ長調）
    prog = [(38, [53, 57, 60, 64]), (43, [53, 59, 64, 69]), (36, [52, 55, 59, 62]), (33, [55, 61, 65, 67])]
    ev = []
    for bi in range(nbar):
        root, ch = prog[bi % 4]
        t0 = bi * bar
        for st, d in ((0, 1.4), (1.5 + sw / 2, 0.4), (2.75, 0.9)):
            gs.put(mix, _ep_rich(ch, b * d, .5), _hum(t0 + st * b), 0.36, -0.1)
        if bi % 4 == 3:                                          # 4小節ごとの短い合いの手（高い所で2音）
            for k, m in enumerate((ch[-1] + 12, ch[-2] + 12)):
                gs.put(mix, bgm.rhodes(m, b * 0.3, .35), _hum(t0 + (3 + k * 0.5) * b), 0.12, 0.25)
        for q in range(16):
            tq = t0 + (q + (sw if q % 2 else 0)) * s16
            vel = (0.45, 0.22, 0.32, 0.22)[q % 4] * _HR.uniform(0.85, 1.1)
            gs.put(mix, ml.hat(False, vel), _hum(tq, 4), 0.12, 0.1)
        for q in (1, 3):
            rim = sosfilt(butter(2, [900, 6000], "bandpass", fs=SR, output="sos"), ml.snare()[:int(0.08 * SR)])
            gs.put(mix, rim, _hum(t0 + q * b, 3), 0.16)
        for st in (0, 1.75 + sw / 4, 2.5):
            gs.put(mix, ml.kick(0.2) * 0.55, _hum(t0 + st * b, 3), 0.2)
        for st, d, off in ((0, 1.3, 0), (1.75, 0.5, 0), (2.5, 0.6, 7), (3.25, 0.5, 12)):
            ev.append((int((t0 + st * b) * SR), int(d * b * SR), root + off, 0.55, 0, 0))
    bass = sosfilt(butter(2, 600, "lowpass", fs=SR, output="sos"), Bass(SR).render(ev, n))
    gs.put(mix, bass, 0, 0.3)
    mix = _tape(mix, 1.15)
    return dry_finish(mix, nbar * bar, sub_cut=-5), "ジャズ・今っぽく", \
        "84 BPM・ハ長調。Dm9→G13→Cmaj9→A7(♭13) のエレピ、跳ねる16分のハイハット（強弱つき）、リム、丸いベース、4小節ごとの短い合いの手。ネオソウル寄り。残響なし。"


# ------------------------------------------------------------------ 長い808の発展形（10/7夜3）
# 本人「トラップ長い808いい。もっと凝ったり効果をつけたり。方向をいくつか。別でBPMの速いのも」。
# どれも残響なし。効果は「曲の区切り」にだけ置き、声の邪魔をしない。

def _riser(sec, seed=0):
    """白い雑音が上がっていく（区切りの前の「シューッ」）。"""
    n = int(sec * SR)
    t = np.arange(n) / SR
    x = bgm.tvf(np.random.default_rng(seed).standard_normal(n), 400 * 30 ** (t / sec), q=2.0, kind="bp")
    return x * (t / sec) ** 2 * 0.5


def _tape_stop(seg):
    """テープが止まるように、音程と速さが下がっていく（区切りの最後に）。"""
    n = len(seg)
    speed = np.linspace(1.0, 0.0, n) ** 0.7
    pos = np.cumsum(speed)
    pos = np.clip(pos, 0, n - 1)
    out = np.stack([np.interp(pos, np.arange(n), seg[:, c]) for c in range(2)], axis=1)
    return out * np.linspace(1, 0.2, n)[:, None]


def _stutter(mix, t_from, slice_sec, times=4):
    """区切りの直前を、短く刻んで繰り返す（ダダダダ）。"""
    a = int(t_from * SR)
    L = int(slice_sec * SR)
    piece = mix[a:a + L].copy()
    for k in range(times):
        s = a + k * L
        mix[s:s + L] = piece[:len(mix[s:s + L])] * (0.9 ** k)


def _crush(x, bits=8, down=3):
    """ビットを落とし、サンプルを間引く（ローファイ）。"""
    q = 2 ** (bits - 1)
    y = np.round(x * q) / q
    y = np.repeat(y[::down], down, axis=0)[:len(x)]
    return y


def _trap_core(bpm, nbar, line, hat_mode="16", snare_beats=(1, 3), kick_g=0.12, b808=0.16,
               decay=1.3, glide=0.09, drive=2.4, hat_g=0.14):
    """長い808＋ハイハット＋手拍子の土台。line は小節（4つ周期）ごとの [(拍, MIDI)]。"""
    b = 60 / bpm
    bar = 4 * b
    s16 = b / 4
    n = int((nbar * bar + 3) * SR)
    mix = np.zeros((n, 2))
    notes, times = [], []
    for bi in range(nbar):
        t0 = bi * bar
        if hat_mode == "16":
            _hat16(mix, t0, b, bi, g=hat_g)
        elif hat_mode == "trip":                                 # ドリル: 3連が混ざる
            for beat in range(4):
                if beat % 2 == 1:
                    for r in range(3):
                        gs.put(mix, ml.hat(False, 0.45), t0 + (beat + r / 3) * b, hat_g, 0.1)
                else:
                    for r in range(4):
                        gs.put(mix, ml.hat(False, 0.5 if r % 2 == 0 else 0.3), t0 + (beat + r / 4) * b, hat_g, 0.1)
        elif hat_mode == "8":                                    # 速い曲は8分で軽く
            for q in range(8):
                gs.put(mix, ml.hat(False, 0.5 if q % 2 == 0 else 0.32), t0 + q * b / 2, hat_g, 0.1)
            if bi % 2 == 1:
                for r in range(4):
                    gs.put(mix, ml.hat(False, 0.4), t0 + (3.5 + r / 8) * b, hat_g * 0.8, 0.1)
        for q in snare_beats:
            gs.put(mix, ml.clap(), t0 + q * b, 0.18)
        for st, m in line[bi % len(line)]:
            notes.append(m)
            times.append(t0 + st * b)
            gs.put(mix, ml.kick(0.18) * 0.6, t0 + st * b, kick_g)
    bass = ml.k808(notes, times, n, decay=decay, drive=drive, glide=glide)
    bass = sosfilt(butter(2, 45, "highpass", fs=SR, output="sos"), bass)
    gs.put(mix, bass, 0, b808)
    return mix, n, b, bar, s16


LINE_CAF = {0: [(0, 36), (1.75, 36), (2.5, 43)], 1: [(0, 33), (1.5, 45), (2.5, 40)],
            2: [(0, 29), (1.75, 29), (2.5, 41)], 3: [(0, 31), (1.5, 38), (2.75, 43), (3.5, 31)]}


def trap808_fx():
    """王道トラップの演出: 8小節目で刻み、9小節目の前にシューッ、最後はテープが止まる。"""
    nbar = 16
    mix, n, b, bar, s16 = _trap_core(96, nbar, LINE_CAF)
    _stutter(mix, 7 * bar + 3 * b, s16, times=4)                 # 8小節目の最後の拍を刻む
    gs.put(mix, _riser(2 * bar - 0.05, 1), 6 * bar, 0.10)        # 9小節目の前にシューッ
    a, z = int((15 * bar + 2 * b) * SR), int(16 * bar * SR)
    mix[a:z] = _tape_stop(mix[a:z])                              # 最後の2拍でテープが止まる
    return dry_finish(mix, nbar * bar, sub_cut=-3), "808・演出つき", \
        "96 BPM。長い808とハイハットの土台に、8小節目の最後を「ダダダダ」と刻み、9小節目の前に雑音がシューッと上がり、最後の2拍でテープが止まるように音程が下がる。旋律なし・残響なし。"


def trap808_filter():
    """フィルター: 曲全体がこもった所から8小節かけて開き、また閉じる。ときどき小さなはじく音。"""
    nbar = 16
    mix, n, b, bar, s16 = _trap_core(96, nbar, LINE_CAF)
    for bi in range(nbar):
        if bi % 4 == 2:
            for k, m in enumerate((72, 76, 79, 76)):
                gs.put(mix, bgm.pluck(m, .45, bi * 4 + k), (bi * bar) + (2 + k * 0.5) * b, 0.06, 0.3 - 0.2 * k)
    t = np.arange(n) / SR
    L = nbar * bar
    ph = (t % L) / L
    fc = 600 * (12000 / 600) ** np.where(ph < 0.5, ph * 2, (1 - ph) * 2)   # 600Hz → 12kHz → 600Hz
    out = np.stack([bgm.tvf(mix[:, c], fc, q=0.9) for c in range(2)], axis=1)
    return dry_finish(out, L, sub_cut=-3), "808・フィルター", \
        "96 BPM。長い808とハイハットの土台全体に、こもった音から8小節かけて開いてまた閉じるフィルター。3小節目ごとに小さなはじく音が4つ。残響なし。"


def trap808_lofi():
    """ローファイ: 少しざらついた音（ビットを落とす）、レコードの音、ゆっくり。"""
    nbar = 16
    line = {0: [(0, 38), (2.5, 45)], 1: [(0, 35), (2.5, 42)], 2: [(0, 31), (1.75, 31), (2.5, 38)], 3: [(0, 33), (2.5, 40), (3.5, 33)]}
    mix, n, b, bar, s16 = _trap_core(84, nbar, line, b808=0.13, decay=1.5)
    for bi in range(nbar):
        if bi % 2 == 0:
            ch = ([62, 66, 69, 73], [59, 62, 66, 69], [55, 59, 62, 66], [57, 61, 64, 67])[(bi // 2) % 4]
            gs.put(mix, _ep_rich(ch, b * 0.5, .5), bi * bar + 0.5 * b, 0.16, -0.1)
    mix = _crush(mix, bits=9, down=2)
    cr = np.zeros(n)
    idx = rng.integers(0, n, int(n / SR * 5))
    cr[idx] = rng.standard_normal(len(idx)) * 0.5
    mix += gs.stereo(sosfilt(butter(2, [1500, 7000], "bandpass", fs=SR, output="sos"), cr), 0) * 0.06
    mix = sosfilt(butter(2, 9000, "lowpass", fs=SR, output="sos"), mix, axis=0)
    return dry_finish(mix, nbar * bar, sub_cut=-3), "808・ローファイ", \
        "84 BPM・ニ長調。長い808に、ざらついた音（ビットを落とす）とレコードのぱちぱち。2小節に1度だけエレピの和音が短く入る。残響なし。"


def trap808_drill():
    """ドリル: 3連の混ざるハイハット、よくすべる808、少し遅れた手拍子。速め。"""
    nbar = 16
    line = {0: [(0, 36), (1.5, 43), (2.75, 48)], 1: [(0, 33), (1.5, 40), (2.5, 45), (3.25, 43)],
            2: [(0, 29), (1.5, 36), (2.75, 41)], 3: [(0, 31), (1.5, 38), (2.5, 43), (3.5, 38)]}
    mix, n, b, bar, s16 = _trap_core(142, nbar, line, hat_mode="trip", snare_beats=(1.5, 3.5),
                                     decay=0.9, glide=0.12, b808=0.15)
    gs.put(mix, _riser(bar - 0.05, 3), 7 * bar, 0.08)
    return dry_finish(mix, nbar * bar, sub_cut=-3), "808・ドリル（速い）", \
        "142 BPM。3連の混ざるハイハット、よくすべる808、少し遅れて入る手拍子。8小節目の終わりに雑音が上がる。旋律なし・残響なし。"


def trap808_hyper():
    """速い: 150 BPM、8分のハイハットと細かい詰め、跳ねる808。"""
    nbar = 16
    line = {0: [(0, 36), (0.75, 36), (2, 43), (3, 36)], 1: [(0, 33), (1, 45), (2, 40), (3.5, 33)],
            2: [(0, 29), (0.75, 29), (2, 41), (3, 29)], 3: [(0, 31), (1, 38), (2, 43), (3, 38), (3.5, 31)]}
    mix, n, b, bar, s16 = _trap_core(150, nbar, line, hat_mode="8", decay=0.5, glide=0.05, b808=0.15, kick_g=0.14)
    a, z = int((15 * bar + 3 * b) * SR), int(16 * bar * SR)
    mix[a:z] = _tape_stop(mix[a:z])
    return dry_finish(mix, nbar * bar, sub_cut=-3), "808・ハイパー（速い）", \
        "150 BPM。8分のハイハットと2小節ごとの細かい詰め、短く跳ねる808、2・4拍の手拍子。最後の1拍でテープが止まる。旋律なし・残響なし。"


def club808():
    """クラブ風（速い）: 140 BPM、はずむキックの並び（ドッ・ドッ・ドドド）と808。"""
    bpm, nbar = 140, 16
    b = 60 / bpm
    bar = 4 * b
    n = int((nbar * bar + 3) * SR)
    mix = np.zeros((n, 2))
    notes, times = [], []
    roots = [36, 33, 29, 31]
    for bi in range(nbar):
        t0 = bi * bar
        for st in (0, 1, 2, 2.75, 3.5):                          # はずむキック
            gs.put(mix, ml.kick(0.2) * 0.6, t0 + st * b, 0.2)
        for q in (1, 3):
            gs.put(mix, ml.clap(), t0 + q * b, 0.16)
        for q in range(8):
            gs.put(mix, ml.hat(False, 0.45 if q % 2 else 0.3), t0 + q * b / 2, 0.11, 0.1)
        for st, off in ((0, 0), (2, 7), (2.75, 12)):
            notes.append(roots[bi % 4] + off)
            times.append(t0 + st * b)
    bass = ml.k808(notes, times, n, decay=0.45, drive=2.0, glide=0.06)
    bass = sosfilt(butter(2, 45, "highpass", fs=SR, output="sos"), bass)
    gs.put(mix, bass, 0, 0.13)
    return dry_finish(mix, nbar * bar, sub_cut=-3), "808・クラブ（速い）", \
        "140 BPM。「ドッ・ドッ・ドドド」とはずむキック、2・4拍の手拍子、8分のハイハット、短い808。旋律なし・残響なし。"


ALL = ["trap808_fx", "trap808_filter", "trap808_lofi", "trap808_drill", "trap808_hyper", "club808", "trap_808_long", "modern_setsuna", "modern_jazz", "backing_pop", "backing_jpop", "backing_jazz", "backing_vamp", "backing_sixties", "backing_bright", "trap_hats", "trap_808", "dry_electro", "dry_backing", "chillhouse", "jazzhop", "funklight", "futurepop", "everyday", "nighter", "scoreboard", "dugout", "comeback"]


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
