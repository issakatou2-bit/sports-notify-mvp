"""既存の声と最終VOICEVOX queryから閉/小/大。APSCの方式を参照。"""
import json
import math
import os
from pathlib import Path
import wave

import numpy as np

FPS = 24
TRACK = []


def enabled():
    return os.environ.get('COLLESPO_LIPSYNC') == 'voice'


def smooth(raw, hold=2):
    out, state, age = [], 0, hold
    for target in raw:
        if target != state and age >= hold:
            state += 1 if target > state else -1
            age = 0
        out.append(state)
        age += 1
    return out


def envelope(x, sr, fps=FPS):
    rms = np.array([np.sqrt(np.mean(x[int(i*sr/fps):int((i+1)*sr/fps)]**2))
                    for i in range(math.ceil(len(x)*fps/sr))])
    if not len(rms) or rms.max() < .002:
        return [0] * len(rms)
    ref = max(.006, float(np.percentile(rms[rms > .002], 85)))
    return np.where(rms < max(.002, ref*.12), 0, np.where(rms < ref*.60, 1, 2)).tolist()


def query_frames(query, duration, fps=FPS):
    speed = float(query.get('speedScale', 1))
    if speed <= 0 or duration <= 0:
        raise ValueError('queryの速さ/音声長が不正')
    segments = [(query.get('prePhonemeLength', 0)/speed, 0)]
    for phrase in query['accent_phrases']:
        for mora in phrase['moras']:
            vowel = mora['vowel']
            state = 2 if vowel in ('a', 'o') else 1 if vowel in ('i', 'e', 'u') else 0
            segments.append(((mora.get('consonant_length') or 0)/speed, state))
            segments.append((mora['vowel_length']/speed, state))
        if phrase.get('pause_mora'):
            length = query.get('pauseLength')
            if length is None:
                length = phrase['pause_mora']['vowel_length']/speed
            segments.append((length*query.get('pauseLengthScale', 1), 0))
    segments.append((query.get('postPhonemeLength', 0)/speed, 0))
    ends = np.cumsum([s[0] for s in segments])
    if ends[-1] <= 0:
        raise ValueError('queryの長さが0')
    return [segments[min(len(segments)-1, int(np.searchsorted(ends, (i+.5)/fps*ends[-1]/duration)))][1]
            for i in range(math.ceil(duration*fps))]


def audio_frames(path, fps=FPS):
    with wave.open(str(path), 'rb') as w:
        sr, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width not in (1, 2, 4):
        raise ValueError('対応していないWAV形式')
    x = np.frombuffer(raw, dtype={1:np.uint8, 2:np.int16, 4:np.int32}[width]).astype(float)
    x = (x-128)/128 if width == 1 else x/2**(8*width-1)
    x = x.reshape(-1, channels).mean(axis=1)
    levels = envelope(x, sr, fps)
    sidecar = Path(path).with_suffix('.lipsync.json')
    source = 'audio-envelope'
    if sidecar.exists():
        data = json.loads(sidecar.read_text(encoding='utf-8'))
        # 古い/別のWAVのqueryを取り違えない。
        import hashlib
        if data['wav_sha256'] != hashlib.sha256(Path(path).read_bytes()).hexdigest():
            raise ValueError('口パクqueryとWAVの指紋が不一致')
        phonemes = query_frames(data['query'], len(x)/sr, fps)
        levels = [v if levels[i] else 0 for i,v in enumerate(phonemes)]
        source = 'voicevox-query'
    return smooth(levels), source


def prepare(segs, durations, out_dir, fps=FPS):
    TRACK.clear()
    if not enabled():
        return
    start = 0.
    for seg, duration in zip(segs, durations):
        n = int(duration*fps)
        path = seg.get('file')
        levels, source = audio_frames(path, fps) if path else ([], 'silence')
        TRACK.append(dict(start=start, end=start+n/fps, speaker=seg.get('speaker', 2),
                          frames=(levels+[0]*n)[:n], source=source, file=path))
        start += n/fps
    Path(out_dir, 'lipsync-confirmation.json').write_text(
        json.dumps(dict(fps=fps,segments=TRACK), ensure_ascii=False, indent=2), encoding='utf-8')


def at(clock, speaker, fps=FPS):
    for seg in TRACK:
        if seg['start'] <= clock < seg['end'] and seg['speaker'] == speaker:
            i = int((clock-seg['start'])*fps+1e-6)
            return seg['frames'][i] if i < len(seg['frames']) else 0
    return 0
