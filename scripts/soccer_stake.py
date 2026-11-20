"""欧州の注目試合を「この一戦で何が懸かっているか」で1本にする（本人 11/19「注目試合は根本なので形を変えて残す」）。

一覧の「今夜の注目試合｜A vs B ほか」は直近4週で大半が1〜10回だった。勝点の差を題に出した回（467回）が最も伸びた。
そこで1本1試合にし、題の先頭と冒頭の札で「勝点の差・順位の線」を言い、順位・直近の調子・日本人選手・開始時刻の順に答える。
数字はすべて保存済みの材料（football-data の順位表と終わった試合、ESPN の日程、Premier League 公式の選手成績）から計算する。
「勝てば◯位」は他の試合の結果で変わるので言わない。言うのは今の順位・勝点・差だけ。
"""
import argparse
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cutline
import short_common
import soccer_national as national
from soccer_national_topics import METAN, ZUNDA, Unavailable

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = 'soccer_stake'
VIDEO = 'collespo_national_topic.mp4'
JST = timezone(timedelta(hours=9))
LEAGUES = ('PL', 'PD', 'SA', 'BL1', 'FL1')
NEAR = 3          # 線や相手との勝点差がこの数以下なら「懸かっている」と言う
FORM = 5          # 直近の試合数
SEC_PER_CHAR = 51.33 / 345
BUDGET = 42       # 描画は45秒で止まるので、見込みで余裕を持たせる
CREDIT_MEDIA = {'football-data': 'football-data.org', 'espn': 'ESPN', 'fpl': 'プレミア公式'}
ESPN_SLUG = {'PL': 'eng.1', 'PD': 'esp.1', 'BL1': 'ger.1', 'SA': 'ita.1', 'FL1': 'fra.1'}
ESPN_STANDINGS = 'https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings'
LEDGER = ROOT / 'data/soccer_stake_published.json'


def club_jp(team_en):
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from notability_engine import club_name_jp
    return club_name_jp(team_en)


def club_short(team_en):
    import club_display_names
    return club_display_names.display(team_en, short=True) or club_jp(team_en)


def finished(comp):
    rows = ((comp.get('preview_angle_context') or {}).get('finished') or {}).get('payload', {}).get('matches') or []
    return sorted((m for m in rows if m.get('status') == 'FINISHED'), key=lambda m: m['utcDate'])


def form(comp, team):
    """リーグ戦の直近 FORM 試合（古い順）。W/D/L と相手・スコア。"""
    out = []
    for m in finished(comp):
        home = m['homeTeam']['name'] == team
        if not home and m['awayTeam']['name'] != team:
            continue
        s = m['score']['fullTime']
        if s.get('home') is None or s.get('away') is None:
            continue
        gf, ga = (s['home'], s['away']) if home else (s['away'], s['home'])
        out.append(dict(result='W' if gf > ga else 'L' if gf < ga else 'D', gf=gf, ga=ga, date=m['utcDate']))
    return out[-FORM:]


def record(rows):
    w = sum(r['result'] == 'W' for r in rows)
    d = sum(r['result'] == 'D' for r in rows)
    return f"{w}勝{d}分{len(rows) - w - d}敗"


def streak(rows):
    """末尾から同じ結果が続く数と種類。"""
    if not rows:
        return 0, None
    last = rows[-1]['result']
    n = 0
    for r in reversed(rows):
        if r['result'] != last:
            break
        n += 1
    return n, last


def streak_words(name, rows):
    n, kind = streak(rows)
    if n < 3:
        return ''
    if n == len(rows) and kind != 'D':
        return f"{name}は直近{n}試合すべて{'勝ち' if kind == 'W' else '負け'}です。"
    return f"{name}は{n}{'連勝' if kind == 'W' else '連敗' if kind == 'L' else '試合続けて引き分け'}中です。"


def lines(code, clubs):
    """（境目の順位, 名前, 上側か）。残留は「その順位まで残留」。"""
    out = []
    for at, label in cutline.lines_for(code):
        if label == '残留':
            out.append((min(at, clubs), '降格圏', False))
        else:
            out.append((at, label, True))
    return out


