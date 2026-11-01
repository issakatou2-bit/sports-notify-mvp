"""予告の点数・日付・gateの共通判定。材料外の成績は作らない。"""
import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import club_display_names as clubs
import soccer_match_interest as interest
ROOT=Path(__file__).resolve().parents[1]
JST=timezone(timedelta(hours=9))


def policy():return json.loads((ROOT/'data/soccer_interest_weights.json').read_text(encoding='utf8'))
def competitions():return json.loads((ROOT/'data/soccer_competitions.json').read_text(encoding='utf8'))['competitions']
def competition(game):
    return next((c for c in competitions() if game.get('competition_code')==c['code'] or game.get('league') in (c['code'],c['name'])),None)
def kickoff(game,generated):
    import soccer_slots_v4
    return soccer_slots_v4.kickoff(game,generated)
def members(game):
    # 所属名簿は先発/出場の確定と扱わない。
    import notability_engine as ne
    saved=game.get('jp_by_side') or {}
    return {s:saved[s] if s in saved else [p['name_jp'] for p in ne.jp_players_for_club(game.get(s+'_team_name'))] for s in ('home','away')}


def visible_members(game):
    omitted=game.get('preview_out_names') or []
    return {s:[n for n in values if n not in omitted] for s,values in members(game).items()}


def missing_clubs(data, now):
    """今後7日の未登録名。選定点数に関係なく、試合と別名のまま知らせる。"""
    found = {}
    for game in data['games']:
        try:
            start = kickoff(game, data['generated_at'])
        except (ValueError, KeyError, TypeError):
            continue
        if not now <= start < now + timedelta(days=7):
            continue
        if game.get('status') in ('POSTPONED', 'CANCELLED', 'FINISHED', 'ABANDONED'):
            continue
        for side in ('home', 'away'):
            name = game.get(side + '_team_name')
            row = clubs.lookup(name)
            if not row or not row.get('display') or not row.get('reading'):
                found.setdefault(name or '(名称なし)', set()).add(str(game.get('game_id')))
    return [dict(club=name, game_ids=sorted(ids), candidates=clubs.candidates(name))
            for name, ids in sorted(found.items())]


def opponent_fallbacks(game):
    """名簿で所属を確認できる登録クラブの相手だけ、原語表示へ救う。"""
    people=members(game)
    registered={side:clubs.lookup(game.get(side+'_team_name')) for side in ('home','away')}
    complete=lambda row: bool(row and row.get('display') and row.get('reading'))
    if not any(people[side] and complete(registered[side]) for side in registered):
        return None
    fallback={}
    for side,row in registered.items():
        if complete(row):continue
        name=game.get(side+'_team_name')
        # 登録行の読み欠測・曖昧な別名・空名は救わず、従来どおり止める。
        if row or not isinstance(name,str) or not re.fullmatch(r"[A-Za-zÀ-ž0-9][A-Za-zÀ-ž0-9 .&'’()/-]*",name):return None
        if clubs.normalize(name) in clubs.index():return None
        fallback[side]=name
    return fallback


def registration_warning(row):
    message='::warning::今後7日の未登録クラブ: '+row['club']+' / 試合 '+', '.join(row['game_ids'])
    suggestions=row.get('candidates') or []
    if suggestions:
        message+=' / 候補：'+', '.join(c['display']+' ('+c['id']+')' for c in suggestions)
    return message


