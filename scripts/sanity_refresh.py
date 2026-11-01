"""再点検専用の読み取り。原稿・共有データを書き換えず、公式材料を再取得する。"""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.request
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sanity_material as material
import sanity_sources as sources

MAX_REQUESTS = 8
TIMEOUT = 8
HOSTS = {'statsapi.mlb.com', 'api.football-data.org', 'site.api.espn.com'}


def fetch(url, headers=None):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS:
        raise ValueError('再取得先が公式APIの許可範囲外')
    request = urllib.request.Request(url, headers=dict({'User-Agent': 'collespo/sanity'}, **(headers or {})))
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def refresh(documents, materials):
    result, log, cache = copy.deepcopy(materials), [], {}
    now = datetime.now(timezone.utc)
    today = now.astimezone(material.JST).date().isoformat()

    def get(url, headers=None):
        if url not in cache:
            if len(cache) >= MAX_REQUESTS:
                raise ValueError('材料再取得の回数上限')
            cache[url] = None  # 失敗も1回として数える。同じ失敗を繰り返さない。
            cache[url] = fetch(url, headers)
        if cache[url] is None:
            raise ValueError('この取得は失敗済み')
        return cache[url]

    for doc in documents:
        key, day = sources.key(doc), material.document_day(doc)
        text = '。'.join(s.get('text') or '' for s in doc.get('segments') or [])
        # 別日の順位や所属を昔の原稿の材料に置き換えない。
        if day != today:
            log.append(dict(document_key=key, status='対象日外・保存材料を維持', date_jst=day))
            continue
        rows = sources.for_document(doc, result)
        fresh = []

        def attempt(category, url, build, headers=None):
            try:
                source = build(get(url, headers))
                if not sources.usable(source):
                    raise ValueError('対象材料が空')
                source.update(document_key=key, date_jst=day, used_for_date=day,
                              retrieved_at=now.isoformat(), source_url=url, refresh_category=category)
                fresh.append(source)
                log.append(dict(document_key=key, category=category, source_url=url,
                                status='再取得', retrieved_at=now.isoformat()))
            except Exception as error:
                log.append(dict(document_key=key, category=category, source_url=url,
                                status='取得失敗・保存材料を維持', error_type=type(error).__name__))

        if any(s.get('series') for s in rows) or any(w in text for w in ('シリーズ', 'WS')):
            import ps_series
            start, end = day[:4]+'-09-01', day[:4]+'-12-01'
            url = (f'{ps_series.API}/schedule?sportId=1&season={day[:4]}&startDate={start}'
                   f'&endDate={end}&gameType=F,D,L,W&hydrate=team')
            attempt('PS', url, lambda data: dict(source='refresh.PS', series=ps_series.build(
                [g for d in data.get('dates') or [] for g in d.get('games') or []])))
        codes = {c['code'] for s in rows for c in s.get('competitions') or [] if c.get('code')}
        # 材料不足のhighでも、指摘人物から取得すべき大会と名簿を特定する。
        import notability_engine as ne
        codes.update(p['league'] for p in ne.JP_PLAYERS_SOCCER
                     if p.get('league') and p.get('name_jp') and p['name_jp'] in text)
        codes.update(code for code, name in ne.SOCCER_COMPETITIONS.items()
                     if any(g.get('league') in (code, name) for s in rows for g in s.get('games') or []))
        token = os.environ.get('FOOTBALL_DATA_API_KEY', '')
        for code in sorted(codes):
            if not token:
                log.append(dict(document_key=key, category='順位表・名簿', code=code, status='キーなし'))
                continue
            headers = {'X-Auth-Token': token}
            old = next((c for s in rows for c in s.get('competitions') or [] if c.get('code') == code),
                       dict(code=code, jp=[dict(name=p['name_jp'], club_jp=p.get('team_jp'))
                           for p in ne.JP_PLAYERS_SOCCER if p.get('league') == code
                           and p.get('name_jp') and p['name_jp'] in text]))

            def table(data, old=old):
                import soccer_preview
                import soccer_race
                import soccer_sanity_material as soccer
                table_rows = soccer_preview._table_rows(data)
                if not table_rows:
                    raise ValueError('順位表が空')
                players = [dict(name=r['name'], club_jp=r['club_jp'],
                    match=soccer_race._norm(r['club_jp'])) for r in old.get('jp') or []
                    if r.get('name') and r.get('club_jp')]
                # 順位再取得で所属を推測しない。名簿は別の公式応答で確認する。
                jp = soccer_race.jp_in_table(table_rows, players, code,
                                            max((r.get('played') or 0 for r in table_rows), default=0))
                games = []
                leader = max((r.get('points') or 0 for r in table_rows), default=0)
                for source in rows:
                    for original in source.get('games') or []:
                        if (original.get('league') not in (code, ne.SOCCER_COMPETITIONS.get(code))
                                or original.get('final_score') or isinstance(original.get('score'), dict)):
                            continue  # 終了試合の当時の順位を現在の表へ置換しない。
                        game = copy.deepcopy(original)
                        for side in ('home', 'away'):
                            name = original.get(side+'_team_name')
                            match = next((r for r in table_rows if set(soccer.aliases(name or '')) &
                                set(soccer.aliases(ne.club_name_jp(r.get('team') or '')))), None)
                            if match:
                                game[side+'_standing'] = dict(game.get(side+'_standing') or {},
                                    rank=match.get('position'), points=match.get('points'),
                                    points_back=leader-match['points'] if match.get('points') is not None else None)
                        games.append(game)
                return dict(source='refresh.table', sport='soccer', games=games, competitions=[dict(
                    old, table=table_rows, jp=jp)])
            attempt('順位表', f'https://api.football-data.org/v4/competitions/{code}/standings', table, headers)

            def roster(data, code=code, old=old):
                import notability_engine as ne
                identities = {p.get('name_en'): p.get('name_jp') for p in ne.JP_PLAYERS_SOCCER}
                found = []
                for team in data.get('teams') or []:
                    for player in team.get('squad') or []:
                        name = identities.get(player.get('name'))
                        if name and name in text:
                            found.append(dict(name=name, club_jp=ne.club_name_jp(team['name'])))
                if not found:
                    raise ValueError('指摘選手の名簿が未取得')
                return dict(source='refresh.roster', sport='soccer', competitions=[dict(code=code, jp=found)])
            attempt('名簿', f'https://api.football-data.org/v4/competitions/{code}/teams', roster, headers)
        for source in rows:
            players = source.get('players') or (source.get('game_material') or {}).get('players') or []
            if isinstance(players, dict):
                players = list(players.values())
            for player in players:
                ident = player.get('id') or player.get('player_id') or (player.get('_row') or {}).get('id')
                name = player.get('name_jp') or player.get('name')
                if name and name in text and source.get('sport') != 'soccer':
                    def roster_mlb(data, player=player):
                        from notability_engine import MLB_TEAM_NAME_JP
                        candidates = data.get('people') or []
                        person = next((p for p in candidates if str(p.get('id')) == str(ident)), None) if ident else next(
                            (p for p in candidates if p.get('fullName') == english), None)
                        if person is None:
                            raise ValueError('名簿の本人ID・氏名を確認できず')
                        team = person['currentTeam']
                        return dict(source='refresh.roster', sport='baseball', players=[dict(
                            player, team_name=MLB_TEAM_NAME_JP.get(str(team['id']), team['name']))])
                    english = player.get('name_en') or next((p['name_en'] for p in ne.JP_PLAYERS_MLB
                        if name in (p.get('name_jp'), p.get('name_en'))), player.get('name'))
                    if ident:
                        url = f'https://statsapi.mlb.com/api/v1/people/{ident}?hydrate=currentTeam'
                    elif english and english.isascii():
                        url = 'https://statsapi.mlb.com/api/v1/people/search?names='+quote(english)+'&hydrate=currentTeam'
                    else:
                        log.append(dict(document_key=key, category='名簿', status='本人ID・原綴り不足'))
                        continue
                    attempt('名簿', url, roster_mlb)
            for game in source.get('games') or []:
                ident = game.get('gamePk') or game.get('id') or game.get('game_id')
                if not ident:
                    continue
                if source.get('sport') == 'soccer':
                    if not game.get('id') and game.get('game_id'):
                        # football-dataの試合IDとESPNのevent IDは別物。
                        if not token:
                            log.append(dict(document_key=key, category='試合結果', status='キーなし'))
                            continue
                        def score_football(data, game=game):
                            score = (data.get('score') or {}).get('fullTime') or {}
                            if any(score.get(s) is None for s in ('home', 'away')):
                                raise ValueError('未終了の試合結果は未確定')
                            return dict(source='refresh.result', sport='soccer', games=[dict(game,
                                final_score=score, score=score)])
                        attempt('試合結果', f'https://api.football-data.org/v4/matches/{ident}',
                                score_football, {'X-Auth-Token': token})
                        continue
                    slug = game.get('espn') or game.get('league_slug')
                    if not slug:
                        import soccer_results
                        code = game.get('league_code') or game.get('code') or game.get('league')
                        code = next((c for c, n in ne.SOCCER_COMPETITIONS.items() if n == code), code)
                        slug = soccer_results.LEAGUES.get(code)
                    if not slug:
                        continue
                    def score_espn(data, game=game):
                        comp = data['header']['competitions'][0]
                        sides = {c['homeAway']: c for c in comp['competitors']}
                        score = {s: int(sides[s]['score']) for s in ('home', 'away')}
                        return dict(source='refresh.result', sport='soccer', games=[dict(game, final_score=score, score=score)])
                    url = f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={ident}'
                    attempt('試合結果', url, score_espn)
                else:
                    def score_mlb(data, game=game):
                        g = data['dates'][0]['games'][0]
                        sides = g['teams']
                        return dict(source='refresh.result', sport='baseball', games=[dict(game,
                            final_score={s: sides[s]['score'] for s in ('home', 'away')},
                            date_jst=datetime.fromisoformat(g['gameDate'].replace('Z', '+00:00')).astimezone(
                                material.JST).date().isoformat())])
                    attempt('試合結果', f'https://statsapi.mlb.com/api/v1/schedule?gamePk={ident}', score_mlb)
        if not any(r.get('document_key') == key for r in log):
            log.append(dict(document_key=key, status='取得先を特定できず・保存材料を維持'))
        # 新しい同種材料が成功した範囲だけ置換。別原稿・過去の試合材料は残す。
        for new in fresh:
            for old in result:
                if old.get('document_key') != key:
                    continue
                if new.get('series'):
                    old.pop('series', None)
                for nc in new.get('competitions') or []:
                    for oc in old.get('competitions') or []:
                        if nc.get('code') == oc.get('code'):
                            if new['refresh_category'] == '順位表':
                                oc.update(copy.deepcopy(nc))
                            else:
                                for nr in nc.get('jp') or []:
                                    for row in oc.get('jp') or []:
                                        if row.get('name') == nr.get('name'):
                                            if row.get('club_jp') != nr.get('club_jp'):
                                                # 移籍先の順位へ移籍前の数字を持ち越さない。
                                                row.update(position=None, points=None, lines=[])
                                            row.update(nr)
                for field in ('players', 'games'):
                    if not isinstance(old.get(field), list):
                        continue
                    for row in old[field]:
                        for nr in new.get(field) or []:
                            if (field == 'games' and new['refresh_category'] == '順位表'
                                    and row.get('home_team_name') and row.get('away_team_name')
                                    and all(row.get(s+'_team_name') == nr.get(s+'_team_name') for s in ('home', 'away'))):
                                for side in ('home', 'away'):
                                    if nr.get(side+'_standing'):
                                        row[side+'_standing'] = copy.deepcopy(nr[side+'_standing'])
                                continue
                            if ((row.get('id') and row.get('id') == nr.get('id')) or
                                    (field == 'players' and row.get('name') == nr.get('name')) or
                            (field == 'games' and any(row.get(k) and row.get(k) == nr.get(k)
                                                     for k in ('gamePk', 'game_id')))):
                                row.update(nr)
            result.append(new)
    return result, log
