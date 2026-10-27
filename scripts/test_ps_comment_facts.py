"""10/27の公開実材料で、選択・原稿・再点検・訂正を通して検査する。"""
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ps_comment_facts as guard
import sanity_material
import sanity_sources
import sanity_recheck

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'scripts/fixtures/ps_comment/849804.json').read_text(encoding='utf-8'))


class CommentFacts(unittest.TestCase):
    def setUp(self):
        self.topic = copy.deepcopy(FIXTURE['topic'])
        self.score = self.topic['game_v4']['score']

    def narration(self, topic=None):
        import generate_asset_video as asset
        topic = topic or self.topic
        with patch.dict(asset.LIST_TOPICS, {topic['key']: topic}):
            return asset.build_narration(topic['key'])

    def test_real_topic_is_attached_to_actual_asset_narration(self):
        document = self.narration()
        materials = sanity_material.grounding([document])
        game = next(g for s in materials for g in s.get('games', []) if g.get('game_pk') == 849804)
        self.assertEqual(game['final_score'], dict(away=10, home=1))
        self.assertEqual(game['ps_score']['innings'][-1], dict(num=9, away=0, home=1))
        self.assertEqual(game['decisive']['inning'], '3回表')
        self.assertIn('ガッサー 6回を無失点', dict(game['items'])['先発'])
        self.assertEqual(sanity_sources.availability([document], materials)[0]['categories']['試合結果'], '材料あり')
        short = sanity_recheck.short_materials([document], materials)
        self.assertTrue(any(g.get('ps_score') for s in short for g in s.get('games', [])))

    def test_real_high_is_confirmed_and_survives_recheck_without_ai(self):
        document = self.narration()
        materials = sanity_material.grounding([document])
        issues, errors = sanity_material.assess([FIXTURE['issue']], [document], materials)
        self.assertTrue(errors)
        self.assertTrue(sanity_material.blocking(issues[0]))
        self.assertEqual(issues[0]['verification'], '材料と矛盾あり')
        # 再取得に失敗しても添付した当時の材料を保持する。
        with patch('sanity_refresh.fetch', side_effect=OSError('offline')):
            reviewed, errors, _, attempts = sanity_recheck.run([document], issues, materials, [], errors)
        self.assertTrue(sanity_material.blocking(reviewed[0]))
        self.assertTrue(errors)
        self.assertEqual(attempts[-1]['ai']['calls'], 0)

    def test_strict_asset_cli_holds_upload_without_ai(self):
        import sanity
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            narr, out, hold = [base / n for n in ('narr.json', 'report.json', 'hold.json')]
            narr.write_text(json.dumps(self.narration(), ensure_ascii=False), encoding='utf-8')
            args = ['sanity.py', '--strict', '--kind', 'asset', '--narration', str(narr),
                    '--out', str(out), '--hold-record', str(hold)]
            with patch.object(sys, 'argv', args), patch('sanity_refresh.fetch', side_effect=OSError('offline')):
                status = sanity.main()
            self.assertEqual(status, 1)
            self.assertTrue(json.loads(out.read_text(encoding='utf-8'))['upload_held'])
            self.assertEqual(json.loads(hold.read_text(encoding='utf-8'))['status'], 'held')

    def test_selection_skips_real_bad_translation_and_uses_next_candidate(self):
        import ps_game_story as story
        def candidate(title, ja, likes):
            return dict(title=title, ja=ja, likes=likes, matchup='BREWERS vs RAYS',
                        at='2026-10-27T03:42:25Z', url='https://www.youtube.com/watch?v=b7BE1gwgv64')
        bad = candidate(self.topic['voice']['text'], self.topic['voice']['said'], 72)
        good = candidate('Great pitching', 'ブリュワーズの投手が素晴らしい', 1)
        feed = dict(gameData=dict(teams=dict(away=dict(id=158, teamName='Brewers'), home=dict(id=139, teamName='Rays'))),
                    liveData=dict(linescore=dict(teams={s: dict(runs=self.score[s]['total']) for s in ('away', 'home')},
                        innings=[dict(num=r['num'], away=dict(runs=r['away']), home=dict(runs=r['home']))
                                 for r in self.score['innings']])))
        self.assertEqual(guard.from_feed(feed)['home']['total'], 1)
        selected = story.pick_voice(dict(voices=[bad, good]), feed, '2026-10-27', {}, {}, {}, [])
        self.assertEqual(selected['said'], good['ja'])
        self.assertIsNone(story.pick_voice(dict(voices=[bad]), feed, '2026-10-27', {}, {}, {}, []))

    def test_numeric_claims_and_missing_facts_are_not_delegated_to_ai(self):
        for text in ('レイズが最後に2点を返した', 'レイズが最後に1点を返し、点差が8点まで縮まった',
                     'レイズが最後に大量得点した', 'レイズが5回に1点を返した',
                     'レイズが最後に一気に攻め立てた。3点追加', 'レイズが2点',
                     'レイズが最後に1点返して、さらに3点追加', 'レイズが満塁弾を打った', 'レイズが最後に三点追加'):
            with self.subTest(text=text):
                self.assertFalse(guard.acceptable('Rays finally scored a run', text, self.score))
        self.assertFalse(guard.acceptable('Rays scored a big run', 'レイズが最後に1点を返した', {}))
        self.assertFalse(guard.acceptable('Rays scored a big run', 'レイズが素晴らしい', self.score))
        self.assertTrue(guard.review('レイズが最後に1点を返して8点差に縮めた', self.score)[0])

    def test_accurate_one_run_and_opinion_remain_candidates(self):
        self.assertTrue(guard.acceptable(self.topic['voice']['text'],
            'レイズが最後に1点だけ返し、点差が9点まで縮まった', self.score))
        self.assertFalse(guard.review('レイズが最後に1点だけ返し、点差が9点まで縮まった', self.score)[0])
        self.assertTrue(guard.acceptable('Finally great pitching', 'ようやく素晴らしい投球が見られた', {}))
        # 勝者が1点しか取っていないとは決めつけず、当該球団の値を使う。
        self.assertTrue(guard.acceptable('Brewers scored 8 runs', 'ブリュワーズが5回に8点を取った', self.score))

    def test_negation_wish_and_other_game_are_not_confirmed_contradictions(self):
        for text in ('レイズは大量得点ではなく最後に1点だけ返した',
                     'レイズは次は大量得点してほしい', 'レイズは前の試合で3点を取った',
                     'ブリュワーズが1点を取った', 'レイズが8点差まで縮めた'):
            with self.subTest(text=text):
                errors, unknown = guard.review(text, self.score)
                self.assertEqual(errors, [])
                self.assertTrue(unknown)

    def test_correction_removes_voice_from_both_narration_and_card(self):
        import correct_video
        fix = correct_video.load_fix('ps_comment_849804_20261027')
        corrected = correct_video.apply_edits(self.topic, fix['edits'])
        self.assertIsNone(corrected['voice'])
        self.assertNotIn('ハイライトのコメント欄から', dict(corrected['items']))
        document = self.narration(corrected)
        self.assertNotIn('大量得点', json.dumps(document, ensure_ascii=False))
        self.assertEqual(sanity_material.check(document, sanity_material.grounding([document])), [])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