def line_relation(table, code, row):
    """一番近い境目との勝点差。NEAR より遠ければ None。"""
    best = None
    by_pos = {r['position']: r for r in table}
    for at, label, upper in lines(code, len(table)):
        inside = row['position'] <= at
        if upper:
            if inside:
                other = by_pos.get(at + 1)
                if not other:
                    continue
                gap = row['points'] - other['points']
                words = f"{label}の{at}位以内にいて、" + (f"{at + 1}位と勝点が同じ" if gap == 0 else f"{at + 1}位との差は勝点{gap}")
                short = f"{label}を守れるか {at + 1}位と勝点{gap}差"
            else:
                other = by_pos[at]
                gap = other['points'] - row['points']
                words = f"{label}の{at}位まで勝点{gap}"
                short = f"{label}まで勝点{gap}"
        else:
            if inside:
                other = by_pos.get(at + 1)
                if not other:
                    continue
                gap = row['points'] - other['points']
                words = f"、{label}の{at + 1}位との差が勝点{gap}"
                short = f"降格圏まで勝点{gap}"
            else:
                other = by_pos[at]
                gap = other['points'] - row['points']
                words = f"{label}にいて、{at}位まで勝点{gap}"
                short = f"残留圏まで勝点{gap}"
        if gap <= NEAR and (best is None or gap < best['gap']):
            best = dict(gap=gap, label=label, words=words, short=short, at=at, inside=inside, upper=upper,
                        vs=other['position'])
    return best


def available_players(game, side):
    """出場できる日本人（欠場の印が付いた選手は出さない）。成績は Premier League 公式だけ。"""
    stats = {p['name']: p for p in game.get('season_players') or [] if p.get('scope') == 'season'}
    names = []
    for name in (game.get('jp_by_side') or {}).get(side) or []:
        row = stats.get(name)
        if row and row.get('out'):
            continue
        names.append(dict(name=name, stats=row if row and game.get('competition_code') == 'PL' else None))
    return names


def stake(game, comp):
    """この試合で懸かっている物。無ければ None。"""
    code = game.get('competition_code')
    if code not in LEAGUES:
        return None
    table = comp.get('table') or []
    by_team = {r['team']: r for r in table}
    home, away = by_team.get(game['home_team_name']), by_team.get(game['away_team_name'])
    if not home or not away or not table:
        return None
    clubs = len(table)
    gap = abs(home['points'] - away['points'])
    jp = dict(home=available_players(game, 'home'), away=available_players(game, 'away'))
    relation = dict(home=line_relation(table, code, home), away=line_relation(table, code, away))
    lines_of = lines(code, clubs)
    relegation = next((at for at, label, upper in lines_of if not upper), clubs)
    europe = max((at for at, label, upper in lines_of if upper), default=0)
    kind = None
    if gap <= NEAR and home['position'] > relegation - NEAR and away['position'] > relegation - NEAR:
        kind = '残留争い'
    elif gap <= NEAR and home['position'] <= europe + NEAR and away['position'] <= europe + NEAR:
        kind = '上位争い'
    elif gap <= 1:
        kind = '順位の近い直接対決'
    elif relation['home'] or relation['away']:
        kind = '境目'
    if not kind:
        return None
    jp_sides = sum(bool(jp[s]) for s in ('home', 'away'))
    # 選ぶ順：日本人の多さ、懸かり方の強さ（差が小さいほど上）。
    score = jp_sides * 10 + (3 if kind in ('残留争い', '上位争い') else 2 if kind == '順位の近い直接対決' else 1) * 2 - gap
    return dict(kind=kind, gap=gap, home=home, away=away, jp=jp, relation=relation, score=score,
                relegation=relegation, europe=europe, clubs=clubs)


def kickoff(game):
    at = datetime.fromisoformat(game['start_time_utc'].replace('Z', '+00:00')).astimezone(JST)
    return at


def speech_time(at):
    return f"日本時間の{at.month}月{at.day}日{at.hour}時" + (f"{at.minute}分" if at.minute else '')


def screen_time(at):
    return f"{at.month}/{at.day} {at.hour}:{at.minute:02d}"


def jp_title(names, club):
    return (names[0]['name'] + 'の' + club) if names else club


