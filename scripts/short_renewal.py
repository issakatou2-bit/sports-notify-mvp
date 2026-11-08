"""11/8刷新の編集。数字は入力から、フックと札と読み上げは同じ定義から。"""
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

import short_common


def hook(subject, value, unit, *, prefix='', context=''):
    return dict(subject=subject, value=value, unit=unit, context=context,
                text=f'{subject}、{prefix}{value}{unit}。')


def opening_check(item):
    """名前と最初の数字の発音開始までを毎秒6モーラで見積もる。実音声の保証ではない。"""
    import notability_engine as ne
    from number_readings import kana,integer
    text=item['text'];number=re.search(r'\d',text)
    if not number or item['subject'] not in text:return dict(passed=False,reason='名前か数字がない')
    reach=max(number.start(),text.find(item['subject']))
    prefix=text[:reach]
    if item.get('subject_reading'):prefix=prefix.replace(item['subject'],item['subject_reading'])
    prefix=re.sub(r'\d+',lambda match:kana(integer(match[0])),prefix)
    try:prefix=ne.apply_readings(prefix)
    except ValueError:
        return dict(passed=False,reason='名前の読み辞書の確認が必要')
    # 未登録の漢字は短く見積もらず、1字2モーラとして扱う。
    reading_text=re.sub(r'[^ぁ-んァ-ヶ一-龯々ー]', '', prefix)
    mora=sum(2 if re.match(r'[一-龯々]',c) else 0 if c in 'ゃゅょャュョァィゥェォ' else 1 for c in reading_text)
    seconds=mora/6
    return dict(passed=seconds<=2,estimated_number_onset=round(seconds,3),mora=mora,method='原稿・毎秒6モーラ')


def positive(player):
    return player.get('status')!='none' and any(type(player.get(k)) is int and player[k]>0 for k in ('goals','assists'))


def impact_units(game, player):
    from soccer_story_lines import goal_trace
    import soccer_result_facts as facts
    units=[];selected=[]
    for goal,before,after in goal_trace(game):
        if goal.get('own_goal'):continue
        scored=goal.get('japanese_goal') and facts.scorer_name(goal)==player['name']
        assisted=player['name'] in facts.assist_names(goal)
        if not scored and not assisted:continue
        side=goal['side'];other='away' if side=='home' else 'home';a,b=after[side],after[other]
        if before[side]<before[other] and a>b:change='逆転'
        elif a==b:change='同点'
        elif before[side]==before[other]:change='先制' if not sum(before.values()) else '勝ち越し'
        else:change='リードを広げました' if a>b else '点差を縮めました'
        conclusion={'逆転':'逆転しました','同点':'同点に追いつきました','先制':'先制しました','勝ち越し':'勝ち越しました'}.get(change,change)
        who='この得点で' if scored else 'このアシストから'
        units.append(f"{who}{game[side]['name_jp']}は{a}対{b}と{conclusion}。")
        selected.append(goal)
    return units,selected


def season_context(game, player):
    """同大会・同クラブの試合後の明示値だけ。試合前の通算に足し算しない。"""
    import soccer_results as r
    import club_display_names as names
    output=[]
    for row in game.get('season_players') or []:
        if row.get('name')!=player['name'] or row.get('scope')!='season' or not row.get('source') or not row.get('season'):continue
        if row.get('competition')!=game.get('league') or not row.get('as_of'):continue
        try:
            if not r.utc(game['finished_utc'])<=r.utc(row['as_of'])<=r.utc(game['finished_utc'])+r.timedelta(days=1):continue
        except (ValueError,TypeError):continue
        if names.display(row.get('club') or '')!=names.display(player['club']):continue
        key='goals' if player.get('goals') else 'assists';value=row.get(key)
        if type(value) is not int or value<(player.get(key) or 0):continue
        unit='得点' if key=='goals' else 'アシスト'
        output.append(dict(label=row['season']+' '+game['league_jp'],value=f'今季{value}{unit}',
                           text=f"{player['name']}は今季の{game['league_jp']}で{value}{unit}です。",source=row['source']))
    return output[:1] if len(output)==1 else []


