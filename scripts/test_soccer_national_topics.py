"""代表戦の話題ショート。固定の保存材料だけで、数字・問いの形・除外条件・題・新しい見た目・workflow を見る。
通信・音声・公開なし。手元の保存材料・Windowsのフォント・パスに頼らない。"""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]
import soccer_national as n
import soccer_national_topics as topics
from duo import ZUNDA, METAN

FIXTURE = ROOT / 'scripts/fixtures/soccer_national_topics.json'
MEETINGS = [
    dict(date='2026-06-30', competition='ワールドカップ', stage='ラウンド32', gf=1, ga=2, result='loss'),
    dict(date='2025-10-14', competition='親善試合', gf=3, ga=2, result='win'),
]
ALL = ('team-numbers', 'late-winner', 'opponent-star', 'keeper', 'early-goals', 'rematch')
REACTIONS_FIXTURE = ROOT / 'scripts/fixtures/soccer_national_reactions.json'
_REACTIONS = topics.REACTIONS
FOLLOWUPS_FIXTURE = ROOT / 'scripts/fixtures/soccer_national_followups.json'
_FOLLOWUPS = topics.FOLLOWUPS


def setUpModule():
    # 本物の data/ ではなく、試験用の写しの試合後の声を読む。
    topics.REACTIONS = REACTIONS_FIXTURE
    topics.FOLLOWUPS = FOLLOWUPS_FIXTURE


def tearDownModule():
    topics.REACTIONS = _REACTIONS
    topics.FOLLOWUPS = _FOLLOWUPS
DIGITS = '[0-9０-９〇一二三四五六七八九十百千万]'


def summary():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def make(topic, raw=None, **kw):
    kw.setdefault('meetings', MEETINGS)
    return topics.narration(raw or summary(), topic, **kw)


def spoken(doc):
    return [s['text'] for s in doc['segments']]


def stat(raw, team, key):
    row = next(t for t in raw['boxscore']['teams'] if t['team']['id'] == team)
    return next(s['displayValue'] for s in row['statistics'] if s['name'] == key)


