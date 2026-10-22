"""導入の段取りだけを比べる。割付は公開日のJST、受領記録は実動画に結ぶ。"""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST = 'hook-20261023'
KINDS = ('morning_press', 'asset:season_player')
JST = timezone(timedelta(hours=9))


def publication_day(value=None):
    if not value or re.fullmatch(r'\d{2}:\d{2}', value):
        return datetime.now(JST).date().isoformat()
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (parsed.astimezone(JST) if parsed.tzinfo else parsed).date().isoformat()


def assignment(kind, day, enabled=None):
    on = os.getenv('COLLESPO_HOOK_AB') == 'on' if enabled is None else enabled
    eligible = kind in KINDS and day >= '2026-10-23'
    # 種類ごとの日付ブロック。同日の同種は同条件。日ごと交代の司会と交絡させない。
    phase = KINDS.index(kind) if kind in KINDS else 0
    variant = 'B' if on and eligible and (date.fromisoformat(day).toordinal()+phase) % 4 in (1, 2) else 'A'
    return dict(ab_test=TEST, ab_variant=variant, ab_enabled=bool(on and eligible),
                ab_kind=kind, ab_day=day, ab_rule='jst-day-abba-v1')


def _subjects(text):
    import notability_engine as ne
    words = [p['name_jp'] for p in ne.JP_PLAYERS_MLB]
    words += list(ne.MLB_TEAM_NAME_JP.values())
    return {w for w in words if w in text}


def _press(segments):
    """引用を改変せず、同じ主役・論点の引用を直後へ。全札を保持。"""
    intro = segments[0]
    rows = (intro.get('meta') or {}).get('quote_rows') or []
    lead = next((r['said'] for r in rows if not r.get('fact')), '')
    if not lead:
        return _press_legacy(segments)
    subjects = _subjects(lead)
    # 選手名だけ一致する別ニュース（例：敗退と競売）を混ぜない。
    themes = [w for w in ('敗退', '進出', '優勝', '記録', '最高', '最多', '移籍', '感謝', '負傷', '復帰') if w in lead]
    target = next((i for i, seg in enumerate(segments[1:-1], 1)
                   if any(subjects & _subjects(r.get('said', ''))
                          and any(w in r.get('said', '') for w in themes)
                          for r in (seg.get('meta') or {}).get('quote_rows', [])
                          if not r.get('fact'))), None)
    if target is None:
        return '同じ主役・論点の説明がないためAを維持'
    # 本文の引用も出典もそのまま。日付は画面/公開記録に残す。
    intro['text'] = lead.rstrip('。') + '。'
    segments.insert(1, segments.pop(target))
    return None


def _press_legacy(segments):
    """従来の札でも同じ描画へ、関連する見出しを先に渡す。"""
    intro = segments[0]
    sources = (intro.get('meta') or {}).get('source_headlines') or []
    if not sources:
        return '主見出しがないためAを維持'
    lead = sources[0].get('jp') or sources[0].get('title', '')
    subjects = _subjects(lead)
    themes = [w for w in ('敗退', '進出', '優勝', '記録', '最高', '最多', '移籍', '感謝', '負傷', '復帰') if w in lead]
    for i, seg in enumerate(segments[1:-1], 1):
        meta = seg.get('meta') or {}
        rows = meta.get('source_headlines') or []
        if seg['kind'] != 'headlines' or len(rows) != len(meta.get('picked') or []):
            continue
        match = next((j for j, r in enumerate(rows)
                      if subjects & _subjects(r.get('jp') or r.get('title', ''))
                      and any(w in (r.get('jp') or r.get('title', '')) for w in themes)), None)
        if match is None:
            continue
        order = [match]+[j for j in range(len(rows)) if j != match]
        # 引用を一字も変更しない。全札・出典・索引を対応させて順番だけ変える。
        meta['source_headlines'] = [rows[j] for j in order]
        meta['picked'] = [meta['picked'][j] for j in order]
        seg['text'] = ''.join(f"{r.get('source', '')}。{r.get('jp') or r.get('title', '')}。" for r in meta['source_headlines'])
        intro['text'] = lead.rstrip('。')+'。'
        segments.insert(1, segments.pop(i))
        return None
    return '同じ主役・論点の説明がないためAを維持'


