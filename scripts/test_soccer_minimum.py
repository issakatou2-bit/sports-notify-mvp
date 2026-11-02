"""26.833秒の不足、材料枯渇、声の失敗、旧出力を通信なしで確かめる。"""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import soccer_minimum as minimum
import soccer_slots_v4 as slots
from test_soccer_race_length import material


class MinimumTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, COLLESPO_SOCCER_LOOK='v6', COLLESPO_SHORT_LOOK='v4',
                         COLLESPO_SOCCER_FOCUS='on', COLLESPO_HOST_SPLIT='off')
        env.start()
        self.addCleanup(env.stop)

    def race(self):
        with patch.object(slots, 'enabled', return_value=True):
            return slots.program('race', material(29))['narration']

    def audio(self, narr):
        return [dict(copy.deepcopy(s), file=__file__, duration=26.833 / len(narr['segments']))
                for s in narr['segments']]

    @staticmethod
    def measure(mode, data, narr, audio):
        return [r['duration'] for r in audio]

    @staticmethod
    def rebuild(seg, previous, directory, stage):
        return dict(previous, **seg, duration=previous['duration'] + 4)

    def test_26833_seconds_adds_one_unused_fact_and_restores(self):
        narr = self.race()
        before = copy.deepcopy(narr)
        audio = self.audio(narr)
        result, voices, skip = minimum.fit('race', material(29), narr, audio, '.',
            measure=self.measure, rebuild=self.rebuild)
        self.assertFalse(skip)
        self.assertEqual(len(result['minimum_repair']), 1)
        self.assertGreater(sum(v['duration'] for v in voices), 27)
        self.assertEqual(narr, before)
        self.assertEqual(minimum.restore(narr, result, 'race', material(29)), result)
        change = result['minimum_repair'][0]
        self.assertIn('勝点', change['text'])
        self.assertEqual(voices[change['index']]['speaker'], audio[change['index']]['speaker'])
        changed = copy.deepcopy(result)
        changed['segments'][0]['text'] += '改ざん'
        with self.assertRaises(ValueError):
            minimum.restore(narr, changed, 'race', material(29))

    def test_27_seconds_and_off_do_not_rebuild(self):
        for focus, seconds in [('on', 27), ('off', 26.833)]:
            narr = self.race()
            voices = self.audio(narr)
            voices[0]['duration'] += seconds - 26.833
            with patch.dict(os.environ, COLLESPO_SOCCER_FOCUS=focus), patch.object(minimum, 'candidates') as facts:
                result, audio, skip = minimum.fit('race', material(29), narr, voices, '.', measure=self.measure)
            facts.assert_not_called()
            self.assertFalse(skip)
            self.assertEqual(result, narr)
            self.assertEqual(audio, voices)

    def test_empty_candidates_skip_and_bad_voice_stays_error(self):
        narr = self.race()
        with patch.object(minimum, 'candidates', return_value=[]):
            self.assertTrue(minimum.fit('race', {}, narr, self.audio(narr), '.', measure=self.measure)[2])
        with self.assertRaisesRegex(ValueError, 'broken'):
            minimum.fit('race', {}, narr, self.audio(narr), '.', measure=self.measure,
                        rebuild=lambda *args: (_ for _ in ()).throw(ValueError('broken')))

    def test_finite_facts_are_not_repeated_when_voice_stays_short(self):
        narr = self.race()
        result, _, skip = minimum.fit('race', material(29), narr, self.audio(narr), '.',
            measure=self.measure, rebuild=lambda seg, prev, *_: dict(prev, **seg))
        self.assertTrue(skip)
        texts = [r['text'] for r in result['minimum_repair']]
        self.assertEqual(len(texts), len(set(texts)))
        self.assertLess(len(texts), 20)

    def test_preview_week_and_results_only_use_matching_material(self):
        cases = [
            ('preview', dict(games=[dict(game_id='a',home_team_name='Liverpool FC',away_team_name='Arsenal FC',home_standing=dict(rank=2,points=20),away_standing={},jp_by_side={})]),
             dict(kind='preview',text='対戦です。',speaker=2,meta=dict(game_id='a'))),
            ('week', dict(rows=[dict(club='クラブA',opp='クラブB',gf=2,ga=1)]),
             dict(kind='jp_player',text='選手の成績です。',speaker=2,meta=dict(club='クラブA'))),
            ('results', dict(players=[dict(event_id='a',status='starter',name='選手',club='クラブ',goals=1,assists=0)]),
             dict(kind='intro',text='結果です。',speaker=2,meta=dict(event_id='a')))]
        for mode, data, seg in cases:
            with self.subTest(mode=mode), patch('soccer_result_facts.player_line', return_value='選手は1得点でした。'):
                narr = dict(segments=[seg])
                result, _, skip = minimum.fit(mode, data, narr, self.audio(narr), '.', measure=self.measure, rebuild=self.rebuild)
                self.assertFalse(skip)
                self.assertEqual(len(result['minimum_repair']), 1)

    def test_cli_skip_receipt_and_output(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            narr = self.race()
            for name, payload in [('data.json',{}), ('narration.json',narr), ('manifest.json',dict(segments=self.audio(narr)))]:
                minimum.write(folder/name, payload)
            args = ['soccer_minimum.py','--mode','week','--data',str(folder/'data.json'),
                    '--narration',str(folder/'narration.json'),'--audio-dir',str(folder)]
            with (patch.object(sys,'argv',args), patch.dict(os.environ,GITHUB_OUTPUT=str(folder/'output')),
                    patch.object(minimum,'measured',self.measure)):
                # fitの既定引数も実測の代用品へ明示的に差替える。
                real_fit = minimum.fit
                with patch.object(minimum,'fit',side_effect=lambda *a:real_fit(*a,measure=self.measure)), patch('voice_manifest.save'):
                    minimum.main()
            self.assertEqual((folder/'output').read_text(), 'skip=true\n')
            self.assertEqual(minimum.read(folder/'minimum_result.json')['status'],'skipped')

    def test_workflows_gate_every_publish_and_confirmation(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        for name in ('race','week','daily','results'):
            doc = yaml.safe_load((root/'.github/workflows'/f'soccer_{name}.yml').read_text(encoding='utf8'))
            steps = doc['jobs']['build']['steps']
            length = next(i for i,s in enumerate(steps) if s.get('id') == 'length')
            sanity = next(i for i,s in enumerate(steps) if s.get('id') == 'sanity')
            self.assertLess(length, sanity)
            for step in steps[length+1:]:
                command = step.get('run','')
                if any(word in command for word in ('upload_youtube.py','soccer_week_publish.py','verify_published.py','post_bluesky.py','post_threads.py','post_tiktok.py')):
                    self.assertIn("steps.length.outputs.skip != 'true'", step['if'])

    def test_wave_measurement_and_renderer_use_the_repaired_script(self):
        import short_content
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            narr = self.race()
            # 順位の札だけにし、実測26.81秒が30fpsで26.833秒へ丸まる状況を再現。
            narr['segments'] = [next(s for s in narr['segments'] if s['kind'] == 'standings')]
            def wav(path, seconds):
                with wave.open(str(path), 'wb') as stream:
                    stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    stream.writeframes(b'\0\0' * round(seconds * 8000))
            original = folder/'original.wav'
            wav(original, 26.81)
            audio = [dict(narr['segments'][0], file=str(original), duration=26.81)]
            def rebuild(seg, previous, directory, stage):
                target = folder/'repaired.wav'
                wav(target, 28.5)
                return dict(previous, **seg, file=str(target), duration=28.5)
            self.assertAlmostEqual(sum(minimum.measured('race',material(29),narr,audio)),805/30)
            result, voices, skip = minimum.fit('race',material(29),narr,audio,folder,rebuild=rebuild)
            self.assertFalse(skip)
            self.assertEqual(short_content.assess(result,slots.video_times(result['segments'],voices),material(29),maximum=40)['status'],'passed')
            minimum.write(folder/'race_narration.json',result)
            minimum.write(folder/'data.json',material(29))
            (folder/'audio').mkdir()
            minimum.write(folder/'audio/manifest.json',dict(segments=voices))
            plan=dict(mode='race',data=material(29),narration=narr,shared={})
            def render(plan, audio, out):
                self.assertEqual(plan['narration'],result)
                self.assertEqual(slots.video_times(plan['narration']['segments'],audio),[28.5])
            with patch.object(slots,'program',return_value=plan),patch.object(slots,'render_video',side_effect=render),patch('host_split.bind_video'):
                slots.run_compat('race',folder/'data.json',audio_dir=folder/'audio',out=folder/'video')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
