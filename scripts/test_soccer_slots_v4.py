"""3枠の保存材料・v4配置とv3の画素不変を別プロセスで検査する。"""
import hashlib
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import soccer_slots_v4 as slots
import review_render_v3 as r3
import soccer_v4_cards as cards

FIX=ROOT/'scripts/fixtures/soccer-slots'


def load(mode):return json.loads((FIX/(mode+'.json')).read_text(encoding='utf-8'))


class Slots(unittest.TestCase):
    def test_v3_frames_identical_to_base(self):
        if slots.enabled():return
        import generate_video as gv
        import generate_morning_short as gm
        preview,race,week=(load(m) for m in ('preview','race','week'))
        comp=next(c for c in race['competitions'] if c['code'] in race['picked'])
        calls=[(gv,'render_intro',(1.0,'10月10日',{})),(gv,'render_game',(1.0,preview['games'][0],1,3)),
            (gm,'render_week_intro',(1.0,week,'9月22日')),(gm,'render_week_rows',(1.0,week,[0,1])),
            (gm,'render_race_intro',(1.0,race,'9月24日')),(gm,'render_race_japanese',(1.0,race)),(gm,'render_race_line',(1.0,comp,comp['lines'][0]))]
        expected=json.loads((FIX/'v3-frame-hashes.json').read_text(encoding='utf-8'))
        sources=json.loads((FIX/'v3-render-source-hashes.json').read_text(encoding='utf-8'))
        for module in (gv,gm):
            for node in ast.parse(Path(module.__file__).read_text(encoding='utf-8')).body:
                key=module.__name__+'.'+node.name if isinstance(node,ast.FunctionDef) else ''
                if key in sources:
                    self.assertEqual(hashlib.sha256(ast.dump(node,include_attributes=False).encode('utf-8')).hexdigest(),sources[key],key)
        # 基点との画素比較を記録したWindows環境で実行。Linuxは書体が違うためソース不変を検査。
        if sys.platform!='win32':return
        for module,name,args in calls:self.assertEqual(hashlib.sha256(getattr(module,name)(*args).tobytes()).hexdigest(),expected[name],name)
        for module in ('soccer_preview','soccer_race','soccer_jp_week'):
            self.assertIsNone(__import__(module).v4_program({}))

    def test_native_all_screens_safe(self):
        if not slots.enabled():return
        for mode in ('preview','race','week'):
            plan=slots.program(mode,load(mode));self.assertTrue(plan['narration']['segments'])
            for seg in plan['narration']['segments']:
                for t in ((3,) if seg['kind']=='outro' else (0,.8,1.4)):
                    r3.set_caption(seg['text'],12,40,speaker=2,hide_caption=seg['kind']=='outro');r3.set_program_clock(t)
                    im=slots.frame(t,seg,plan)
                    self.assertEqual(slots.check_frame(im,plan),[],(mode,seg['kind'],t))
                    self.assertIsNone(im.info.get('v3_background_team'))
            r3.set_program_clock(None)

    def test_preview_gate_home_away_and_weekday(self):
        if not slots.enabled():return
        data=load('preview');plan=slots.program('preview',data)
        for seg in plan['narration']['segments']:
            if seg['kind']=='preview':
                self.assertIn('ホームの'+seg['meta']['home'],seg['text'])
                self.assertIn('アウェーの'+seg['meta']['away'],seg['text'])
                self.assertRegex(seg['meta']['date'],r'（[月火水木金土日]）')
                self.assertRegex(seg['meta']['time'],r'\d\d:\d\d')
                self.assertNotIn('迎える',seg['text'])
        for g in data['games']:g['home_has_jp']=g['away_has_jp']=False
        self.assertEqual(slots.program('preview',data)['narration']['segments'],[])
        game=load('preview')['games'][0];game['start_time_jst']='01/01 03:30'
        game.pop('start_time_utc',None)
        self.assertEqual(slots.kickoff(game,'2026-12-31T09:00:00Z').year,2027)

    def test_race_highlights_and_grounded_gap(self):
        if not slots.enabled():return
        plan=slots.program('race',load('race'))
        screens=[s['meta'] for s in plan['narration']['segments'] if s['kind']=='standings']
        self.assertTrue(screens)
        for spec in screens:
            self.assertTrue(spec['lines'])
            self.assertTrue(set(spec['highlights'])<=set(r['team'] for r in spec['rows']))
            if spec['gap']:self.assertTrue(spec['gap'].startswith('は'))

    def test_non_premier_personal_stats_not_spoken_or_drawn(self):
        if not slots.enabled():return
        data=load('week');row=next(r for r in data['rows'] if r['league']!='PL')
        row['players'][0]['stats']={'goals':9876,'assists':7654,'minutes':9999}
        plan=slots.program('week',data)
        self.assertNotIn('9876',json.dumps(plan['narration'],ensure_ascii=False))
        self.assertNotIn('7654',json.dumps(plan['narration'],ensure_ascii=False))
        for spec in [s['meta'] for s in plan['narration']['segments'] if s['kind']=='jp_roster']:
            for r in spec['rows']:
                if r['name']==row['players'][0]['name']:self.assertEqual(r['values'],[])

    def test_premier_known_stats_and_no_duplicate_hero(self):
        if not slots.enabled():return
        data=load('week');row=next(r for r in data['rows'] if r['league']=='PL')
        row['players'][0].update(stats=dict(goals=2,assists=1,minutes=90),out=False)
        data['rows']=[row]
        plan=slots.program('week',data);hero=next(s for s in plan['narration']['segments'] if s['kind']=='jp_player')
        self.assertEqual(hero['meta']['big'],'2');self.assertNotIn([2,'得点'],hero['meta']['chips'])
        row['players'][0]['stats']['minutes']=0;row['players'][0]['stats']['goals']=0;row['players'][0]['stats']['assists']=0
        for p in row['players']:p.update(out=True)
        self.assertEqual(slots.program('week',data)['narration']['segments'],[])

    def test_numeric_and_badge_negative_checks(self):
        if not slots.enabled():return
        plan=slots.program('preview',load('preview'));seg=plan['narration']['segments'][0]
        r3.set_caption('',12,40);im=slots.frame(1.4,seg,plan)
        im.info['v4_badges']=[];self.assertTrue(cards.check_club_badges(im,plan['clubs']))
        im=slots.frame(1.4,seg,plan)
        __import__('short_v4_cards').text(im,100,700,'987654',60,r3.GOLD,number=True)
        self.assertTrue(any('numbers_missing_from_material' in e for e in slots.check_frame(im,plan)))

    def test_common_outro_and_title_metadata(self):
        if not slots.enabled():return
        import upload_youtube as upload
        for mode in ('preview','race','week'):
            plan=slots.program(mode,load(mode));seg=plan['narration']['segments'][-1]
            self.assertEqual(seg['text'],r3.OUTRO_TEXT)
            im=slots.frame(3,seg,plan);self.assertTrue(im.info['v3_outro'])
            self.assertTrue(any(e.get('text')==slots.TAGLINE for e in im.info['v3_layout']))
            with tempfile.TemporaryDirectory() as directory:
                file=Path(directory)/'narr.json';file.write_text(json.dumps(plan['narration'],ensure_ascii=False),encoding='utf-8')
                meta=upload.build_metadata(str(FIX/'preview.json'),'10月10日','daily' if mode=='preview' else 'soccer_'+mode,narration_path=str(file),sport='soccer')
            self.assertEqual(meta['snippet']['title'],plan['narration']['title'][:100])
            self.assertIn('VOICEVOX:四国めたん',meta['snippet']['description'])

    def test_saved_manifest_and_40_second_budget(self):
        if not slots.enabled():return
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'one.wav'
            with wave.open(str(file),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\x00\x00'*24000)
            for mode in ('preview','race','week'):
                narr=slots.program(mode,load(mode))['narration']
                audio=json.loads(json.dumps([dict(s,file=str(file),duration=1) for s in narr['segments']]))
                self.assertLessEqual(sum(slots.durations(narr['segments'],audio)),40)
                for s in audio:s['duration']=41
                with patch('synthesize_narration.audio_duration',return_value=41):
                    with self.assertRaisesRegex(ValueError,'40秒'):slots.durations(narr['segments'],audio)

    def test_cli_success_and_saved_narration(self):
        if not slots.enabled():return
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);file=out/'narr.json'
            for mode in ('preview','race','week'):
                self.assertIsNone(slots.run_compat(mode,FIX/(mode+'.json'),narration_out=file))
                narr=json.loads(file.read_text(encoding='utf-8'))
                self.assertEqual(narr,slots.program(mode,load(mode))['narration'])
                (out/'manifest.json').write_text(json.dumps(dict(segments=narr['segments'])),encoding='utf-8')
                with patch.object(slots,'render_video',return_value=dict(seconds=30)) as draw:
                    self.assertEqual(slots.run_compat(mode,FIX/(mode+'.json'),audio_dir=out,out=out,narration_path=file),0)
                    draw.assert_called_once()


if __name__=='__main__':
    if '--child' in sys.argv:unittest.main(argv=[sys.argv[0]],verbosity=1)
    else:
        failures=0
        for look in ('v3','v4'):
            proc=subprocess.run([sys.executable,'-X','utf8',__file__,'--child'],env=dict(os.environ,COLLESPO_SHORT_LOOK=look),capture_output=True,text=True,encoding='utf-8',errors='replace')
            print(look,proc.stderr.strip()[-5000:]);failures+=bool(proc.returncode)
            if proc.returncode:
                # run_checks は最後の行しか見せないので、落ちた検査と理由を NG の行に入れる
                lines=proc.stderr.splitlines()
                bad=[l for l in lines if l.startswith(('FAIL:','ERROR:'))]+[l for l in lines if 'Error' in l and not l.startswith(' ')][-3:]
                print('NG',look,' / '.join(bad)[:900])
        print('ok soccer slots v3 pixels/v4 rules' if not failures else 'NG soccer slots');raise SystemExit(bool(failures))
