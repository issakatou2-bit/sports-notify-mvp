"""欧州サッカーの分析ショート。材料・画面の札・出典・公開の班を偽の材料で確かめる。"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import soccer_national_topics as topics
import topic_dialogue


ROOT = Path(__file__).resolve().parents[1]
SUBJECT = 'マイケル・オリーゼ'


def material():
    return dict(
        checked_on='2026-11-27',
        title='クリスタルパレス 勝点22で立て直し オリーゼの数値',
        league='プレミアリーグ',
        team='Crystal Palace',
        readings={SUBJECT: 'マイケルオリーゼ'},
        hook=dict(score=SUBJECT, result='監督交代', subject='勝点', big='22', unit='', note='ここまでの勝点'),
        opening='クリスタルパレスの動きが気になるのだ！',
        items=[
            dict(ask='勝点は、どうなのだ？', text=f'クリスタルパレスは勝点22で、{SUBJECT}が活躍しているわ。',
                 head='リーグの位置', rows=[['勝点', '22']],
                 big=dict(label='勝点', value='22', unit=''),
                 source_names='プレミアリーグ公式・ESPN',
                 sources=['https://www.premierleague.com/tables', 'https://www.espn.com/soccer/standings']),
            dict(ask='得点は、どうなのだ？', text=f'{SUBJECT}はリーグ戦で5得点だったわ。',
                 head='個人の数字', rows=[['得点', '5']],
                 big=dict(label='得点', value='5', unit=''),
                 source_names='ESPN・クラブ公式',
                 sources=['https://www.espn.com/soccer/standings', 'https://www.cpfc.co.uk/news']),
        ],
        sub='数字で読む',
    )


class AnalysisTopics(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'topics.json'
        self.write(material())
        self.applied = patch.object(topics, 'ANALYSIS', self.path)
        self.applied.start()
        self.addCleanup(self.applied.stop)

    def write(self, data):
        self.path.write_text(json.dumps({'events': {'palace': data}}, ensure_ascii=False), encoding='utf-8')

    def doc(self):
        return topics.analysis_narration('analysis-palace')

    def test_script_and_material_are_made_from_fake_material(self):
        doc = self.doc()
        self.assertEqual(topics.check(doc), [])
        self.assertEqual(topic_dialogue.problems(doc['segments']), [])
        self.assertEqual(doc['program'], topics.PROGRAM)
        self.assertEqual(doc['screen_title'], 'プレミアリーグ')
        self.assertEqual(doc['sub'], '数字で読む')
        self.assertEqual(doc['topic_key'], 'analysis-palace')
        self.assertTrue(all(s['meta'].get('sub') == '数字で読む'
                            for s in doc['segments'] if s['kind'] != 'outro'))
        self.assertEqual(doc['analysis_material'], material())
        self.assertEqual(doc['segments'][0]['meta']['hook']['score'], SUBJECT)
        self.assertEqual([s['speaker'] for s in doc['segments'][-3:-1]], [topics.ZUNDA, topics.METAN])
        self.assertTrue(any('22' in s['text'] for s in doc['segments'][-3:-1]))
        out = Path(self.folder.name) / 'out'
        topics.main(['--sport', 'soccer', '--topic', 'analysis-palace', '--out', str(out)])
        self.assertEqual(json.loads((out / 'narration.json').read_text(encoding='utf-8')), topics.doc_as_json(doc))
        self.assertEqual(json.loads((out / 'material.json').read_text(encoding='utf-8')), material())

    def test_one_source_and_a_missing_number_are_stopped(self):
        data = material()
        data['items'][0]['sources'] = ['https://www.premierleague.com/tables']
        self.write(data)
        with self.assertRaises(topics.Unavailable):
            self.doc()
        data = material()
        data['items'][0]['big']['value'] = '99'
        self.write(data)
        with self.assertRaises(topics.Unavailable):
            self.doc()

    def test_the_reading_of_the_opening_name_is_required(self):
        data = material()
        data['readings'] = {}
        self.write(data)
        with self.assertRaises(topics.Unavailable):
            self.doc()

    def test_a_second_publication_of_the_same_key_is_stopped(self):
        doc = self.doc()
        ledger = {doc['topic_key']: dict(video_id='OLD', publish_at='x', title='t')}
        args = SimpleNamespace(narration='n', games='g', sport='soccer', kind=topics.ANALYSIS_PROGRAM,
                               publish_at='', video='v')

        def read(path):
            return ledger if path == topics.ANALYSIS_LEDGER else (doc if path == 'n' else doc['analysis_material'])

        env = {'COLLESPO_SOCCER_ANALYSIS_PUBLISH': 'true', 'COLLESPO_TOPIC_REPLACES': ''}
        with patch.dict(os.environ, env), patch.object(topics.national, 'read', side_effect=read),         patch.object(topics, 'check', return_value=[]):
            with self.assertRaisesRegex(ValueError, '予約・投稿済み'):
                topics.validate_upload(args)
        with patch.dict(os.environ, env), patch.object(topics.national, 'read', return_value={}),         patch.object(topics.national, 'save') as save:
            topics.record_published(doc, 'NEW', '2026-11-27T04:00:00+00:00')
        path, saved = save.call_args.args
        self.assertEqual(path, topics.ANALYSIS_LEDGER)
        self.assertEqual(saved[doc['topic_key']]['publish_at'], '2026-11-27T13:00:00+09:00')
        before = {doc['topic_key']: dict(video_id='OLD', publish_at='x', title='t')}
        with patch.object(topics.national, 'read', return_value=copy.deepcopy(before)),         patch.object(topics.national, 'save') as save:
            topics.record_published(doc, 'NEW', '2026-11-27T04:00:00+00:00')
        self.assertEqual(save.call_args.args[1][doc['topic_key']]['replaced'], ['OLD'])

    def test_default_publish_flag_does_not_allow_upload(self):
        doc = self.doc()
        args = SimpleNamespace(narration='n', games='g', sport='soccer', kind=topics.ANALYSIS_PROGRAM,
                               publish_at='', video='v')
        env = {key: value for key, value in os.environ.items() if not key.startswith('COLLESPO_')}

        def read(path):
            return {} if path == topics.ANALYSIS_LEDGER else (doc if path == 'n' else doc['analysis_material'])

        with patch.dict(os.environ, env, clear=True), patch.object(topics.national, 'read', side_effect=read),         patch.object(topics, 'check', return_value=[]):
            with self.assertRaisesRegex(ValueError, '手動指定'):
                topics.validate_upload(args)

    def test_render_keeps_the_league_and_the_sub_label(self):
        import review_render_v3 as r3
        import soccer_national_topics_render as render
        doc = self.doc()
        clubs = render.clubs_for(doc)
        shown = 0
        for i, seg in enumerate(doc['segments']):
            if seg['kind'] == 'outro':
                continue
            r3.set_program_clock(0)
            r3.set_caption(seg['text'], 3.2, 20, speaker=seg['speaker'])
            image = render.frame(1.0, seg, doc, clubs, i, len(doc['segments']))
            text = ' '.join(entry['text'] for entry in image.info['v3_layout'])
            self.assertIn('プレミアリーグ', text)
            if not seg['meta'].get('hook'):
                self.assertIn('数字で読む', text)
                shown += 1
            self.assertEqual(render.validate_frame(image, clubs, doc), [])
        r3.set_program_clock(None)
        self.assertEqual(shown, 5)

    def test_a_club_badge_is_optional(self):
        import soccer_national_topics_render as render
        data = material()
        data.pop('team')
        self.write(data)
        doc = self.doc()
        self.assertEqual(render.clubs_for(doc), {})
        image = render.frame(1.0, doc['segments'][2], doc, {}, 2, len(doc['segments']))
        self.assertIn('数字で読む', ' '.join(entry['text'] for entry in image.info['v3_layout']))

    def test_metadata_has_the_league_and_no_mlb_tag(self):
        snippet = topics.metadata(self.doc())['snippet']
        self.assertIn(f'#欧州サッカー #サッカー #プレミアリーグ #{SUBJECT}', snippet['description'])
        self.assertNotIn('#MLB', snippet['description'])
        self.assertEqual(snippet['tags'], ['欧州サッカー', 'サッカー', 'プレミアリーグ', SUBJECT])


# 材料に足した回はすべて、流れと同じ見た目の設定で全場面を描いて画面検査に通す
# （11/27 パレスの回で、つかみの札の名前と札が重なり、見本の実行で初めて落ちた）。
REAL_FRAME_PROBE = """
import json
import review_render_v3 as r3
import soccer_national_topics as topics
import soccer_national_topics_render as render
events = json.load(open('../data/soccer_analysis_topics.json', encoding='utf-8'))['events']
for key in events:
    doc = topics.analysis_narration('analysis-' + key)
    clubs = render.clubs_for(doc)
    for i, seg in enumerate(doc['segments'][:-1]):
        r3.set_caption(seg['text'], 5, 60, speaker=seg['speaker'])
        image = render.frame(1.5, seg, doc, clubs, i, len(doc['segments']))
        errors = render.validate_frame(image, clubs, doc)
        assert errors == [], (key, i, errors)
"""


class RealMaterials(unittest.TestCase):
    def test_every_scene_of_every_material_passes_the_frame_check(self):
        import subprocess
        import sys
        env = {key: value for key, value in os.environ.items() if not key.startswith('COLLESPO_')}
        env.update(PYTHONUTF8='1', COLLESPO_STYLE='v2', COLLESPO_SOCCER_LOOK='v6', COLLESPO_SOCCER_FOCUS='on',
                   COLLESPO_SHORT_LOOK='v4', COLLESPO_SOLO_HOST='metan', COLLESPO_SOCCER_TITLE_V2='on')
        result = subprocess.run([sys.executable, '-c', REAL_FRAME_PROBE], cwd=Path(__file__).resolve().parent,
                                env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
