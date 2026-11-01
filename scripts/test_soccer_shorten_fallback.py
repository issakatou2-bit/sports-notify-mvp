import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import soccer_slots_v4 as slots
import synthesize_narration as sn
from test_soccer_length import material, wav
import ui_voice_policy as policy

class ShorteningFallback(unittest.TestCase):
    def test_ui_shortening_never_calls_voisona(self):
        with tempfile.TemporaryDirectory() as directory:
            plan,audio=material('2026-10-15',Path(directory))
            with patch('solo_host.for_segments',return_value='ui'), patch('solo_host.synthesize') as voisona, self.assertRaises(slots.PreviewVoiceUnavailable):
                slots.fit_preview(plan,audio)
            voisona.assert_not_called()
    def test_full_original_rebuild_and_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            plan,audio=material('2026-10-15',folder)
            original=copy.deepcopy(plan['narration']['segments'])
            plan['narration']['host_original_segments']=original
            plan['narration']['host_assignment']={'kind':'daily_soccer'}
            plan['narration']['segments'][1]['text']='敬語に変換した途中の雨衣原稿です。'
            def fake(argv):
                src=Path(argv[argv.index('--narration')+1]);out=Path(argv[argv.index('--out-dir')+1])
                data=json.loads(src.read_text(encoding='utf-8'))
                self.assertEqual(data['segments'],original)
                self.assertEqual(os.environ['COLLESPO_SOLO_HOST'],'metan')
                rows=[]
                for i,seg in enumerate(data['segments']):
                    path=out/f'{i}.wav';wav(path,2)
                    rows.append(dict(seg,file=str(path),duration=2))
                (out/'manifest.json').write_text(json.dumps({'segments':rows}),encoding='utf-8')
            with patch.object(sn,'main',side_effect=fake),patch('solo_host.synthesize') as voisona:
                rows,target,manifest=slots.rebuild_preview_metan(plan,folder)
            self.assertTrue((folder/'voice-hold.json').exists())
            self.assertTrue(all(Path(r['file']).parent==target for r in rows))
            self.assertEqual(plan['narration']['host_delivery']['comparison_eligible'],False)
            self.assertEqual(plan['narration']['voice_resolution']['host'],'metan')
            voisona.assert_not_called()
    def test_runner_routes_all_audio_to_metan_and_saves_final_shortened_source(self):
        import host_split
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'COLLESPO_SOLO_HOST':'metan'}):
            folder=Path(directory);audio_dir=folder/'ui';audio_dir.mkdir()
            plan,audio=material('2026-10-15',audio_dir)
            plan['narration']['host_original_segments']=copy.deepcopy(plan['narration']['segments'])
            data_path=folder/'data.json';data_path.write_text('{}',encoding='utf-8')
            supplied=folder/'source.json';supplied.write_text(json.dumps(plan['narration']),encoding='utf-8')
            (audio_dir/'manifest.json').write_text(json.dumps({'segments':audio}),encoding='utf-8')
            calls=[]
            def fit(p,rows):
                calls.append(True)
                if len(calls)==1:raise slots.PreviewVoiceUnavailable('fake runner')
                p['narration']['segments'][1]['text']='短縮後の確定原稿です。'
                rows[1]['text']=p['narration']['segments'][1]['text']
            def fake(argv):
                src=Path(argv[argv.index('--narration')+1]);out=Path(argv[argv.index('--out-dir')+1])
                doc=json.loads(src.read_text(encoding='utf-8'));rows=[]
                for i,seg in enumerate(doc['segments']):
                    path=out/f'{i}.wav';wav(path,2);rows.append(dict(seg,file=str(path),duration=2))
                (out/'manifest.json').write_text(json.dumps(dict(segments=rows,narration_path=str(src))),encoding='utf-8')
            def render(p,rows,out):
                self.assertEqual(os.environ['COLLESPO_SOLO_HOST'],'metan')
                self.assertTrue(all('metan-rebuild' in r['file'] for r in rows))
                self.assertEqual(json.loads((audio_dir/'metan-rebuild/narration.json').read_text(encoding='utf-8'))['segments'],p['narration']['segments'])
                self.assertEqual(json.loads(supplied.read_text(encoding='utf-8'))['segments'],p['narration']['segments'])
            os.environ['COLLESPO_SOLO_HOST']='ui'
            with patch.object(slots,'program',return_value=plan), patch.object(host_split,'enabled',return_value=False), patch.object(slots,'fit_preview',side_effect=fit), patch.object(sn,'main',side_effect=fake), patch.object(slots,'render_video',side_effect=render) as rendered, patch.object(host_split,'bind_video'), patch('solo_host.synthesize') as voisona:
                slots.run_compat('preview',data_path,audio_dir=audio_dir,out=folder/'video',narration_path=supplied)
                rendered.assert_called_once();voisona.assert_not_called()
            self.assertEqual(len(calls),2)

    def test_incomplete_metan_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);plan,audio=material('2026-10-15',folder)
            plan['narration']['host_original_segments']=copy.deepcopy(plan['narration']['segments'])
            def fake(argv):
                out=Path(argv[argv.index('--out-dir')+1]);(out/'manifest.json').write_text('{"segments":[]}',encoding='utf-8')
            with patch.object(sn,'main',side_effect=fake),self.assertRaises(policy.VoiceUnavailable):
                slots.rebuild_preview_metan(plan,folder)

if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
