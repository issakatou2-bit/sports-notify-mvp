"""欧州カップ、MLB市場の長編と誘導ショートを保存材料から作る。"""
import argparse
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

import market_watch
import metan_tone
import phase2_shorts
import soccer_national as national
import soccer_national_topics as short
import soccer_weekly_long as weekly
import topic_dialogue
import video_visibility

ROOT = Path(__file__).resolve().parents[1]
JST = national.JST
CUP = 'soccer_cup_long'
MARKET = 'mlb_market_long'
HIGHLIGHT = phase2_shorts.HIGHLIGHT
SWITCH = {CUP: 'COLLESPO_CUP_LONG_PUBLISH', MARKET: 'COLLESPO_MARKET_LONG_PUBLISH'}
WEEKDAY = {CUP: 3, MARKET: 5}
TITLE = {CUP: 'チャンピオンズリーグ・ヨーロッパリーグの日本人選手',
         MARKET: 'MLB 移籍市場の1週間'}
LEDGER = ROOT / 'data/published_videos.json'
RECEIPTS = ROOT / 'data/scheduled_long_published.json'
MATCH_FILE = 'data/soccer_results.json'


def load(path):
    return national.read(path) if Path(path).is_file() else {}


def kickoff(day):
    return datetime.combine(day, time(20, 30), JST)


def day_words(day):
    day = date.fromisoformat(str(day)[:10])
    return f'{day.month}月{day.day}日'


def saved_matches():
    """朝の結果の保存版を読む。上書き前の結果も履歴で取得する。"""
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, encoding='utf-8')
    yield from load(ROOT / MATCH_FILE).get('games', [])
    for sha in git('log', '-16', '--format=%H', '--', MATCH_FILE).splitlines():
        yield from json.loads(git('show', sha + ':' + MATCH_FILE)).get('games', [])


def cup_material(day, games):
    zone = ZoneInfo('Europe/Paris')
    start = day - timedelta(days=2)
    picked = {}
    for game in games:
        if game.get('league') not in ('CL', 'EL') or not game.get('finished_utc'):
            continue
        first = national.instant(game['start_utc'])
        final = national.instant(game['finished_utc'])
        if not start <= first.astimezone(zone).date() <= day or final > kickoff(day):
            continue
        if not any(appearance(p) for p in game.get('players', [])):
            continue
        if set(game.get('score', {})) != {'home', 'away'}:
            continue
        picked.setdefault(str(game['id']), game)
    rows = sorted(picked.values(), key=lambda g: (g['start_utc'], g['id']))
    reason = '' if len(rows) >= 2 else '日本人選手の出場を確認できるCL・ELの保存試合が2件未満です。'
    return dict(kind=CUP, key=day.isoformat(), start=start.isoformat(), rows=rows,
                can_make=not reason, reason=reason)


def market_material(day, stage2, published, videos):
    start = day - timedelta(days=6)
    rows = {}
    for key, entry in sorted(stage2.items()):
        if not start.isoformat() <= entry['checked_on'] <= day.isoformat():
            continue
        try:
            rows['followup-' + key] = market_watch.large_followup(entry)
        except (KeyError, ValueError):
            continue
    for key, receipt in published.items():
        if not video_visibility.is_public(videos.get(key) or receipt, kickoff(day)):
            continue
        if key.removeprefix('followup-') not in short.MLB_TEAMS:
            continue
        data = short.mlb_narration(key)['followup_material']
        if start.isoformat() <= data['checked_on'] <= day.isoformat():
            rows[key] = data
    ordered = [dict(key=k, data=v) for k, v in sorted(
        rows.items(), key=lambda pair: (pair[1]['checked_on'], pair[0]))]
    reason = '' if len(rows) >= 2 else 'この7日間で確認できる段2の報道・公開済みの移籍が2件未満です。'
    return dict(kind=MARKET, key=day.isoformat(), start=start.isoformat(), rows=ordered,
                can_make=not reason, reason=reason)


def appearance(player):
    return player.get('status') in ('starter', 'subbed_in', 'substitute')


def team(game, side):
    return game[side]['name_jp']


def score(game):
    return f'{game["score"]["home"]}対{game["score"]["away"]}'


def cup_source(ident):
    return f'https://www.espn.com/soccer/match/_/gameId/{ident}'


def winner(game):
    a, b = game['score']['home'], game['score']['away']
    return '引き分けだったわ。' if a == b else team(game, 'home' if a > b else 'away') + 'が勝ったわ。'


def goal_flow(game):
    tally = dict(home=0, away=0)
    if not game.get('goals_complete'):
        return
    for goal in game['goals']:
        tally[goal['side']] += 1
        yield goal, dict(tally)


