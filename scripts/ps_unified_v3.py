"""検証済みPSカードを、共通表紙・項目札へ写す。元カードは変更しない。"""
import re
import review_render_v3 as r3
import v3_slot_render as common


def starter_name(value):
    from generate_narration import speech_name
    if value in ('確認中','未定','先発予定'):
        return ''
    name = speech_name(str(value))
    return name if name and not re.search(r'[A-Za-zÀ-ž]', name) else ''


def ticker_text(card):
    return '　'.join(' '.join(str(x).split()) for x in
                    (card['date'],card.get('subhead'),
                     card.get('glossary') if card.get('card_index') is None else '') if x)


def rows(card):
    result = []
    for row in (card.get('scoreboard') or {}).get('rows', []):
        result.append((row['abbr']+'　'+row['name'], str(row['wins'])+'勝　'+'・'.join(row.get('players') or [])))
    for row in card.get('items', []):
        if card['layout'] == 'schedule':
            result.append((row['home']+' 対 '+row['away'], row['when']))
        elif card['layout'] == 'facts':
            head, body = row['label'], str(row['value'])
            if '先発' in head:
                body = starter_name(body) or '先発予定'
            result.append((head, body))
        elif card['layout'] == 'bracket':
            result.append((row['home']+' 対 '+row['away'], row['when']+'　'+row['next']))
        else:
            result.append((row.get('attribution',''), '「'+row['quote']+'」'))
    result += [('', x) for x in card.get('affiliations', [])]
    if card.get('round_game'):
        result.insert(0, ('', card['round_game']))
    if (card.get('scoreboard') or {}).get('need'):
        result.append(('シリーズの決着', str(card['scoreboard']['need'])+'勝先取'))
    return result


def lead_card(program):
    cover = program['segments'][0]['meta']['card']
    candidates = [s['meta']['card'] for s in program['segments'] if s['meta']['card'].get('scoreboard')]
    return next((c for c in candidates if any(r['name'] in cover['headline'] for r in c['scoreboard']['rows'])), candidates[0] if candidates else cover)


def spec(card, focus=None):
    from ps_render_template import background_team
    chosen = focus or card
    board = chosen.get('scoreboard') or {}
    clock = next((m.group() for _, body in rows(chosen) if (m := re.search(r'\d{1,2}:\d{2}', body))), '')
    unit = ''
    if not clock:
        hour = next((m for _, body in rows(chosen) if (m := re.search(r'(\d{1,2})時(?:(\d{1,2})分)?',body))), None)
        if hour:
            clock = hour[1]+':'+hour[2] if hour[2] else hour[1]
            unit = '' if hour[2] else '時'
    chips = [{'label': r['name'], 'score': str(r['wins'])+'勝', 'win': bool(r['wins'])} for r in board.get('rows', [])]
    chips += [{'label': h, 'score': b} for h,b in rows(chosen) if '先発' in h][:2]
    return {'team_id': background_team(chosen), 'heading': card['headline'].replace('\n','　'),
            'page': f"{card['card_index']}/{card['card_total']}" if card.get('card_index') else None,
            'hook': chosen['headline'].replace('\n','　'),
            'v3': {'who': chosen['headline'].replace('\n','　'), 'big': clock, 'unit': unit,
                   'tag': chosen.get('subhead',''), 'chips': chips,
                   'ticker': ticker_text(card)}}


def frame(t, card, focus=None, cover=False, duration=20):
    view = spec(card, focus)
    if card.get('card_index') is None or (cover and t < min(4, duration/3)):
        im = r3.intro(t, view, card.get('label','PS'))
        r3.source(r3.ImageDraw.Draw(im), '出典：'+card.get('source_label','説明欄'), r3.colors(view['team_id'])[1])
        return im
    if cover:
        t -= min(4, duration/3)
    return common.frame(t, view, rows(card), card.get('label','PS'), '出典：'+card.get('source_label','説明欄'))


def cues(card, focus=None, cover=False, duration=20):
    if card.get('card_index') is None:
        return r3.cues('intro', spec(card, focus))
    result=common.cues(rows(card))
    if cover:
        result=r3.cues('intro', spec(card,focus))+[(at+min(4,duration/3),kind,var,db) for at,kind,var,db in result]
    return result


def render(card, presenters='right', layers=False, focus=None):
    if presenters != 'right':
        raise ValueError('v3のPSは四国めたん（右下）です')
    image = frame(3, card, focus)
    # 照合対象は元の検証済みカード。描画の項目は派生行として明示する。
    manifest = {'card': card, 'text': [{'text': h+'　'+b, 'role': 'important'} for h,b in rows(card)],
                'presenters': [{'side': 'right', 'asset': 'metan/3-black/base.png'}],
                'public': False, 'design': 'review_render_v3', 'source': card['source_url']}
    return (image, manifest, image.convert('RGBA')) if layers else (image, manifest)
