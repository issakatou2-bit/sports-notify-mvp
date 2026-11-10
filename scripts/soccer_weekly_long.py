"""欧州日本人の週まとめ。既存の日次取得と確定文だけを使う（生成APIなし）。"""
import argparse
import copy
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import soccer_results as results

ROOT = Path(__file__).resolve().parents[1]
JST = results.JST
SWITCH = 'COLLESPO_SOCCER_WEEKLY_LONG'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def week_window(monday):
    monday = date.fromisoformat(str(monday))
    if monday.weekday() != 0:
        raise ValueError('週キーは月曜日です')
    end = datetime.combine(monday, time(9), JST)
    return end-timedelta(days=7), end


def current_week(now=None):
    now = (now or datetime.now(JST)).astimezone(JST)
    monday = now.date()-timedelta(days=now.weekday())
    if now < datetime.combine(monday, time(9), JST):
        monday -= timedelta(days=7)
    return monday.isoformat()


def nightly_days(monday):
    start, end = week_window(monday)
    # 日次は7:15締め。開始日の夜から、終了日の7:15〜9:00を含む夜まで。
    return [(start.date()+timedelta(days=i)).isoformat() for i in range(8)]


def collect(monday, directory, runner=None):
    """取得は既存CLI（内部でsoccer_results.build）へ一任。失敗は空週と扱わない。"""
    runner = runner or subprocess.run
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    nights = []
    for day in nightly_days(monday):
        path = directory/f'results_{day}.json'
        runner([sys.executable, str(ROOT/'scripts/soccer_results.py'), '--date', day,
                '--out', str(path)], check=True)
        nightly = load(path)
        results.validate_data(nightly)
        nights.append(nightly)
    return nights


def identity(club):
    import club_display_names as clubs
    return (clubs.lookup(club) or {}).get('id')


def club_label(value):
    import club_display_names as clubs
    label = clubs.display(value) if clubs.lookup(value) else results.ne.club_name_jp(value)
    if (re.search(r'[A-Za-z]', label) and not re.search(r'[一-龯ぁ-んァ-ヶ]', label)
            and label not in latin_display_names()):
        raise ValueError('英字のクラブ名が残っています: '+label)
    return label


def display_names():
    import club_display_names as clubs
    names = set(results.ne.SOCCER_CLUB_NAME_JP.values())
    for row in clubs.rows():
        names.update(row.get(key) or '' for key in ('display', 'short', 'legacy', 'current'))
    return {n for n in names if n}


def latin_display_names():
    # 表示名の表に英字だけで載せた名前（PSV・AZ・NEC・PSG・QPR）は、日本の報道でもこの形。
    # 表に無い英字だけを止める（11/9 15時の週の長編が「PSV」で止まった）。
    return {n for n in display_names()
            if re.search(r'[A-Za-z]', n) and not re.search(r'[一-龯ぁ-んァ-ヶ]', n)}


def known_japanese_names():
    # 表示名の表にある日本語の名前（マンチェスターU、ボルシアMG、ハンブルガーSV等）は、
    # 英字を含んでも正しい。略号を1つずつ許すと、表に足した名前のたびに止まる（11/3「U」で停止）。
    names = display_names()
    return sorted((n for n in names if re.search(r'[ァ-ヶ]', n) and re.search(r'[A-Za-z]', n)), key=len, reverse=True)


def check_public_names(text):
    for name in known_japanese_names():
        text = text.replace(name, '')
    for name in sorted(latin_display_names(), key=len, reverse=True):
        text = re.sub(r'(?<![A-Za-z])'+re.escape(name)+r'(?![A-Za-z])', '', text)
    # リーグ名・大会の略号（セリエA、CL等）は保つ。
    allowed = {'A', 'B', 'C', 'CL', 'EL'}
    unknown = sorted({m[0] for m in re.finditer(r'[A-Za-z]+', text) if m[0] not in allowed})
    if unknown:
        raise ValueError('英字のクラブ名が残っています: '+'、'.join(unknown))