def cup_highlights(game):
    home, away = (team(game, x) for x in ('home', 'away'))
    stats = game.get('match_stats') or {}
    on = {side: (stats.get(side) or {}).get('on_target') for side in ('home', 'away')}
    if any(type(n) is not int for n in on.values()):
        return
    for goal, tally in goal_flow(game):
        if not goal.get('japanese_goal') or goal.get('own_goal'):
            continue
        player = next((p for p in game['players'] if str(p['athlete_id']) == str(goal['athlete_id'])), None)
        if not player or player.get('goals') != 1:
            continue
        side = goal['side']
        other = 'away' if side == 'home' else 'home'
        if game['score'][side] <= game['score'][other] or on[other] - on[side] < 3:
            continue
        minute = national.minute_words(goal['minute'])
        name, club = player['name'], player['club']
        lead = f'{tally["home"]}対{tally["away"]}'
        shape = ('先制点' if sum(tally.values()) == 1 else '同点ゴール' if tally['home'] == tally['away'] else '勝ち越し点')
        if shape == '勝ち越し点' and tally[goal['side']] - tally['away' if goal['side'] == 'home' else 'home'] != 1:
            continue
        later = [g for g, _ in goal_flow(game) if g['side'] == side and
                 short.Material.minute_number({'clock': {'displayValue': g['minute']}}) >
                 short.Material.minute_number({'clock': {'displayValue': goal['minute']}})]
        closing = ''
        if len(later) == 1 and game['score'][side] - game['score'][other] == 1:
            after = national.minute_words(later[0]['minute'])
            method = '相手のオウンゴールで' if later[0].get('own_goal') else ''
            closing = f'{club}はその後の{after}に、{method}勝ち越したわ。'
        yield dict(key=f'{game["id"]}-goal-{player["athlete_id"]}',
                   label='欧州サッカー', credit='ESPN', sources=[cup_source(game['id'])],
                   title=f'{name}が同点弾 {club}は枠内シュート{on[side]}対{on[other]}で勝利' if shape == '同点ゴール'
                         else f'{name}が{shape} {club}は枠内シュート{on[side]}対{on[other]}で勝利',
                   ending=(f'{name}のゴールで流れが変わったのだ。',
                           f'そうなの。{name}が{shape}を決めて、{club}が勝ち切ったわ。'),
                   panels=[
                       (topic_dialogue.pick(game['id'], f'{name}がゴールを決めたのだ！',
                                            f'{name}のゴール、見応えがあったのだ！'),
                        f'ええ、{home}と{away}の試合ね。{name}が{minute}に{shape}を決めて、{lead}になったわ。',
                        shape, [[name, minute], ['得点直後', lead]]),
                       ('そのあと、どっちが勝ったのだ？',
                        f'そうね。枠内シュートは{home}が{on["home"]}本、{away}が{on["away"]}本だったわ。'
                        f'{closing}最終スコアは{score(game)}よ。{winner(game)}',
                        '枠内シュートと試合結果', [[home, f'{on["home"]}本'], [away, f'{on["away"]}本'],
                                             ['最終スコア', score(game)]])])


def market_highlights(row):
    data = row['data']
    if not data.get('large_contract'):
        return
    data = market_watch.large_followup(data['large_contract'])
    yield dict(key=row['key'], label='MLB', credit=data['items'][0]['source_names'],
               sources=list(dict.fromkeys(url for item in data['items'] for url in item['sources'])),
               title=data['title'], ending=topic_dialogue.market_ending(data),
               panels=[(line, answer, head, [r for r in rows if r[0] != '出典'])
                       for line, answer, head, rows, _ in short.market_panels(data, row['key'])])


def highlights(data):
    builder = cup_highlights if data['kind'] == CUP else market_highlights
    return [h for row in data['rows'] for h in builder(row)][:3]


def highlight_narration(data, key, long_video_id):
    if not data['can_make'] or not re.fullmatch(r'[A-Za-z0-9_-]{11}', long_video_id):
        raise ValueError('長編または公開の動画IDが不明です')
    h = next(h for h in highlights(data) if h['key'] == key)
    if any('長編で' in line for panel in h['panels'] for line in panel[:2]):
        raise ValueError('短編の答えは本編で完結させます')
    doc = phase2_shorts.dialogue(HIGHLIGHT, f'{data["kind"]}:{data["key"]}:{key}',
                                 h['title'] + ' #Shorts', data['key'], h['label'], h['credit'], h['panels'],
                                 ending=h['ending'], source_url=h['sources'][0], source_urls=h['sources'], long_material=data,
                                 highlight_key=key, long_video_id=long_video_id)
    doc['segments'][-1]['text'] = 'ほかは長編で。'
    return short.tone_gate(doc)



