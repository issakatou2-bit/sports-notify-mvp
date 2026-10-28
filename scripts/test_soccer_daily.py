"""10/24〜26の実行記録を固定した、誤停止・再実行・少数札の回帰。外部通信なし。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

import yaml
os.environ['COLLESPO_SHORT_LOOK']='v4'
os.environ['COLLESPO_SOCCER_LOOK']='v6'
import preview_soccer_daily as preview
import soccer_preview_history as history
import soccer_readable as layout
import sanity_material
import upload_youtube as upload

ROOT=Path(__file__).resolve().parents[1]


class DailyRegression(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',
                       COLLESPO_MOTION='on',COLLESPO_SOLO_HOST='metan',COLLESPO_DUO='off')
        env.start();self.addCleanup(env.stop)

    def test_real_one_two_four_games_fit_every_scene_without_smaller_type(self):
        for count,plan in preview.plans():
            with self.subTest(count=count):
                original=copy.deepcopy(plan)
                for seg in plan['narration']['segments'][:-1]:
                    im=preview.draw(plan,seg)
                    self.assertEqual(layout.check_frame(im,plan['clubs']),[])
                    entries=im.info['v3_layout']
                    cards=[e for e in entries if e['role']=='card']
                    self.assertEqual(len(cards),count)
                    self.assertLessEqual(max(e['box'][3]-e['box'][1] for e in cards),286)
                    self.assertEqual(sum(e.get('v5_font')==68 for e in entries),count)
                    for e in entries:
                        if e['role']=='supplement' and e['box'][1]<layout.BODY_TOP:
                            self.assertFalse(any(layout.intersects(e['box'],card['box']) for card in cards))
                    expected=sorted(plan['data']['games'],key=lambda g:g['start_time_utc'])
                    actual=im.info['semantic_items']
                    self.assertEqual(len(actual),3*count)
                    for i,game in enumerate(expected):
                        self.assertEqual(actual[3*i:3*i+2],[
                            layout.c.club_display_names.display(plan['clubs'][game[s+'_team_name']]) for s in ('home','away')])
                self.assertEqual(plan,original)

    def test_original_empty_card_is_still_rejected(self):
        _,plan=next(preview.plans());im=preview.draw(plan,plan['narration']['segments'][0])
        # 10/26と同じ札底。中央配置の宣言があっても札内検査は免除しない。
        card=next(e for e in im.info['v3_layout'] if e['role']=='card')
        card['box']=[72,390,940,1426]
        self.assertTrue(any('empty_card_bottom' in e for e in layout.check_frame(im,plan['clubs'])))

    def test_oct24_full_high_is_false_stop_but_wrong_gap_still_stops(self):
        case=json.loads((ROOT/'scripts/fixtures/sanity_false_stops/20261024_soccer_daily_full_issue.json').read_text(encoding='utf8'))
        materials=sanity_material.grounding([case['document']])
        issues,errors=sanity_material.assess(case['issues'],[case['document']],materials)
        self.assertFalse(errors)
        self.assertTrue(issues)
        self.assertFalse(any(i.get('confirmed') for i in issues))
        self.assertTrue(issues[0]['supported'])
        wrong=copy.deepcopy(case['document'])
        wrong['segments'][0]['text']=wrong['segments'][0]['text'].replace('勝点差13','勝点差14')
        self.assertTrue(sanity_material.check(wrong,sanity_material.grounding([wrong])))
        past=copy.deepcopy(wrong)
        past['segments'][0]['text']='昨季の勝点差14。アストンヴィラ対マンチェスターC。'
        self.assertFalse(sanity_material.check(past,sanity_material.grounding([past])))

    def test_oct25_result_alias_does_not_count_as_a_preview(self):
        entry=dict(video_id='1Iy8UsDuSl8',backfilled=True,
            title='【欧州サッカー】佐野海舟が先発｜マインツ 2-3 ブレーメン ほか 日本人選手の結果 #Shorts')
        _,plan=next(preview.plans());data=plan['data']
        day=data['generated_at'][:10]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'published.json'
            path.write_text(json.dumps(dict(daily_soccer={day:entry})),encoding='utf8')
            self.assertEqual(upload.published_video('daily_soccer',day,str(path)),{})
        with self.assertRaisesRegex(ValueError,'予告の記録がありません'):
            history.snapshot(data,plan['narration'],dict(daily_soccer={day:entry}))

    def test_same_day_rerun_keeps_saved_original_even_if_new_script_differs(self):
        _,plan=next(preview.plans());data=plan['data'];narr=plan['narration'];day=data['generated_at'][:10]
        entry=dict(video_id='original-preview',title=narr['title'],preview_binding=history.binding(data,narr))
        published=dict(daily_soccer={day:entry});record=history.snapshot(data,narr,published)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,value in [('games',data),('published',published),('history',{day:record})]:
                (root/(name+'.json')).write_text(json.dumps(value),encoding='utf8')
            before=(root/'history.json').read_bytes()
            argv=['history','--games',str(root/'games.json'),'--published',str(root/'published.json'),
                  '--narration',str(root/'regenerated-or-missing.json'),'--out',str(root/'history.json')]
            with patch.object(sys,'argv',argv),patch('soccer_result_context.capture_before') as fetch:
                history.main();history.main()
                fetch.assert_not_called()
            self.assertEqual((root/'history.json').read_bytes(),before)
        changed=copy.deepcopy(narr);changed['segments'][0]['text']+='別原稿'
        with self.assertRaisesRegex(ValueError,'hash'):
            history.snapshot(data,changed,published)

    def test_skip_upload_emits_false_and_history_requires_an_actual_new_upload(self):
        _,plan=next(preview.plans())
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'output';games=Path(folder)/'games.json'
            video=Path(folder)/'video.mp4';video.touch()
            games.write_text(json.dumps(plan['data']),encoding='utf8')
            argv=['upload','--kind','daily','--sport','soccer','--games',str(games),'--video',str(video)]
            with patch.dict(os.environ,GITHUB_OUTPUT=str(output)),patch.object(sys,'argv',argv),\
                 patch.object(upload,'published_video',return_value=dict(video_id='original',url='fixture')),\
                 patch.object(upload,'build',new=Mock()) as api:
                upload.main()
                api.assert_not_called()
            self.assertEqual(output.read_text(encoding='utf8'),'uploaded=false\n')
        workflow=yaml.safe_load((ROOT/'.github/workflows/soccer_daily.yml').read_text(encoding='utf8'))
        step=next(s for s in workflow['jobs']['build']['steps'] if s['name']=='Save the actually published preview')
        self.assertIn("steps.upload.outputs.uploaded == 'true'",step['if'])


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
