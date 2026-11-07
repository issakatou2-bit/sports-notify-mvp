"""固定用語原稿の欠落・言い換え・誤札・自動採用を防ぐ。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import asset_policy
import duo
import generate_asset_video as gav
import generated_topics
import mlb_terms
import next_asset


class TermsTest(unittest.TestCase):
    def test_all_eight_preserve_material(self):
        raw = json.loads((mlb_terms.ROOT / 'data/mlb_terms.json').read_text(encoding='utf8'))['terms']
        self.assertEqual(len(raw), 8)
        for row in raw:
            with self.subTest(topic=row['key']):
                spec = gav.LIST_TOPICS[row['key']]
                doc = gav.build_narration(row['key'])
                segs = doc['segments']
                self.assertEqual([s['text'] for s in segs[:-1]], [s['text'] for s in row['lines']])
                self.assertEqual(spec['items'], [(c['head'], c['body']) for c in row['cards']])
                self.assertEqual(spec['title'], row['title'])
                self.assertEqual(duo.check_term(segs, spec), [])
                self.assertLessEqual(duo.estimate(segs), 40)
                self.assertEqual(doc['duration_budget']['limit'], 40)
                for line, seg in zip(row['lines'], segs):
                    meta = seg['meta']
                    self.assertTrue(meta['duo'])
                    self.assertEqual(seg['speaker'], duo.ZUNDA if line['who'] == 'zundamon' else duo.METAN)
                    self.assertEqual(meta.get('term_card'), line.get('card'))
                    if seg['speaker'] == duo.ZUNDA:
                        self.assertNotIn('term_card', meta)
                        self.assertNotIn('start', meta)
                    if 'term_card' in meta:
                        self.assertTrue(0 <= meta['term_card'] < len(row['cards']))
                self.assertEqual(segs[-1]['text'], __import__('review_render_v3').OUTRO_TEXT)

    def test_no_auto_selection_even_with_player_name_and_stats(self):
        for key, spec in mlb_terms.load().items():
            self.assertIn(key, generated_topics.keys())
            trap = dict(spec, title='大谷翔平', source='MLB Stats API', game_type='R')
            self.assertFalse(asset_policy.selectable(key, trap, {'大谷翔平'}))
            self.assertFalse(asset_policy.selectable('asset:' + key, trap, {'大谷翔平'}))

    def test_actual_audio_gate(self):
        spec = mlb_terms.load()['mlb_term_qo']
        segments = duo.term(spec)
        self.assertTrue(duo.check_term(segments, spec, [5] * len(segments)))
        self.assertTrue(duo.check_term(segments, spec, [0] * len(segments)))
        changed = deepcopy(segments)
        changed[0]['text'] += '！'
        self.assertTrue(duo.check_term(changed, spec))
        changed = deepcopy(segments)
        changed[0]['meta']['term_card'] = 0
        self.assertTrue(duo.check_term(changed, spec))

    def test_missing_audio_cannot_make_video(self):
        import sys
        import review_render_v3 as r3
        doc = gav.build_narration('mlb_term_qo')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / 'narration.json'
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf8')
            manifest = dict(segments=[dict(s, file=None, duration=0) for s in doc['segments']])
            (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
            args = ['generate_asset_video.py', '--topic', 'mlb_term_qo', '--narration', str(path),
                    '--audio-dir', str(folder), '--out', str(folder / 'render')]
            with patch.object(r3, 'LOOK', 'v4'), patch.object(sys, 'argv', args):
                with self.assertRaisesRegex(ValueError, 'VOICEVOX実音声'):
                    gav.main()
            self.assertFalse(list(folder.rglob('*.mp4')))

    def test_invalid_cards_fail_on_load(self):
        raw = json.loads((mlb_terms.ROOT / 'data/mlb_terms.json').read_text(encoding='utf8'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'terms.json'
            for value in (-1, 3, True):
                bad = deepcopy(raw)
                bad['terms'][0]['lines'][2]['card'] = value
                path.write_text(json.dumps(bad), encoding='utf8')
                with self.assertRaises(ValueError):
                    mlb_terms.load(path)
            bad = deepcopy(raw)
            bad['terms'][0]['lines'][0]['card'] = 0
            path.write_text(json.dumps(bad), encoding='utf8')
            with self.assertRaises(ValueError):
                mlb_terms.load(path)

    def test_metadata_published_only(self):
        spec = mlb_terms.load()['mlb_term_qo']
        meta = mlb_terms.metadata(spec, {'assets': {}})
        self.assertEqual(meta['title'], spec['title'])
        self.assertEqual(meta['lead'][0], 'MLB用語：' + spec['term'])
        self.assertIn('出典：' + spec['source_label'] + ' ' + spec['source_url'], meta['lead'])
        self.assertEqual(spec['longform_url'], '')
        for privacy in ('private', 'unlisted', 'public'):
            saved = {'assets': {'mlb_term_fa': dict(privacy=privacy, url='https://youtu.be/example', published_at='2026-01-01T00:00:00Z')}}
            leads = mlb_terms.metadata(spec, saved)['lead']
            self.assertEqual(any(s.startswith('あわせて：') for s in leads), privacy == 'public')
        for extra in ({'hold_video': True}, {'publish_at': '2099-01-01T00:00:00Z'}):
            saved = {'assets': {'mlb_term_fa': dict(privacy='public', url='https://youtu.be/example', published_at='2026-01-01T00:00:00Z', **extra)}}
            self.assertFalse(any(s.startswith('あわせて：') for s in mlb_terms.metadata(spec, saved)['lead']))

    def test_final_metadata_and_information(self):
        import upload_youtube as yt
        import short_content
        for key, spec in mlb_terms.load().items():
            with self.subTest(topic=key):
                doc = gav.build_narration(key)
                meta = yt.build_asset_metadata(key, doc)['snippet']
                self.assertEqual(meta['title'], spec['title'])
                self.assertEqual(meta['description'].splitlines()[0], 'MLB用語：' + spec['term'])
                self.assertIn('出典：' + spec['source_label'] + ' ' + spec['source_url'], meta['description'])
                self.assertGreaterEqual(len(short_content.information(doc, spec)), 3)

    def test_daily_limit_applies_to_manual_terms(self):
        with patch.object(next_asset, 'posted_today', return_value=True):
            self.assertTrue(next_asset.daily_limit_reached('unused', 'mlb_term_qo'))
            self.assertTrue(next_asset.daily_limit_reached('unused', 'mlb_term_qo', again=True))
        with patch.object(next_asset, 'posted_today', return_value=False) as today:
            self.assertFalse(next_asset.daily_limit_reached('unused', 'mlb_term_qo'))
        # 毎晩の資産動画とは別の枠。用語の回だけを数える。
        self.assertEqual(today.call_args.kwargs, {'kinds': {'mlb'}})

    def test_frames_eight_terms_keep_cards_in_bounds(self):
        import review_render_v3 as r3
        with patch.object(r3, 'LOOK', 'v4'):
            for key, spec in mlb_terms.load().items():
                gav.VOICE_CREDIT = duo.credit(duo.term(spec))
                for seg in duo.term(spec):
                    with self.subTest(topic=key, line=seg['meta'].get('term_line', 'outro')):
                        gav.set_asset_caption(seg, 5, 35, spec)
                        image = gav.render_v3(1, seg['kind'], seg['meta'], spec, key, seg, 5)
                        self.assertEqual(image.size, (1080, 1920))
                        if seg['kind'] != 'outro':
                            self.assertEqual(image.info['asset_v4']['kind'], 'term')
                            self.assertTrue(image.info['skip_short_effects'])


if __name__ == '__main__':
    import sys
    unittest.main(argv=[sys.argv[0]])
