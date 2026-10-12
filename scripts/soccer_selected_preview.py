import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""点数で選定済みのカード。日本人選手の所属は必須にしない。"""
import soccer_slots_v4 as slots
import soccer_selection as selection
import soccer_match_interest as interest
import notability_engine as ne


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
        text=f"日本時間{at.hour}時"+(f"{at.minute}分" if at.minute else '')+f"、ホームの{ne.club_name_jp(g['home_team_name'])}と、アウェーの{ne.club_name_jp(g['away_team_name'])}。"
        ranks={s:(g.get(s+'_standing') or {}).get('rank') for s in ('home','away')};ranks={s:n for s,n in ranks.items() if type(n) is int and n>0}
        spec=dict(date=f'{at.month}月{at.day}日（{"月火水木金土日"[at.weekday()]}）',time=at.strftime('%H:%M'),league=g['league'],home=g['home_team_name'],away=g['away_team_name'],ranks=ranks,jp=jp,game_id=str(g['game_id']))
        segs.append(slots.segment('preview',text,spec))
    return interest.enrich_plan(slots.package('preview',data,segs,list(names),head,clubs))