def cup_story(game):
    home, away = (team(game, x) for x in ('home', 'away'))
    heading = f'{home} 対 {away}'
    start = topic_dialogue.pick(game['id'], f'{home}と{away}の対戦なのだ！',
                                'ここも日本人選手が気になる試合なのだ！',
                                '欧州カップの舞台で、日本人選手に注目なのだ！')
    sections = [([['大会', game['league_jp']], ['試合結果', score(game)]],
                [(3, start),
                 (2, f'ええ、{game["league_jp"]}の{home}と{away}ね。結果は{score(game)}よ。{winner(game)}')])]
    for p in game['players']:
        if not appearance(p):
            continue
        name, club = p['name'], p['club']
        values = ['先発' if p['status'] == 'starter' else '途中出場']
        if p.get('minutes') is not None:
            values.append(('約' if p.get('minutes_approx') else '') + str(p['minutes']) + '分出場')
        for field, unit in (('goals', '得点'), ('assists', 'アシスト'), ('saves', 'セーブ')):
            if p.get(field, 0) > 0:
                values.append(f'{p[field]}{unit}')
        turn = (f'{club}では{name}のプレーが気になるのだ。' if len(sections) == 1
                else f'{name}の出場も見ておきたいのだ。')
        response = 'そうね' if len(sections) == 1 else 'そうなの'
        sections.append(([[name, '・'.join(values)]],
                         [(3, turn),
                          (2, topic_dialogue.receive(f'{name}は' + '、'.join(values) + 'だったわ。', response))]))
    goals = list(goal_flow(game))
    for first in range(0, len(goals), 5):
        facts, lines = [], []
        if first == 0:
            lines.append((3, '試合が動いたところも見ておきたいのだ。'))
        for event, tally in goals[first:first + 5]:
            minute = national.minute_words(event['minute'])
            club = team(game, event['side'])
            progression = f'{tally["home"]}対{tally["away"]}'
            jp = next((p['name'] for p in game['players'] if str(p['athlete_id']) == str(event['athlete_id'])), '')
            if event.get('own_goal'):
                facts.append([minute, f'オウンゴールで{club}の得点・{progression}'])
                lines.append((2, f'{minute}にオウンゴールで{club}に得点が入り、{progression}になったわ。'))
            else:
                facts.append([minute, f'{jp or club}が得点・{progression}'])
                lines.append((2, f'{minute}に{jp or club}が決めて、{progression}になったわ。'))
        sections.append((facts, lines))
    stats = game.get('match_stats') or {}
    a, b = stats.get('home') or {}, stats.get('away') or {}
    if all(isinstance(side.get(k), (int, float)) for side in (a, b) for k in ('shots', 'on_target')):
        sections.append(([['シュート', f'{a["shots"]}本 対 {b["shots"]}本'],
                          ['枠内シュート', f'{a["on_target"]}本 対 {b["on_target"]}本']],
                         [(3, 'シュートの本数はどうだったのだ？'),
                          (2, f'そうね。シュートは{home}が{a["shots"]}本、{away}が{b["shots"]}本よ。'
                              f'枠内に飛んだのは順に{a["on_target"]}本と{b["on_target"]}本だったわ。')]))
    sections[-1][1].extend([(3, '出場した選手と試合の流れがつながったのだ。'),
                            (2, 'そうなの。' + winner(game))])
    return heading, sections


def market_story(row):
    data = row['data']
    sections = [(item['rows'], [(3, line), (2, answer)]) for item, (line, answer, *_) in
                zip(data['items'], short.market_panels(data, row['key']))]
    reaction, answer = topic_dialogue.market_ending(data)
    sections[-1][1].extend([(3, reaction), (2, answer)])
    return data['hook']['score'] + 'の移籍', sections


