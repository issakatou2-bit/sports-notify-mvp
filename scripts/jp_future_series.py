"""保存済み対象名と公式取引だけの番号つき連載。公開成功時だけ番号を確定。"""
import copy
import json
from pathlib import Path

TITLE = '日本人選手の来季'
DESCRIPTION = '連載「日本人選手の来季」では、MLB公式に確定した移籍・契約などの動きを追います。'


def targets(root=Path('data')):
    kana = json.loads((root/'player_kana.json').read_text(encoding='utf-8'))['names']
    season = json.loads((root/'season_topics.json').read_text(encoding='utf-8'))['topics']
    candidates = json.loads((root/'offseason_players.json').read_text(encoding='utf-8'))['players']
    # 日本人個人の保存済み成績札で対象を確定する。日本語名だけで国籍を推測しない。
    roster = json.loads((root/'roster_snapshot.json').read_text(encoding='utf-8'))['players']
    result = {roster[str(r['player_id'])]['name']: r['jp'] for r in season
              if r.get('jp') and str(r.get('player_id')) in roster}
    for row in candidates:
        if not kana.get(row['name_en']):
            raise ValueError('連載対象の名前がplayer_kanaにありません')
        result[row['name_en']] = kana[row['name_en']]
    return result, kana


def number(state):
    return 1 + max((r.get('series_number', 0) for r in state.get('topics', {}).values()), default=0)


def topic(rows, day, season, state=None, episode=None):
    import offseason_news as news
    if not rows:
        return None
    jp, kana = targets()
    seen = set((state or {}).get('events', []))
    pending = []
    for row in rows:
        raw = row.get('raw', {})
        en = (raw.get('person') or {}).get('fullName') or (raw.get('person') or {}).get('name')
        if en not in jp or row['event_id'] in seen:
            continue
        if not kana.get(en):
            raise ValueError('連載の名前がplayer_kanaにありません')
        if row.get('name') != kana[en]:
            raise ValueError('連載の名前が辞書と不一致')
        pending.append(copy.deepcopy(row))
    spec = news.topic('transactions', pending, day, season)
    if not spec:
        return None
    n = episode or number(state or {})
    names = list(dict.fromkeys(r['name'] for r in spec['offseason']['events']))
    actions = list(dict.fromkeys(r['head'].split('｜')[-1] for r in spec['offseason']['events']))
    heading = f'{TITLE} 第{n}回'
    title = f'{"・".join(names)}の{"と".join(actions)}｜{heading}'
    spec.update(label=title, heading=heading, hook=title, description_line=DESCRIPTION)
    spec['offseason']['series_number'] = n
    spec['offseason']['series_title'] = TITLE
    # 材料に応じた結論を冒頭へ。本文は既存の公式照合をそのまま通す。
    spec['intro'] = f'{heading}です。{"・".join(names)}の{"と".join(actions)}がMLB公式に記録されました。'
    return spec


def validate_pending(spec, state):
    evidence = spec.get('offseason', {})
    if not evidence.get('series_number'):
        return
    if evidence['series_number'] != number(state):
        raise ValueError('連載番号が最新の公開記録と不一致')
    if any(r['event_id'] in set(state.get('events', [])) for r in evidence['events']):
        raise ValueError('公開済みの確定情報です')
