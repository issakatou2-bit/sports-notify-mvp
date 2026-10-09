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
    return program_ticker({'segments':[{'meta':{'card':card}}]})


def program_ticker(program):
    """検証済みの日程/次戦から一本の開始予定文。原稿やカードは変更しない。"""
    records = set()
    cards = [s['meta']['card'] for s in program['segments']]
    for card in cards:
        date = str(card['date'])[:10]
        board = (card.get('scoreboard') or {}).get('rows',[])
        pair = '対'.join(r['name'] for r in board)
        for row in card.get('items',[]):
            if card.get('layout') == 'schedule':
                body = row['when']; matchup = row['home']+'対'+row['away']
            elif card.get('layout') == 'facts' and ('開始' in row['label'] or '次の試合' in row['label']):
                body = str(row['value']); matchup = pair
            else:
                continue
            if not matchup:
                continue
            day = date
            md = re.search(r'(\d{1,2})月(\d{1,2})日|(\d{1,2})/(\d{1,2})',body)
            if md:
                month,number = (md[1],md[2]) if md[1] else (md[3],md[4])
                day = f'{date[:4]}-{int(month):02d}-{int(number):02d}'
            clock = re.search(r'(\d{1,2}):(\d{2})|(\d{1,2})時(?:(\d{1,2})分)?',body)
            if clock:
                hour,minute = (clock[1],clock[2]) if clock[1] else (clock[3],clock[4] or '0')
                records.add((day,int(hour),int(minute),matchup))
    if not records:
        date = cards[0]['date']
        return f'日本時間{int(date[5:7])}月{int(date[8:10])}日　'+ ' '.join(str(cards[0].get('headline','PS')).split())
    parts=[]; previous=None
    for day,hour,minute,pair in sorted(records):
        if day != previous:
            parts.append(f'日本時間{int(day[5:7])}月{int(day[8:10])}日')
            previous=day
        parts.append(f'{hour}時'+(f'{minute}分' if minute else '')+' '+pair)
    return '　'.join(parts)


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
                body = starter_name(body)
                if not body:
                    continue
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


def spec(card, focus=None, ticker_line=None):
    chosen = focus or card
    board = chosen.get('scoreboard') or {}
    clock = next((m.group() for _, body in rows(chosen) if (m := re.search(r'\d{1,2}:\d{2}', body))), '')
    unit = ''
    if not clock:
        hour = next((m for _, body in rows(chosen) if (m := re.search(r'(\d{1,2})時(?:(\d{1,2})分)?',body))), None)
        if hour:
            clock = hour[1]+':'+hour[2] if hour[2] else hour[1]
            unit = '' if hour[2] else '時'
    chips = [{'label': r['name'], 'score': str(r['wins'])+'勝'} for r in board.get('rows', [])]
    chips += [{'label': h, 'score': b} for h,b in rows(chosen) if '先発' in h][:2]
    return {'team_id': None, 'heading': card['headline'].replace('\n','　'),
            'page': f"{card['card_index']}/{card['card_total']}" if card.get('card_index') else None,
            'hook': chosen['headline'].replace('\n','　'),
            'v3': {'who': chosen['headline'].replace('\n','　'), 'big': clock, 'unit': unit,
                   'tag': chosen.get('subhead',''), 'chips': chips,
                   'ticker': ticker_line if ticker_line is not None else ticker_text(card), 'ticker_once': True}}


def frame(t, card, focus=None, cover=False, duration=20, ticker_line=None):
    if card.get('next_line'):
        import next_line
        return next_line.frame(t,card['next_line'])
    view = spec(card, focus, ticker_line)
    if card.get('outro'):
        view['text']=r3.OUTRO_TEXT
        closing=common.outro(t,view,card.get('lineup_kind','daily'))
        if closing is not None:
            return closing
    if card['layout']=='schedule':
        return common.schedule(t,view,card['items'],'PS予告','出典：'+card.get('source_label','MLB公式日程'))
    if r3.LOOK == 'v4':
        from short_v4_cards import focus as draw_focus, situation
        if card.get('label')=='PS情勢' and card.get('scoreboard'):
            return situation(t,card,spec(card,card,ticker_line))
        chosen=(focus or card) if card.get('card_index') is None else card
        if chosen.get('scoreboard') and (card.get('card_index') is None or t<min(8,duration*.5)):
            return draw_focus(t,chosen,spec(chosen,chosen,ticker_line))
    if card.get('card_index') is None and not card.get('outro'):
        im = r3.intro(t, view, card.get('label','PS'))
        r3.source(r3.ImageDraw.Draw(im), '出典：'+card.get('source_label','説明欄'), r3.colors(view['team_id'])[1])
        if r3.LOOK=='v4':
            from short_v4_cards import balance_content, ensure_team_badges
            im.info['v4_ticker_text']=view['v3'].get('ticker','')
            ensure_team_badges(im);balance_content(im,t)
        return im
    page_rows=rows(card)
    pages=common.paginate(view,page_rows)
    im=common.frame(t, view, page_rows, card.get('label','PS'), '出典：'+card.get('source_label','説明欄'),
                    page_seconds=duration/max(1,len(pages)))
    if r3.LOOK=='v4':
        from short_v4_cards import balance_content, ensure_team_badges
        im.info['v4_ticker_text']=view['v3'].get('ticker','')
        ensure_team_badges(im)
        balance_content(im,t)
    return im


def check_layout(card):
    if card.get('next_line'):
        import next_line
        import v3_rules
        if v3_rules.check_layout(next_line.frame(3,card['next_line'])):
            raise ValueError('次情報の札が安全域外です')
        return {'pages':1,'next_line':True}
    if card.get('outro'):
        return {'pages':1,'outro':True}
    view=spec(card)
    if card['layout']=='schedule':
        if len(card['items'])>4:
            raise ValueError('明日の全試合一覧が4試合を超えています')
        return {'pages':1,'top':340,'bottom':340+len(card['items'])*180,'ticker_top':1486}
    content=rows(card)
    if common.check_pages(view,content):
        raise ValueError('PSの札が見出し下/テロップ上の安全域を超えています')
    return {'pages':len(common.paginate(view,content)),'boxes':[cell['box'] for p in common.paginate(view,content) for cell in p]}


def transition(previous, image, index, fade_frames, elapsed, ticker_line):
    """画面を混ぜ終わった後に帯を一度だけ描く。帯の時刻は番組全体で連続。"""
    from video_common import crossfade, short_transition
    raw=(short_transition(previous,image,index,30,True) if r3.LOOK=='v4' else
         crossfade(previous,image,index,fade_frames,(1080,1920)))
    result = r3.Image.frombytes('RGB',(1080,1920),raw)
    if not image.info.get('v3_outro'):
        r3.ticker(result,elapsed,ticker_line,once=True)
    return result.tobytes()


def cues(card, focus=None, cover=False, duration=20):
    if card.get('outro'):
        return r3.outro_cues(card.get('lineup_kind','daily'))
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
