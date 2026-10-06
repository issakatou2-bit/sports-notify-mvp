#!/usr/bin/env python3
"""読み上げに BGM と効果音を重ねる（numpy だけ。Actions でも動く）。

なぜ要るのか:
  10/6、本人「BGMもいい感じだけど主張しすぎない感じにしたい」「効果音は画面の動きに連動」。
  - BGM は声より十分小さく（既定 -20dB）、声が出ている間はさらに下げる（ダッキング）。
  - 効果音は画面の動きの時刻（cues）に置く。声よりは小さく、BGM よりは大きく。
  - 最後に全体の山が 0.95 を超えないように丸める。

使い方:
  mixed = sound_mix.mix(voice, bgm=bgm_loop, cues=[(秒, "swish", "a", 音量), ...])
"""
import numpy as np

import sfx

SR = sfx.SR


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) + 1e-9


def loop_to(x: np.ndarray, n: int) -> np.ndarray:
    """ループ素材を n サンプルまで繰り返す。"""
    if len(x) >= n:
        return x[:n].copy()
    reps = int(np.ceil(n / len(x)))
    return np.tile(x, reps)[:n]


def voice_envelope(voice: np.ndarray, win: float = 0.12, attack: float = 0.05, release: float = 0.45) -> np.ndarray:
    """声の有無（0〜1）。立ち上がりは速く、戻りはゆっくり（BGMが急に戻らないように）。"""
    hop = int(0.01 * SR)                                   # 10ms ごとに見る
    frames = len(voice) // hop + 1
    pad = np.zeros(frames * hop)
    pad[:len(voice)] = voice
    power = np.sqrt(np.mean(np.square(pad.reshape(frames, hop)), axis=1))
    w = max(1, int(win / 0.01))
    power = np.convolve(power, np.ones(w) / w, mode="same")
    on = (power > 0.25 * _rms(voice)).astype(float)
    up, down = 0.01 / attack, 0.01 / release
    env = np.zeros(frames)
    level = 0.0
    for i, v in enumerate(on):
        level = min(v, level + up) if v > level else max(v, level - down)
        env[i] = level
    return np.interp(np.arange(len(voice)), np.arange(frames) * hop, env)


def duck_gain(voice: np.ndarray, duck_db: float = -6.0) -> np.ndarray:
    env = voice_envelope(voice)
    return 10 ** (duck_db * env / 20)


def mix(voice: np.ndarray, bgm: np.ndarray = None, cues=(), bgm_db: float = -20.0, duck_db: float = -6.0,
        sfx_db: float = -9.0, fade: float = 1.2) -> np.ndarray:
    """voice（モノラル）に BGM（モノラル/ステレオ）と効果音を重ね、ステレオで返す。

    bgm_db・sfx_db は声の平均の大きさからの差。cues は (秒, 種類, 案, 追加の音量dB)。
    """
    n = len(voice)
    ref = _rms(voice)
    out = np.stack([voice, voice], axis=1)
    if bgm is not None:
        b = bgm if bgm.ndim == 2 else np.stack([bgm, bgm], axis=1)
        b = np.stack([loop_to(b[:, 0], n), loop_to(b[:, 1], n)], axis=1)
        b = b / _rms(b) * ref * 10 ** (bgm_db / 20)
        g = duck_gain(voice, duck_db)
        f = np.ones(n)
        k = min(n // 2, int(fade * SR))
        f[-k:] = np.linspace(1, 0, k)
        out += b * (g * f)[:, None]
    if cues:
        t = np.zeros(n)
        for at, kind, variant, db in cues:
            s = sfx.make(kind, variant)
            sfx.place(t, s / (np.max(np.abs(s)) + 1e-9), at, 10 ** (db / 20))
        out += np.stack([t, t], axis=1) * ref * 10 ** (sfx_db / 20) * 4
    pk = np.max(np.abs(out))
    if pk > 0.95:
        out = out / pk * 0.95
    return out


def _read_wav(path):
    import wave
    with wave.open(str(path), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype={1: np.uint8, 2: np.int16, 4: np.int32}[sw]).astype(np.float64)
    x = (x - 128) / 128 if sw == 1 else x / float(2 ** (8 * sw - 1))
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        x = np.interp(np.arange(int(len(x) * SR / sr)) * sr / SR, np.arange(len(x)), x)
    return x


def _decode(path):
    """mp3 などを ffmpeg で 44100Hz・ステレオに。"""
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "2", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float64).reshape(-1, 2) / 32768


def mix_file(narration_wav, out_wav, bgm_path=None, cues=(), **kw):
    """読み上げの wav に BGM と効果音を重ねて out_wav（44100Hz・ステレオ）に書く。"""
    import wave
    voice = _read_wav(narration_wav)
    bgm = _decode(bgm_path) if bgm_path else None
    y = mix(voice, bgm=bgm, cues=cues, **kw)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return out_wav