def dialogue(data):
    if not data['can_make']:
        raise ValueError(data['reason'])
    kind = data['kind']
    panels, segments = {}, []
    chapters = [dict(id='opening', title='冒頭')]
    label = TITLE[kind]
    if kind == CUP:
        atomic = sorted({team(g, side) for g in data['rows'] for side in ('home', 'away')}
                        | {p['name'] for g in data['rows'] for p in g['players']})
    else:
        atomic = sorted({name for row in data['rows'] for name in row['data'].get('readings', {})})
    period = day_words(data['start']) + '〜' + day_words(data['key'])
    def scene(key, chapter, heading, rows, lines):
        panels[key] = dict(type='soccer_weekly', heading=heading,
                           rows=[f'{name}　{value}' for name, value in rows], atomic=atomic)
        for speaker, text in lines:
            segments.append(dict(kind='talk', speaker=speaker,
                text=metan_tone.fix(text) if speaker == 2 else text, panel=key, chapter=chapter,
                meta=dict(who='四国めたん' if speaker == 2 else 'ずんだもん')))

    if kind == CUP:
        start = topic_dialogue.pick(data['key'], '欧州の大舞台で日本人選手の出番なのだ！',
                                    '欧州カップ、日本人選手のプレーが気になるのだ！',
                                    '今週も欧州カップに注目なのだ！')
        scope = '日本人選手が出場した試合'
    else:
        start = topic_dialogue.pick(data['key'], '今週も移籍市場が動いたのだ！',
                                    '移籍市場に新しいニュースが来たのだ！')
        scope = '移籍の合意や球団の発表'
    scene('opening', 'opening', label, [('対象期間', period), ('確認した件数', str(len(data['rows'])) + '件')],
          [(3, start), (2, f'ええ。{period}に確認できた{scope}を振り返るわ。')])
    for index, row in enumerate(data['rows'], 1):
        heading, sections = (cup_story if kind == CUP else market_story)(row)
        chapter = f'game_{index}'
        chapters.append(dict(id=chapter, title=heading))
        for page, (facts, lines) in enumerate(sections):
            scene(f'{chapter}_{page}', chapter, heading, facts, lines)
    return dict(kind=kind, label=data['key'], top=label, title=f'{label} {period}',
                chapters=chapters, panels=panels, segments=segments, scheduled_long_material=data,
                sanity_materials=[dict(source='保存した公式成績・確認済み報道',
                                       sport='soccer' if kind == CUP else 'mlb', facts=data)])


def validate_document(doc):
    if dialogue(doc['scheduled_long_material']) != doc:
        raise ValueError('長編の台本・数字・出典が保存材料と一致しません')
    topic_dialogue.require(doc['segments'])
    short.tone_gate(doc)


def metadata(doc, timeline_path=None):
    validate_document(doc)
    data = doc['scheduled_long_material']
    urls = ([cup_source(g['id']) for g in data['rows']] if data['kind'] == CUP else
            list(dict.fromkeys(u for row in data['rows'] for item in row['data']['items'] for u in item['sources'])))
    lines = [doc['title'], *weekly.rendered_chapters(doc, timeline_path), '出典', *urls,
             '音声: VOICEVOX:ずんだもん・四国めたん']
    return snippet(doc['title'], '\n'.join(lines))


def snippet(title, description):
    return dict(snippet=dict(title=title, description=description, categoryId='17',
                             defaultLanguage='ja', defaultAudioLanguage='ja'))


def highlight_metadata(doc):
    errors = phase2_shorts.check(doc)
    if errors:
        raise ValueError(errors[0])
    return snippet(doc['title'], '\n'.join([*doc['source_urls'], 'https://youtu.be/' + doc['long_video_id'],
                                           '音声: VOICEVOX:ずんだもん・四国めたん', '#Shorts']))


def public_parents(ledger, receipts, now):
    for kind in SWITCH:
        for key, current in ledger.get(kind, {}).items():
            saved = receipts.get(kind, {}).get(key) or {}
            if video_visibility.is_public(current, now) and saved.get('video_id') == current['video_id']:
                yield kind, key, current, saved['material']


def related_rows(ledger, receipts, now):
    matched = {}
    for kind, key, parent, material in public_parents(ledger, receipts, now):
        parent_id = parent['video_id']
        refs = {str(r['id'] if kind == CUP else r['key']) for r in material['rows']}
        kinds = ('soccer_goal_short', 'soccer_club_topic', 'soccer_results') if kind == CUP else ('mlb_market_topic',)
        for section in (HIGHLIGHT, *kinds):
            for topic, child in ledger.get(section, {}).items():
                if section == HIGHLIGHT:
                    same = topic.startswith(f'{kind}:{key}:')
                else:
                    same = bool(refs & (set(topic.split(':')) | {str(x) for x in child.get('event_ids', [])}))
                if same and video_visibility.is_public(child, now) and child['video_id'] != parent_id:
                    matched[(child['video_id'], parent_id)] = (child['title'], parent['title'])
    return matched