def injury_notes(payload, end):
    if not payload:
        return {}
    try:
        updated = results.utc(payload['updated_at'])
    except (ValueError, KeyError, TypeError):
        return {}
    if not end-timedelta(days=2) <= updated <= end+timedelta(days=2):
        return {}
    if payload.get('source') != 'https://fantasy.premierleague.com/api/bootstrap-static/':
        return {}
    months = dict(zip('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), range(1, 13)))
    notes = {}
    for name, row in payload.get('players', {}).items():
        news = row.get('news') or ''
        if row.get('out') is not True or not re.search(r'\binjury\b', news, re.I):
            continue
        note = 'けがで離脱中'
        match = re.search(r'\bExpected back (\d{1,2}) ('+'|'.join(months)+r')\s*$', news)
        if match:
            day, month = int(match[1]), months[match[2]]
            try:
                date(end.year+(month < end.month), month, day)
            except ValueError:
                pass
            else:
                note += f'、{month}月{day}日に復帰見込み'
        notes[name] = dict(name=name, name_en=row.get('name_en'), club=club_label(row['club_jp']), note=note)
    return notes


def fetch_context(games):
    """順位と次戦も既存の取得部品で。取得できた項目だけ返す。"""
    import soccer_result_context as context
    previews = [dict(home=g['home']['name_en'], away=g['away']['name_en'],
                     competition_code=g['league']) for g in games]
    # カップだけ出たクラブのリーグ順位・次戦も取得する。
    for code in results.LEAGUES:
        if previews:
            previews.append(dict(previews[0], competition_code=code))
    today = (datetime.now(JST).date()-timedelta(days=1)).isoformat()
    tables, upcoming = {}, []
    # CL等と国内リーグに同じクラブがいても、カップの順位で上書きしない。
    for code in sorted({g['competition_code'] for g in previews}):
        preview = dict(games=[g for g in previews if g['competition_code'] == code])
        _, table, matches = context.after_context(dict(date_jst=today), preview)
        tables.update({k: row for k, row in table.items() if row.get('competition') in results.LEAGUES})
        upcoming.extend(matches)
    return dict(tables=tables, upcoming=upcoming,
                as_of=datetime.now(timezone.utc).isoformat())


def aggregate(nights, monday, context=None, availability=None):
    start, end = week_window(monday)
    seen = {}
    for night in nights:
        for game in night['games']:
            if not start <= results.utc(game['finished_utc']).astimezone(JST) < end:
                continue
            key = str(game['id'])
            if key in seen:
                # 同じ試合の内容が変わった場合は黙って片方を採らない。
                fields = ('score', 'players', 'home', 'away', 'finished_utc')
                if any(seen[key].get(k) != game.get(k) for k in fields):
                    raise ValueError('重複試合の材料が不一致: '+key)
                continue
            seen[key] = copy.deepcopy(game)
    games = sorted(seen.values(), key=lambda g: (g['start_utc'], str(g['id'])))
    people = {}
    for g in games:
        for p in g['players']:
            if p['event_id'] != g['id'] or p['status'] not in results.STATUS:
                raise ValueError('選手の試合・出場区分が不正')
            who = p.get('name_en') or p['name']
            person = people.setdefault(who, dict(name=p['name'], name_en=p.get('name_en'), matches=[]))
            side = p['side']
            other = 'away' if side == 'home' else 'home'
            gf, ga = g['score'][side], g['score'][other]
            person['matches'].append(dict(
                event_id=g['id'], date=results.utc(g['finished_utc']).astimezone(JST).date().isoformat(),
                finished_utc=g['finished_utc'], competition=g['league_jp'], competition_code=g['league'],
                club=club_label(p['club']), opponent=club_label(g[other]['name_jp']), home=side == 'home',
                gf=gf, ga=ga, result='勝ち' if gf > ga else '負け' if gf < ga else '引き分け',
                status=p['status'], minutes=p.get('minutes'), minutes_approx=bool(p.get('minutes_approx')),
                **{k: p.get(k) for k in ('goals', 'assists', 'yellow_cards', 'red_cards', 'shots', 'on_target', 'saves')}))
    context = copy.deepcopy(context or {})
    availability = copy.deepcopy(availability or {})
    injuries = injury_notes(availability, end)
    for row in injuries.values():
        if not any(p['name'] == row['name'] for p in people.values()):
            people[row.get('name_en') or row['name']] = dict(name=row['name'], name_en=row.get('name_en'),
                                                           club=row['club'], matches=[], availability_only=True)
    for p in people.values():
        if p['matches']:
            p['club'] = p['matches'][-1]['club']
        p['appeared'] = any(m['status'] != 'none' for m in p['matches'])
        p['goals'] = sum(m['goals'] or 0 for m in p['matches'])
        p['assists'] = sum(m['assists'] or 0 for m in p['matches'])
        injury = injuries.get(p['name'])
        if not p['appeared'] and injury and identity(injury['club']) == identity(p['club']):
            p['injury_note'] = injury['note']
        club_id = identity(p['club'])
        rank = context.get('tables', {}).get(club_id)
        if rank and rank.get('competition') in results.LEAGUES:
            p['standing'] = rank
        choices = []
        for nxt in context.get('upcoming', []):
            threshold = max(end, results.utc(context['as_of'])) if context.get('as_of') else end
            if results.utc(nxt['start_utc']) < threshold:
                continue
            if club_id and club_id in (identity(nxt['home']), identity(nxt['away'])):
                choices.append(nxt)
        if choices:
            nxt = min(choices, key=lambda n: results.utc(n['start_utc']))
            opponent = nxt['away'] if identity(nxt['home']) == club_id else nxt['home']
            p['next'] = dict(date=results.utc(nxt['start_utc']).astimezone(JST).date().isoformat(),
                             opponent=club_label(opponent), source=nxt['source'])
    def order(p):
        tier = 0 if p['goals'] or p['assists'] else 1 if any(m['status'] == 'starter' for m in p['matches']) else 2 if p['appeared'] else 3
        return tier, -p['goals'], -p['assists'], p['name']
    players = sorted(people.values(), key=order)
    count = sum(p['appeared'] for p in players)
    return dict(schema_version=1, kind='soccer_weekly', key=str(monday),
                start=start.isoformat(), end=end.isoformat(), games=games, context=context, availability=availability,
                players=players, can_make=count >= 3,
                reason='' if count >= 3 else f'出場を確認できた日本人選手が{count}人で、3人未満のため作りません。',
                supplied_nights=sorted(n['date_jst'] for n in nights))


def period(data):
    days = sorted({results.utc(g['finished_utc']).astimezone(JST).date() for g in data['games'] if g['players']})
    if not days:
        return ''
    return f'{days[0].month}/{days[0].day}〜{days[-1].month}/{days[-1].day}'


def headline(data):
    for p in data['players']:
        if p['goals'] or p['assists']:
            bits = [f"{p[k]}{unit}" for k, unit in (('goals', '得点'), ('assists', 'アシスト')) if p[k]]
            return p['name']+'が'+'・'.join(bits)
    return ''


def title(data):
    lead = headline(data)
    text = '【欧州サッカー】'+(lead+'｜' if lead else '')+f'日本人選手の1週間（{period(data)}）'
    check_public_names(text)
    return text


def appearance(m):
    text = results.STATUS[m['status']]
    if m['status'] != 'none' and m.get('minutes') is not None:
        text += '、'+('約' if m.get('minutes_approx') else '')+str(m['minutes'])+'分出場'
    if m['status'] == 'none':
        return text
    for key, unit in (('goals', '得点'), ('assists', 'アシスト')):
        if m.get(key):
            text += f'、{m[key]}{unit}'
    for key, label in (('yellow_cards', '警告'), ('red_cards', '退場')):
        if m.get(key):
            text += f'、{label}{m[key]}回'
    # 追加の統計は材料の正の値から1つだけ。GKはセーブ、攻撃は枠内を優先。
    for key, label in (('saves', 'セーブ'), ('on_target', '枠内シュート'), ('shots', 'シュート')):
        if m.get(key):
            # 「セーブ4本」とは言わない。GKは「4セーブ」。
            text += f'、{m[key]}セーブ' if key == 'saves' else f'、{label}{m[key]}本'
            break
    return text


def day_label(day):
    d = date.fromisoformat(day)
    return f'{d.month}月{d.day}日'


LEAGUE_ORDER = ('PL', 'PD', 'BL1', 'SA', 'FL1', 'cups')
LEAGUE_HEAD = dict(results.LEAGUE_NAMES, cups='カップ戦')


def game_players(data, game):
    people = []
    for person in data['players']:
        for match in person['matches']:
            if match['event_id'] == game['id']:
                people.append(dict(name=person['name'], **match,
                                   **{k: person[k] for k in ('standing', 'next') if person.get(k)}))
    return sorted(people, key=lambda p: (0 if p.get('goals') or p.get('assists') else
                  1 if p['status'] == 'starter' else 2 if p['status'] == 'substitute' else 3, p['name']))


def game_line(game):
    ended = results.utc(game['finished_utc']).astimezone(JST).date().isoformat()
    return (f"{day_label(ended)} {game['league_jp']} / {club_label(game['home']['name_jp'])} "
            f"{game['score']['home']}-{game['score']['away']} {club_label(game['away']['name_jp'])}")


def sections(data):
    games = [g for g in data['games'] if any(p['status'] != 'none' for p in g['players'])]
    featured = [g for g in games if any(p.get('goals') or p.get('assists') for p in g['players'])]
    featured.sort(key=lambda g: (-sum(p.get('goals') or 0 for p in g['players']),
                                -sum(p.get('assists') or 0 for p in g['players']), g['finished_utc']))
    shown = {g['id'] for g in featured}
    output = [('results', '今週の結果', featured)] if featured else []
    for league in LEAGUE_ORDER:
        rows = [g for g in games if g['id'] not in shown and
                (g['league'] == league if league != 'cups' else g['league'] not in results.LEAGUES)]
        rows.sort(key=lambda g: (0 if any(p['status'] == 'starter' for p in g['players']) else 1,
                                 g['finished_utc'], str(g['id'])))
        # 得点試合だけのリーグも、所属リーグと先頭への移動を明示する札を置く。
        featured_here = any(g['league'] == league if league != 'cups' else g['league'] not in results.LEAGUES for g in featured)
        if rows or featured_here:
            output.append((league, LEAGUE_HEAD[league], rows))
    return output


def absent_players(data):
    return [p for p in data['players'] if not p['appeared']]


def absent_line(p):
    info = p.get('injury_note') or '出場なし'
    days = '、'.join(dict.fromkeys(day_label(m['date']) for m in p['matches']))
    if p.get('injury_note'):
        detail = info.removeprefix('けがで離脱中').lstrip('、')
        if p.get('availability_only'):
            detail += '（今週の出場記録なし）'
        return p['name']+' / '+p['club']+' / けがで離脱中'+ ('\n'+detail if detail else '')
    if p.get('availability_only'):
        info += '（今週の出場記録なし）'
    return p['name']+' / '+p['club']+' / '+(days+' / ' if days else '')+info


def description(data, youtube_chapters=None):
    lines = [title(data), '対象：日本時間の月曜9時で区切っています。',
             '欧州5大リーグと登録済みの大会の日本人選手が対象です。', '']
    if youtube_chapters:
        lines += youtube_chapters+['']
    for _, heading, games in sections(data):
        if not games:
            continue
        lines.append(heading)
        for game in games:
            lines.append('・'+game_line(game))
            for p in game_players(data, game):
                lines.append('  '+p['name']+'（'+p['club']+'）：'+appearance(p))
    absent = absent_players(data)
    if absent:
        lines += ['', '出場なし・離脱中']+[absent_line(p) for p in absent]
    lines += ['', '出典：ESPN（終了実時刻・出場区分・個人成績）、football-data.org（取得できたスコアの照合・現在のリーグ順位・次戦）。',
              'https://www.espn.com/soccer/ / https://www.football-data.org/',
              '未取得の順位・予定・出場分は表示しません。「約」の付く出場分は交代記録による概算です。',
              'クラブの勝敗と選手本人の成績は区別しています。順位・予定は取得時点の情報です。']
    if any(p.get('injury_note') for p in absent):
        lines += ['離脱情報：プレミアリーグ公式FPL（保存情報の更新日時：'+data['availability']['updated_at']+'）。',
                  'https://fantasy.premierleague.com/api/bootstrap-static/']
    lines += ['音声：VOICEVOX ずんだもん / 四国めたん', '#欧州サッカー #日本人選手']
    return '\n'.join(lines)


def dialogue(data):
    if not data['can_make']:
        return dict(segments=[], panels={}, soccer_weekly_material=data)
    import review_render_v3
    panels, segments = {}, []
    groups = sections(data)
    chapters = [dict(id='opening', title='冒頭')]+[dict(id=key, title=head) for key, head, _ in groups]
    chapters += [dict(id='absent', title='出場なし・離脱中')]
    def card(key, heading, rows, section, atomic=()):
        panels[key] = dict(type='soccer_weekly', heading=heading, rows=rows, atomic=list(dict.fromkeys(atomic)))
        return key, section
    def say(who, text, ref, **extra):
        segments.append(dict(kind='talk', speaker=who, text=text, panel=ref[0], chapter=ref[1],
                             meta=dict(who='ずんだもん' if who == 3 else 'めたん'), **extra))
    def call(kind):
        # generate_dialogue.pyの冒頭/締めと同じ、二人同時の番組名。
        return [dict(kind=kind, text='コレスポ', speaker=who, panel=None, meta=dict(who=name))
                for who, name in ((3, 'ずんだもん'), (2, 'めたん'))]
    opening = card('opening', '欧州サッカー 日本人選手の1週間',
                   [headline(data) or '今週の出場記録', period(data)+'（終了日・日本時間）', '月曜9:00から翌月曜9:00に終了'], 'opening')
    say(3, (headline(data)+'なのだ。' if headline(data) else '日本人選手の1週間を振り返るのだ。'), opening)
    first, last = period(data).split('〜')
    first_month, first_day = first.split('/')
    last_month, last_day = last.split('/')
    say(2, f"{first_month}月{first_day}日から{last_month}月{last_day}日に終わった試合です。日本時間の月曜朝9時で区切り、リーグごとに振り返ります。", opening)
    introductions = ('{day}の{league}は、{home}対{away}なのだ。',
                     '続いては{home}対{away}。{day}の{league}なのだ。',
                     '{league}から、{day}に終わった{home}対{away}なのだ。')
    game_index = 0
    told = set()
    def context(p):
        # 順位と次戦は、そのクラブが最初に出てくる試合で1文だけ添える。
        # 最後に一覧で読むと20クラブ・22行の羅列になり、同じ試合が両側から2回出た（11/3 実データ）。
        # 「A 対 B」と書くとホーム・アウェーに読めるので、次戦は「Bと対戦」とだけ言う。
        if p['club'] in told:
            return None
        told.add(p['club'])
        parts = []
        rank, n = p.get('standing'), p.get('next')
        if rank:
            parts.append(f"いま{results.LEAGUE_NAMES[rank['competition']]}{rank['rank']}位")
        if n:
            parts.append(f"次は{day_label(n['date'])}に{n['opponent']}と対戦します")
        if not parts:
            return None
        if not n:
            parts[-1] += 'です'
        return p['club']+'は'+'、'.join(parts)+'。'
    for section, heading, games in groups:
        ref = card('league_'+section, heading, [f'{len(games)}試合の出場記録' if games else '得点・アシストの記録は冒頭の「今週の結果」で紹介'], section)
        say(3, ('今週の得点とアシストの記録からなのだ。' if section == 'results' else heading+'の結果なのだ。'), ref)
        for game in games:
            people = game_players(data, game)
            home, away = club_label(game['home']['name_jp']), club_label(game['away']['name_jp'])
            ended = results.utc(game['finished_utc']).astimezone(JST).date().isoformat()
            rows = [f"{day_label(ended)} {game['league_jp']} / {game['score']['home']}-{game['score']['away']}（ホーム-アウェー）"]
            rows += [p['name']+' / '+p['club']+' / '+appearance(p) for p in people]
            notes = [c for c in (context(p) for p in people) if c]
            rows += [c.rstrip('。') for c in notes]
            ref = card('game_'+str(game['id']), home+' 対 '+away, rows, section,
                       atomic=[home, away]+[p['name'] for p in people]+[p['club'] for p in people]
                       +[p['next']['opponent'] for p in people if p.get('next')])
            text = introductions[game_index % len(introductions)].format(day=day_label(ended), league=game['league_jp'], home=home, away=away)
            game_index += 1
            say(3, text, ref, event_id=game['id'])
            a, b = game['score']['home'], game['score']['away']
            result = f'{home}が{a}対{b}で勝ちました。' if a > b else f'{away}が{b}対{a}で勝ちました。' if b > a else f'{a}対{b}の引き分けでした。'
            say(2, result, ref, event_id=game['id'])
            for i, p in enumerate(people):
                who = 3 if i % 2 == 0 else 2
                say(who, p['name']+'は'+appearance(p)+('なのだ。' if who == 3 else 'でした。'), ref, event_id=game['id'])
            for note in notes:
                say(2, note, ref, event_id=game['id'])
    absent = absent_players(data)
    if absent:
        ref = card('absent', '出場なし・離脱中', [absent_line(p) for p in absent], 'absent',
                   atomic=[p['name'] for p in absent]+[p['club'] for p in absent]+['けがで離脱中', '復帰見込み'])
        say(2, '対象試合で出場のなかった選手と、公式情報で離脱中の選手の一覧です。', ref)
        for p in absent:
            if p.get('injury_note'):
                say(2, p['name']+'は'+p['injury_note']+'です。', ref)
    closing = card('closing', 'コレスポ', ['日本人選手の1週間', period(data)], 'absent')
    say(2, review_render_v3.INSEASON_OUTRO_TEXT, closing)
    public = title(data)+' '.join(s['text'] for s in segments)+' '.join(p['heading']+' '+' '.join(p['rows']) for p in panels.values())
    check_public_names(public)
    return dict(kind='soccer_weekly', label=data['key'], top='日本人選手の1週間 '+period(data),
                title=title(data), chapters=chapters, panels=panels,
                sanity_materials=[dict(source='soccer_weekly_material', sport='soccer', date_jst=data['key'],
                                       games=data['games'], players=data['players'], source_url=results.SOURCE)],
                segments=call('intro')+segments+call('outro'), soccer_weekly_material=data)


def validate_document(doc):
    """材料から全文と全札を再構成し、書換え・材料外の数字を止める。"""
    material = doc['soccer_weekly_material']
    rebuilt = aggregate([dict(date_jst=material['key'], games=material['games'])], material['key'],
                        material['context'], material.get('availability'))
    for key in ('players', 'games', 'can_make', 'start', 'end'):
        if rebuilt[key] != material[key]:
            raise ValueError('週まとめの材料が不一致: '+key)
    expected = dialogue(material)
    for key in ('title', 'panels', 'segments', 'top', 'chapters', 'label', 'sanity_materials'):
        if doc.get(key) != expected.get(key):
            raise ValueError('週まとめの確定台本と不一致: '+key)


def rendered_chapters(doc, timeline_path=None):
    """完成動画と対応が確かめられる実タイムラインだけを秒に変換する。"""
    if not timeline_path or not Path(timeline_path).is_file():
        return []
    timeline_path = Path(timeline_path)
    video = timeline_path.parent/'collespo_longform.mp4'
    if not video.is_file():
        return []
    from voice_manifest import sha256
    timeline = load(timeline_path)
    if timeline.get('video_sha256') != sha256(video):
        raise ValueError('チャプターの完成動画と時刻記録が一致しません')
    sources = {r['line_id']: r for r in timeline['source_lines']}
    for i, seg in enumerate(doc['segments'], 1):
        if sources.get(i, {}).get('text') != seg['text'] or sources[i].get('speaker') != seg['speaker']:
            raise ValueError('チャプターの音声原稿が一致しません')
    entries = ['0:00 冒頭']
    for chapter in doc['chapters']:
        if chapter['id'] == 'opening':
            continue
        ids = {i for i, seg in enumerate(doc['segments'], 1) if seg.get('chapter') == chapter['id']}
        times = [line['start'] for line in timeline['lines'] if ids.intersection(line['source_line_ids'])]
        if not times:
            continue
        second = int(min(times))
        entries.append(f"{second//60}:{second%60:02d} {chapter['title']}")
    return entries


def metadata(doc, timeline_path=None):
    validate_document(doc)
    data = doc['soccer_weekly_material']
    if not data['can_make']:
        raise ValueError(data['reason'])
    return dict(snippet=dict(title=title(data), description=description(data, rendered_chapters(doc, timeline_path)), categoryId='17',
                             tags=['欧州サッカー', '日本人選手', '週間まとめ'], defaultLanguage='ja', defaultAudioLanguage='ja'))


def validate_upload(args, now=None):
    now = (now or datetime.now(JST)).astimezone(JST)
    if os.environ.get(SWITCH) != 'on':
        raise ValueError('週まとめ長尺の公開変数が無効です')
    doc = load(args.narration)
    validate_document(doc)
    data = load(args.games)
    if data != doc['soccer_weekly_material'] or not data['can_make']:
        raise ValueError('投稿用の材料と台本が一致しません')
    if args.force:
        raise ValueError('週まとめ長尺は週キーでの二重投稿を許可しません')
    if data['key'] != now.date().isoformat() or args.video_date != data['key']:
        raise ValueError('投稿は対象の月曜日に限ります')
    if now < week_window(data['key'])[1]:
        raise ValueError('月曜9時の締め前は投稿しません')
    if args.publish_at != '20:30' or now >= datetime.combine(now.date(), time(20, 29), JST):
        raise ValueError('月曜20:30の予約に間に合わないため投稿しません')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--monday')
    ap.add_argument('--results-dir', type=Path, help='保存済みの日次材料だけを使用（検証用）')
    ap.add_argument('--context', type=Path, help='保存済みの順位・予定（検証用）')
    ap.add_argument('--availability', type=Path, default=ROOT/'data/soccer_availability.json')
    ap.add_argument('--out-dir', type=Path, default=ROOT/'build/soccer_weekly')
    args = ap.parse_args()
    monday = args.monday or current_week()
    if args.results_dir:
        nights = [load(p) for p in sorted(args.results_dir.glob('results_*.json'))]
        if not nights:
            raise ValueError('保存済み材料がありません')
    else:
        nights = collect(monday, args.out_dir/'nights')
    availability = load(args.availability) if args.availability.exists() else {}
    data = aggregate(nights, monday, availability=availability)
    context = load(args.context) if args.context else {} if args.results_dir else fetch_context(data['games'])
    data = aggregate(nights, monday, context, availability)
    save(args.out_dir/'material.json', data)
    save(args.out_dir/'dialogue.json', dialogue(data))
    if data['can_make']:
        doc = dialogue(data)
        validate_document(doc)
        save(args.out_dir/'metadata.json', metadata(doc))
    print(data['reason'] or title(data))
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf8') as stream:
            stream.write(f"can_make={'true' if data['can_make'] else 'false'}\nkey={monday}\n")


if __name__ == '__main__':
    main()
