import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""点数で選定済みのカード。日本人選手の所属は必須にしない。"""
import soccer_slots_v4 as slots
import soccer_selection as selection
import soccer_match_interest as interest
import notability_engine as ne
import re
import club_display_names as display_names


def preview_details(game):
    """取得済みの注目理由だけから補足。AI解説の自由文は取り込まない。"""
    details=[]
    for reason in game.get('reasons', []):
        if reason.get('tag') != 'quality':
            continue
        for name, scope, rank in re.findall(r'([^（）]+)（昨季([^（）]+?)(\d+)位）', reason.get('text', '')):
            # 「と」で連結された2クラブも、その試合のクラブへ一意に照合。
            name=name.removeprefix('と').strip()
            row=display_names.lookup(name)
            if row and any((display_names.lookup(game[s+'_team_name']) or {}).get('id')==row['id'] for s in ('home','away')):
                fact=f"{row['display']}は昨季{scope}{int(rank)}位"
                if fact not in details:details.append(fact)
    # 欠測の「—」は上の数値抽出で渡らない。片側だけの実績はクラブ名つきの
    # 独立した事実として保ち、後段でも2クラブの順位差とは語らない。
    # 0位や大会違いの2件を比較へ渡さない。正常な文と順序は保つ。
    sides = {s: (display_names.lookup(game.get(s+'_team_name')) or {}).get('display')
             for s in ('home', 'away')}
    paired = [re.fullmatch(r'(.+)は昨季(.+?)(\d+)位', fact) for fact in details]
    if (not 1 <= len(paired) <= 2 or not all(paired)
            or any(m[1] not in sides.values() for m in paired)
            or any(not 1 <= int(m[3]) <= 64 for m in paired)):
        return []
    if len(paired)==2 and ({m[1] for m in paired} != set(sides.values()) or paired[0][2] != paired[1][2]):
        return []
    return details


def spoken_club(game,side):
    if side in (game.get('preview_name_fallbacks') or {}):
        return 'ホームのクラブ' if side=='home' else 'アウェーのクラブ'
    # 和名の表に無いクラブは原語のまま返る（Beşiktaş JK を声で読んでいた）。画面と同じ表で読む。
    name=ne.club_name_jp(game[side+'_team_name'])
    return name if re.search(r'[ぁ-んァ-ヶ一-龯]',name) else display_names.display(name)


def program(data):
    picked=data['preview_selection']['selected_ids']
    games=[g for ident in picked for g in data['games'] if str(g['game_id'])==ident]
    if not games:return slots.package('preview',data,[],[], '')
    names={g[s+'_team_name'] for g in games for s in ('home','away')}
    fallback_names={name for g in games for name in (g.get('preview_name_fallbacks') or {}).values()}
    clubs=slots.clubs_for(names-fallback_names);lead=games[0]
    for g in games:
        for side,name in (g.get('preview_name_fallbacks') or {}).items():
            club=dict(team_en=name,name_jp=name,abbr=name[:3].upper(),primary=None,secondary=None)
            clubs[name]=club
    people=selection.visible_members(lead);who=next((n for s in ('home','away') for n in people[s]),'')
    home,away=(clubs[lead[s+'_team_name']]['name_jp'] for s in ('home','away'))
    head=f'{home}対{away}の注目試合'
    if who:
        side='home' if who in people['home'] else 'away';other='away' if side=='home' else 'home'
        head=f"{who}の{clubs[lead[side+'_team_name']]['name_jp']}が{clubs[lead[other+'_team_name']]['name_jp']}と対戦"
    at=slots.kickoff(lead,data['generated_at']);cover_club=lead['home_team_name'] if not who or who in people['home'] else lead['away_team_name']
    segs=[slots.segment('cover','欧州サッカーの注目試合です。',dict(kicker='欧州サッカー　予告',name=who,club=cover_club,big=at.strftime('%H:%M'),unit='日本時間',context=head,chips=[]))]
    for g in games:
        at=slots.kickoff(g,data['generated_at']);jp=selection.visible_members(g)
        text=f"日本時間{at.hour}時"+(f"{at.minute}分" if at.minute else '')+f"、{spoken_club(g,'home')}対{spoken_club(g,'away')}。"
        ranks={s:(g.get(s+'_standing') or {}).get('rank') for s in ('home','away')};ranks={s:n for s,n in ranks.items() if type(n) is int and n>0}
        spec=dict(date=f'{at.month}月{at.day}日（{"月火水木金土日"[at.weekday()]}）',time=at.strftime('%H:%M'),league=g['league'],home=g['home_team_name'],away=g['away_team_name'],ranks=ranks,jp=jp,game_id=str(g['game_id']))
        segs.append(slots.segment('preview',text,spec))
    plan=interest.enrich_plan(slots.package('preview',data,segs,list(names),head,clubs))
    for seg,g in zip(plan['narration']['segments'][1:-1],games):
        meta=seg['meta'];facts=preview_details(g)
        if facts:
            paired=[re.search(r'は昨季(.+?)(\d+)位$', f) for f in facts]
            if len(paired)==2 and all(paired) and paired[0][1]==paired[1][1]:
                seg['text']+='。'.join(facts)+'。'
            else:
                seg['text']+='注目は昨季の成績。'+'。'.join(facts)+'。'
            if not meta['interest']['reasons']:
                meta['interest']['reasons']=[dict(kind='previous_season',text=f,evidence='reasons.quality') for f in facts]
        elif not meta['interest']['reasons']:
            seg['text']+=f"注目は{g['league']}での、この両チームの対戦です。"
        people=selection.visible_members(g)
        who=next((n for values in people.values() for n in values),'')
        if who:
            seg['text']+=f'{who}の所属クラブの一戦。出場する場合のプレーにも注目です。'
        elif len(facts)==2:
            seg['text']+='見どころは、この順位差が今回どう表れるかです。'
        else:
            seg['text']+=f"見どころは{spoken_club(g,'home')}のホームで、{spoken_club(g,'away')}がどう戦うかです。"
        meta['preview_duration_limit']=55
    plan['narration']['duration_budget']=dict(limit=55,grace=0)
    # 表示と音声を分離する。根拠のある補足に相手名があっても未確認の読みを作らない。
    for seg in plan['narration']['segments']:
        for g in games:
            for side,name in (g.get('preview_name_fallbacks') or {}).items():
                seg['text']=seg['text'].replace(name,'ホームのクラブ' if side=='home' else 'アウェーのクラブ')
    import soccer_title_v2
    if soccer_title_v2.enabled():
        plan = soccer_title_v2.preview_plan(plan)
    return plan