def result_program(data):
    import soccer_title_v2 as title
    import soccer_stats as stats
    import soccer_result_facts as facts
    import sanity_sources
    eligible=[p for p in data.get('players',[]) if positive(p)]
    if not data.get('can_make') or not eligible:
        return dict(label=data['date_jst'],segments=[],duration_budget=dict(limit=60,grace=0),selection_reason='日本人の得点・アシストなし')
    import soccer_results as results
    lead=min(eligible,key=results.rank_key);game=next(g for g in data['games'] if str(g['id'])==str(lead['event_id']))
    selected=copy.deepcopy(data);selected['games']=[game];selected['players']=game['players']
    selected['preview_followup']=dict(games=[r for r in (data.get('preview_followup') or {}).get('games',[]) if str(r['event_id'])==str(game['id'])])
    narr=title.result_narration(selected)
    metric='goals' if lead.get('goals') else 'assists';opening=hook(lead['name'],lead[metric],'得点' if metric=='goals' else 'アシスト')
    first=narr['segments'][0];first.update(text=opening['text'],caption_units=[opening['text']]);first['meta']['opening_hook']=opening
    units,goals=impact_units(game,lead)
    remaining=[first]
    if units:
        remaining.append(dict(kind='followup-detail',text=''.join(units),caption_units=units,speaker=2,
            meta=dict(event_id=game['id'],goals=goals,details=facts.display_details(game,{}),required=True)))
    # 最終スコアは得点の意味に続け、冒頭の個人数と取り違えない。
    remaining.append(dict(kind='followup',text=facts.result_opening(game,lead),speaker=2,
                          meta=dict(event_id=game['id'],score_only=True)))
    context=season_context(game,lead)
    for row in context:
        remaining.append(dict(kind='impact-context',text=row['text'],speaker=2,
            meta=dict(event_id=game['id'],fact_rows=[(row['label'],row['value'])],row_texts=[row['text']],progressive_rows=True,source=row['source'])))
    changes=[s for s in narr['segments'] if s['kind']=='followup-change']
    remaining.extend(changes)
    detail=stats.personal_narration(lead)
    minutes=stats.minutes_label(lead)
    if detail or minutes:
        index=[p for p in game['players'] if p['status']!='none'].index(lead)
        text=lead['name']+'は'+'、'.join(s for s in (minutes,detail) if s)+'。'
        remaining.append(dict(kind='player-stats',text=text,speaker=2,meta=dict(event_id=game['id'],start=index,count=1)))
    remaining.append(dict(kind='outro',text=short_common.OUTRO_TEXT,speaker=2,meta={}))
    narr['segments']=remaining;narr['opening_check']=opening_check(opening)
    narr['short_content_version'] = '1108'
    narr['title']=title.title(opening['text'].rstrip('。'))
    narr=sanity_sources.attach(narr,selected,sport='soccer')
    return narr


def race_program(plan):
    if not plan['narration']['segments']:return plan
    import soccer_race as race
    import notability_engine as ne
    lead=race.lead(plan['data'])
    tables=[s for s in plan['narration']['segments'] if s['kind']=='standings']
    table=next((s for s in tables if not lead or (s['meta']['title'].split('　')[0]==lead[2]
                and any(at == lead[1]['line'] for at, _ in s['meta']['lines']))),None)
    if table is None:
        plan['narration']['segments']=[]
        plan['narration']['selection_reason']='主役の大会の順位表を確認できません'
        return plan
    meta=table['meta'];rows=meta['rows'];at=meta['lines'][0][0]
    if lead:
        who,near,label=lead;subject=who['name'];gap=near['diff']
        own=next((r for r in rows if r['position']==who['position']),None)
        if own is None:
            key=who['club_jp'];plan['clubs'].setdefault(key,dict(team_en=key,name_jp=key,abbr='JPN',primary=None,secondary=None))
            own=dict(position=who['position'],points=who['points'],played=None,team=key);rows=rows+[own]
        primary=own['team']
        meta['gap']='は'+race.phrase(near)
    else:
        subject=meta['title'].split('　')[0]
        boundary=[r for r in rows if r['position'] in (at,at+1)]
        if len(boundary)!=2:
            plan['narration']['segments']=[]
            plan['narration']['selection_reason']='境目の2クラブの勝点を確認できません'
            return plan
        gap=abs(boundary[0]['points']-boundary[1]['points']);primary=boundary[0]['team']
    opening=hook(subject,gap,'差',prefix='勝点',context=lead[1].get('label','順位争い') if lead else meta['title'])
    opening['display_unit']='勝点差'
    cover=next((s for s in plan['narration']['segments'] if s['kind']=='cover'),None)
    if cover is None:cover=dict(kind='cover',speaker=2,meta=dict(plan['shared']))
    cover.update(text=opening['text']);cover['meta'].update(opening_hook=opening)
    keep=sorted(rows,key=lambda r:(r['team']!=primary,abs(r['position']-at),r['position']))[:4]
    keep.sort(key=lambda r:r['position'])
    # 全角の空白を f 文字列の式の中に置くと、検査の Python 3.11 の ast.unparse が扱えない。
    league = meta['title'].replace('　', 'の')
    scope = f"{league}の境目は、{at}位と{at+1}位です。"
    row_texts = []
    for row in keep:
        club = ne.club_name_jp(row['team'])
        played = row.get('played')
        games = f'{played}試合を終え、' if type(played) is int and played >= 0 else ''
        row_texts.append(f"{club}は{games}{row['position']}位で勝点{row['points']}。")
    meta.update(rows=keep,shown=[[r['position'],r['position']] for r in keep],primary=primary,focus=primary,
                progressive_rows=True,row_texts=row_texts,leading_text=scope)
    table.update(text=scope+''.join(row_texts),caption_units=[scope]+row_texts)
    ending=dict(kind='outro',text=short_common.OUTRO_TEXT,speaker=2,meta=dict(plan['shared']))
    plan['narration']['segments']=[cover,table,ending];plan['narration']['opening_check']=opening_check(opening)
    plan['narration']['short_content_version'] = '1108'
    return plan


