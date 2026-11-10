"""招集選手のリーグ戦・今季集計。本人、所属、季を照合できない数値は使わない。"""
import copy
from datetime import timedelta
import hashlib
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
SITE='https://site.api.espn.com/apis/site/v2/sports/soccer'
CORE='https://sports.core.api.espn.com/v2/sports/soccer/leagues'
LEAGUES={
 'PL':('eng.1','プレミアリーグ'),'ELC':('eng.2','イングランド2部'),
 'PD':('esp.1','ラ・リーガ'),'SA':('ita.1','セリエA'),
 'BL1':('ger.1','ブンデスリーガ'),'BL2':('ger.2','ドイツ2部'),
 'FL1':('fra.1','リーグ・アン'),'DED':('ned.1','オランダ1部'),
 'BEL':('bel.1','ベルギー1部'),'DEN':('den.1','デンマーク1部'),'J1':('jpn.1','J1')}
# JFA表記と既存の英名の対応だけ。所属リーグや在籍は実行時の名簿で再確認する。
CLUBS=dict(zip([
 '鹿島アントラーズ','シントトロイデンVV','アストン・ビラ','ボルシア・メンヘングラートバッハ',
 'フェイエノールト','TSGホッフェンハイム','バイエルン・ミュンヘン','ル・アーヴルAC',
 'サンフレッチェ広島','カリャリ・カルチョ','FCコペンハーゲン','KRCゲンク','ASモナコ',
 'クリスタル・パレス','コベントリー・シティ','FC町田ゼルビア','イプスウィッチ・タウン',
 'アイントラハト・フランクフルト','リーズ・ユナイテッド','オリンピック・リヨン',
 'マインツ05','レアル・ソシエダ','SCフライブルク','サウサンプトンFC','PSVアイントホーフェン','カールスルーエSC'
],[
 'Kashima Antlers','Sint-Truidense VV','Aston Villa FC','Borussia Mönchengladbach',
 'Feyenoord Rotterdam','TSG 1899 Hoffenheim','FC Bayern München','Le Havre AC',
 'Sanfrecce Hiroshima','Cagliari Calcio','FC Copenhagen','KRC Genk','AS Monaco FC',
 'Crystal Palace FC','Coventry City FC','FC Machida Zelvia','Ipswich Town FC',
 'Eintracht Frankfurt','Leeds United FC','Olympique Lyonnais','1. FSV Mainz 05',
 'Real Sociedad de Fútbol','SC Freiburg','Southampton FC','PSV Eindhoven','Karlsruher SC'
]))


def club_id(name):
    import club_display_names as clubs
    return (clubs.lookup(name) or {}).get('id') or clubs.normalize(name)


def team_rows(payload):
    rows=list(payload.get('teams') or [])
    for sport in payload.get('sports') or []:
        for league in sport.get('leagues') or []:rows.extend(league.get('teams') or [])
    return [r.get('team',r) for r in rows]


def athlete_rows(payload):
    rows=[]
    for row in payload.get('athletes') or []:
        rows.extend(row.get('items') or [row])
    return [dict(athlete=r.get('athlete',r)) for r in rows]


def stats_url(url,slug,year,athlete_id,team_id=None):
    parsed=urlparse(str(url))
    path=f'/v2/sports/soccer/leagues/{slug}/seasons/{year}/types/1/athletes/{athlete_id}/statistics'
    paths=[path,path+'/0']
    if team_id:
        team_path=path.replace('/athletes/','/teams/'+str(team_id)+'/athletes/')
        paths += [team_path,team_path+'/0']
    if parsed.hostname!='sports.core.api.espn.com' or parsed.path.rstrip('/') not in paths:
        raise ValueError('リーグ・季・選手が特定できる今季集計の参照ではありません')
    return 'https://sports.core.api.espn.com'+parsed.path+('?' + parsed.query if parsed.query else '')


def values(payload):
    categories=(payload.get('splits') or {}).get('categories',payload.get('categories',[]))
    aliases={'appearances':('appearances','totalAppearances','gamesPlayed'),
             'goals':('totalGoals','goals'),'assists':('goalAssists','assists')}
    result={}
    for field,keys in aliases.items():
        found=[]
        for category in categories:
            for row in category.get('stats') or []:
                if row.get('name') not in keys:continue
                value=row.get('value')
                if type(value) not in (int,float) or not float(value).is_integer() or value<0:
                    raise ValueError('今季集計の数値が不正です')
                found.append(int(value))
        if len(set(found))>1:raise ValueError('同じ今季集計に異なる数字があります')
        if found:result[field]=found[0]
    return result