def build(game, comp, *, as_of):
    s = stake(game, comp)
    if not s:
        raise Unavailable('懸かっている物が言えない試合')
    H, A = s['home'], s['away']
    hn, an = club_jp(H['team']), club_jp(A['team'])
    hs, as_ = club_short(H['team']), club_short(A['team'])
    at = kickoff(game)
    league = comp.get('name_jp') or game.get('league')
    gap = s['gap']
    # 題：先頭は懸かっている物（Neon 11/19「スマホでは後ろが切れる」）、続けて日本人とクラブ。
    who = f"{jp_title(s['jp']['home'], hs)}対{jp_title(s['jp']['away'], as_)}"
    pair = f"{H['position']}位と{A['position']}位"
    kind_word = '直接対決' if s['kind'] == '順位の近い直接対決' else s['kind']
    if gap == 0:
        title = f"{pair}が勝点{H['points']}で並ぶ{kind_word} {who}"
    else:
        title = f"{kind_word}は{pair}で勝点{gap}差 {who}" if s['kind'] in ('残留争い', '上位争い') else             f"{pair}が勝点{gap}差の{kind_word} {who}"
    mine = rel = None
    if s['kind'] == '境目':
        # 相手との差ではなく、境目との差が懸かっている物。日本人のいる側を先に見る。
        side = next((x for x in ('home', 'away') if s['jp'][x] and s['relation'][x]), None) or             next(x for x in ('home', 'away') if s['relation'][x])
        mine = H if side == 'home' else A
        rel = s['relation'][side]
        own = jp_title(s['jp'][side], club_short(mine['team']))
        title = f"{rel['short']} {own}が{club_short((A if side == 'home' else H)['team'])}戦"
    # 冒頭の札：日本人どうしなら選手名、続けて勝点の差（Neon 11/19「日本人対決が札に無い」）。
    hp, ap = s['jp']['home'], s['jp']['away']
    if hp and ap:
        score = f"{hp[0]['name']} 対 {ap[0]['name']}"
    elif hp or ap:
        score = f"{(hp or ap)[0]['name']}の{hs if hp else as_}"
    else:
        score = f"{hs} 対 {as_}"
    hook = dict(score=score, result=kind_word if s['kind'] != '境目' else rel['label'],
                subject=f"{hs}と{as_}の勝点", big=str(gap), unit='差')
    if gap == 0:
        hook.update(subject=f"{hs}と{as_}は勝点", big=str(H['points']), unit='で並ぶ')
    if s['kind'] == '境目':
        hook.update(subject=f"{mine['position']}位{club_short(mine['team'])}は{rel['short'].rsplit('勝点', 1)[0]}勝点",
                    big=str(rel['gap']), unit='')
    if s['kind'] == '残留争い':
        hook['note'] = f"{pair}　{s['relegation'] + 1}位から下が降格圏"
    elif s['kind'] == '上位争い':
        hook['note'] = f"{pair}　{s['europe']}位までが欧州の大会の出場圏"
    else:
        hook['note'] = pair if s['kind'] != '境目' else league
    panels = []
    # 1. 何が懸かっているか。勝点の差は1回だけ言い、「勝てばどうなるか」を2クラブの間だけで言う。
    if hp and ap:
        ask0 = f"{hp[0]['name']}と{ap[0]['name']}の対戦は、何が懸かっているのだ？"
    elif hp or ap:
        ask0 = f"{(hp or ap)[0]['name']}の{hn if hp else an}の試合は、何が懸かっているのだ？"
    else:
        ask0 = f"{hn}対{an}は、何が懸かっているのだ？"
    first = f"{H['position']}位の{hn}と、{A['position']}位の{an}の{kind_word if s['kind'] != '境目' else '対戦'}です。"
    upper, lower = (H, A) if H['position'] < A['position'] else (A, H)
    # 2回目からは短い名前（パレス・ソシエダ）。45秒に収め、聞き取りやすくする。
    un, ln = club_short(upper['team']), club_short(lower['team'])
    if gap == 0:
        first += f"勝点は{H['points']}で並び、勝った方が勝点で上に立ちます。"
    elif gap <= 2:
        first += f"勝点の差は{gap}で、{ln}が勝てば勝点で{un}を上回ります。"
    elif gap == 3:
        first += f"勝点の差は{gap}で、{ln}が勝てば勝点で並びます。"
    else:
        first += f"勝点の差は{gap}です。"
    said = {}
    for side, name, other in (('home', hs, A), ('away', as_, H)):
        r = s['relation'][side]
        # 境目が相手の順位そのもので差も同じなら、いま言った勝点差の言い直しなので省く。
        if r and not (r['vs'] == other['position'] and r['gap'] == gap):
            said.setdefault(r['words'], []).append(name)
    for words, names in said.items():
        first += f"{'2クラブとも' if len(names) == 2 else names[0]}は{words}です。".replace('2クラブともは', '2クラブとも、')
    compare = [['順位', f"{H['position']}位", f"{A['position']}位"], ['勝点', str(H['points']), str(A['points'])],
               ['得点', str(H['gf']), str(A['gf'])], ['失点', str(H['ga']), str(A['ga'])]]
    panels.append((ask0, first, '順位と勝点',
                   [], dict(compare=dict(teams=[hs, as_], rows=compare),
                            big=dict(label='勝点差', value=hook['big'], unit=''))))
    # 2. 日本人選手（Neon 11/19「一番の注目点が3番目では遅い」）
    people = [(p, name) for side, name in (('home', hn), ('away', an)) for p in s['jp'][side]]
    if people:
        said, rows = [], []
        for p, club in people:
            st = p['stats']
            if st:
                # 「0得点2アシスト」と言わない。どちらも0なら出場時間だけ。
                parts = ([f"{st['goals']}得点"] if st['goals'] else []) + ([f"{st['assists']}アシスト"] if st['assists'] else [])
                said.append(f"{p['name']}は今季{st['minutes']}分の出場で{''.join(parts)}です。" if parts
                            else f"{p['name']}は今季{st['minutes']}分に出場しています。")
                rows.append((f"{p['name']}　{club_short_from_jp(club, H, A)}",
                             f"{''.join(parts)}　{st['minutes']}分" if parts else f"{st['minutes']}分出場"))
            else:
                said.append(f"{club_short_from_jp(club, H, A)}には{p['name']}がいます。")
                rows.append((p['name'], club_short_from_jp(club, H, A)))
        panels.append(('日本人選手は、どうなのだ？', ''.join(said), '日本人選手', rows, {}))
    # 3. 直近の調子（連勝・連敗と、失点の多さまで言う）
    fh, fa = form(comp, H['team']), form(comp, A['team'])
    if len(fh) == FORM and len(fa) == FORM:
        text = f"直近{FORM}試合は、{hs}が{record(fh)}、{as_}が{record(fa)}です。"
        text += streak_words(hs, fh) + streak_words(as_, fa)
        gh, ga_ = sum(r['ga'] for r in fh), sum(r['ga'] for r in fa)
        if max(gh, ga_) >= 2 * FORM and max(gh, ga_) - min(gh, ga_) >= 3:
            worse = hs if gh > ga_ else as_
            text += f"{worse}はこの{FORM}試合で{max(gh, ga_)}失点です。"
            # 「パレスは4連敗中です。パレスはこの5試合で…」を1文につなぐ。
            text = re.sub(re.escape(worse) + r"は(\d+連[勝敗]中)です。" + re.escape(worse) + "は",
                          lambda m: f"{worse}は{m.group(1)}で、", text)
        # 比べる表は数字の字で描くので、1つの欄に数字は1つ（「2勝0分3敗」は欠字で止まる）。
        count = lambda rows, mark: sum(r['result'] == mark for r in rows)
        rows = [['勝ち', f"{count(fh, 'W')}勝", f"{count(fa, 'W')}勝"],
                ['負け', f"{count(fh, 'L')}敗", f"{count(fa, 'L')}敗"],
                ['失点', str(gh), str(ga_)]]
        panels.append(('最近の調子は、どうなのだ？', text, f'直近{FORM}試合', [], dict(compare=dict(teams=[hs, as_], rows=rows))))
    # 4. 開始時刻（締めは淡々と。結果は試合後にまとめる）
    panels.append(('試合は、いつなのだ？', f"{speech_time(at)}に始まります。", '試合開始',
                   [('日本時間', screen_time(at)), ('大会', league)], {}))
    # 長いときは、上の帯に出ている開始時刻の区間から省く（帯は全編に「大会　月/日 時:分」が出る）。
    outro = 14  # 「高評価と登録、お願いします。」
    while sum(len(q) + len(a_) for q, a_, *_ in panels) + outro > BUDGET / SEC_PER_CHAR and len(panels) > 2:
        panels.pop()
    segments = []
    sub = f"{league}　{screen_time(at)}"
    for i, (question, answer, head, rows, extra) in enumerate(panels):
        meta = dict(duo=True, topic='stake', panel=i, head=head, rows=rows, sub=sub, **extra)
        ask = dict(meta, duo_ask=True, who='ずんだもん')
        if i == 0:
            ask['hook'] = hook
        segments += [dict(kind='list', text=question, speaker=ZUNDA, meta=ask),
                     dict(kind='list', text=answer, speaker=METAN, meta=dict(meta, who='四国めたん'))]
    sources = ['football-data', 'espn'] + (['fpl'] if any(p['stats'] for p, _ in people) else [])
    clubs = {name: dict(team_en=team, name_jp=name, abbr=name[:3], primary=None, secondary=None, league=league)
             for team in (H['team'], A['team']) for name in {club_jp(team), club_short(team)}}
    doc = dict(program=PROGRAM, date_jst=as_of.astimezone(JST).date().isoformat(), title=title + ' #Shorts', topic='stake',
               topic_key=f"stake:{game.get('espn_event_id') or game['game_id']}", event_id=str(game.get('espn_event_id') or game['game_id']),
               source_url='https://www.espn.com/soccer/match/_/gameId/' + str(game.get('espn_event_id') or ''),
               screen_title=league, clubs=clubs,
               credit='音声: VOICEVOX:ずんだもん・四国めたん　出典: ' + '・'.join(CREDIT_MEDIA[k] for k in sources),
               segments=segments, stake=dict(kind=s['kind'], gap=gap, home=H, away=A, relation=s['relation']),
               form=dict(home=fh, away=fa), game=copy.deepcopy(game), duration_budget=dict(limit=45, grace=0),
               sanity_materials=[dict(source='football-data 順位表・試合結果 / ESPN 日程', sport='soccer',
                                      facts=dict(table=comp.get('table'), game=game))])
    doc = short_common.prepare(doc)
    seconds = estimate_seconds(doc)
    if seconds > BUDGET:
        raise ValueError(f'原稿が長すぎます（見込み{seconds:.1f}秒、上限{BUDGET}秒）')
    return doc