def write_related(out, ledger, receipts, now):
    path = out / f'related_videos_{now.astimezone(JST):%Y%m%d}.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['# 関連動画の設定先', '']
    for (child, parent), (short_title, long_title) in sorted(related_rows(ledger, receipts, now).items()):
        lines.append(f'- [{short_title}](https://youtu.be/{child}) → [{long_title}](https://youtu.be/{parent})')
    if len(lines) == 2:
        lines.append('この時点で台帳に公開済みの組み合わせはありません。')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def remember(doc, video_id):
    data = doc['scheduled_long_material']
    receipts = load(RECEIPTS)
    receipts.setdefault(data['kind'], {})[data['key']] = dict(video_id=video_id, material=data)
    national.save(RECEIPTS, receipts)



def confirm_public(service, video_id):
    """予約の経過に加えて、投稿直前のYouTube側の状態も照合する。"""
    response = service.videos().list(part='status', id=video_id).execute()
    if not any(r['id'] == video_id and r['status']['privacyStatus'] == 'public'
               for r in response.get('items', [])):
        raise ValueError('誘導先の長編がYouTubeで公開されていません')


def validate_upload(args, now=None):
    now = (now or datetime.now(JST)).astimezone(JST)
    doc, data = load(args.narration), load(args.games)
    if args.force or args.privacy != 'public':
        raise ValueError('長編・誘導は公開用の予約だけを受け付けます')
    kind = args.kind
    if kind in SWITCH:
        validate_document(doc)
        if (data != doc['scheduled_long_material'] or kind != data['kind']
                or args.video_date != data['key'] or now.date().isoformat() != data['key']
                or now.weekday() != WEEKDAY[kind] or args.publish_at != '20:30'
                or now >= kickoff(now.date()) - timedelta(minutes=1)
                or os.getenv(SWITCH[kind]) != 'true'):
            raise ValueError('長編の材料・曜日・20:30の予約・公開変数を確認してください')
        return
    if doc.get('program') != HIGHLIGHT or phase2_shorts.check(doc) or data != doc['long_material']:
        raise ValueError('誘導ショートの答え・根拠を照合できません')
    if args.video_date != doc['topic_key'] or not args.publish_at or national.instant(args.publish_at) <= now:
        raise ValueError('誘導ショートの題材と予約時刻を確認してください')
    parents = public_parents(load(LEDGER), load(RECEIPTS), now)
    if (os.getenv(SWITCH[data['kind']]) != 'true' or not any(
            current['video_id'] == doc['long_video_id'] and material == data
            for _, _, current, material in parents)):
        raise ValueError('台帳で長編の公開を確認できません')


def prepare_long(kind, day, out):
    if day.weekday() != WEEKDAY[kind]:
        raise ValueError('指定した日は長編の公開曜日と異なります')
    if kind == CUP:
        data = cup_material(day, saved_matches())
    else:
        data = market_material(day, load(market_watch.LARGE_CONTRACTS).get('events', {}),
                               load(short.MLB_LEDGER), load(LEDGER).get('mlb_market_topic', {}))
    national.save(out / 'material.json', data)
    if not data['can_make']:
        print('見送り | ' + data['reason'])
        return False
    doc = dialogue(data)
    national.save(out / 'dialogue.json', doc)
    print(doc['title'])
    return True


def prepare_highlights(out, now):
    ledger, receipts = load(LEDGER), load(RECEIPTS)
    count = 0
    for kind, key, parent, data in public_parents(ledger, receipts, now):
        if os.getenv(SWITCH[kind]) != 'true' or not 0 <= (now.date() - date.fromisoformat(key)).days <= 7:
            continue
        for h in highlights(data):
            doc = highlight_narration(data, h['key'], parent['video_id'])
            if doc['topic_key'] in ledger.get(HIGHLIGHT, {}):
                continue
            if kind == MARKET and video_visibility.is_public(
                    ledger.get('mlb_market_topic', {}).get(h['key']), now):
                continue
            count += 1
            folder = out / str(count)
            national.save(folder / 'narration.json', doc)
            national.save(folder / 'material.json', data)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=(*SWITCH, 'related', 'highlights'))
    parser.add_argument('--date', type=date.fromisoformat)
    parser.add_argument('--out', type=Path, default=Path('build'))
    args = parser.parse_args()
    now = datetime.now(JST)
    day = args.date or now.date()
    if args.kind == 'related':
        print(write_related(args.out, load(LEDGER), load(RECEIPTS), now))
        return
    if args.kind == 'highlights':
        outputs = dict(count=prepare_highlights(args.out, now))
    else:
        can_make = prepare_long(args.kind, day, args.out)
        outputs = dict(can_make=str(can_make).lower(), key=day.isoformat())
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf8') as stream:
            for key, value in outputs.items():
                stream.write(f'{key}={value}\n')


if __name__ == '__main__':
    main()
