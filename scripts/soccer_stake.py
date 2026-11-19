"""欧州の注目試合を「この一戦で何が懸かっているか」で1本にする（本人 11/19「注目試合は根本なので形を変えて残す」）。

一覧の「今夜の注目試合｜A vs B ほか」は直近4週で大半が1〜10回だった。勝点の差を題に出した回（467回）が最も伸びた。
そこで1本1試合にし、題の先頭と冒頭の札で「勝点の差・順位の線」を言い、順位・直近の調子・日本人選手・開始時刻の順に答える。
数字はすべて保存済みの材料（football-data の順位表と終わった試合、ESPN の日程、Premier League 公式の選手成績）から計算する。
「勝てば◯位」は他の試合の結果で変わるので言わない。言うのは今の順位・勝点・差だけ。
"""
import argparse
import copy
import json
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
CREDIT_MEDIA = {'football-data': 'football-data.org', 'espn': 'ESPN', 'fpl': 'プレミアリーグ公式'}


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
                words = f"{label}の{at}位以内にいて、{at + 1}位との差は勝点{gap}"
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
            best = dict(gap=gap, label=label, words=words, short=short, at=at, inside=inside, upper=upper)
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
                subject=f"{H['position']}位{hs}と{A['position']}位{as_}の勝点", big=str(gap), unit='差')
    if gap == 0:
        hook.update(subject=f"{H['position']}位{hs}と{A['position']}位{as_}は勝点", big=str(H['points']), unit='で並ぶ')
    if s['kind'] == '境目':
        hook.update(subject=f"{mine['position']}位{club_short(mine['team'])}は{rel['short'].rsplit('勝点', 1)[0]}勝点",
                    big=str(rel['gap']), unit='')
    if s['kind'] == '残留争い':
        hook['note'] = f"{s['relegation'] + 1}位から下が降格圏"
    elif s['kind'] == '上位争い':
        hook['note'] = f"{s['europe']}位までが欧州の大会の出場圏"
    else:
        hook['note'] = league
    panels = []
    # 1. 何が懸かっているか。勝点の差は1回だけ言い、「勝てばどうなるか」を2クラブの間だけで言う。
    if hp and ap:
        ask0 = f"{hp[0]['name']}と{ap[0]['name']}の対戦は、何が懸かっているのだ？"
    elif hp or ap:
        ask0 = f"{(hp or ap)[0]['name']}の{hn if hp else an}の試合は、何が懸かっているのだ？"
    else:
        ask0 = f"{hn}対{an}は、何が懸かっているのだ？"
    first = f"{league}で{H['position']}位の{hn}と、{A['position']}位の{an}の{kind_word if s['kind'] != '境目' else '対戦'}です。"
    upper, lower = (H, A) if H['position'] < A['position'] else (A, H)
    un, ln = club_jp(upper['team']), club_jp(lower['team'])
    if gap == 0:
        first += f"勝点は{H['points']}で並び、勝った方が勝点で上に立ちます。"
    elif gap <= 2:
        first += f"勝点の差は{gap}で、{ln}が勝てば勝点で{un}を上回ります。"
    elif gap == 3:
        first += f"勝点の差は{gap}で、{ln}が勝てば勝点で並びます。"
    else:
        first += f"勝点の差は{gap}です。"
    for side, name in (('home', hn), ('away', an)):
        r = s['relation'][side]
        if r:
            first += f"{name}は{r['words']}です。"
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
                parts = [f"{st['goals']}得点"] + ([f"{st['assists']}アシスト"] if st['assists'] else [])
                said.append(f"{club}の{p['name']}は、今季のリーグ戦で{st['minutes']}分に出て{''.join(parts)}です。")
                rows.append((p['name'], f"{club_short_from_jp(club, H, A)}　{'・'.join(parts)}　{st['minutes']}分出場"))
            else:
                said.append(f"{club}には{p['name']}がいます。")
                rows.append((p['name'], club_short_from_jp(club, H, A)))
        panels.append(('日本人選手は、どうなのだ？', ''.join(said), '日本人選手', rows, {}))
    # 3. 直近の調子（連勝・連敗と、失点の多さまで言う）
    fh, fa = form(comp, H['team']), form(comp, A['team'])
    if len(fh) == FORM and len(fa) == FORM:
        text = f"リーグ戦の直近{FORM}試合は、{hn}が{record(fh)}、{an}が{record(fa)}です。"
        text += streak_words(hn, fh) + streak_words(an, fa)
        gh, ga_ = sum(r['ga'] for r in fh), sum(r['ga'] for r in fa)
        if max(gh, ga_) >= 2 * FORM and max(gh, ga_) - min(gh, ga_) >= 3:
            worse = hn if gh > ga_ else an
            text += f"この{FORM}試合で{worse}は{max(gh, ga_)}失点しています。"
        rows = [[f'直近{FORM}試合', record(fh), record(fa)],
                ['得点', str(sum(r['gf'] for r in fh)), str(sum(r['gf'] for r in fa))],
                ['失点', str(gh), str(ga_)]]
        panels.append(('最近の調子は、どうなのだ？', text, f'直近{FORM}試合', [], dict(compare=dict(teams=[hs, as_], rows=rows))))
    # 4. 開始時刻（締めは淡々と。結果は試合後にまとめる）
    panels.append(('試合は、いつなのだ？', f"{speech_time(at)}に始まります。結果は試合後にまとめます。", '試合開始',
                   [('日本時間', screen_time(at)), ('大会', league)], {}))
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
    return short_common.prepare(doc)


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
    ap.add_argument('--out', type=Path, default=ROOT / 'build/soccer_stake')
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    games, preview = national.read(args.games), national.read(args.preview)
    rows = candidates(games, preview, start=now.astimezone(JST), end=(now + timedelta(hours=args.hours)).astimezone(JST))
    listing = [dict(score=sc, event=g.get('espn_event_id'), kickoff=g['start_time_jst'], league=g.get('league'),
                    match=f"{club_jp(s['home']['team'])} 対 {club_jp(s['away']['team'])}", kind=s['kind'], gap=s['gap'])
               for sc, g, comp, s in rows]
    if args.list:
        print(json.dumps(listing, ensure_ascii=False, indent=1))
        return
    pick = next(((g, comp) for _, g, comp, _ in rows if not args.event or str(g.get('espn_event_id')) == str(args.event)), None)
    if not pick:
        raise Unavailable('対象の試合がありません')
    doc = build(*pick, as_of=now)
    args.out.mkdir(parents=True, exist_ok=True)
    national.save(args.out / 'narration.json', doc)
    national.save(args.out / 'material.json', dict(game=pick[0], candidates=listing))
    print(doc['title'])


if __name__ == '__main__':
    main()
