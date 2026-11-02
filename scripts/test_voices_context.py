"""11/2の依頼に記載された誤訳と、通信しない生成・停止経路の回帰試験。"""
import copy
import json
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import local_voices as lv
import generate_morning_short as g
import sanity_internal
import sanity
import sanity_refresh
import sanity_recheck
import voices_context as vc

FIX = json.loads((Path(__file__).parent/'fixtures/comment/voices-context-20261102.json').read_text(encoding='utf-8'))


class Context(unittest.TestCase):
    def document(self, original=None, ja=None):
        original = original or FIX['original']
        ja = ja or FIX['bad_translation']
        return dict(segments=[dict(kind='thread', text=ja+'。', meta=dict(source_voices=[
            dict(original=original, ja=ja, reply=True)]))])

    def test_real_missed_ball_cannot_be_swing(self):
        self.assertEqual(vc.unsupported(FIX['original'], FIX['bad_translation']), ['空振り'])
        self.assertTrue(vc.ambiguous_reply(FIX['original']))
        self.assertTrue(sanity_internal.check([self.document()]))

    def test_play_terms_and_precise_word_boundaries(self):
        for original, ja in [('Wonderful!', '守備が最高'), ('Great player', '投手が最高'),
                             ('missed the ball', '見逃した'), ('nice bank', '三振'),
                             ('nice strike', '三振'), ('k is a letter', '三振'),
                             ('great game', '好捕'), ('nice ball', '投球がいい')]:
            with self.subTest(original=original, ja=ja):
                self.assertTrue(vc.unsupported(original, ja))
        for original, ja in [('He whiffed', '空振りした'), ('He struck out', '三振した'),
                             ('10 Ks', '10三振'), ('10K', '10三振'), ('10Ks', '10三振'),
                             ('struck him out', '三振'), ('strikeout', '三振'),
                             ('called strike', '見逃し'), ('great pitcher', 'いい投手'),
                             ('great pitching', 'いい投球'), ('dropped the ball', '落球した'),
                             ('Gold Glove defense', '守備がいい'), ('great catch', '好捕')]:
            with self.subTest(original=original, ja=ja):
                self.assertFalse(vc.unsupported(original, ja))

    def test_short_clear_replies_remain(self):
        for text in ['Great catch!', 'Ohtani is amazing', 'He struck out ten', 'He hit a home run']:
            self.assertFalse(vc.ambiguous_reply(text))
        self.assertFalse(vc.unsupported('When he missed the ball', 'ボールを逃したとき'))

    def test_video_kind_never_assumes_rank(self):
        self.assertEqual(vc.intro([dict(video_title=FIX['video_description'])]), 'MLB公式の動画のコメント欄です。')
        self.assertEqual(vc.intro([dict(video_title='Gold Glove Awards', matchup='A vs. B')]), 'MLB公式の動画のコメント欄です。')
        self.assertIn('試合ハイライト', vc.intro([dict(video_title='Yankees vs. Dodgers Highlights')]))
        for videos in [[], [dict(video_title='Best plays')], [dict(matchup='A vs B'), dict(title='Awards')]]:
            self.assertNotIn('いちばん', vc.intro(videos))
            self.assertNotIn('試合', vc.intro(videos))

    @patch.object(lv.token_log, 'allowed', return_value=True)
    @patch.object(lv.token_log, 'record')
    def test_translate_receives_full_video_title_and_omits_ambiguous_reply(self, *_):
        item = dict(title='Great defense', video_title='Gold Glove Awards full title',
                    reply_texts=[FIX['original'], 'Great catch!'])
        response = NS(stop_reason='end_turn', content=[NS(type='text', text='1|称賛|守備が最高\n2|称賛|好捕！')])
        with patch('backstage_guard.create', return_value=response) as create:
            got = lv.translate(Mock(), [item])
        prompt = create.call_args.kwargs['messages'][0]['content']
        self.assertIn(item['video_title'], prompt)
        self.assertNotIn('への返信）'+FIX['original'], prompt)
        self.assertIn('原文にない打撃・守備・投球', prompt)
        self.assertEqual([r['original'] for r in got[0]['reply_ja']], ['Great catch!'])

    @patch.object(lv.token_log, 'allowed', return_value=True)
    @patch.object(lv.token_log, 'record')
    def test_translate_drops_wrong_scene_and_model_rejected_reply(self, *_):
        response = NS(stop_reason='end_turn', content=[NS(type='text', text='1|称賛|空振りした\n2|称賛|守備が最高\n3|不採用|不採用')])
        with patch('backstage_guard.create', return_value=response):
            got = lv.translate(Mock(), [dict(title='missed the ball'),
                                      dict(title='Great defense', reply_texts=['No idea what happened'])])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]['reply_ja'], [])

    def test_generation_attaches_used_originals_without_mutating_data(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/comment/voices-20261024.json').read_text(encoding='utf-8'))
        data = fixture['data']
        for voice in data['voices']['voices']:
            voice['video_title'] = FIX['video_description']
        before = copy.deepcopy(data)
        document = g.build_narration(data, 'voices')
        self.assertIn('MLB公式の動画のコメント欄です', document['segments'][0]['text'])
        self.assertNotIn('いちばん多かった試合', document['segments'][0]['text'])
        self.assertTrue(any((s.get('meta') or {}).get('source_voices') for s in document['segments']))
        self.assertEqual(data, before)

    def test_low_ambiguity_holds_only_matching_reply(self):
        doc = self.document('Great catch!', '素晴らしい捕球')
        issue = dict(severity='low', where='素晴らしい捕球', why='どの話にかかるか不明です')
        self.assertTrue(vc.checks([doc], [issue]))
        self.assertFalse(vc.checks([doc], [dict(issue, where='別の返信')]))
        self.assertFalse(vc.checks([doc], [dict(issue, why='少し口調が硬い')]))
        doc['segments'][0]['meta']['source_voices'][0]['reply'] = False
        self.assertFalse(vc.checks([doc], [issue]))

    def test_unused_bad_translation_does_not_hold(self):
        doc = self.document()
        doc['segments'][0]['text'] = '別の言葉です。'
        self.assertFalse(vc.checks([doc]))

    def structured_document(self):
        bad = dict(original='Great catch!', ja='素晴らしい捕球', reply=True)
        good = dict(original='Great catch again!', ja='次の捕球も素晴らしい', reply=True)
        return dict(segments=[
            dict(kind='thread', text='こう返っています。', meta=dict(quote_rows=[dict(said='こう返っています。', read=True, fact=True)])),
            dict(kind='thread', text=bad['ja']+'。', meta=dict(source_voices=[bad], quote_rows=[dict(said=bad['ja'], read=True)])),
            dict(kind='thread', text=good['ja']+'。', meta=dict(source_voices=[good], quote_rows=[
                dict(said=bad['ja'], read=False), dict(said=good['ja'], read=True)]))])

    def test_omit_independent_reply_removes_later_screen_history(self):
        doc = self.structured_document()
        before = copy.deepcopy(doc)
        issues = [dict(severity='low', where='素晴らしい捕球', why='どの話にかかるか不明')]
        repaired, omitted = vc.omit_low_replies(doc, issues)
        self.assertEqual(len(omitted), 1)
        self.assertEqual(doc, before)
        self.assertEqual(len(repaired['segments']), 2)
        import comment_render
        raw = dict(voices=[dict(ja='親コメント', reply_ja=[
            dict(ja='素晴らしい捕球'), dict(ja='次の捕球も素晴らしい')])])
        for seg in repaired['segments']:
            self.assertNotIn('素晴らしい捕球', seg['text'])
            self.assertNotIn('素晴らしい捕球', [r.get('said') for r in comment_render.voices_for_segment(seg, raw)])
        self.assertFalse(vc.checks([repaired], issues))
        self.assertFalse(vc.omit_low_replies(repaired, issues)[1])
        # 最後の返信も外す場合、返答の予告だけが残らない。
        doc['segments'] = doc['segments'][:2]
        self.assertEqual(vc.omit_low_replies(doc, issues)[0]['segments'], [])

    def test_legacy_or_combined_scene_is_held_without_partial_rewrite(self):
        issue = dict(severity='low', where='素晴らしい捕球', why='文脈が不明')
        doc = self.document('Great catch!', '素晴らしい捕球')
        self.assertEqual(vc.omit_low_replies(doc, [issue]), (doc, []))
        doc = self.structured_document()
        doc['segments'][1]['text'] += '素晴らしい捕球。'
        self.assertEqual(vc.omit_low_replies(doc, [issue]), (doc, []))

    def test_actual_v4_group_omits_reply_and_rebuilds_screen_rows(self):
        import comment_render
        import review_render_v3
        fixture = json.loads((Path(__file__).parent/'fixtures/comment/voices-20261024.json').read_text(encoding='utf-8'))
        data = fixture['data']
        replies = next(v['reply_ja'] for v in data['voices']['voices'] if v.get('reply_ja'))
        issues = [dict(severity='low', where=r['ja'], why='どの話にかかるか不明') for r in replies]
        with patch.dict(os.environ, fixture['env']), patch.object(review_render_v3, 'LOOK', 'v4'):
            doc = g.build_narration(data, 'voices')
            self.assertTrue(any(len((s.get('meta') or {}).get('quote_rows') or []) > 1 for s in doc['segments']))
            repaired, omitted = vc.omit_low_replies(doc, issues[:1])
            self.assertEqual(len(omitted), 1)
            for seg in repaired['segments']:
                self.assertNotIn(replies[0]['ja'].rstrip('。！!、.'), seg['text'])
                self.assertNotIn(replies[0]['ja'], [r.get('said') for r in comment_render.voices_for_segment(seg, data['voices'])])
            repaired, omitted = vc.omit_low_replies(doc, issues)
            self.assertEqual(len(omitted), len(replies))
            self.assertNotIn('こう返っています', ''.join(s['text'] for s in repaired['segments']))

    def test_pre_audio_cli_omits_reply_and_passes_recheck(self):
        doc = self.structured_document()
        issue = dict(kind='説明不足・文脈', severity='low', where='素晴らしい捕球', why='文脈が不明')
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            path = p/'narration.json'
            path.write_text(json.dumps(doc), encoding='utf-8')
            argv = sanity.command('morning_voices', path, p/'report.json', p/'hold.json')[1:]+['--omit-ambiguous-replies']
            with patch.object(sys, 'argv', argv), \
                 patch.dict(os.environ, ANTHROPIC_API_KEY='TEST', GITHUB_STEP_SUMMARY=''), \
                 patch.object(sanity, 'general', return_value=[issue]), \
                 patch.object(sanity, 'check_stat_files', return_value=[]), \
                 patch.object(sanity, 'check_scores', return_value=[]), \
                 patch.object(sanity_refresh, 'refresh', return_value=([], [])), \
                 patch.object(sanity_recheck, 'ai_review', return_value=([], {})), \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(sanity.main(), 0)
            self.assertEqual(json.loads((p/'hold.json').read_text())['status'], 'passed')
            repaired = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(len(repaired['segments']), 2)
            self.assertEqual(len(json.loads((p/'report.json').read_text(encoding='utf-8'))['reply_omissions']), 1)

    def test_strict_gate_holds_actual_error_and_low_reply_issue(self):
        for doc, issues in [(self.document(), []),
                            (self.document('Great catch!', '素晴らしい捕球'), [dict(
                                kind='説明不足・文脈', severity='low', where='素晴らしい捕球',
                                why='どの話にかかるか不明です')])]:
            with self.subTest(issues=issues), tempfile.TemporaryDirectory() as folder:
                p = Path(folder)
                (p/'narration.json').write_text(json.dumps(doc), encoding='utf-8')
                with patch.object(sys, 'argv', sanity.command('test', p/'narration.json', p/'report.json', p/'hold.json')[1:]), \
                     patch.dict(os.environ, ANTHROPIC_API_KEY='TEST', GITHUB_STEP_SUMMARY=''), \
                     patch.object(sanity, 'general', return_value=issues), \
                     patch.object(sanity, 'check_stat_files', return_value=[]), \
                     patch.object(sanity, 'check_scores', return_value=[]), \
                     patch.object(sanity_refresh, 'refresh', return_value=([], [])), \
                     patch.object(sanity_recheck, 'ai_review', return_value=([], {})), \
                     patch('sys.stdout', new_callable=io.StringIO):
                    self.assertEqual(sanity.main(), 1)
                self.assertEqual(json.loads((p/'hold.json').read_text(encoding='utf-8'))['status'], 'held')
                report = json.loads((p/'report.json').read_text(encoding='utf-8'))
                self.assertTrue(report['upload_held'])

    @patch.dict(os.environ, {'YOUTUBE_API_KEY': 'TEST'}, clear=True)
    def test_fetch_keeps_full_source_video_title(self):
        video = dict(video_id='fictional', title='Gold Glove Awards '+('full title '*10))
        response = Mock(status_code=200)
        response.json.return_value = dict(items=[dict(snippet=dict(topLevelComment=dict(
            snippet=dict(textOriginal='Amazing defense indeed', likeCount=4))))])
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'buzz.json'
            p.write_text(json.dumps(dict(videos=[video])), encoding='utf-8')
            with patch.object(lv.requests, 'get', return_value=response):
                got = lv.fetch_youtube_comments(str(p))
        self.assertEqual(got[0]['video_title'], video['title'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
