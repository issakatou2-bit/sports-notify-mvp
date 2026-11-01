"""本物の選定材料・sanity・短さ検査・札検査を通す次点制作。合成とエンコードは偽物。"""
import io
import os
import re
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_soccer_stable import Offline, load, audio_rows
import sanity
import sanity_budget as budget
import soccer_daily_retry as retry
import soccer_slots_v4 as slots
import soccer_preview_history as history
import preview_soccer_daily as preview
import short_content


class Retry(Offline):
    def setup_run(self, tmp, cause='information'):
        root = Path(tmp)
        args = SimpleNamespace(**{k:root/v for k,v in dict(games='games.json',narration='soccer_narration.json',
            sanity='sanity.json',hold='hold.json',audio_dir='audio',out='video',
            published='published.json',record='evidence/retry.json').items()},
            sanity_outcome='failure' if cause=='sanity_high' else 'success',
            video_outcome='skipped' if cause=='sanity_high' else 'failure')
        retry.write(args.games,load('20261025'))
        slots.run_compat('preview',args.games,narration_out=args.narration)
        retry.write(args.published,{})
        retry.write(args.sanity,dict(upload_held=cause=='sanity_high',
                    blocking_issues=[dict(severity='high',why='初回の確定した矛盾')] if cause=='sanity_high' else []))
        retry.write(args.hold,dict(status='held' if cause=='sanity_high' else 'passed',reasons=['初回の理由']))
        digest = retry.segments_hash(retry.read(args.narration))
        if cause=='information':
            retry.write(args.out/'short_content_gate.json',dict(status='held',information_count=1,
                        reasons=['情報1件'],segments_sha256=digest))
        if cause=='layout':
            retry.write(args.out/'layout_hold.json',dict(status='held',scene=0,
                        errors=[dict(empty_card_bottom=[72,390,940,1426])],segments_sha256=digest))
        args.out.mkdir(exist_ok=True)
        (args.out/'collespo_short.mp4').write_bytes(b'failed-old-video')
        return args

    def runner(self, fail=None):
        stages = []
        def run(command):
            script = Path(command[1]).name; stages.append(script)
            def arg(flag): return Path(command[command.index(flag)+1])
            if script=='generate_narration.py':
                slots.run_compat('preview',arg('--games'),narration_out=arg('--out'))
                if fail=='sanity':
                    doc=retry.read(arg('--out'))
                    # 昨季の段落へ追記せず、実際の現在勝点差を壊す。
                    doc['segments'][1]['text']=re.sub(r'勝点差\d+(?:\.\d+)?', '勝点差999',doc['segments'][1]['text'],count=1)
                    retry.write(arg('--out'),doc)
            elif script=='sanity.py':
                if fail=='false_success':
                    retry.write(arg('--out'),dict(upload_held=False,blocking_issues=[dict(severity='high')]))
                    retry.write(arg('--hold-record'),dict(status='passed'))
                    return 0
                def fake_general(*args,**kwargs):
                    budget.reserve('sanity')
                    current=retry.read(arg('--narration'))['segments'][1]['text'].split('期待選手は')[0]
                    return [dict(kind='事実の誤り',severity='high',where=current,why='勝点差が材料と矛盾')] if fail=='sanity' else []
                with patch.object(sys,'argv',command[1:]),patch.dict(os.environ,ANTHROPIC_API_KEY='fake-test-only'), \
                     patch.object(sanity,'general',side_effect=fake_general), \
                     patch.object(sanity,'check_stat_files',return_value=[]),patch.object(sanity,'check_scores',return_value=[]), \
                     patch('sanity_refresh.refresh',side_effect=lambda d,m:(m,[])), \
                     patch('sanity_recheck.ai_review',return_value=([],dict(calls=0))):
                    return sanity.main()
            elif script=='synthesize_narration.py':
                rows=audio_rows(retry.read(arg('--narration')),arg('--out-dir'),[4,20,7])
                retry.write(arg('--out-dir')/'manifest.json',dict(segments=rows))
            elif script=='generate_video.py':
                def render(plan,audio,out):
                    out=Path(out); out.mkdir(parents=True,exist_ok=True)
                    durations=slots.video_times(plan['narration']['segments'],audio)
                    if fail=='information': plan['narration']['segments'][1]['text']='対戦の予告です。'
                    short_content.require(plan['narration'],durations,out,plan['data'],maximum=55,video_name='collespo_short.mp4')
                    for seg in plan['narration']['segments'][:-1]:
                        image=preview.draw(plan,seg)
                        if fail=='layout':
                            next(e for e in image.info['v3_layout'] if e['role']=='card')['box']=[72,390,940,1426]
                        errors=slots.check_frame(image,plan)
                        if errors:
                            retry.write(out/'layout_hold.json',dict(status='held',errors=errors))
                            raise ValueError('札検査で停止')
                    (out/'collespo_short.mp4').write_bytes(b'fixture-media-after-checks')
                    retry.write(out/'verification.json',dict(layout_badges_numbers='PASS'))
                try:
                    with patch.object(slots,'render_video',side_effect=render):
                        return slots.run_compat('preview',arg('--games'),audio_dir=arg('--audio-dir'),out=arg('--out')) or 0
                except ValueError:
                    return 1
            return 0
        return run,stages

    def test_real_runner_up_passes_all_gates_after_each_failure_type(self):
        for cause in ('information','sanity_high','layout'):
            with self.subTest(cause=cause),tempfile.TemporaryDirectory() as tmp, \
                 patch.dict(os.environ,COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')), \
                 patch('sys.stdout',new_callable=io.StringIO):
                args=self.setup_run(tmp,cause); original=args.games.read_bytes()
                budget.reserve('sanity'); run,stages=self.runner()
                self.assertEqual(retry.build(args,run),0)
                self.assertEqual(stages,['generate_narration.py','sanity.py','synthesize_narration.py','generate_video.py'])
                saved=retry.read(args.games)
                self.assertEqual(saved['preview_selection']['selected_ids'],['560613'])
                self.assertEqual((Path(args.record).parent/'first-games.json').read_bytes(),original)
                self.assertEqual(len(budget.state()['calls']),2)
                self.assertEqual(retry.read(args.hold)['soccer_retry']['status'],'passed')
                doc=retry.read(args.narration)
                entry=dict(video_id='fixture',title=doc['title'],preview_binding=history.binding(saved,doc))
                self.assertEqual(history.snapshot(saved,doc,dict(daily_soccer={'2026-10-25':entry}))['games'][0]['game_id'],'560613')
                # 同一実行での2回目の復旧も禁止。原材料の証拠を上書きしない。
                again=Mock(); self.assertEqual(retry.build(args,again),1); again.assert_not_called()

    def test_second_failure_never_tries_third_candidate_or_promotes_old_video(self):
        for fail in ('sanity','information','layout','false_success'):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as tmp, \
                 patch.dict(os.environ,COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')), \
                 patch('sys.stdout',new_callable=io.StringIO):
                args=self.setup_run(tmp); original=args.games.read_bytes()
                budget.reserve('sanity'); run,stages=self.runner(fail)
                self.assertEqual(retry.build(args,run),1)
                self.assertEqual(args.games.read_bytes(),original)
                self.assertEqual((args.out/'collespo_short.mp4').read_bytes(),b'failed-old-video')
                self.assertEqual(stages.count('generate_narration.py'),1)
                self.assertEqual(retry.read(args.hold)['status'],'held')
                self.assertEqual(retry.read(args.record)['status'],'held')
                if fail in ('sanity','false_success'):
                    self.assertNotIn('synthesize_narration.py',stages)
                    self.assertTrue(retry.read(args.record)['attempts'][1]['sanity']['blocking_issues'])

    def test_no_next_budget_spent_unrelated_stale_or_published_do_not_rebuild(self):
        for reason in ('no_next','budget_used','unrelated','stale','published'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as tmp, \
                 patch.dict(os.environ,COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')), \
                 patch('sys.stdout',new_callable=io.StringIO):
                args=self.setup_run(tmp); budget.reserve('sanity')
                if reason=='no_next': retry.write(args.games,load('20261030'))
                if reason=='budget_used': budget.reserve('sanity_recheck')
                if reason=='unrelated': retry.write(args.out/'short_content_gate.json',dict(status='passed',information_count=4))
                if reason=='stale': retry.write(args.out/'short_content_gate.json',dict(status='held',information_count=1,segments_sha256='old'))
                if reason=='published':
                    doc=retry.read(args.narration)
                    retry.write(args.published,dict(daily_soccer={'2026-10-25':dict(video_id='existing',title=doc['title'])}))
                original=args.games.read_bytes(); runner=Mock()
                self.assertEqual(retry.build(args,runner),1)
                runner.assert_not_called(); self.assertEqual(args.games.read_bytes(),original)

    def test_workflow_first_success_and_zero_games_never_enter_retry(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        job=yaml.safe_load((root/'.github/workflows/soccer_daily.yml').read_text(encoding='utf8'))['jobs']['build']
        steps=job['steps']; recovery=next(s for s in steps if s.get('id')=='retry')
        self.assertIn("steps.gate.outputs.count != '0'",recovery['if'])
        self.assertIn("steps.sanity.outcome == 'failure'",recovery['if'])
        self.assertIn("steps.video.outcome == 'failure'",recovery['if'])
        self.assertIn('COLLESPO_SANITY_BUDGET_FILE',job['env'])
        for name in ('Upload to YouTube','Post to Bluesky','Post to Threads','Post to TikTok'):
            condition=next(s['if'] for s in steps if s['name']==name)
            self.assertIn("steps.video.outcome == 'success'",condition)
            self.assertIn("steps.retry.outcome == 'success'",condition)
        import sanity_workflows
        self.assertEqual(sanity_workflows.errors(root),[])
        upload_if=next(s['if'] for s in steps if s['name']=='Upload to YouTube')
        def evaluate(expression,count,sanity_outcome,video_outcome,retry_outcome):
            values={'steps.gate.outputs.count':str(count),'steps.sanity.outcome':sanity_outcome,
                    'steps.video.outcome':video_outcome,'steps.retry.outcome':retry_outcome}
            for key,value in values.items(): expression=expression.replace(key,repr(value))
            return eval(expression.replace('&&',' and ').replace('||',' or '),{'__builtins__':{}})
        for count,san,video,recovered,expected in (
                (1,'success','success','skipped',True),(0,'success','success','skipped',False),
                (1,'failure','skipped','failure',False),(1,'success','failure','skipped',False),
                (1,'failure','skipped','success',True),(1,'success','failure','success',True)):
            self.assertEqual(evaluate(upload_if,count,san,video,recovered),expected)
        self.assertFalse(evaluate(recovery['if'],1,'success','success','skipped'))
        self.assertFalse(evaluate(recovery['if'],0,'failure','failure','skipped'))

    def test_process_start_failure_keeps_hold_and_consumes_the_only_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,
                COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')),patch('sys.stdout',new_callable=io.StringIO):
            args=self.setup_run(tmp); budget.reserve('sanity')
            before=args.games.read_bytes()
            self.assertEqual(retry.build(args,Mock(side_effect=OSError('fake'))),1)
            self.assertEqual(args.games.read_bytes(),before)
            self.assertEqual(retry.read(args.hold)['status'],'held')
            self.assertEqual(retry.read(args.record)['attempts'][1]['error_type'],'OSError')
            runner=Mock(); self.assertEqual(retry.build(args,runner),1); runner.assert_not_called()


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