def espn_table(code, fetch=None):
    """ESPN の順位表（2つ目の出どころ）。[(英語名, 順位, 勝点)]。"""
    if fetch is None:
        import urllib.request
        def fetch(url):
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode('utf8'))
    data = fetch(ESPN_STANDINGS.format(slug=ESPN_SLUG[code]))
    standings = ((data.get('children') or [data])[0]).get('standings') or {}
    rows = []
    for entry in standings.get('entries') or []:
        stats = {x['name']: x.get('value') for x in entry.get('stats') or []}
        rows.append((entry['team']['displayName'], int(stats['rank']), int(stats['points'])))
    return rows


def crosscheck(doc, fetch=None):
    """題と冒頭に出す2クラブの順位・勝点を ESPN の順位表と照らす。違えば止める。"""
    import club_display_names as names
    code = doc['game']['competition_code']
    rows = espn_table(code, fetch)
    ident = lambda name: (names.lookup(name) or {}).get('id')
    checked = {}
    for side in ('home', 'away'):
        mine = doc['stake'][side]
        found = [r for r in rows if ident(r[0]) and ident(r[0]) == ident(mine['team'])]
        if len(found) != 1:
            raise ValueError(f"ESPN の順位表で {mine['team']} を1つに決められません")
        team, rank, points = found[0]
        if (rank, points) != (mine['position'], mine['points']):
            raise ValueError(f"順位表が出どころで違います: {mine['team']} football-data {mine['position']}位{mine['points']} / ESPN {rank}位{points}")
        checked[side] = dict(team=team, position=rank, points=points)
    return dict(source='ESPN 順位表', url=ESPN_STANDINGS.format(slug=ESPN_SLUG[code]), clubs=checked)


