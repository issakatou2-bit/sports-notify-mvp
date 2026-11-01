"""保存した11/1見本3本の公開文・字幕と、対象外の完全一致を検査する。"""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import offseason_public as op
import upload_youtube as yt
import generate_asset_video as av
import asset_sns
import buffer_daily as bd
import caption_breaks as cb
import review_render_v3 as r3
from test_offseason_text import old_module

SAMPLES = json.loads(Path(__file__).with_name('fixtures').joinpath('offseason-public/samples.json').read_text(encoding='utf-8'))


class OffseasonPublic(unittest.TestCase):
    def tearDown(self):
        r3.set_caption('', 0)

    def test_series_title_keeps_player_and_action(self):
        spec = dict(label='村上宗隆のFA契約｜日本人選手の来季 第1回', heading='日本人選手の来季 第1回',
                    offseason=dict(kind='transactions', series_number=1))
        meta = op.metadata(spec)
        self.assertEqual(meta['title'], f'【MLB】{spec["label"]} #Shorts')
        self.assertEqual(meta['lead'][0], '日本人選手の来季 第1回を、MLB公式の記録から紹介します。')

    def test_actual_metadata_and_sns_of_all_three(self):
        for row in SAMPLES:
            spec = row['spec']
            with patch.object(yt, 'generated_topic', return_value=spec):
                snippet = yt.build_asset_metadata(spec['key'], row['narration'])['snippet']
            self.assertEqual(snippet['title'], f'【MLB】{spec["heading"]} #Shorts')
            desc = snippet['description']
            self.assertNotIn('（）', desc)
            self.assertNotIn('同じ内容を音声で', desc)
            self.assertIn('MLB公式の記録から紹介します。', desc)
            self.assertIn('音声: VOICEVOX:四国めたん', desc)
            self.assertNotIn('ずんだもん', desc)
            self.assertNotIn('#' + spec['label'].replace(' ', ''), desc)
            if spec.get('offseason_sample'):
                self.assertIn(spec['intro'], desc)
            kind, _ = asset_sns.register(spec['key'], 'offseason-news', {'path': 'offseason_news.yml'})
            record = dict(title=snippet['title'], description=desc, video_id='SAMPLE_LINK')
            for service in ('instagram', 'bluesky', 'twitter'):
                text = bd.caption(service, '2026-11-01', record, kind)
                self.assertNotIn('ずんだもん', text)
                self.assertNotIn('（）', text)
                if service != 'twitter':
                    self.assertIn('音声：VOICEVOX:四国めたん', text)
                else:
                    self.assertLessEqual(bd.x_weight(text), 280)
            self.assertLessEqual(len(bd.caption('bluesky', '2026-11-01', record, kind)), 300)

    def test_credits_use_saved_voice_over_selected_host(self):
        from ui_voice_queue import UI_CREDIT
        with patch.dict('os.environ', {'COLLESPO_SOLO_HOST': 'ui'}):
            doc = copy.deepcopy(SAMPLES[0]['narration'])
            self.assertEqual(op.voice_credit(doc), 'VOICEVOX:四国めたん')
            doc['voice_resolution'] = {'host': 'ui'}
            self.assertEqual(op.voice_credit(doc), UI_CREDIT)
            self.assertEqual(op.description_voice('音声: ' + UI_CREDIT), UI_CREDIT)
            doc['voice_resolution'] = {'host': 'metan'}
            self.assertEqual(op.voice_credit(doc), 'VOICEVOX:四国めたん')
        self.assertEqual(op.voice_credit({'segments': [{'speaker': 2}, {'speaker': 3}]}),
                         'VOICEVOX:四国めたん / VOICEVOX:ずんだもん')
        with self.assertRaises(ValueError):
            op.description_voice('no credit')
        for resolution in ({'host': 'unknown'}, {'host': 'ui', 'audio_available': False}):
            with self.assertRaises(ValueError):
                op.voice_credit(dict(doc, voice_resolution=resolution))
        receipt = dict(video_sha256='same-video', voice_resolution={'host': 'ui'})
        self.assertEqual(op.voice_credit(op.saved_voice(doc, receipt, 'same-video')), UI_CREDIT)
        with self.assertRaises(ValueError):
            op.saved_voice(doc, receipt, 'other-video')

    def test_all_caption_pages_and_rows_keep_words_and_fixed_size(self):
        draw = ImageDraw.Draw(Image.new('RGB', (1080, 1920)))
        width = r3.CAPTION_RIGHT - (r3.LEFT - 8) - 64
        for row in SAMPLES:
            for seg in row['narration']['segments']:
                r3.set_caption(seg['text'], 10, phrase_wrap=True)
                pages = r3.caption_chunks(seg['text'])
                self.assertEqual(cb.violations(seg['text'], pages, splitter=op.caption_phrases), [])
                self.assertEqual(''.join(pages), seg['text'])
                for page in pages:
                    lines = [''.join(s for s, _ in line) for line in r3._caption_lines(draw, page, 42, width)]
                    self.assertLessEqual(len(lines), 3)
                    self.assertEqual(cb.violations(page, lines, splitter=op.caption_phrases), [])
                    for word in ('宣言', '契約'):
                        at = 0
                        for line in lines[:-1]:
                            at += len(line)
                            start = 0
                            while (start := page.find(word, start)) >= 0:
                                self.assertFalse(start < at < start + len(word), (page, lines))
                                start += len(word)

    def test_other_generated_metadata_matches_origin_character_for_character(self):
        old = old_module('upload_youtube')
        # 追加修正に触れない、既存の非オフ生成話題を全件比較する。
        count = 0
        for spec in av.LIST_TOPICS.values():
            if not op.applies(spec):
                self.assertEqual(yt.asset_meta_from_spec(spec), old.asset_meta_from_spec(spec))
                count += 1
        self.assertGreater(count, 20)

    def test_actual_bubble_layout_cache_and_font_are_preserved(self):
        import characters
        layout = characters.caption_layout()
        width, size, max_rows = layout
        r3._offseason_caption_chunks.cache_clear()
        for row in SAMPLES:
            for seg in row['narration']['segments']:
                r3.set_caption(seg['text'], 10, phrase_wrap=True)
                r3.caption_chunks(seg['text'])  # 別幅の計算を先にしても本物の幅へ漏らさない。
                actual = r3.caption_chunks(seg['text'], layout=layout)
                r3._offseason_caption_chunks.cache_clear()
                self.assertEqual(actual, r3.caption_chunks(seg['text'], layout=layout))
                self.assertEqual(''.join(actual), seg['text'])
                self.assertNotIn('11月2日、', actual)
                for page in actual:
                    image = Image.new('RGB', (1080, 1920))
                    characters.bubble(image, 'metan', page)
                    self.assertEqual(image.info['duo_caption']['font_size'], size)
                    self.assertLessEqual(image.info['duo_caption']['rows'], max_rows)
                    lines = [''.join(t for t, _ in line) for line in r3._caption_lines(ImageDraw.Draw(image), page, size, width)]
                    self.assertEqual(cb.violations(page, lines, splitter=op.caption_phrases), [])

    def test_other_sns_and_caption_pixels_match_origin(self):
        old_bd = old_module('buffer_daily')
        record = dict(title='【MLB】大谷翔平の成績 #Shorts', description='音声: VOICEVOX:ずんだもん / 四国めたん', video_id='SAMPLE_LINK')
        for kind in ('morning', 'daily', 'morning_press', 'daily_soccer'):
            for service in ('twitter', 'instagram', 'bluesky'):
                self.assertEqual(bd.caption(service, '2026-11-01', record, kind), old_bd.caption(service, '2026-11-01', record, kind))
        old_r3 = old_module('review_render_v3')
        old_characters = old_module('characters')
        with patch.object(r3, 'LOOK', 'v4'), patch.object(old_r3, 'LOOK', 'v4'):
            for text in ('今永昇太は七回を投げました。', '鈴木誠也は3打数2安打です。'):
                r3.set_caption(text, 10)
                old_r3.set_caption(text, 10)
                actual, expected = Image.new('RGB', (1080, 1920)), Image.new('RGB', (1080, 1920))
                r3.caption(actual, 1)
                old_r3.caption(expected, 1)
                self.assertEqual(actual.tobytes(), expected.tobytes())
                import characters
                actual, expected = Image.new('RGB', (1080, 1920)), Image.new('RGB', (1080, 1920))
                characters.bubble(actual, 'metan', text)
                old_characters.bubble(expected, 'metan', text)
                self.assertEqual(actual.tobytes(), expected.tobytes())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
