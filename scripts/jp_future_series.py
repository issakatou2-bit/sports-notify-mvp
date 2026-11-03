"""保存済み対象名と公式取引だけの番号つき連載。公開成功時だけ番号を確定。"""
import copy
from jp_future_catalog import TITLE, targets, number

DESCRIPTION = '連載「日本人選手の来季」では、MLB公式に確定した移籍・契約などの動きを追います。'


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