def metadata(doc):
    said = '\n'.join(s['text'] for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro')
    sources = ['出典:', '順位・勝点・直近の結果: football-data.org', '順位・勝点の照合: ESPN 順位表',
               '試合の日程: ESPN 試合ページ', doc['source_url']]
    if 'プレミア公式' in doc.get('credit', ''):
        sources.append('日本人選手の今季成績: Premier League 公式')
    league = doc.get('screen_title') or ''
    description = (said + '\n\n' + '\n'.join(sources) + '\n\n役に立ったら高評価・チャンネル登録をお願いします。'
                   '\n音声: VOICEVOX:ずんだもん・四国めたん\n#欧州サッカー #' + league + ' #Shorts')
    return dict(snippet=dict(title=doc['title'], description=description,
                             tags=['サッカー', '欧州サッカー', league, '日本人選手', 'コレスポ'], categoryId='17',
                             defaultLanguage='ja', defaultAudioLanguage='ja'))


def validate_upload(args, now=None):
    import os
    doc = national.read(args.narration)
    if doc.get('program') != PROGRAM:
        raise ValueError('注目試合の原稿ではありません')
    if os.getenv('COLLESPO_STAKE_PUBLISH') != 'true':
        raise ValueError('注目試合（懸かっている物）の公開は COLLESPO_STAKE_PUBLISH=true の時だけです')
    if national.read(args.games).get('game') != doc['game']:
        raise ValueError('原稿と材料が不一致')
    check = doc.get('crosscheck') or {}
    if check.get('source') != 'ESPN 順位表' or any(check['clubs'][s]['position'] != doc['stake'][s]['position'] or
                                                 check['clubs'][s]['points'] != doc['stake'][s]['points'] for s in ('home', 'away')):
        raise ValueError('順位表を2つ目の出どころで照らしていません')
    if doc['event_id'] in national.read(LEDGER):
        raise ValueError('同じ試合の注目試合は予約・投稿済みです')
    if not args.publish_at:
        raise ValueError('未来の予約時刻が必要です')
    at = national.instant(args.publish_at)
    now = now or datetime.now(timezone.utc)
    if not (now < at < datetime.fromisoformat(doc['game']['start_time_utc'].replace('Z', '+00:00')) - timedelta(minutes=45)):
        raise ValueError('予約は今より後、試合開始45分前より前にしてください')
    import short_content
    report = short_content.validate_upload(args.video)
    if report['actual_seconds'] > 45:
        raise ValueError('注目試合は45秒までです')
    if not (Path(args.narration).parent / 'audio/voice_manifest.json').exists() and not (Path(args.video).parent / 'voice_manifest.json').exists():
        raise ValueError('実音声の記録がありません')


def record_published(doc, video_id, publish_at):
    """公開台帳と、翌朝の結果ショートへ渡す前提の記録。"""
    import soccer_stake_followup
    ledger = national.read(LEDGER)
    ledger[doc['event_id']] = dict(video_id=video_id, publish_at=national.instant(publish_at).astimezone(JST).isoformat(),
                                   title=doc['title'], date_jst=national.instant(publish_at).astimezone(JST).date().isoformat())
    national.save(LEDGER, ledger)
    soccer_stake_followup.save(doc, video_id, doc['as_of'])


def published_today(day, path=LEDGER):
    """この日（JST）に注目試合を予約・公開したか。今の「今夜の注目試合」を出さない合図。"""
    path = Path(path)
    return path.exists() and any(v.get('date_jst') == day for v in json.loads(path.read_text(encoding='utf8')).values())


def information(doc):
    """公開前の関門（short_content）用。読んで画面にも出す事実だけを、出どころつきで数える。"""
    found = []
    said = ''.join(seg['text'] for seg in doc['segments'])
    stake = doc['stake']
    for side in ('home', 'away'):
        row = stake[side]
        if f"{row['position']}位" in said:
            found.append(dict(subject=row['team'], fact='順位と勝点', value=[row['position'], row['points']],
                              source='football-data.org 順位表', segments=[1]))
        rows = (doc.get('form') or {}).get(side) or []
        if len(rows) == FORM and record(rows) in said:
            found.append(dict(subject=row['team'], fact=f'直近{FORM}試合', value=record(rows),
                              source='football-data.org 試合結果', segments=[]))
    for seg in doc['segments']:
        for label, line in (seg.get('meta') or {}).get('rows') or []:
            name = label.split('　')[0]
            if seg['speaker'] == METAN and name in seg['text'] and re.search(r'\d+分$', line):
                found.append(dict(subject=name, fact='今季のリーグ戦成績', value=line,
                                  source='プレミアリーグ公式', segments=[]))
    game = doc.get('game') or {}
    if game.get('start_time_utc'):
        found.append(dict(subject=doc['event_id'], fact='開始予定', value=game['start_time_utc'],
                          source='ESPN 日程', segments=[]))
    return found


def estimate_seconds(doc):
    """11/19 の見本（345字・9区間で51.3秒）から、1字0.149秒で見積もる。描画は45秒で止まる。"""
    return round(sum(len(seg['text']) for seg in doc['segments']) * SEC_PER_CHAR, 1)


def club_short_from_jp(club_jp_name, H, A):
    for row in (H, A):
        if club_jp(row['team']) == club_jp_name:
            return club_short(row['team'])
    return club_jp_name


def candidates(games, preview, *, start, end):
    comps = {c['code']: c for c in preview.get('competitions') or []}
    out = []
    for g in games.get('games') or []:
        comp = comps.get(g.get('competition_code'))
        if not comp:
            continue
        at = kickoff(g)
        if not (start <= at < end):
            continue
        s = stake(g, comp)
        if s:
            out.append((s['score'], g, comp, s))
    return sorted(out, key=lambda x: (-x[0], x[1]['start_time_utc']))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--games', type=Path, default=ROOT / 'data/soccer_games.json')
    ap.add_argument('--preview', type=Path, default=ROOT / 'data/soccer_preview.json')
    ap.add_argument('--event', help='ESPN の event id。無ければ候補の1位')
    ap.add_argument('--hours', type=float, default=72, help='今からこの時間内に始まる試合')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--no-crosscheck', action='store_true', help='通信なしの試し用（公開の検査で止まる）')
    ap.add_argument('--min-lead', type=float, default=0, help='開始まで最低この分数ある試合だけ（予約が開始45分前までに収まるように）')
    ap.add_argument('--require-jp', action='store_true', help='日本人選手のいる試合だけ（定時の公開用）')
    ap.add_argument('--github-output', type=Path, help='found=true/false を書く。対象が無い日は止めずに false')
    ap.add_argument('--out', type=Path, default=ROOT / 'build/soccer_stake')
    ap.add_argument('--published-today', action='store_true', help='今日（JST）注目試合を予約・公開済みなら終了コード0')
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    if args.published_today:
        raise SystemExit(0 if published_today(now.astimezone(JST).date().isoformat()) else 1)
    games, preview = national.read(args.games), national.read(args.preview)
    rows = candidates(games, preview, start=(now + timedelta(minutes=args.min_lead)).astimezone(JST),
                      end=(now + timedelta(hours=args.hours)).astimezone(JST))
    if args.require_jp:
        rows = [r for r in rows if r[3]['jp']['home'] or r[3]['jp']['away']]
    listing = [dict(score=sc, event=g.get('espn_event_id'), kickoff=g['start_time_jst'], league=g.get('league'),
                    match=f"{club_jp(s['home']['team'])} 対 {club_jp(s['away']['team'])}", kind=s['kind'], gap=s['gap'])
               for sc, g, comp, s in rows]
    if args.list:
        print(json.dumps(listing, ensure_ascii=False, indent=1))
        return
    pick = next(((g, comp) for _, g, comp, _ in rows if not args.event or str(g.get('espn_event_id')) == str(args.event)), None)
    if not pick:
        if args.github_output:
            # 懸かっている物のある試合が無い日は、今の「今夜の注目試合」に任せる。
            with args.github_output.open('a', encoding='utf8') as out:
                out.write('found=false\n')
            print('対象の試合がありません')
            return
        raise Unavailable('対象の試合がありません')
    doc = build(*pick, as_of=now)
    doc['as_of'] = now.isoformat()
    if not args.no_crosscheck:
        doc['crosscheck'] = crosscheck(doc)
    args.out.mkdir(parents=True, exist_ok=True)
    national.save(args.out / 'narration.json', doc)
    national.save(args.out / 'material.json', dict(game=pick[0], candidates=listing))
    print(doc['title'])
    if args.github_output:
        with args.github_output.open('a', encoding='utf8') as out:
            out.write('found=true\n')


if __name__ == '__main__':
    main()