def score(game,availability=None,cfg=None):
    cfg=cfg or policy();comp=competition(game)
    if not comp:return dict(score=0,factors=[],interest={'reasons':[],'player':None},japanese=False)
    w=cfg['weights'];factors=[]
    def add(key,points,evidence):factors.append(dict(key=key,points=points,evidence=evidence))
    category=comp['code'] if comp['code'] in ('CL','EL','UECL') else 'league' if comp['football_free'] else 'cup'
    add('competition',cfg['competition'][category],comp['name'])
    if game.get('phase')=='knockout' and game.get('phase_source'):
        add('knockout',cfg['knockout_bonus'].get(category,0),game['phase_source'])
    facts=interest.decide(game,limit=None)
    for reason in facts['reasons']:
        kind=reason['kind']
        if kind=='points':
            if reason['gap']<=3:add('points_close',w['points_close'],reason)
        else:add(kind,w.get(kind,0),reason)
    marquee={clubs.normalize(v) for v in cfg['marquee_clubs']}
    for side in ('home','away'):
        row=clubs.lookup(game.get(side+'_team_name'))
        if row and clubs.normalize(row['id']) in marquee:add('marquee_'+side,w['marquee_each'],row['id'])
    people=members(game);japanese=any(people.values()) or bool(game.get('home_has_jp') or game.get('away_has_jp'))
    if japanese:add('japanese_club',w['japanese_club'],people)
    # 出場見込みは同じクラブ、公式FPL、時刻、実出場時間の裏づけを要する。
    if availability and availability.get('source')=='https://fantasy.premierleague.com/api/bootstrap-static/':
        at=interest.timestamp(availability.get('updated_at'));start=interest.timestamp(game.get('start_time_utc'))
        if at and start and 0<=(start-at).total_seconds()<=48*3600:
            eligible=[]
            identities={interest.club_id(game.get(s+'_team_name')) for s in ('home','away')}
            for name in [n for names in people.values() for n in names]:
                p=(availability.get('players') or {}).get(name) or {}
                identity=interest.club_id(p.get('club_jp'))
                if identity is None or identity not in identities:continue
                if p.get('out') is False and interest.number(p.get('minutes'),1) and interest.number(p.get('chance_next'),50):eligible.append(name)
            if eligible:add('japanese_available',w['japanese_available'],eligible)
    if facts['player']:add('expectation',w['expectation'],facts['player'])
    facts['reasons']=facts['reasons'][:2]
    return dict(score=sum(f['points'] for f in factors),factors=factors,interest=facts,japanese=japanese)