def collect(roster,as_of,directory=None,fetch=None,fixture=False):
    """既存soccer_results.fetch_jsonを使用。coreの公式参照を辿り、季の総数だけ読む。"""
    import soccer_national as n
    import soccer_results as results
    fetch=fetch or results.fetch_json
    n.instant(as_of)
    season_year=int(roster['season'].split('/')[0])
    cache={};failures={}
    def get(url):
        if url not in cache:
            payload=fetch(url)
            if not isinstance(payload,dict):raise ValueError('今季集計の応答がJSONオブジェクトではありません')
            cache[url]=payload
            if directory:
                path=Path(directory);path.mkdir(parents=True,exist_ok=True)
                n.save(path/(hashlib.sha256(url.encode()).hexdigest()+'.json'),dict(url=url,as_of=as_of,payload=payload))
        return cache[url]
    candidates={}
    for code,(slug,label) in LEAGUES.items():
        year=n.instant(as_of).year if code=='J1' else season_year
        url=f'{SITE}/{slug}/teams?season={year}&limit=100'
        try:
            for team in team_rows(get(url)):
                name=team.get('displayName') or team.get('name')
                if not name or not str(team.get('id','')).isdigit():continue
                candidates.setdefault(club_id(name),[]).append((code,slug,label,year,team,url))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):failures[code]='teams_unavailable'
    accepted=[];missing=[]
    for player in roster['players']:
        canonical=CLUBS.get(player['club'],player['club'])
        found=candidates.get(club_id(canonical),[])
        unique={(r[1],str(r[4]['id'])):r for r in found}
        if len(unique)!=1:
            missing.append(dict(name=player['name_jp'],reason='club_unconfirmed' if not unique else 'club_ambiguous'));continue
        code,slug,label,year,team,teams_source=next(iter(unique.values()))
        roster_url=f'{SITE}/{slug}/teams/{team["id"]}/roster?season={year}'
        try:
            resolved=results.resolve_player(athlete_rows(get(roster_url)),player['name_en'])
            if resolved is None:raise ValueError('athlete_unconfirmed')
            athlete=resolved['athlete'];ident=str(athlete.get('id',''))
            if not ident.isdigit():raise ValueError('athlete_id_missing')
            ref=athlete.get('statistics') or {}
            if not isinstance(ref,dict) or not ref.get('$ref'):
                profile_url=f'{CORE}/{slug}/seasons/{year}/athletes/{ident}'
                profile=get(profile_url)
                if str(profile.get('id'))!=ident or results.resolve_player([dict(athlete=profile)],player['name_en']) is None:
                    raise ValueError('athlete_profile_mismatch')
                ref=profile.get('statistics') or {}
            if not isinstance(ref,dict):raise ValueError('今季集計への参照がありません')
            url=stats_url(ref.get('$ref'),slug,year,ident,str(team['id']))
            raw=get(url);counts=values(raw)
            if 'appearances' not in counts and (player['position']=='GK' or 'goals' not in counts):
                raise ValueError('season_counts_missing')
            accepted.append(dict(name=player['name_jp'],name_en=player['name_en'],club=player['club'],
                athlete_id=ident,team_id=str(team['id']),league=code,league_slug=slug,league_label=label,
                season=str(year) if code=='J1' else roster['season'],season_year=year,
                scope='league_season',as_of=as_of,source=url,roster_source=roster_url,teams_source=teams_source,
                values=counts,evidence=dict(athlete=athlete,team=team,statistics=raw)))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            missing.append(dict(name=player['name_jp'],reason='athlete_or_season_unconfirmed'))
    return dict(version=1,as_of=as_of,season=roster['season'],fixture=fixture,players=accepted,missing=missing,league_errors=failures)


