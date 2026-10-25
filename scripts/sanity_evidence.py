"""明示された主語・試合・日付だけを材料と照合。部分一致から事実を推測しない。"""
import re


def review(text, materials, why=None, day=None):
    values = []
    for source in materials or []:
        players = list(source.get('players') or []) if not isinstance(source.get('players'), dict) else source['players']
        if isinstance(players, dict):
            players = list(players.values())
        players += (source.get('game_material') or {}).get('players') or []
        for row in players:
            name = row.get('name_jp') or row.get('name')
            team = row.get('team_name') or row.get('team_jp')
            if name and team:
                for m in re.finditer(re.escape(name)+r'は([^。、\n]+?)(?:所属|の投手|の選手)(?:です|だ)?', text):
                    # 「に所属」「今季も所属」、過去・否定をクラブ名の違いと誤読しない。
                    if (re.search(r'昨季|昨年|以前|かつて|元', text[:m.end()])
                            or re.match(r'った|でした|では|じゃ', text[m.end():])):
                        continue
                    claimed = re.sub(r'^(?:(?:今季|現在|いま|今|すでに|既に)(?:は|も)?)', '', m[1])
                    claimed = re.sub(r'(?:に|へ)$', '', claimed)
                    from team_names import team_names_jp
                    values.append(team_names_jp(claimed) == team_names_jp(team))
        for series in source.get('series') or []:
            names = [r.get('name') for r in series.get('teams') or []]
            if len(names) != 2 or not all(names):
                continue
            pair = '(?:'+re.escape(names[0]+'対'+names[1])+'|'+re.escape(names[1]+'対'+names[0])+')'
            nxt = series.get('next') or {}
            pattern = r'(?:(\d+)月(\d+)日の)?'+pair+r'は'+re.escape(series.get('round_jp') or '')+r'第(\d+)戦(?:です|だ)?[。]?'
            claim = re.fullmatch(pattern, text.strip())
            if claim:
                values.append(int(claim[3]) == nxt['game'] if nxt.get('game') is not None else None)
                if nxt.get('day'):
                    if claim[1]:
                        values.append(f'{int(claim[1])}月{int(claim[2])}日' == nxt['day'])
                    elif day:
                        values.append(f'{int(day[5:7])}月{int(day[8:10])}日' == nxt['day'])
                    else:
                        values.append(None)
                else:
                    values.append(None)
        games = source.get('games') or []
        for game in games:
            names = [game.get(s+'_team_name') or (game.get(s) or {}).get('name_jp')
                     for s in ('home', 'away')]
            score = game.get('final_score') or game.get('score') or {}
            if not all(names) or not isinstance(score, dict):
                continue
            # 週次の同じカードの別試合を混ぜない。原稿の各日の段落に合わせる。
            pair_days = {g.get('date_jst') for g in games
                         if {g.get('home_team_name'), g.get('away_team_name')} == set(names)
                         and g.get('date_jst')}
            if len(pair_days) > 1 and game.get('date_jst') != day:
                continue
            for a, b, sa, sb in ((names[0], names[1], 'home', 'away'),
                                 (names[1], names[0], 'away', 'home')):
                expected = (score.get(sa), score.get(sb))
                if None not in expected:
                    for m in re.finditer(re.escape(a+'対'+b)+r'は(\d+)対(\d+)', text):
                        values.append(tuple(map(int, m.groups())) == tuple(map(int, expected)))
                    for m in re.finditer(re.escape(a+'は'+b+'に')+r'(\d+)対(\d+)で(勝|敗|負)', text):
                        values.append(tuple(map(int, m.groups()[:2])) == tuple(map(int, expected))
                                      and ((int(expected[0]) > int(expected[1])) == (m[3] == '勝')))
                when = game.get('date_jst')
                if when:
                    for m in re.finditer(r'(\d+)月(\d+)日の'+re.escape(a+'対'+b), text):
                        values.append(f'{int(m[1]):02d}-{int(m[2]):02d}' == when[5:10])
    if False in values:
        return False
    if why is not None and re.search(r'所属|試合番号|第\d+戦|スコア|得点|日付|勝敗', why):
        return True if values and all(values) else None
    return None