def _season(segments, spec):
    name, hook = spec.get('jp'), spec.get('hook')
    items = spec.get('items') or []
    meaning = next(((h, b) for h, b in items if h == '自己最多'), None)
    meaning = meaning or next(((h, b) for h, b in items if h.startswith('昨季')), None)
    if not name or not hook or not meaning:
        return '同じ選手の自己最多・昨季比較がないためAを維持'
    head, body = meaning
    # 数字の意味は既存の公式材料からのみ。順位・日付の総覧へ戻らない。
    # 最初は比較の1指標だけ。全指標は元の札・本文で読み、導入を長くしない。
    first = re.split(r'[　・]', body)[0].strip()
    # 「勝利 7から1」の半角空白はそのまま保つ。
    meaning_speech = (f'MLBでの自己最多、{first}。' if head == '自己最多'
                      else f'昨季から、{first}。')
    segments[0]['text'] = f'{name}。{hook}。{meaning_speech}'
    return None


def prepare(narration, kind, day=None, spec=None, preview=None):
    if kind not in KINDS or 'hook_ab' in narration:
        return narration  # 録音済み原稿を再割付しない。
    result = copy.deepcopy(narration)
    plan = assignment(kind, day or publication_day())
    if preview is not None:
        if preview not in ('A', 'B'):
            raise ValueError('見本の条件はA/Bです')
        plan.update(ab_variant=preview, ab_enabled=False, ab_preview=True)
    if plan['ab_enabled'] or preview is not None:
        segments = copy.deepcopy(result['segments'])
        reason = _press(segments) if kind == 'morning_press' else _season(segments, spec or {})
        # Bだけ材料の厚い日に絞る選択バイアスを避け、Aにも同じ適格性を記録。
        plan['ab_content_eligible'] = reason is None
        if reason:
            plan['ab_content_reason'] = reason
        if plan['ab_variant'] == 'B':
            if reason:
                plan.update(ab_assigned_variant='B', ab_variant='A', ab_fallback_reason=reason)
            else:
                result['segments'] = segments
    result['hook_ab'] = plan
    return result


def receipt_path(video):
    return Path(str(video)+'.hook-ab.json')


class SceneRecorder:
    """既存描画が返す札/ページの識別子を観測するだけ。描画や動きは変えない。"""
    def __init__(self):
        self.previous = object()
        self.starts = []

    def observe(self, image, frame, fps, screen):
        info = image.info
        card = info.get('asset_v4') or info.get('v4_quote') or {}
        key = (screen, tuple(str(card.get(k, '')) for k in
                            ('kind', 'head', 'body', 'name', 'row', 'item', 'page', 'said')))
        if key != self.previous:
            self.starts.append(round(frame/fps, 6))
            self.previous = key


def bind_video(video, narration, segments, durations, fps, scene_starts=None):
    """場面は描画フレーム、台詞は音声結合の区間開始。文境界の推測はしない。"""
    plan = narration.get('hook_ab')
    if not plan:
        return
    if len(segments) != len(narration['segments']) or len(segments) != len(durations):
        raise ValueError('A/Bの原稿・音声・場面の数が一致しません')
    frames, audio_elapsed = 0, 0.0
    scenes, lines = [], []
    previous = object()
    for i, (spoken, text, dur) in enumerate(zip(segments, narration['segments'], durations)):
        if spoken.get('text') is not None and (spoken['text'], spoken.get('kind')) != (text['text'], text['kind']):
            raise ValueError('A/Bの音声が録音に使った原稿と一致しません')
        start = frames / fps
        meta = text.get('meta') or {}
        screen = meta.get('screen', i)
        if i == 0 or screen != previous:
            scenes.append(round(start, 6))
        previous = screen
        lines.append(dict(index=i, start=round(audio_elapsed, 6), scene_start=round(start, 6), text=text['text'], speaker=spoken.get('speaker', text.get('speaker')),
                          audio_available=bool(spoken.get('file'))))
        frames += int(dur*fps)
        spoken_seconds = float(spoken.get('duration') or 0)
        audio_elapsed += (spoken_seconds if spoken.get('file') and dur-spoken_seconds <= .02 else dur)
    scenes = sorted(set(scenes + (scene_starts or [])))
    data = dict(plan, scene_starts=scenes, dialogue_starts=lines, duration_seconds=frames/fps,
                timing_basis='scenes:rendered-frames/dialogue:audio-segment-playback',
                video_sha256=hashlib.sha256(Path(video).read_bytes()).hexdigest())
    receipt_path(video).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def publication(video, publish_at=None):
    p = receipt_path(video)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding='utf-8'))
    if data['video_sha256'] != hashlib.sha256(Path(video).read_bytes()).hexdigest():
        raise ValueError('A/B記録と動画が一致しません。動画を作り直してください')
    if data.get('ab_preview'):
        raise ValueError('A/B見本動画は公開に使えません')
    if data.get('ab_enabled') and publication_day(publish_at) != data['ab_day']:
        raise ValueError('A/B割付と公開日が異なります。原稿から作り直してください')
    return data
