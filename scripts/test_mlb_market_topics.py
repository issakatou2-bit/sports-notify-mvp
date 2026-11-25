"""MLBの材料、代表から引き継いだ画面、手動公開の接続を確認する。"""

import metan_tone
import copy
import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import short_content
import soccer_national_topics as topics
from synthesize_narration import baseball_average_reading


class MarketTopics(unittest.TestCase):
    def test_both_scripts_keep_material_and_switch_sport(self):
        materials = topics.national.read(topics.MLB_FOLLOWUPS)['events']
        self.assertEqual(set(materials), {'sato-cubs', 'taira-bluejays'})
        for event, material in materials.items():
            with self.subTest(event=event):
                doc = topics.mlb_narration('followup-' + event)
                self.assertEqual(topics.check(doc), [])
                self.assertEqual(doc['program'], topics.MLB_PROGRAM)
                self.assertEqual(doc['screen_title'], 'MLB')
                player = material['hook']['score']
                self.assertEqual(doc['segments'][0]['meta']['hook']['score'], player)
                info = short_content.information(doc)
                self.assertEqual(len(info), 5)
                for index, item in enumerate(material['items']):
                    ask, answer = doc['segments'][2*index:2*index+2]
                    self.assertEqual((ask['speaker'], ask['text']), (topics.ZUNDA, item['ask']))
                    self.assertEqual((answer['speaker'], answer['text']), (topics.METAN, metan_tone.fix(item['text'])))
                    self.assertEqual(answer['meta']['followup_sources'], item['sources'])
                    self.assertGreaterEqual(len(set(item['sources'])), 2)
                    if 'big' in item:
                        self.assertTrue(topics.mlb_big_in_text(item['big'], answer['text']))
                snippet = topics.metadata(doc)['snippet']
                self.assertIn(f'#MLB #メジャーリーグ #移籍 #{player}', snippet['description'])
                self.assertNotIn('#サッカー', snippet['description'])
                for name, reading in material['readings'].items():
                    self.assertEqual(topics.speech_readings(doc)[name], ('player',reading))
        self.assertEqual(baseball_average_reading('.306'), '3割6厘')

    def test_reject_missing_number_duplicate_source_and_changed_script(self):
        doc = topics.mlb_narration('followup-taira-bluejays')
        for field, value in [('big', dict(label='譲渡金', value='1387.6', unit='万ドル')),
                             ('sources', ['https://example.com'] * 2)]:
            data = copy.deepcopy(doc['followup_material'])
            data['items'][2][field] = value
            with self.subTest(field=field), self.assertRaises(topics.Unavailable):
                topics.followup_panels(data, mlb=True)
        doc['segments'][1]['text'] += '。'
        self.assertTrue(topics.check(doc))

    def test_metan_tone_is_gated_in_build_and_sanity(self):
        # 台本はめたんの口調で書いてあり、1件でも「です・ます」が残れば原稿を作らない。sanity も同じ kind の原稿を検査する。
        import json, tempfile
        import sanity
        for event in ('sato-cubs', 'taira-bluejays'):
            doc = topics.mlb_narration('followup-' + event)
            self.assertEqual(list(metan_tone.check(doc['segments'])), [])
            for item in topics.national.read(topics.MLB_FOLLOWUPS)['events'][event]['items']:
                self.assertEqual(metan_tone.problems(item['text']), [], item['text'])
            bad = copy.deepcopy(doc)
            bad['segments'][1]['text'] = '球団の正式発表はまだです。ESPNが報じています。'
            with self.assertRaises(ValueError):
                topics.tone_gate(bad)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'narration.json'
                path.write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
                self.assertTrue(any('めたんの語尾' in line for line in sanity.check_narration([str(path)])))

    def test_frames_have_mlb_badge_and_sources(self):
        env = {key: value for key,value in os.environ.items() if not key.startswith('COLLESPO_')}
        env.update(PYTHONUTF8='1', COLLESPO_STYLE='v2', COLLESPO_SOCCER_LOOK='v6',
                   COLLESPO_SOCCER_FOCUS='on', COLLESPO_SHORT_LOOK='v4', COLLESPO_SOLO_HOST='metan')
        result = subprocess.run([sys.executable, '-c', FRAME_PROBE],
                                cwd=Path(__file__).resolve().parent, env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_publish_is_manual_and_uses_own_ledger(self):
        import yaml
        workflow = topics.ROOT / '.github/workflows/mlb_market_topics.yml'
        config = yaml.safe_load(workflow.read_text(encoding='utf-8'))
        triggers = config[True]
        self.assertEqual(set(triggers), {'workflow_dispatch'})
        self.assertFalse(triggers['workflow_dispatch']['inputs']['publish']['default'])
        self.assertIn('inputs.publish && !inputs.sample_only', config['env']['PUBLISH'])
        steps = {step.get('name'): step for step in config['jobs']['build']['steps']}
        self.assertEqual(steps['Upload to YouTube']['if'], "env.PUBLISH == 'true'")
        self.assertIn('--kind mlb_market_topic --sport mlb', steps['Upload to YouTube']['run'])
        self.assertIn(topics.MLB_LEDGER.name, steps['Commit publication record']['run'])
        self.assertNotIn(topics.LEDGER.name, steps['Commit publication record']['run'])
        doc = topics.mlb_narration('followup-sato-cubs')
        with patch.object(topics.national, 'read', return_value={}), patch.object(topics.national, 'save') as save:
            topics.record_published(doc, 'video', '2026-11-25T00:00:00+00:00')
        path, ledger = save.call_args.args
        self.assertEqual(path, topics.MLB_LEDGER)
        self.assertEqual(ledger[doc['topic_key']]['publish_at'], '2026-11-25T09:00:00+09:00')


    def test_replacing_held_video_needs_its_id(self):
        doc = topics.mlb_narration('followup-sato-cubs')
        ledger = {doc['topic_key']: dict(video_id='OLD', publish_at='x', title='t')}
        args = SimpleNamespace(narration='n', games='g', sport='mlb', kind=topics.MLB_PROGRAM, publish_at='', video='v')
        def run(replaces):
            env = {'COLLESPO_MLB_MARKET_TOPIC_PUBLISH': 'true', 'COLLESPO_TOPIC_REPLACES': replaces}
            def read(path):
                return ledger if path == topics.MLB_LEDGER else (doc if path == 'n' else doc['followup_material'])
            with patch.dict(os.environ, env), patch.object(topics.national, 'read', side_effect=read),                     patch.object(topics, 'check', return_value=[]):
                return topics.validate_upload(args)
        for wrong in ('', 'OTHER'):
            with self.assertRaisesRegex(ValueError, '予約・投稿済み'):
                run(wrong)
        with self.assertRaisesRegex(ValueError, '未来の予約時刻'):
            run('OLD')
        with patch.object(topics.national, 'read', return_value=dict(ledger)), patch.object(topics.national, 'save') as save:
            topics.record_published(doc, 'NEW', '2026-11-25T13:00:00+00:00')
        entry = save.call_args.args[1][doc['topic_key']]
        self.assertEqual((entry['video_id'], entry['replaced']), ('NEW', ['OLD']))

FRAME_PROBE = """
import review_render_v3 as r3
import soccer_national_topics as topics
import soccer_national_topics_render as render
from mlb_pinstripe_badge import render as badge
from soccer_v5_cards import L

for event, team in [('sato-cubs', '112'), ('taira-bluejays', '141')]:
    doc = topics.mlb_narration('followup-' + event)
    clubs = render.clubs_for(doc)
    for i, seg in enumerate(doc['segments'][:-1]):
        r3.set_caption(seg['text'], 5, 60, speaker=seg['speaker'])
        image = render.frame(1.5, seg, doc, clubs, i, len(doc['segments']))
        layout = image.info['v3_layout']
        text = ' '.join(entry['text'] for entry in layout)
        assert 'MLB' in text and '日本代表' not in text and '#サッカー' not in text, text
        source = doc['followup_material']['items'][i//2]['source_names']
        assert source in text.replace(' ', ''), (event, i, source, text)
        # 字幕の箱と出典は YouTube ショートの UI に隠れない安全範囲の内側（SAFE_BOTTOM 1440）にある。
        import shorts_safe_area as safe
        shown = {e['role']: e['box'] for e in layout if e['role'] in ('caption', 'source')}
        assert set(shown) == {'caption', 'source'}, (event, i, shown)
        assert not [b for b in shown.values() if safe.outside(b)], (event, i, shown)
        assert render.caption_source_problems(image) == [], (event, i)
        errors = render.validate_frame(image, clubs, doc)
        assert not errors, (event, i, errors)
        stamp = badge(team, 108, 54)
        assert image.getpixel((L+454, 190)) == stamp.getpixel((54,27))[:3], (event, i)
"""



class DurationLimit(unittest.TestCase):
    def test_mlb_dialogue_up_to_90_but_soccer_topic_stays_45(self):
        self.assertEqual(topics.MLB_LIMIT, 90)
        self.assertEqual(topics.LIMIT, 45)

    def test_market_report_stays_60(self):
        doc = {'offseason': {'kind': 'market'}, 'segments': []}
        self.assertEqual(short_content.assess(doc, [1.0], maximum=90)['maximum_seconds'], 60)

if __name__ == '__main__':
    unittest.main(argv=[__file__])