def validate(sheet,roster,as_of):
    import soccer_national as n
    import soccer_results as results
    import sample_only
    if sheet.get('fixture') and not sample_only.enabled():raise ValueError('試験の数字はsample_onlyだけで使用します')
    at=n.instant(sheet['as_of']);now=n.instant(as_of)
    if not now-timedelta(days=2)<=at<=now:raise ValueError('今季の数字が古いか未来です')
    if sheet['season']!=roster['season']:raise ValueError('招集名簿と数字の季が違います')
    people={p['name_jp']:p for p in roster['players']};seen=set()
    for row in sheet['players']:
        p=people[row['name']]
        if row['name'] in seen:raise ValueError('今季集計の重複')
        seen.add(row['name'])
        if (row['name_en'],row['club'])!=(p['name_en'],p['club']) or row['scope']!='league_season':
            raise ValueError('今季集計の選手・所属・範囲が違います')
        code=row['league'];slug,label=LEAGUES[code]
        year=now.year if code=='J1' else int(roster['season'].split('/')[0])
        if row['season_year']!=year or row['season']!=(str(year) if code=='J1' else roster['season']):
            raise ValueError('今季集計の季が違います')
        if row['league_slug']!=slug or row['league_label']!=label or row['as_of']!=sheet['as_of']:
            raise ValueError('リーグ・取得時刻が違います')
        stats_url(row['source'],slug,year,row['athlete_id'],row['team_id'])
        if row['roster_source']!=f'{SITE}/{slug}/teams/{row["team_id"]}/roster?season={year}':
            raise ValueError('所属名簿の出典が違います')
        if row['teams_source']!=f'{SITE}/{slug}/teams?season={year}&limit=100':raise ValueError('リーグ名簿の出典が違います')
        evidence=row['evidence'];athlete=evidence['athlete'];team=evidence['team']
        if str(athlete.get('id'))!=row['athlete_id'] or results.resolve_player([dict(athlete=athlete)],p['name_en']) is None:
            raise ValueError('選手本人が一致しません')
        if str(team['id'])!=row['team_id'] or club_id(team.get('displayName') or team.get('name'))!=club_id(CLUBS.get(p['club'],p['club'])):
            raise ValueError('所属クラブが一致しません')
        if values(evidence['statistics'])!=row['values'] or not row['values']:raise ValueError('今季の数字が元の応答と一致しません')
        if 'appearances' not in row['values'] and (p['position']=='GK' or 'goals' not in row['values']):
            raise ValueError('表示に使う出場数・得点がありません')
    return sheet


def attach(data,sheet):
    import soccer_national as n
    roster=n.read(ROOT/'data/soccer_national_squad.json')
    validate(sheet,roster,data['as_of'])
    result=copy.deepcopy(data);lookup={p['name']:p for p in sheet['players']}
    result['national_numbers']=copy.deepcopy(sheet)
    for p in result['players']:p['season_numbers']=copy.deepcopy(lookup.get(p['name']))
    return result


def check_attached(data):
    if 'national_numbers' not in data:
        if any(p.get('season_numbers') is not None for p in data['players']):
            raise ValueError('今季の数字の出典材料がありません')
        return
    import soccer_national as n
    validate(data['national_numbers'],n.read(ROOT/'data/soccer_national_squad.json'),data['as_of'])
    expected={p['name']:p for p in data['national_numbers']['players']}
    if any(p.get('season_numbers')!=expected.get(p['name']) for p in data['players']):
        raise ValueError('札の数字と取得した数字が一致しません')


def metric(player):
    row=player.get('season_numbers')
    if not row:return None
    counts=row['values']
    if player['position']!='GK' and counts.get('goals',0)>0:return 'goals',counts['goals'],'得点'
    if 'appearances' in counts:return 'appearances',counts['appearances'],'試合出場'
    if player['position']!='GK' and 'goals' in counts:return 'goals',counts['goals'],'得点'
    return None


def featured(data):
    pool=[p for p in data['players'] if metric(p)]
    return max(pool,key=rank) if pool else None


def rank(player):
    item=metric(player)
    return (item[0]=='goals' and item[1]>0,item[1]) if item else (False,-1)


def stat_line(player):
    row=player.get('season_numbers')
    if not row:return ''
    counts=row['values'];parts=[]
    if 'appearances' in counts:parts.append(str(counts['appearances'])+'試合')
    if player['position']!='GK' and 'goals' in counts:parts.append(str(counts['goals'])+'得点')
    return 'リーグ戦 '+'・'.join(parts) if parts else ''