class Topics(unittest.TestCase):
    def test_core_sound_prefers_the_matching_answer_and_falls_back_to_the_first_number(self):
        import soccer_national_topics_render as render

        def ask(panel, **meta):
            return dict(kind='list', speaker=ZUNDA, meta=dict(panel=panel, **meta))

        def answer(panel, value):
            return dict(kind='list', speaker=METAN, meta=dict(panel=panel, big=dict(value=value)))

        segments = [ask(0, hook=dict(big='5')), answer(0, 2), ask(1), answer(1, 5),
                    dict(kind='outro', speaker=METAN, meta={})]
        frames = [60, 90, 60, 90, 60]
        self.assertEqual(topics.core_panel(segments), 1)
        self.assertEqual(render.topic_transition_cues(segments, frames, 90), [(5, 'transition', 'b', -12)])
        segments[0]['meta']['hook']['big'] = '7'
        self.assertEqual(topics.core_panel(segments), 0)
        self.assertEqual(render.topic_transition_cues(segments, frames, 90), [(3, 'transition', 'b', -12)])
        for seg in segments:
            seg['meta'].pop('big', None)
        self.assertIsNone(topics.core_panel(segments))
        self.assertEqual(render.topic_transition_cues(segments, frames, 90), [])

    def test_all_six_topics_are_made_from_the_fixture(self):
        made, excluded = topics.available(summary(), meetings=MEETINGS)
        self.assertEqual(sorted(made), sorted(ALL + ('reactions', 'followup-shiogai', 'followup-ueda', 'followup-endo', 'followup-tomiyasu', 'followup-nagatomo')))
        self.assertEqual(excluded, {})

    def test_numbers_match_the_material(self):
        raw = summary()
        doc = make('team-numbers')
        text = '\n'.join(spoken(doc))
        jp, br = n.JAPAN, '205'
        for key, unit in (('totalShots', '本'), ('shotsOnTarget', '本')):
            self.assertIn(f'日本が{stat(raw, jp, key)}{unit}', text)
            self.assertIn(f'ブラジルが{stat(raw, br, key)}{unit}', text)
        self.assertIn(f"日本が{round(float(stat(raw, jp, 'possessionPct')))}パーセント", text)
        self.assertIn(f"ブラジルが{round(float(stat(raw, br, 'possessionPct')))}パーセント", text)
        self.assertIn('3対2', text)
        last = [s for s in doc['segments'] if s['kind'] != 'outro' and (s['meta'].get('compare'))][-1]
        self.assertEqual(last['meta']['compare']['rows'],
                         [['ボール支配率', '42%', '58%'], ['シュート', '8本', '17本'], ['枠内シュート', '4本', '6本'], ['得点', '3点', '2点']])
        # 解説：数字で下回っても勝てた理由（本人 11/15「解説的な視点」）。枠内と得点の比は材料から計算した物だけ。
        self.assertIn('日本は4本で3点、ブラジルは6本で2点', text)
        # 小数の支配率をそのまま出さない（整数で原稿と画面を揃える）
        self.assertNotIn('42.4', text)

        late = '\n'.join(spoken(make('late-winner')))
        self.assertIn('坂元達裕', late)
        self.assertIn('後半追加時間1分', late)
        self.assertIn('72分に堂安律と交代', late)
        self.assertIn('VARの確認を経て認められました', late)
        self.assertIn('出場してから19分で決めた決勝点', late)

        star = '\n'.join(spoken(make('opponent-star')))
        self.assertIn('ヴィニシウス・ジュニオールが2得点', star)
        self.assertIn('33分・75分', star)
        self.assertIn('シュートは4本', star)
        self.assertIn('枠内シュートは2本', star)
        self.assertIn('ペナルティエリアの外', star)
        self.assertIn('ブルーノ・ギマランイスのアシスト', star)
        self.assertIn('ブラジルの得点は、すべてヴィニシウスです', star)
        self.assertIn('チーム全体のシュート17本のうち、4本を打っています', star)

        keeper = '\n'.join(spoken(make('keeper')))
        self.assertIn('鈴木彩艶のセーブ数は4', keeper)
        self.assertIn('ブラジルのシュートは17本', keeper)
        self.assertIn('枠内は6本。鈴木彩艶はそのうち4本を止め、決められたのは2本', keeper)
        self.assertIn('ブラジルのゴールキーパーのセーブ数は1', keeper)

        early = '\n'.join(spoken(make('early-goals')))
        self.assertIn('前半15分、堂安律のスルーパスから、久保建英が左足で決めました', early)
        self.assertIn('4分後の前半19分、中野就斗のクロスから、中村敬斗が右足で決めました', early)
        # 2点のあとの流れも言う（Argon 11/15：3-2 に飛ばない）。
        self.assertIn('ヴィニシウス・ジュニオールが33分と75分に決めて2対2', early)
        self.assertIn('坂元達裕が後半追加時間1分に決めて3対2', early)
        flow = make('early-goals')['segments'][-2]['meta']['rows']
        self.assertEqual([list(r) for r in flow], [['15分 日本', '久保建英'], ['19分 日本', '中村敬斗'], ['33分 ブラジル', 'ヴィニシウス'],
                                                  ['75分 ブラジル', 'ヴィニシウス'], ['90+1分 日本', '坂元達裕']])

        rematch = '\n'.join(spoken(make('rematch')))
        self.assertTrue(rematch.split('\n')[1].startswith('日本が3対2で勝ちました'), rematch)
        self.assertIn('6月30日のワールドカップのラウンド32', rematch)
        self.assertIn('1対2で敗れました', rematch)
        self.assertIn('2025年10月の親善試合では、日本が3対2で勝っています', rematch)
        self.assertNotIn('通算', rematch)
        # 画面の対戦は両国名つきで新しい順に積む（「1-2 ブラジル」だけにしない）。
        board = [list(r) for r in make('rematch')['segments'][-2]['meta']['rows']]
        self.assertEqual([v for _, v in board], ['日本 3-2 ブラジル', '日本 1-2 ブラジル', '日本 3-2 ブラジル'])

    def test_opening_hook_shows_the_title_fact_with_the_result(self):
        # 最初の問いの区間＝サムネ（1.6秒目）に題の中心の数字（本人 11/15「事実は抑えたうえで、ちゃんとひきこむものに」）。
        for topic in ALL:
            doc = make(topic)
            hook = doc['segments'][0]['meta']['hook']
            self.assertEqual(hook['result'], '勝利', topic)
            self.assertEqual(hook['score'], '日本 3-2 ブラジル', topic)
            said = doc['title'] + ' '.join(s['text'] for s in doc['segments'])
            for value in re.findall(r'\d+', hook['big'] + hook['unit'] + hook.get('note', '')):
                self.assertIn(value, said, (topic, hook))
            self.assertNotIn('hook', doc['segments'][1]['meta'], topic)
        self.assertNotIn('hook', make('reactions')['segments'][0]['meta'])

    def test_names_come_from_the_roster_not_by_hand(self):
        self.assertEqual(n.player_name('Tatsuhiro Sakamoto', True), '坂元達裕')
        self.assertIn('坂元達裕', make('late-winner')['title'])
        for topic in ALL:
            blob = json.dumps(make(topic), ensure_ascii=False)
            self.assertNotIn('坂本', blob)

    def test_zundamon_only_asks_short_questions_without_numbers(self):
        for topic in ALL:
            doc = make(topic)
            asks = [s for s in doc['segments'] if s['speaker'] == ZUNDA]
            self.assertGreaterEqual(len(asks), 3, topic)
            for s in asks:
                self.assertTrue(s['text'].endswith('？'), s['text'])
                self.assertIsNone(re.search(DIGITS, s['text']), s['text'])
                self.assertLessEqual(len(s['text']), 24, s['text'])
            answers = [s for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro']
            self.assertEqual(len(answers), len(asks), topic)
            # 問いと答えは交互で、答えが問いの直後に来る
            order = [s['speaker'] for s in doc['segments'] if s['kind'] != 'outro']
            self.assertEqual(order, [ZUNDA, METAN] * len(asks))
            self.assertEqual(doc['segments'][-1]['kind'], 'outro')
            self.assertEqual(doc['segments'][-1]['text'], n.short_common.OUTRO_TEXT)

    def test_conditions_that_are_not_met_do_not_make_a_topic(self):
        # 決勝点の選手が先発
        raw = summary()
        for team in raw['rosters']:
            for r in team['roster']:
                if r['athlete']['displayName'] == 'Tatsuhiro Sakamoto':
                    r['starter'] = True
        with self.assertRaises(topics.Unavailable):
            make('late-winner', raw)
        # 相手の2得点目を別の選手へ（2得点の選手がいない）
        raw = summary()
        goals = [e for e in raw['keyEvents'] if e.get('scoringPlay') and e['team']['id'] == '205']
        goals[1]['participants'][0] = dict(goals[0]['participants'][1])
        with self.assertRaises(topics.Unavailable):
            make('opponent-star', raw)
        # 名前表に無い相手
        with self.assertRaises(topics.Unavailable):
            make('opponent-star', names={})
        # 日本の2得点が5分より離れる
        raw = summary()
        goal = next(e for e in raw['keyEvents'] if e.get('scoringPlay') and e['clock']['displayValue'] == "19'")
        goal['clock']['displayValue'] = "25'"
        with self.assertRaises(topics.Unavailable):
            make('early-goals', raw)
        # 数字で上回る項目がある
        raw = summary()
        row = next(t for t in raw['boxscore']['teams'] if t['team']['id'] == n.JAPAN)
        next(s for s in row['statistics'] if s['name'] == 'wonCorners')['displayValue'] = '12'
        with self.assertRaises(topics.Unavailable):
            make('team-numbers', raw)
        # 過去の対戦が確認一覧に無い・W杯の敗戦が無い
        for meetings in ([], [MEETINGS[1]], [dict(MEETINGS[0], competition='親善試合')]):
            with self.assertRaises(topics.Unavailable):
                make('rematch', meetings=meetings)
        # 今日以降の対戦は過去として数えない
        with self.assertRaises(topics.Unavailable):
            make('rematch', meetings=[dict(MEETINGS[0], date='2026-11-14')])
        made, excluded = topics.available(summary(), names={}, meetings=[])
        self.assertNotIn('opponent-star', made)
        self.assertIn('opponent-star', excluded)
        self.assertIn('rematch', excluded)

    def test_no_unconfirmed_names_or_claims(self):
        names = json.loads(topics.NAMES.read_text(encoding='utf-8'))
        self.assertNotIn('Pedro Luccas', names)
        self.assertNotIn('ペドロ・ルッカス', topics.NAMES.read_text(encoding='utf-8'))
        for topic in ALL:
            doc = make(topic)
            blob = json.dumps(doc, ensure_ascii=False)
            blob_without_source = json.dumps({k: v for k, v in doc.items() if k != 'topic_summary' and k != 'sanity_materials'}, ensure_ascii=False)
            for word in ('ハフィーニャ', 'ラフィーニャ', '退場', '代表初ゴール', '初ゴール', '通算2勝', 'ルッカス',
                         '圧倒', '完璧', '歴史的', '衝撃', '快挙'):
                self.assertNotIn(word, blob_without_source, (topic, word))
        # 相手GKは名前を出さず役職で言う
        self.assertIn('ブラジルのゴールキーパー', '\n'.join(spoken(make('keeper'))))
        # 材料のうち固定に取り込むのは必要な欄だけ（写真・ロゴ・記事・コメントの名前を持たない）
        raw = make('keeper')['topic_summary']
        self.assertEqual(sorted(raw), ['boxscore', 'commentary', 'header', 'keyEvents', 'rosters'])
        self.assertNotIn('logo', json.dumps(raw))
        self.assertNotIn('headshot', json.dumps(raw))

    def test_titles_say_the_content_directly(self):
        expected = {
            'team-numbers': '日本3-2ブラジル 支配率42% シュート8本で勝利 #Shorts',
            'late-winner': '坂元達裕 途中出場から90+1分の決勝点 #Shorts',
            'opponent-star': 'ヴィニシウス 2得点とも箱の外から #Shorts',
            'keeper': '鈴木彩艶 4セーブでブラジルに勝利 #Shorts',
            'early-goals': '久保建英と中村敬斗 4分間で2得点 #Shorts',
            'rematch': 'W杯で敗れたブラジルに3-2で勝利 #Shorts',
        }
        for topic, title in expected.items():
            self.assertEqual(make(topic)['title'], title)
            self.assertLessEqual(len(title), 100)
            for bad in '！？!?【】、，':
                self.assertNotIn(bad, title)

    def test_script_length_is_in_the_short_range(self):
        for topic in ALL:
            seconds = topics.estimate(make(topic))
            self.assertGreaterEqual(seconds, 20, topic)
            self.assertLessEqual(seconds, topics.LIMIT, topic)
            self.assertEqual(make(topic)['duration_budget']['limit'], topics.LIMIT)

    def test_check_information_readings_and_metadata(self):
        import short_content
        for topic in ALL:
            doc = json.loads(json.dumps(make(topic)))
            self.assertEqual(topics.check(doc), [], topic)
            self.assertGreaterEqual(len(topics.information(doc)), short_content.MIN_INFORMATION, topic)
            self.assertGreaterEqual(len(short_content.information(doc)), short_content.MIN_INFORMATION)
            meta = topics.metadata(doc)['snippet']
            self.assertIn('https://www.espn.com/soccer/match/_/gameId/401916337', meta['description'])
            self.assertEqual(meta['title'], doc['title'])
            tampered = copy.deepcopy(doc)
            answer = next(s for s in tampered['segments'] if s['speaker'] == METAN)
            answer['text'] = answer['text'].replace('3対2', '4対2').replace('42パーセント', '43パーセント') + '。'
            self.assertTrue(topics.check(tampered), topic)
            ask = copy.deepcopy(doc)
            next(s for s in ask['segments'] if s['speaker'] == ZUNDA)['text'] = 'ブラジルに3本打たれたのだ。'
            self.assertTrue(topics.check(ask), topic)
        shots = topics.metadata(make('team-numbers'))['snippet']['description']
        self.assertIn('枠内シュート：', shots)
        rematch = topics.metadata(make('rematch'))['snippet']['description']
        self.assertIn('soccer-king.jp', rematch)
        readings = topics.speech_readings(make('opponent-star'))
        self.assertEqual(readings['ヴィニシウス・ジュニオール'][1], 'ヴィニシウスジュニオール')
        self.assertEqual(readings['ヴィニシウス'][1], 'ヴィニシウス')
        self.assertEqual(readings['ブルーノ・ギマランイス'][0], 'player')

    def test_reservation_is_today_only_and_ledger_blocks_repeats(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 15, 1, 0, tzinfo=timezone.utc)   # JST 10:00
        first = topics.reservation(now, {})
        self.assertEqual(first.hour, 12)
        taken = {'x': dict(publish_at=first.isoformat())}
        self.assertEqual(topics.reservation(now, taken).hour, 19)
        late = datetime(2026, 11, 15, 12, 30, tzinfo=timezone.utc)  # JST 21:30
        with self.assertRaises(ValueError):
            topics.reservation(late, {})


PROBE = r'''
import json, os, sys
sys.path[:0] = [sys.argv[1] + '/scripts', sys.argv[1]]
os.environ.update(COLLESPO_SOCCER_LOOK='v6', COLLESPO_SOCCER_FOCUS='on', COLLESPO_SHORT_LOOK='v4', COLLESPO_SOLO_HOST='metan')
import soccer_national as n
import soccer_national_topics as topics
import soccer_national_topics_render as render
import soccer_v5_cards as c
import review_render_v3 as r3
summary = json.load(open(sys.argv[1] + '/scripts/fixtures/soccer_national_topics.json', encoding='utf-8'))
meetings = json.loads(sys.argv[2])
out = dict(style=c.STYLE_V2, errors=[], old=0, who=[], x=[], slide=[], frames=0)
OLD = {(196, 244, 76)}
# 試合後の声（相手国側の組も）は引用の行に数字が入る（11/15 行が重なって描画が止まった）。
for topic in ('team-numbers', 'late-winner', 'opponent-star', 'keeper', 'early-goals', 'rematch', 'reactions') + tuple(topics.reaction_topics(summary['header']['id'])) + tuple(topics.followup_topics(summary['header']['id'])):
    doc = topics.narration(summary, topic, meetings=meetings)
    clubs = render.clubs_for(doc)
    for i, seg in enumerate(doc['segments']):
        if seg['kind'] == 'outro':
            continue
        r3.set_program_clock(0); r3.set_caption(seg['text'], 4.0, 20, speaker=seg['speaker'])
        for t in (.1, 1.5, 3.0, 3.9):
            im = render.frame(t, seg, doc, clubs, i, len(doc['segments']))
            out['errors'] += [[topic, i, str(e)[:160]] for e in render.validate_frame(im, clubs, doc)]
            rgb = im.convert('RGB')
            colors = set(rgb.getdata())
            out['old'] += len(colors & OLD)
            out['frames'] += 1
            if t == 1.5:
                layer = im.info['duo_layer'][0]
                out['who'].append([seg['speaker'], layer['who']]); out['x'].append(layer['at'][0])
            out['slide'].append([seg['speaker'], t, (im.info.get('v2_slide') or {}).get('phase')])
doc = topics.narration(summary, 'team-numbers')
segments = doc['segments']
clubs = render.clubs_for(doc)
first = 2 * render.FPS
end = render.opening_frames(segments, first)
hook = segments[0]['meta']['hook']
opening = []
for k in (0, first, end - 1, end):
    i = int(k >= first)
    start = first / render.FPS if i else 0
    seg = segments[i]
    r3.set_program_clock(start)
    r3.set_caption(seg['text'], 2.0, 20, speaker=seg['speaker'])
    r3.set_program_clock(k / render.FPS)
    im = render.frame(k / render.FPS - start, seg, doc, clubs, i, len(segments),
                      opening_hook=hook if k < end else None)
    body = im.crop((72, 236, 904, 1150)).tobytes()
    opening.append((body, 'opening_hook' in im.info, im.info['duo_layer'][0]['who']))
    out['errors'] += [['opening', k, str(e)[:160]] for e in render.validate_frame(im, clubs, doc)]
out['opening'] = dict(end=end, long=render.opening_frames(segments, 102),
    missing=render.opening_frames(topics.narration(summary, 'reactions')['segments'], first),
    shown=[frame[1] for frame in opening], who=[frame[2] for frame in opening],
    same=opening[0][0] == opening[1][0] == opening[2][0] != opening[3][0])
r3.set_program_clock(None)
print(json.dumps(out))
'''


def probe(style):
    env = dict(os.environ, PYTHONUTF8='1')
    for key in list(env):
        if key.startswith('COLLESPO'):
            env.pop(key)
    if style:
        env['COLLESPO_STYLE'] = style
    run = subprocess.run([sys.executable, '-c', PROBE, str(ROOT), json.dumps(MEETINGS)], env=env,
                         capture_output=True, text=True, encoding='utf-8', timeout=900)
    if run.returncode:
        raise AssertionError(run.stderr[-2500:])
    return json.loads(run.stdout.strip().splitlines()[-1])


class Reactions(unittest.TestCase):
    def material(self):
        return json.loads(REACTIONS_FIXTURE.read_text(encoding='utf-8'))['events']['401916337']

    def test_quotes_are_said_exactly_with_who_and_source(self):
        doc = make('reactions')
        answers = [s for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro']
        quotes = self.material()['quotes']
        for q in quotes:
            s = next(a for a in answers if '「' + q['quote'] + '」' in a['text'])
            self.assertIn(q['lead'] + 'は、「' + q['quote'] + '」と話し', s['text'])
            # 画面の中央に発言そのものと媒体を出す（Argon 11/15：話した人と出典だけでは中身が見えない）
            self.assertIn([q['who'] + 'の発言', '「' + q['quote'] + '」'], [list(r) for r in s['meta']['rows']])
            self.assertIn(['出典', q['source']], [list(r) for r in s['meta']['rows']])
        # 最初に何の試合の声かを言い、画面にも結果（Argon 11/15）。
        self.assertTrue(answers[0]['text'].startswith('ブラジルに3対2で勝った試合の後、森保一監督は、'))
        self.assertEqual(list(answers[0]['meta']['rows'][0]), ['試合結果', '日本 3-2 ブラジル'])
        # 得点した2人は1つの問いにまとめる（毎回同じ問いで単調。Argon 11/15）。
        asks = [s['text'] for s in doc['segments'] if s['speaker'] == ZUNDA]
        self.assertEqual(len(asks), 4)
        self.assertIn('得点した久保建英と中村敬斗は、何と話したのだ？', asks)
        self.assertIn('分があると思っていた」と話し、中村敬斗は、「本当に僕は決めるだけだった」と話しました。', answers[1]['text'])
        self.assertIn('グローボの報道です。', answers[2]['text'])
        self.assertIn('レッドカードで退場しました。', answers[3]['text'])
        self.assertEqual(list(answers[3]['meta']['rows'][-1]), ['出典', 'サッカーキング・GOAL'])
        for s in doc['segments']:
            if s['speaker'] == ZUNDA:
                self.assertTrue(s['text'].endswith('？'))
                self.assertIsNone(re.search(DIGITS, s['text']), s['text'])
        self.assertEqual(topics.check(doc), [])
        description = topics.metadata(doc)['snippet']['description']
        for q in quotes:
            self.assertIn(q['source_url'], description)
        for url in self.material()['facts'][0]['sources']:
            self.assertIn(url, description)
        self.assertIn('https://www.espn.com/soccer/match/_/gameId/401916337', description)
        self.assertEqual([i['source'] for i in topics.information(doc)][:4], [q['source_url'] for q in quotes])

    def test_quote_panels_do_not_start_a_line_with_punctuation_and_credit_names_the_media(self):
        import soccer_national_topics_render as render
        lines = render.balanced_lines('日本は強豪チームであり、トップレベルで十分に戦えるチームだ', 64, 812)
        self.assertEqual(''.join(lines), '日本は強豪チームであり、トップレベルで十分に戦えるチームだ')
        for line in lines[1:]:
            self.assertNotIn(line[0], render.NO_START)
        self.assertGreater(min(len(l) for l in lines), 2)
        self.assertEqual(render.credit(make('reactions')), '音声: VOICEVOX:ずんだもん・四国めたん　出典: サッカーキング・グローボ・GOAL・ESPN')
        self.assertEqual(render.credit(make('keeper')), render.CREDIT)

    def test_reading_of_bu_ga_aru(self):
        sys.path.insert(0, str(ROOT))
        from notability_engine import apply_readings
        self.assertIn('ぶがある', apply_readings('僕の方に分があると思っていた'))

    def test_held_claims_and_evaluative_words_are_not_said(self):
        text = ' '.join(spoken(make('reactions')))
        for word in ('代表初ゴール', '初ゴール', '通算2勝', '最後の試合', 'ラストマッチ', '圧倒', '完璧', '歴史的', '衝撃', '快挙', '抗議'):
            self.assertNotIn(word, text)
        self.assertLessEqual(topics.estimate(make('reactions')), topics.LIMIT)

    def test_unchecked_material_does_not_make_the_topic(self):
        import tempfile
        cases = []
        base = json.loads(REACTIONS_FIXTURE.read_text(encoding='utf-8'))
        empty = copy.deepcopy(base); empty['events'] = {}
        cases.append(empty)
        one_source = copy.deepcopy(base); one_source['events']['401916337']['facts'][0]['sources'] = ['https://example.com/a']
        cases.append(one_source)
        no_url = copy.deepcopy(base); no_url['events']['401916337']['quotes'][0]['source_url'] = ''
        cases.append(no_url)
        unchecked = copy.deepcopy(base); unchecked['events']['401916337']['checked_on'] = ''
        cases.append(unchecked)
        for data in cases:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'reactions.json'
                path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                topics.REACTIONS = path
                try:
                    made, excluded = topics.available(summary(), meetings=MEETINGS)
                finally:
                    topics.REACTIONS = REACTIONS_FIXTURE
                self.assertNotIn('reactions', made)
                self.assertIn('reactions', excluded)


class TopicReactions(unittest.TestCase):
    """事実→解説→反応（本人 11/15「二次情報・反応・解説的な視点も」）。"""
    QUOTE = dict(who='テスト記者', ask='専門家は、どう見たのだ？', head='専門家の見方', lead='テスト記者',
                 quote='少ない好機を確実に決めた', via=None, source='テスト新聞',
                 source_url='https://example.com/analysis', where='試合の分析記事')

    def with_material(self, change):
        import tempfile
        data = json.loads(REACTIONS_FIXTURE.read_text(encoding='utf-8'))
        change(data['events']['401916337'])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'reactions.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        topics.REACTIONS = path
        self.addCleanup(setattr, topics, 'REACTIONS', REACTIONS_FIXTURE)

    def test_topic_reaction_is_added_as_the_last_answer_with_its_source(self):
        self.with_material(lambda e: e.setdefault('topic_reactions', {}).update(
            {'team-numbers': dict(checked_on='2026-11-15', quotes=[dict(self.QUOTE)])}))
        doc = make('team-numbers')
        answers = [s for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro']
        self.assertIn('テスト記者は、「少ない好機を確実に決めた」と話しました。', answers[-1]['text'])
        self.assertIn(['出典', 'テスト新聞'], [list(r) for r in answers[-1]['meta']['rows']])
        self.assertEqual(topics.check(doc), [])
        self.assertLessEqual(topics.estimate(doc), topics.LIMIT)
        description = topics.metadata(doc)['snippet']['description']
        self.assertIn('反応:', description)
        self.assertIn('https://example.com/analysis', description)
        self.assertIn('https://example.com/analysis', [i['source'] for i in topics.information(doc)])
        # 確認日の無い反応では作らない。
        self.with_material(lambda e: e.setdefault('topic_reactions', {}).update(
            {'team-numbers': dict(checked_on='', quotes=[dict(self.QUOTE)])}))
        with self.assertRaises(topics.Unavailable):
            make('team-numbers')

    def test_reaction_sets_make_their_own_topic(self):
        quote = dict(self.QUOTE, ask='ブラジルの記者は、どう見たのだ？', verb='書き')
        self.with_material(lambda e: e.setdefault('sets', {}).update(
            {'brazil': dict(checked_on='2026-11-15', checked_by='test', title='ブラジル側の反応',
                            quotes=[quote], facts=[], held=[])}))
        made, excluded = topics.available(summary(), meetings=MEETINGS)
        self.assertIn('reactions-brazil', made)
        doc = make('reactions-brazil')
        # 相手国の組は相手の側から結果を言い、記事の文は「書きました」（話したとは言わない）。
        self.assertIn('日本に2対3で敗れた試合の後、テスト記者は、「少ない好機を確実に決めた」と書きました。', ' '.join(spoken(doc)))
        self.assertEqual(topics.check(doc), [])
        self.assertIn('https://example.com/analysis', topics.metadata(doc)['snippet']['description'])

    def test_credit_of_every_real_reaction_set_fits_on_one_line(self):
        # 11/15 ブラジル側の組で画面下の出典が1行に入らず描画が止まった。本物の材料の組を全部測る。
        import soccer_national_topics_render as render
        import soccer_v5_cards as cards
        topics.REACTIONS = _REACTIONS
        self.addCleanup(setattr, topics, 'REACTIONS', REACTIONS_FIXTURE)
        for topic in ['reactions'] + topics.reaction_topics('401916337'):
            source = render.credit(make(topic)).replace('音声: ', '').replace('　出典: ', ' / ')
            self.assertTrue(any(len(cards.lines(source, size, 1000)) == 1 for size in (30, 28, 26)), source)
        description = topics.metadata(make('reactions-brazil'))['snippet']['description']
        self.assertIn('www.terra.com.br', description)

    def test_metadata_asks_for_likes_and_subscription(self):
        for topic in ALL:
            self.assertIn('高評価・チャンネル登録', topics.metadata(make(topic))['snippet']['description'], topic)


class RenderV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = probe('v2')

    def test_every_screen_passes_the_production_frame_checks(self):
        self.assertTrue(self.v2['style'])
        self.assertGreaterEqual(self.v2['frames'], 6 * 6 * 3)
        self.assertEqual(self.v2['errors'], [])

    def test_no_old_colour_appears_in_the_new_look(self):
        self.assertEqual(self.v2['old'], 0)

    def test_opening_is_static_for_three_seconds_without_delaying_the_answer(self):
        self.assertEqual(self.v2['opening'], dict(end=90, long=102, missing=0,
            shown=[True, True, True, False], who=['zundamon', 'metan', 'metan', 'metan'], same=True))

    def test_zundamon_is_lower_left_and_metan_lower_right(self):
        for speaker, who in self.v2['who']:
            self.assertEqual(who, 'zundamon' if speaker == ZUNDA else 'metan')
        for (speaker, _), x in zip(self.v2['who'], self.v2['x']):
            if speaker == ZUNDA:
                self.assertLess(x, 200)
            else:
                self.assertGreater(x, 500)

    def test_the_screen_enters_on_the_question_and_leaves_after_the_answer(self):
        slides = {(s, t): p for s, t, p in self.v2['slide']}
        self.assertEqual(slides[(ZUNDA, .1)], 'enter')
        self.assertIsNone(slides[(ZUNDA, 3.9)])        # 問いの終わりでは抜けない
        self.assertIsNone(slides[(METAN, .1)])         # 答えの始まりで入り直さない
        self.assertEqual(slides[(METAN, 3.9)], 'exit')
        # 答えは話し終わるまで残す（時刻を1秒進めた分だけ早く抜けていた。Argon 11/15）。
        self.assertIsNone(slides[(METAN, 3.0)])


class Workflow(unittest.TestCase):
    def test_workflow_is_manual_only_and_publishes_only_when_asked(self):
        import yaml
        path = ROOT / '.github/workflows/soccer_national_topics.yml'
        text = path.read_text(encoding='utf-8')
        workflow = yaml.safe_load(text)
        triggers = workflow.get('on') or workflow.get(True)
        self.assertEqual(list(triggers), ['workflow_dispatch'])
        inputs = triggers['workflow_dispatch']['inputs']
        self.assertTrue(inputs['topic']['required'])
        self.assertFalse(inputs['publish']['default'])
        self.assertIn('sample_only', inputs)
        self.assertIn('publish_at', inputs)
        self.assertNotIn('schedule', text.split('jobs:')[0].replace('schedule なし', ''))
        self.assertIn("COLLESPO_STYLE: ${{ vars.COLLESPO_STYLE || '' }}", text)
        upload = next(s for s in workflow['jobs']['build']['steps'] if s.get('name') == 'Upload to YouTube')
        self.assertEqual(upload['if'], "env.PUBLISH == 'true'")
        self.assertIn('--kind soccer_national_topic', upload['run'])
        self.assertIn('COLLESPO_NATIONAL_TOPIC_PUBLISH', upload['env'])
        self.assertIn('soccer_national_topics_published' + '.json', text)  # workflow の文面の確認。台帳そのものは読まない

    def test_registered_in_the_common_lists(self):
        import sanity_workflows
        self.assertEqual(sanity_workflows.NARRATIONS['soccer_national_topics'], ['build/soccer_national_topics/narration.json'])
        self.assertEqual(sanity_workflows.KINDS['soccer_national_topics'], 'soccer_national_topic')
        self.assertEqual(sanity_workflows.errors(ROOT), [])
        import importlib.util
        spec = importlib.util.spec_from_file_location('style_gallery', str(ROOT / 'scripts/style_gallery.py'))
        gallery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gallery)
        self.assertIn('soccer_national_topics', {w for k in gallery.KINDS.values() for w in k['workflows']})
        import upload_youtube
        self.assertIn('soccer_national_topic', upload_youtube.DATED_KINDS)
        self.assertIn('"soccer_national_topic"', (ROOT / 'scripts/upload_youtube.py').read_text(encoding='utf-8').split('choices=[')[1].split(']')[0])
        self.assertIn('soccer_national_topics.check', (ROOT / 'scripts/sanity_material.py').read_text(encoding='utf-8'))



class TopicFollowup(unittest.TestCase):
    """「そういえば〇〇はどこに？」（本人 11/15）。確かめた事実の組だけで作る。"""

    def with_material(self, change):
        import tempfile
        data = json.loads(FOLLOWUPS_FIXTURE.read_text(encoding='utf-8'))
        change(data['events']['401916337']['shiogai'])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'followups.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        topics.FOLLOWUPS = path
        self.addCleanup(setattr, topics, 'FOLLOWUPS', FOLLOWUPS_FIXTURE)

    def test_followup_is_offered_and_passes_the_checks(self):
        made, excluded = topics.available(summary(), meetings=MEETINGS)
        self.assertIn('followup-shiogai', made, excluded)
        doc = made['followup-shiogai']
        self.assertEqual(topics.check(doc), [])
        self.assertLessEqual(topics.estimate(doc), topics.LIMIT + 0.5)
        self.assertEqual(spoken(doc)[0], 'そういえば、塩貝はどこに行ったのだ？')
        self.assertEqual(doc['segments'][0]['meta']['hook']['result'], '招集外')
        for s in doc['segments']:
            if s['speaker'] == ZUNDA and s['kind'] != 'outro':
                self.assertIsNone(re.search(DIGITS, s['text']), s['text'])

    def test_every_answer_has_two_sources_and_a_source_row(self):
        doc = make('followup-shiogai')
        info = topics.information(doc)
        self.assertEqual(len(info), 4)
        for row in info:
            self.assertGreaterEqual(len(row['source'].split()), 2)
        answers = [s for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro']
        for s in answers:
            self.assertEqual(s['meta']['rows'][-1][0], '出典')

    def test_big_number_comes_from_the_answer_and_is_drawn_large(self):
        doc = make('followup-shiogai')
        answers = [s for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro']
        bigs = [s['meta'].get('big') for s in answers]
        self.assertEqual([b and b['value'] for b in bigs], [None, '10', '2', None])
        for s, b in zip(answers, bigs):
            if b:
                self.assertIn(b['value'], s['text'])
        self.with_material(lambda d: d['items'][1]['big'].update(value='99'))
        made, excluded = topics.available(summary(), meetings=MEETINGS)
        self.assertNotIn('followup-shiogai', made)
        self.assertIn('要の数字', excluded['followup-shiogai'])

    def test_one_source_is_not_enough(self):
        self.with_material(lambda d: d['items'][0].update(sources=d['items'][0]['sources'][:1]))
        made, excluded = topics.available(summary(), meetings=MEETINGS)
        self.assertNotIn('followup-shiogai', made)
        self.assertIn('2つの出典', excluded['followup-shiogai'])

    def test_readings_come_from_the_material_and_credit_has_no_espn(self):
        import soccer_national_topics_render as render
        doc = make('followup-shiogai')
        readings = topics.speech_readings(doc)
        self.assertEqual(readings['塩貝健人'], ('player', 'シオガイケント'))
        self.assertEqual(readings['塩貝'], ('player', 'シオガイ'))
        self.assertNotIn('ESPN', render.credit(doc))
        description = topics.metadata(doc)['snippet']['description']
        self.assertIn('https://jfa.jp/samuraiblue/20261117/member.html', description)
        self.assertNotIn('espn.com', description)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