def elapsed(t):
    import review_render_v3 as r3
    ctx=r3._CAPTION
    return max(0,t if r3._PROGRAM_CLOCK[0] is None else r3._PROGRAM_CLOCK[0]-ctx['start'])


def row_state(t,spec,index):
    if not spec.get('progressive_rows'):return True,True
    import review_render_v3 as r3
    units=spec.get('row_texts') or []
    prefix=spec.get('leading_text') or ''
    text=prefix+''.join(units);duration=r3._CAPTION.get('duration') or max(1,len(text)/7.5)
    before=len(prefix)+sum(len(s) for s in units[:index]);part=units[index] if index<len(units) else ''
    number=re.search(r'勝点(\d+)',part) or re.search(r'(\d+)',part);offset=number.start(1) if number else len(part)/2
    total=max(1,len(text));now=elapsed(t)
    return now>=(0 if index==0 else before/total*duration),now>=max(0,(before+offset)/total*duration-.08)


def hook_frame(t,item,clubs,spec):
    from soccer_readable import Screen
    import soccer_v5_cards as c
    label=spec.get('label') or spec.get('title') or '欧州サッカー'
    s=Screen(clubs,max(.35,t),label=label)
    if label in ('現地の報道','現地のファンの声'):
        import review_render_v3 as r3
        from PIL import ImageDraw
        info=s.im.info
        s.im=r3.background(max(.35,t),None);s.im.info=info
        s.im.info['v3_layout']=[]
        r3._header(ImageDraw.Draw(s.im),label,None)
    s.title(item.get('context') or '日本人選手の数字')
    s.panel(600,1330);s.lines(100,650,item['subject'],64,800,role='supplement')
    s.text(100,850,str(item['value']),196,650,c.LIME,True,role='supplement')
    s.text(100,1130,item.get('display_unit') or item['unit'],64,800,role='supplement')
    s.im.info['preview_body']=[64,600,1016,1330]
    s.im.info['opening_hook']=item
    # 主題札と同じ内容の字幕をもう1つ重ねない。声と表情はそのまま。
    import review_render_v3 as r3
    hidden=r3._CAPTION.get('hide_caption',False);r3._CAPTION['hide_caption']=True
    try:return s.finish(spec)
    finally:r3._CAPTION['hide_caption']=hidden


def fact_frame(t,seg,clubs,spec):
    from soccer_readable import Screen
    s=Screen(clubs,t)
    return s.national_facts('得点の意味',seg['meta']['fact_rows'],dict(spec,**{k:seg['meta'][k] for k in ('row_texts','progressive_rows') if k in seg['meta']}),sub='今季の成績')


def morning(document,data,mode):
    if mode not in ('press', 'voices'):
        return document
    if not document.get('segments'):
        document['opening_hold'] = '本文・要約または同じ題材のコメントを確認できません'
        return document
    document['short_content_version'] = '1108'
    item=None
    if mode=='voices':
        text=document['segments'][0]['text'].rstrip('。')
        match=re.fullmatch(r'(.+?)(?:、.+?で|が)(\d+)(セーブ|本塁打|得点|アシスト)(?:を挙げる活躍)?',text)
        if match:item=hook(match[1],int(match[2]),match[3])
    else:
        import morning_content as content
        story=content.press_story(data.get('reporters') or {})
        if story:
            body=''.join(story['parts'])
            match=re.search(r'([ァ-ヶー]+)の選手では(\d+)人目',body)
            subject=re.match(r'(.+?)が',story['parts'][0])
            if match and subject:
                item=hook(subject[1],int(match[2]),'人目',context=match[1]+'の受賞記録')
                item['text']=f"{match[2]}人目、{subject[1]}。"
    if item:
        meta=dict(opening_hook=item,quote_rows=[dict(said=item['text'],who='お題',fact=True,read=True,clip=True)])
        if mode=='voices':
            first=document['segments'][0];first.update(text=item['text']);first['meta'].update(meta)
        else:
            document['segments'].insert(0,dict(kind='intro',text=item['text'],speaker=2,meta=meta))
        document['opening_check']=opening_check(item);document['title']=(story['parts'][0].rstrip('。')+' '+item['text'].rstrip('。') if mode=='press' else item['text'].rstrip('。'))
    else:document['opening_hold']='材料から名前と数字の短いフックを作れません'
    if item and not document['opening_check']['passed']:document['opening_hold']='名前と数字が2秒以内に始まる原稿を確認できません'
    return document
