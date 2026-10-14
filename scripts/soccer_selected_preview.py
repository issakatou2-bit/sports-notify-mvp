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
            if row and any(display_names.lookup(game[s+'_team_name'])['id']==row['id'] for s in ('home','away')):
                fact=f"{row['display']}は昨季{scope}{int(rank)}位"
                if fact not in details:details.append(fact)
    return details[:2]


def program(data):
    picked=data['preview_selection']['selected_ids']
    games=[g for ident in picked for g in data['games'] if str(g['game_id'])==ident]
    if not games:return slots.package('preview',data,[],[], '')
    names={g[s+'_team_name'] for g in games for s in ('home','away')};clubs=slots.clubs_for(names);lead=games[0]
    people=selection.visible_members(lead);who=next((n for s in ('home','away') for n in people[s]),'')
    home,away=(ne.club_name_jp(lead[s+'_team_name']) for s in ('home','away'))
    head=f'{home}対{away}の注目試合'
    if who:
        side='home' if who in people['home'] else 'away';other='away' if side=='home' else 'home'
        head=f"{who}の{ne.club_name_jp(lead[side+'_team_name'])}が{ne.club_name_jp(lead[other+'_team_name'])}と対戦"
    at=slots.kickoff(lead,data['generated_at']);cover_club=lead['home_team_name'] if not who or who in people['home'] else lead['away_team_name']
    segs=[slots.segment('cover','欧州サッカーの注目試合です。',dict(kicker='欧州サッカー　予告',name=who,club=cover_club,big=at.strftime('%H:%M'),unit='日本時間',context=head,chips=[]))]
    for g in games:
        at=slots.kickoff(g,data['generated_at']);jp=selection.visible_members(g)
        text=f"日本時間{at.hour}時"+(f"{at.minute}分" if at.minute else '')+f"、{ne.club_name_jp(g['home_team_name'])}対{ne.club_name_jp(g['away_team_name'])}。"
        ranks={s:(g.get(s+'_standing') or {}).get('rank') for s in ('home','away')};ranks={s:n for s,n in ranks.items() if type(n) is int and n>0}
        spec=dict(date=f'{at.month}月{at.day}日（{"月火水木金土日"[at.weekday()]}）',time=at.strftime('%H:%M'),league=g['league'],home=g['home_team_name'],away=g['away_team_name'],ranks=ranks,jp=jp,game_id=str(g['game_id']))
        segs.append(slots.segment('preview',text,spec))
    plan=interest.enrich_plan(slots.package('preview',data,segs,list(names),head,clubs))
    for seg,g in zip(plan['narration']['segments'][1:-1],games):
        meta=seg['meta'];facts=preview_details(g)
        if facts:
            paired=[re.search(r'は昨季(.+?)(\d+)位$', f) for f in facts]
            if len(paired)==2 and all(paired) and paired[0][1]==paired[1][1]:
                seg['text']+=f'昨季{paired[0][1]}でホーム側は{paired[0][2]}位、アウェー側は{paired[1][2]}位。'
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
            seg['text']+=f"見どころは{ne.club_name_jp(g['home_team_name'])}のホームで、{ne.club_name_jp(g['away_team_name'])}がどう戦うかです。"
        meta['preview_duration_limit']=55
    plan['narration']['duration_budget']=dict(limit=55,grace=0)
    return plan
