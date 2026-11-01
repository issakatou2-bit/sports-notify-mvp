"""通信・声・公開なし。偽の公式応答で境界と既存検査の接続を確かめる。"""
import copy
import contextlib
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

import offseason_news as n


class OffseasonTests(unittest.TestCase):
    day = date(2026, 10, 30)

    def season_payload(self, group='pitching', season=2026, **stat):
        return {'stats': [dict(type={'displayName':'season'}, group={'displayName':group},
            splits=[dict(season=str(season), player={'id':1}, stat=stat)])]}

    def test_person_season_request_and_saved_numeric_grounding(self):
        import generate_asset_video as g
        from unittest.mock import Mock
        payload = self.season_payload(gamesPitched=30, era='3.25', strikeOuts=155)
        fetch = Mock(return_value=payload)
        rows = n.enrich_transactions(self.transactions([self.move()]), fetch)
        fetch.assert_called_once_with('people/1/stats', stats='season', group='hitting,pitching',
                                      season=2026, gameType='R', sportIds=1)
        self.assertIn('2026年は30登板、防御率3.25、155奪三振', rows[0]['body'])
        spec = n.topic('transactions', rows, self.day)
        with patch.dict(g.LIST_TOPICS, {spec['key']: spec}):
            doc = g.build_narration(spec['key'])
        self.assertEqual(n.check(doc), [])
        next(s for s in doc['segments'] if s['kind']=='list')['text'] = rows[0]['body'].replace('155','156')+'。'
        self.assertTrue(n.check(doc))

    def test_person_season_hitting_and_january_previous_season(self):
        payload = self.season_payload('hitting', 2025, gamesPlayed=145, homeRuns=31, avg='.275')
        raw = dict(self.move('SFA', toTeam={'id':145}), date='2026-01-10')
        jp, table = n.names()
        rows = n.transaction_rows({'transactions':[raw]}, date(2026,1,1),date(2026,1,31),jp,table,set())
        def fetch(path, **params):
            self.assertEqual(params['season'], 2025)
            return payload
        self.assertIn('2025年は145試合、31本塁打、打率.275', n.enrich_transactions(rows, fetch)[0]['body'])

    def test_optional_stats_failures_missing_and_wrong_identity_are_omitted(self):
        base = self.transactions([self.move()])
        bad = self.season_payload(gamesPitched=30, era='3.25', strikeOuts=155)
        bad['stats'][0]['splits'][0]['player']['id'] = 999
        for payload in ({}, None, {'stats':None}, bad,
                        self.season_payload(season=2025, gamesPitched=30, era='3.25', strikeOuts=155),
                        self.season_payload(gamesPitched=0, era='-.--', strikeOuts=0)):
            self.assertEqual(n.enrich_transactions(base, lambda *a, **k: payload), base)
        def failure(*args, **kwargs):
            raise ConnectionError('fixture')
        self.assertEqual(n.enrich_transactions(base, failure), base)

    def test_stats_total_only_no_double_count_or_minor_league(self):
        payload = self.season_payload('hitting', gamesPlayed=100, homeRuns=20, avg='.250')
        row = payload['stats'][0]['splits'][0]
        row['team'] = {'id':147}
        payload['stats'][0]['splits'].append(dict(copy.deepcopy(row), team={'id':119}))
        self.assertEqual(n.season_line(payload,2026,1),'')
        total = dict(copy.deepcopy(row), numTeams=2, stat=dict(gamesPlayed=150,homeRuns=30,avg='.260'))
        payload['stats'][0]['splits'].append(total)
        self.assertIn('150試合、30本塁打',n.season_line(payload,2026,1))
        for r in payload['stats'][0]['splits']: r['sport']={'id':11}
        self.assertEqual(n.season_line(payload,2026,1),'')

    def test_collection_continues_when_only_person_stats_fail(self):
        def fetch(path, **params):
            if path.startswith('awards/'):
                return {'awards': []}
            if path == 'stats':
                return {'stats': []}
            if path == 'transactions':
                return {'transactions': [self.move()]}
            if path == 'people/1/stats':
                raise ConnectionError('optional season fixture')
            self.fail(path)
        rows = n.collect(self.day,2026,fetch)['transactions']
        self.assertEqual(len(rows),1)
        self.assertNotIn('season_stats',rows[0])

    def test_only_offseason_reads_body_once_and_changes_outro(self):
        import generate_asset_video as g
        import review_render_v3 as r3
        spec, doc = self.document()
        speech = ''.join(s['text'] for s in doc['segments'] if s['kind']=='list')
        self.assertEqual(speech.count('ゴールドグラブ'), 1)
        self.assertIn('11月1日、ゴールドグラブ',speech)
        for filler in ('守備の表彰結果を確認する日','契約成立の発表とは別','選手が受諾する期限とは別'):
            self.assertNotIn(filler,speech)
        self.assertEqual(doc['segments'][-1]['text'],n.OUTRO_TEXT)
        self.assertEqual(g._list_item_speech({},'見出し','本文'),'見出し。本文。')
        with patch.object(r3, 'outro_rows', side_effect=AssertionError('オフで番組表を呼んだ')):
            image = r3.outro(3, spec)
        self.assertTrue(image.info['v3_outro'])
        self.assertIn('明日の試合',r3.INSEASON_OUTRO_TEXT)

    def test_optional_stats_keeps_transaction_text_visible(self):
        import asset_v4_cards as cards
        payload = self.season_payload(gamesPitched=30, era='3.25', strikeOuts=155)
        rows = n.enrich_transactions(self.transactions([self.move()]), lambda *a, **k: payload)
        spec = n.topic('transactions', rows, self.day)
        image = cards.item(2,spec,'MLB',rows[0]['head'],rows[0]['body'])
        self.assertEqual(image.info['asset_v4']['kind'],'text')
        self.assertIn('FAを宣言しました',image.info['asset_v4']['body'])

    def test_real_fixture_fingerprints(self):
        import hashlib
        pins = json.loads(Path('scripts/fixtures/offseason-real/protected-source.json').read_text(encoding='utf-8'))
        for path, digest in pins.items():
            self.assertEqual(hashlib.sha256(Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),digest,path)

    def test_real_transactions_and_sato_registration(self):
        from name_reading_guard import player_reading
        jp, table = n.names()
        payload = json.loads(Path('scripts/fixtures/offseason-real/transactions.json').read_text(encoding='utf-8'))
        stars = {r['person']['id'] for r in payload['transactions']}
        # 固定試験では日本人・大型の選別を分離し、全種別の実行を確かめる。
        table.update({r['person']['fullName']: r['person']['fullName'] for r in payload['transactions'] if r['person']['fullName'] not in table})
        rows = n.transaction_rows(payload, date(2025,10,29), date(2025,12,31), jp, table, stars)
        self.assertEqual({r['raw']['typeCode'] for r in rows}, {'DFA','SFA','TR'})
        murakami = next(r for r in rows if r['name'] == '村上宗隆')
        self.assertEqual(murakami['body'], '村上宗隆はホワイトソックスとFA契約を結びました')
        self.assertNotIn('ポスティング', str(rows))
        rendon = payload['transactions_2026']
        result = n.transaction_rows({'transactions':rendon}, date(2026,10,25), self.day,
                                    {}, {'Anthony Rendon':'アンソニー・レンドン'}, {543685})
        self.assertEqual(result[0]['body'], 'アンソニー・レンドンはエンゼルスからFAを宣言しました')
        self.assertNotIn('戦力外', result[0]['body'])
        self.assertEqual(jp['Teruaki Sato'], '佐藤輝明')
        self.assertEqual(player_reading('Teruaki Sato'), 'サトウテルアキ')
        sato = self.move('SFA', toTeam={'id':145})
        sato['person'] = {'id':999, 'fullName':'Teruaki Sato'}
        self.assertIn('佐藤輝明', self.transactions([sato])[0]['body'])
        self.assertEqual(self.transactions([self.move('SFA')]), [])

    def test_real_awards_all_positions_stable_and_no_silent_omission(self):
        jp, table = n.names()
        payloads = json.loads(Path('scripts/fixtures/offseason-real/awards.json').read_text(encoding='utf-8'))
        for ident in ('ALGG','NLGG','ALSS','NLSS'):
            raw = payloads[ident]
            # 名前辞書未登録なら部門全体を保留する。
            self.assertEqual(n.award_rows({ident:raw},2025,jp,table), [])
            # 実部門の並びの試験だけに公式英語名を利用。製品の辞書には追加しない。
            complete = dict(table, **{r['player']['nameFirstLast']: r['player']['nameFirstLast'] for r in raw['awards']})
            rows = n.award_rows({ident:raw},2025,jp,complete)
            topics = n.award_topics(rows,self.day,2025)
            self.assertEqual([len(t['items']) for t in topics], [4,3,3])
            actual = [r['event_id'] for t in topics for r in t['offseason']['events']]
            self.assertEqual(len(set(actual)),10)
            reverse = n.award_topics(list(reversed(rows)),self.day,2025)
            self.assertEqual([t['key'] for t in topics],[t['key'] for t in reverse])
            positions = [r['raw']['player']['primaryPosition']['abbreviation'] for t in topics for r in t['offseason']['events']]
            self.assertEqual(positions, sorted(positions,key=n.POSITION_ORDER.get))

    def award(self, name='Shohei Ohtani', season=2026, rank=1, **extra):
        return dict(season=str(season), rank=rank, player=dict(id=1, name=name), **extra)

    def test_calendar_only_confirmed_dates_and_eastern_labels(self):
        rows = n.schedule(self.day)
        self.assertEqual(len(rows), 4)
        self.assertEqual({r['date_et'] for r in rows}, {'2026-11-01', '2026-11-02'})
        self.assertFalse(any('ポスティング' in r['body'] for r in rows))
        self.assertEqual(n.schedule(date(2027, 10, 30)), [])

    def test_awards_missing_year_unknown_name_and_other_season_skip(self):
        jp, table = n.names()
        rows = [self.award(season=2025), self.award(name='Unknown'), dict(player=dict(id=1, name='Shohei Ohtani'))]
        self.assertEqual(n.award_rows({'NLMVP': {'awards': rows}}, 2026, jp, table), [])

    def test_award_before_announcement_is_empty_but_other_errors_stop(self):
        import requests
        def failing(status):
            def fetch(path, **params):
                raise requests.HTTPError(response=Mock(status_code=status))
            return fetch
        self.assertEqual(n.recipients('ALMVP', 2026, failing(404)), {'awards': []})
        with self.assertRaises(requests.HTTPError):
            n.recipients('ALMVP', 2026, failing(500))

    def test_rank_two_is_not_a_finalist(self):
        jp, table = n.names()
        self.assertEqual(n.award_rows({'NLMVP': {'awards': [self.award(rank=2)]}}, 2026, jp, table), [])
        rows = n.award_rows({'NLMVP': {'awards': [self.award(rank=2, notes='Finalist')]}}, 2026, jp, table)
        self.assertEqual(rows, [])

    def test_wrong_award_id_is_not_relabelled(self):
        jp, table = n.names()
        payload = {'NLMVP': {'awards': [dict(self.award(), id='ALCY')]}}
        self.assertEqual(n.award_rows(payload, 2026, jp, table), [])

    def test_japanese_first_and_stable_ids(self):
        jp, table = n.names()
        rows = n.award_rows({'ALMVP': {'awards': [self.award(name='Aaron Judge')]},
                             'NLMVP': {'awards': [self.award()]}}, 2026, jp, table)
        self.assertEqual(rows[0]['name'], '大谷翔平')
        a = n.topic('awards', rows, self.day)
        b = n.topic('awards', rows, self.day+timedelta(days=1))
        self.assertEqual(a['key'], b['key'])

    def test_busy_official_day_does_not_overfill_one_short(self):
        rows = [dict(event_id=str(i), head=str(i), body='公式の事実', source='https://statsapi.mlb.com/', japanese=False) for i in range(20)]
        self.assertEqual(len(n.topic('awards', rows, self.day)['items']), 4)
        self.assertEqual(len(n.topic('transactions', rows, self.day)['items']), 3)

    def move(self, code='DFA', **extra):
        return dict(id=100, date='2026-10-30T00:00:00Z', typeCode=code,
                    person=dict(id=1, fullName='Shohei Ohtani'), **extra)

    def transactions(self, rows, stars=()):
        jp, table = n.names()
        return n.transaction_rows({'transactions': rows}, self.day-timedelta(days=6), self.day, jp, table, set(stars))

    def test_move_types_are_not_conflated(self):
        for code, word in [('DFA', 'FAを宣言'), ('SGN', '契約が公式'), ('TR', 'トレードが公式')]:
            self.assertIn(word, self.transactions([self.move(code)])[0]['body'])
        self.assertNotIn('移籍', self.transactions([self.move()])[0]['body'])
        self.assertEqual(self.transactions([self.move(c) for c in ('FA', 'DES', 'OUT', 'REL', 'SC', 'IL')]), [])

    def test_posting_requires_explicit_official_record(self):
        self.assertEqual(self.transactions([self.move('X', typeDesc='Rumored posting')]), [])
        self.assertEqual(self.transactions([self.move('X', typeDesc='Posting')]), [])

    def test_trade_destination_requires_official_team_id(self):
        rows = self.transactions([self.move('TR', fromTeam={'id': 119}, toTeam={'id': 147})])
        self.assertIn('ドジャースからヤンキースへのトレード', rows[0]['body'])
        rows = self.transactions([self.move('DFA', fromTeam={'id': 119}, toTeam={'id': 147})])
        self.assertIn('ヤンキースからFAを宣言', rows[0]['body'])
        self.assertNotIn('への', rows[0]['body'])

    def test_transactions_reach_existing_v4_material_and_short_gates(self):
        import generate_asset_video as g
        import review_render_v3 as r3
        import sanity_material, short_content
        rows = self.transactions([
            dict(self.move('DFA'), id=101),
            dict(self.move('SGN', toTeam={'id': 119}), id=102),
            dict(self.move('TR', fromTeam={'id': 119}, toTeam={'id': 147}), id=103)])
        spec = n.topic('transactions', rows, self.day)
        with patch.dict(g.LIST_TOPICS, {spec['key']: spec}), patch.object(r3, 'LOOK', 'v4'):
            doc = g.build_narration(spec['key'])
        self.assertEqual(sanity_material.check(doc, sanity_material.grounding([doc])), [])
        self.assertEqual(short_content.assess(doc, [8]*len(doc['segments']), spec)['status'], 'passed')

    def test_unknown_name_outside_window_and_minor_moves_skip(self):
        rows = [dict(self.move(), date='2026-10-01'), dict(self.move(), date='2026-10-31'),
                dict(self.move(), person=dict(id=2, fullName='Aaron Judge'))]
        self.assertEqual(self.transactions(rows), [])
        self.assertEqual(len(self.transactions(rows, stars=[2])), 1)

    def test_malformed_official_response_is_failure(self):
        jp, table = n.names()
        with self.assertRaises(KeyError):
            n.award_rows({'NLMVP': {}}, 2026, jp, table)
        with self.assertRaises(KeyError):
            n.transaction_rows({}, self.day, self.day, jp, table, set())

    def document(self):
        import generate_asset_video as g
        spec = n.topic('schedule', n.schedule(self.day), self.day)
        with patch.dict(g.LIST_TOPICS, {spec['key']: spec}):
            doc = g.build_narration(spec['key'])
        return spec, doc

    def test_existing_material_and_information_checks(self):
        import sanity_material, short_content
        spec, doc = self.document()
        self.assertEqual(n.check(doc), [])
        self.assertEqual(sanity_material.check(doc, sanity_material.grounding([doc])), [])
        result = short_content.assess(doc, [8]*len(doc['segments']), spec)
        self.assertGreaterEqual(result['information_count'], 3)

    def test_changed_spoken_date_is_blocked(self):
        _, doc = self.document()
        segment = next(s for s in doc['segments'] if s['kind'] == 'list')
        segment['text'] = segment['text'].replace('11月1日', '11月9日')
        self.assertTrue(n.check(doc))

    def test_changed_saved_text_cannot_validate_itself(self):
        _, doc = self.document()
        doc['offseason']['events'][0]['body'] = '偽の記録'
        doc['sanity_materials'][-1]['offseason'] = copy.deepcopy(doc['offseason'])
        self.assertTrue(n.check(doc))

    def test_short_and_too_little_information_still_fail(self):
        import short_content
        spec, doc = self.document()
        self.assertEqual(short_content.assess(doc, [1]*len(doc['segments']), spec)['status'], 'held')
        spec['items'] = spec['items'][:1]
        self.assertEqual(short_content.assess(doc, [8]*len(doc['segments']), spec)['status'], 'held')

    def test_switch_default_and_stale_material(self):
        import asset_policy
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(n.enabled())
            self.assertTrue(asset_policy.paused('offseason_awards_test'))
        with patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': 'on'}):
            self.assertTrue(n.enabled())
            self.assertFalse(asset_policy.paused('offseason_awards_test'))
        spec, _ = self.document()
        self.assertTrue(n.available(spec, self.day))
        self.assertFalse(n.available(spec, self.day+timedelta(days=1)))

    def test_workflow_keeps_gates_in_order(self):
        text = Path('.github/workflows/offseason_news.yml').read_text(encoding='utf-8')
        self.assertIn("vars.COLLESPO_OFFSEASON_NEWS == 'on'", text)
        commands = ['sanity.py --general --strict', 'synthesize_narration.py --narration',
                    '--audio-dir', 'upload_youtube.py --video', 'offseason_news.py --record']
        positions = [text.index(c) for c in commands]
        self.assertEqual(positions, sorted(positions))

    def test_major_free_agents_use_official_thresholds(self):
        def fetch(path, **params):
            if path.startswith('awards/'):
                return {'awards': []}
            key = 'homeRuns' if params['group'] == 'hitting' else 'strikeOuts'
            limit = 30 if key == 'homeRuns' else 200
            return {'stats': [{'splits': [dict(season='2026', stat={key: limit+delta},
                player={'id': limit+delta}) for delta in (-1, 0)]}]}
        self.assertEqual(n.notable(2026, fetch), {30, 200})

    def test_collection_does_not_turn_network_failure_into_empty_awards(self):
        with self.assertRaises(ConnectionError):
            n.collect(self.day, 2026, lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))

    def test_generic_asset_picker_excludes_offseason(self):
        source = Path('scripts/next_asset.py').read_text(encoding='utf-8')
        self.assertIn("not k.startswith('offseason_')", source)

    def test_saved_events_cannot_change_winner_into_finalist(self):
        import generate_asset_video as g
        jp, table = n.names()
        rows = n.award_rows({'NLMVP': {'awards': [self.award()]}}, 2026, jp, table)
        spec = n.topic('awards', rows, self.day)
        with patch.dict(g.LIST_TOPICS, {spec['key']: spec}):
            doc = g.build_narration(spec['key'])
        self.assertEqual(n.check(doc), [])
        doc['offseason']['events'][0]['body'] = '最終候補になりました'
        doc['sanity_materials'][-1]['offseason'] = copy.deepcopy(doc['offseason'])
        self.assertTrue(n.check(doc))

    def test_sns_requires_own_production_workflow_and_offseason_switch(self):
        import asset_sns as sns
        from datetime import datetime, timezone
        key = 'offseason_awards_2026_123456abcdef'
        now = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)
        run = dict(path='.github/workflows/offseason_news.yml', head_branch='main', conclusion='success',
            repository={'full_name': sns.bd.REPO}, event='workflow_run',
            created_at='2026-10-30T12:00:00Z', updated_at='2026-10-30T12:30:00Z')
        record = dict(published_at='2026-10-30T12:20:00Z', video_id='abcdefghijk', privacy='public')
        with patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': ''}):
            self.assertEqual(sns.select(run, {key: record}, {key: {'style': 'v3'}}, now), [])
        with patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': 'on'}):
            rows = sns.select(run, {key: record}, {key: {'style': 'v3'}}, now)
            self.assertEqual(len(rows), 1)
            self.assertEqual(sns.select(dict(run, path='.github/workflows/season_review.yml'),
                                       {key: record}, {key: {'style': 'v3'}}, now), [])
            with patch.dict(sns.bd.SOURCES), patch.dict(sns.bd.KIND_WORDS):
                kind, _ = sns.register(key, 'offseason-news', run)
                self.assertEqual(sns.bd.KIND_WORDS[kind]['short'], 'MLB')
        with patch.dict(os.environ, {'V3_SNS_ENABLED': 'true', 'COLLESPO_OFFSEASON_NEWS': ''}), \
                patch.object(sns.bd, 'Ledger') as ledger:
            with self.assertRaises(RuntimeError):
                sns.distribute(run, rows, publish=True)
            ledger.assert_not_called()

    def test_cli_collect_pick_record_and_retry_do_not_repeat_events(self):
        import sys
        folder = Path('build/offseason') / ('pipeline-fixture-' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        previous = Path.cwd()
        materials = dict(schedule=n.schedule(self.day), awards=[], transactions=[])
        try:
            os.chdir(folder)
            with patch.object(n, 'collect', return_value=materials), \
                    patch.dict(os.environ, {'COLLESPO_OFFSEASON_NEWS': 'on'}):
                def cli(*args):
                    output = io.StringIO()
                    with patch.object(sys, 'argv', ['offseason_news', '--day', str(self.day), *args]), \
                            contextlib.redirect_stdout(output):
                        n.main()
                    return output.getvalue().strip()
                cli()
                key = cli('--pick')
                self.assertTrue(key.startswith('offseason_schedule_'))
                with self.assertRaises(FileNotFoundError):
                    cli('--record', key)
                Path('data/published_assets.json').write_text(json.dumps({'assets': {key: {'video_id': 'fixture-only'}}}), encoding='utf-8')
                cli('--record', key)
                state = json.loads(Path('data/offseason_published.json').read_text(encoding='utf-8'))
                self.assertEqual(len(state['events']), 4)
                self.assertEqual(state['topics'][key]['style'], 'v3')
                cli()
                self.assertEqual(cli('--pick'), '')
        finally:
            os.chdir(previous)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