def select(data,now=None,availability=None,cfg=None):
    cfg=cfg or policy();result=copy.deepcopy(data)
    if not isinstance(result.get('games'),list):raise ValueError('試合材料のgamesが配列ではありません')
    material=interest.timestamp(result.get('generated_at'))
    if not material:raise ValueError('試合材料の取得時刻が不明です')
    now=(now or material).astimezone(JST);day=now.date();hh,mm=map(int,cfg['publish_jst'].split(':'))
    publish=datetime(day.year,day.month,day.day,hh,mm,tzinfo=JST)
    earliest=max(publish+timedelta(minutes=cfg['kickoff_margin_minutes']),now+timedelta(minutes=cfg['kickoff_margin_minutes']))
    latest=publish+timedelta(hours=cfg['window_hours']);eligible=[];rejected=[];rescued=[]
    result['club_registration_check'] = dict(days=7, checked_at=now.isoformat(), missing=missing_clubs(result, now), source_errors=result.get('source_errors', []))
    result=interest.attach_season_stats(result,availability)
    for game in result['games']:
        game.pop('preview_name_fallbacks',None)
        game['is_notable']=False;comp=competition(game)
        if not comp:continue
        try:at=kickoff(game,result['generated_at'])
        except (ValueError,KeyError,TypeError):rejected.append(dict(id=game.get('game_id'),reason='開始時刻を照合できません'));continue
        if not earliest<=at<latest:continue
        if game.get('status') in ('POSTPONED','CANCELLED','FINISHED','ABANDONED'):continue
        if not all((row := clubs.lookup(game.get(s+'_team_name'))) and row.get('display') and row.get('reading') for s in ('home','away')):
            fallback=opponent_fallbacks(game)
            if not fallback:
                rejected.append(dict(id=game.get('game_id'),reason='クラブの表示名/読みが未登録'));continue
            game['preview_name_fallbacks']=fallback
            rescued.append(dict(id=game.get('game_id'),reason='日本人所属クラブの相手を原語表示で救済',clubs=fallback,speech='未確認のクラブ名はホーム/アウェーのクラブと読み上げる'))
        snapshot=availability or {};at_snapshot=interest.timestamp(snapshot.get('updated_at'));start=interest.timestamp(game.get('start_time_utc'))
        game['preview_out_names']=[]
        if snapshot.get('source')=='https://fantasy.premierleague.com/api/bootstrap-static/' and at_snapshot and start and 0<=(start-at_snapshot).total_seconds()<=48*3600:
            for name in [n for values in members(game).values() for n in values]:
                player=(snapshot.get('players') or {}).get(name) or {}
                if player.get('out') is True and interest.club_id(player.get('club_jp')) in {interest.club_id(game.get(s+'_team_name')) for s in ('home','away')}:
                    game['preview_out_names'].append(name)
        row=score(game,availability,cfg);game['preview_rating']=row
        if row['score']>=cfg['threshold']:eligible.append((game,at))
    eligible.sort(key=lambda pair:(-pair[0]['preview_rating']['score'],-int(pair[0]['preview_rating']['japanese']),pair[1],str(pair[0]['game_id'])))
    # 辞書追加前に別名のまま補われた保存材料にも、同一カードが二重にある。
    unique = []; seen = set()
    for game, at in eligible:
        key = (competition(game)['code'], *((clubs.lookup(game[s+'_team_name']) or {}).get('id',game[s+'_team_name']) for s in ('home','away')), at.isoformat())
        if key not in seen:
            seen.add(key); unique.append(game)
    picked=unique[:cfg['max_games']];ids=[str(g['game_id']) for g in picked]
    ratings={str(g['game_id']):g.get('preview_rating',{}).get('score',0) for g in result['games']}
    for record in rescued:
        record['score']=ratings[str(record['id'])]
        record['selected']=str(record['id']) in ids
        record['outcome']='selected' if record['selected'] else 'below_threshold' if record['score']<cfg['threshold'] else 'duplicate_or_max_games'
    for g in picked:g['is_notable']=True
    if picked:result['source']='・'.join(sorted({s for g in picked for s in (g.get('fixture_sources') or ['football-data.org'])}))
    picked_ids={id(g) for g in picked};result['games']=picked+[g for g in result['games'] if id(g) not in picked_ids]
    reason='' if picked else '取得不足/名前や日時を確認できない材料があります' if result.get('source_errors') or rejected else '対象時間帯の試合なし' if not any(g.get('preview_rating') for g in result['games']) else '注目度がしきい値以上の試合なし'
    digest=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    result['preview_selection']=dict(day=day.isoformat(),threshold=cfg['threshold'],max_games=cfg['max_games'],policy_sha256=digest,selected_ids=ids,count=len(ids),reason=reason,rejected=rejected,rescued=rescued,source_errors=result.get('source_errors',[]))
    return result


from soccer_preview_assessment import assessment


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--games',type=Path,default=ROOT/'data/soccer_games.json');ap.add_argument('--availability',type=Path,default=ROOT/'data/soccer_availability.json');ap.add_argument('--at');ap.add_argument('--out',type=Path);ap.add_argument('--github-output',type=Path)
    args=ap.parse_args();data=json.loads(args.games.read_text(encoding='utf8'))
    availability=json.loads(args.availability.read_text(encoding='utf8')) if args.availability.exists() else {}
    now=interest.timestamp(args.at) if args.at else datetime.now(JST)
    material=interest.timestamp(data.get('generated_at'))
    if not now:ap.error('--atは時差のある日時が必要です')
    if not material or material.astimezone(JST).date()!=now.astimezone(JST).date():raise ValueError('当日の取得済み材料がありません')
    selected=select(data,now,availability);out=args.out or args.games
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    decision=selected['preview_selection'];print(json.dumps(decision,ensure_ascii=False))
    check = selected['club_registration_check']
    print(json.dumps(dict(club_registration_check=check), ensure_ascii=False))
    for row in check['missing']:
        print(registration_warning(row))
    if args.github_output:
        with args.github_output.open('a',encoding='utf8') as f:f.write(f"count={decision['count']}\n")
if __name__=='__main__':main()
