"""ショート専用の締め・切替音・重複字幕。長編や配信からは呼ばない。"""
import copy
import functools
import json
import math
import unicodedata
from pathlib import Path

OUTRO_TEXT = '毎日更新しています。'
OUTRO_LINE = '毎日 MLB・欧州サッカー'
OUTRO_SECONDS = 2.0
OUTRO_MAX_SECONDS = 2.5


def prepare(document):
    """本編を保ち、番組宣伝だけを共通の短い締めにする。"""
    result = copy.deepcopy(document)
    if 'segments' not in result:
        return result
    segments = [s for s in result.get('segments', []) if s.get('kind') != 'next_program']
    if segments and not any(s.get('kind') == 'outro' for s in segments):
        segments.append(dict(kind='outro', text=OUTRO_TEXT, speaker=2, meta={}))
    for segment in segments:
        if segment.get('kind') == 'outro':
            segment.update(text=OUTRO_TEXT, min_duration=OUTRO_SECONDS)
            segment['speaker'] = 2
            segment.pop('caption_en', None)
            if 'who' in segment.get('meta', {}):
                segment['meta']['who'] = '四国めたん'
            segment.setdefault('meta', {})['short_outro'] = True
    result['segments'] = segments
    return result


def narration(builder):
    @functools.wraps(builder)
    def wrapped(*args, **kwargs):
        document = builder(*args, **kwargs)
        return prepare(document) if document is not None else None
    return wrapped


def duration(segment, normal):
    if segment.get('kind') != 'outro':
        return normal
    speech = float(segment.get('duration') or 0)
    if not math.isfinite(speech) or speech < 0:
        raise ValueError('ショートの締めの実音声の長さが不正です')
    seconds = max(OUTRO_SECONDS, min(OUTRO_MAX_SECONDS, speech + .12))
    if speech > OUTRO_MAX_SECONDS:
        raise ValueError(f'ショートの締めが2.5秒を超えます: {speech:.3f}秒。短い締めの声を作り直してください')
    return seconds


def transition_cues(segments, durations):
    """同じ札での話者交代は鳴らさず、札が変わる瞬間だけ鳴らす。"""
    cues, clock, previous = [], 0.0, None
    for segment, seconds in zip(segments, durations):
        meta = segment.get('meta') or {}
        screen = meta.get('screen')
        identity = ('screen', screen) if screen is not None else (
            segment.get('kind'), json.dumps({k: v for k, v in meta.items()
                if k not in ('who', 'duo', 'answer_text', 'duo_ask', 'short_outro')},
                ensure_ascii=False, sort_keys=True, default=str))
        if previous is not None and identity != previous:
            cues.append((clock, 'transition', 'b', -12))
        previous = identity
        clock += seconds
    return cues


def add_audio(voice, segments, durations, out, bgm=None, cues=None):
    import sound_mix
    return sound_mix.mix_short_file(voice, Path(out) / 'narration_mixed.wav',
        bgm_path=bgm or sound_mix.bgm_path(),
        cues=transition_cues(segments, durations) if cues is None else cues)


def normalized(text):
    value = unicodedata.normalize('NFKC', str(text))
    return ''.join(c.casefold() for i, c in enumerate(value)
        if unicodedata.category(c)[0] in ('L', 'N')
        or (c in '.+-:/%' and i > 0 and value[i-1].isdigit()
            and (c == '%' or i+1 < len(value) and value[i+1].isdigit())))


def duplicate_caption(image, line):
    """描いた本文と同じ文だけ抑える。独自の補足・相槌は残す。"""
    wanted = normalized(line)
    if len(wanted) < 4:
        return False
    blocks = image.info.get('short_visible_texts', [])
    # 本文の行折り返しを連結する。見出し・出典・字幕の文字列は含めない。
    blocks = list(blocks) + [''.join(str(e.get('text', '')) for e in image.info.get('v3_layout', [])
        if e.get('role') in ('text', 'national_fact') and e.get('box', [0, 0])[1] >= 236
        and e.get('box', [0, 0])[1] < 1150)]
    matched = any(wanted in normalized(block) for block in blocks)
    if matched:
        image.info['short_caption_suppressed'] = dict(reason='duplicate', text=str(line))
    else:
        image.info.pop('short_caption_suppressed', None)
    return matched
