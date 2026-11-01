"""6失敗の保存材料と次点制作。通信・有料API・実音声は使わない。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

os.environ['COLLESPO_SHORT_LOOK'] = 'v4'
os.environ['COLLESPO_SOCCER_LOOK'] = 'v6'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sanity
import sanity_budget as budget
import sanity_material
import sanity_recheck
import soccer_daily_retry as retry
import soccer_selected_preview as selected
import soccer_slots_v4 as slots
import review_render_v3 as r3
import short_content
import preview_soccer_daily as preview
import soccer_preview_history as history

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT/'scripts/fixtures/soccer-daily'
DAYS = ('20261020','20261022','20261024','20261025','20261026','20261030')


def load(day):
    return retry.read(FIX/(day+'.json'))


def audio_rows(doc, folder, seconds):
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (seg, length) in enumerate(zip(doc['segments'], seconds)):
        path = folder/f'{index}.wav'
        with wave.open(str(path), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(1000)
            stream.writeframes(b'\0\0'*round(length*1000))
        rows.append(dict(copy.deepcopy(seg), file=str(path), duration=length, index=index))
    return rows


class Offline(unittest.TestCase):
    def setUp(self):
        for context in (
            patch.dict(os.environ, COLLESPO_HOST_SPLIT='', COLLESPO_SOLO_HOST='metan',
                       COLLESPO_SOCCER_LOOK='v6', COLLESPO_SHORT_LOOK='v4', COLLESPO_DUO='off',
                       COLLESPO_MOTION='on', COLLESPO_SANITY_BUDGET_FILE='', GITHUB_STEP_SUMMARY=''),
            patch('requests.sessions.Session.request', side_effect=AssertionError('通信禁止')),
            patch('urllib.request.urlopen', side_effect=AssertionError('通信禁止')),
            patch('solo_host.synthesize', side_effect=AssertionError('音声要求禁止')),
            patch('synthesize_narration.synth_one', side_effect=AssertionError('音声要求禁止')),
            patch.object(r3, 'OUTRO_TEXT', r3.INSEASON_OUTRO_TEXT)):
            context.start(); self.addCleanup(context.stop)


class SavedCases(Offline):
    def test_six_saved_narrations_are_byte_identical_to_main(self):
        baseline = retry.read(ROOT/'scripts/fixtures/soccer-stable/success-narrations.json')
        for day in DAYS:
            with self.subTest(day=day):
                data = load(day); before = copy.deepcopy(data)
                actual = selected.program(data)['narration']
                self.assertEqual(json.dumps(actual, ensure_ascii=False, indent=2),
                                 json.dumps(baseline[day], ensure_ascii=False, indent=2))
                self.assertEqual(data, before)
        empty = load('20261026'); empty['preview_selection'].update(selected_ids=[], count=0)
        self.assertEqual(selected.program(empty)['narration']['segments'], [])

    def test_oct24_both_ranks_exist_and_wrong_gap_still_stops(self):
        self.assertEqual(selected.preview_details(load('20261024')['games'][0]), [
            'アストンヴィラは昨季プレミアリーグ4位', 'マンチェスターCは昨季プレミアリーグ2位'])
        case = retry.read(ROOT/'scripts/fixtures/sanity_false_stops/20261024_soccer_daily_full_issue.json')
        doc = case['document']; materials = sanity_material.grounding([doc])
        issues, errors = sanity_material.assess(case['issues'], [doc], materials)
        self.assertFalse(errors); self.assertTrue(issues[0]['supported'])
        wrong = copy.deepcopy(doc)
        wrong['segments'][0]['text'] = wrong['segments'][0]['text'].replace('勝点差13', '勝点差14')
        self.assertTrue(sanity_material.check(wrong, sanity_material.grounding([wrong])))

    def test_missing_rank_is_not_spoken_and_single_fact_is_not_a_comparison(self):
        for rank in ('—','不明',''):
            data=load('20261024'); game=data['games'][0]
            game['home_standing']={}; game['away_standing']={}
            game['reasons']=[dict(tag='quality',text=f'アストンヴィラ（昨季プレミアリーグ4位）とマンチェスター・シティ（昨季プレミアリーグ{rank}位）')]
            self.assertEqual(selected.preview_details(game),['アストンヴィラは昨季プレミアリーグ4位'])
            text=selected.program(data)['narration']['segments'][1]['text']
            self.assertIn('アストンヴィラは昨季プレミアリーグ4位',text)
            self.assertNotIn('マンチェスターCは昨季',text)
            self.assertNotIn('この順位差',text); self.assertNotIn('—',text)

    def test_zero_or_different_competition_rank_is_omitted(self):
        for scope, rank in (('プレミアリーグ','0'),('ラ・リーガ','2')):
            data = load('20261024'); game = data['games'][0]
            text = f'アストンヴィラ（昨季プレミアリーグ4位）とマンチェスター・シティ（昨季{scope}{rank}位）'
            game['reasons'] = [dict(tag='quality',text=text)]
            self.assertEqual(selected.preview_details(game), [])
            self.assertNotIn('アストンヴィラは昨季', selected.program(data)['narration']['segments'][1]['text'])

    def test_oct20_oct22_long_ui_goes_to_rebuild_without_calling_voisona(self):
        # WAV原本は無い。実材料＋作り物の長短で残存経路だけ再現する。
        for day in ('20261020','20261022'):
            with self.subTest(day=day), tempfile.TemporaryDirectory() as tmp:
                for long in (False, True):
                    plan = selected.program(load(day))
                    rows = audio_rows(plan['narration'], Path(tmp), [2]+[18 if long else 10]*4+[7])
                    with patch.dict(os.environ, COLLESPO_SOLO_HOST='ui'), patch('solo_host.synthesize',
                            side_effect=ValueError('雨衣の声には、この実行環境のVoiSona Talk API認証が必要です')) as synth:
                        if long:
                            with self.assertRaises(slots.PreviewVoiceUnavailable): slots.fit_preview(plan, rows)
                        else:
                            slots.fit_preview(plan, rows)
                        synth.assert_not_called()

    def test_oct25_binding_accepts_saved_pair_and_rejects_changed_script(self):
        plan = selected.program(load('20261025')); data, doc = plan['data'], plan['narration']
        entry = dict(video_id='fixture',title=doc['title'],preview_binding=history.binding(data,doc))
        published = dict(daily_soccer={'2026-10-25':entry})
        self.assertEqual(len(history.snapshot(data,doc,published)['games']), 4)
        wrong = copy.deepcopy(doc); wrong['segments'][0]['text'] += '変更'
        with self.assertRaisesRegex(ValueError, 'hash'): history.snapshot(data,wrong,published)

    def test_oct26_saved_card_fits_and_original_empty_bottom_is_rejected(self):
        plan = selected.program(load('20261026'))
        for seg in plan['narration']['segments'][:-1]:
            image = preview.draw(plan,seg)
            self.assertEqual(slots.check_frame(image,plan), [])
            next(e for e in image.info['v3_layout'] if e['role']=='card')['box'] = [72,390,940,1426]
            self.assertTrue(any('empty_card_bottom' in e for e in slots.check_frame(image,plan)))

    def test_oct30_real_material_and_logged_rounded_durations_pass(self):
        plan = selected.program(load('20261030'))
        with tempfile.TemporaryDirectory() as tmp:
            rows = audio_rows(plan['narration'],Path(tmp),[1.9,14.6,7.6])
            seconds = slots.video_times(plan['narration']['segments'],rows)
            report = short_content.assess(plan['narration'],seconds,plan['data'],maximum=55)
            self.assertEqual(report['status'],'passed',report)
            self.assertEqual(report['information_count'],3)
        doc = copy.deepcopy(plan['narration'])
        doc['segments'][1]['text'] = doc['segments'][1]['text'].split('。')[0]+'。'
        self.assertEqual(len(short_content.information(doc,plan['data'])),1)


class Budget(Offline):
    def test_shared_base_recheck_and_runner_up_allow_two_requests_total(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')):
            budget.reserve('sanity'); self.assertTrue(budget.available())
            budget.reserve('sanity_recheck'); self.assertFalse(budget.available())
            with self.assertRaises(budget.Exhausted): budget.reserve('runner-up')
            self.assertEqual(budget.state()['calls'],['sanity','sanity_recheck'])
            Path(tmp,'budget.json').write_text('{broken',encoding='utf8')
            with self.assertRaises(budget.Exhausted): budget.reserve('runner-up')

    def test_other_kinds_keep_old_sdk_and_backstage_contract_without_budget_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp)/'doc.json'; retry.write(doc,dict(segments=[dict(text='事実です。')]))
            response = SimpleNamespace(content=[SimpleNamespace(type='text',text='[]')])
            with patch('anthropic.Anthropic') as sdk, patch('backstage_guard.create',return_value=response) as create, \
                 patch('backstage_guard.create_once') as once, patch('token_log.record'):
                self.assertEqual(sanity.general([doc],'fake-test-only',materials=[]),[])
                sdk.assert_called_once_with(api_key='fake-test-only')
                create.assert_called_once(); self.assertEqual(create.call_args.kwargs['category'],'sanity')
                once.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()),[doc])

    def test_bounded_general_disables_sdk_retries_and_shares_all_request_slots(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')):
            doc = Path(tmp)/'doc.json'; retry.write(doc,dict(segments=[dict(text='事実です。')]))
            client = Mock(); client.messages.create.return_value = SimpleNamespace(
                content=[SimpleNamespace(type='text',text='[]')])
            with patch('anthropic.Anthropic',return_value=client) as sdk, patch('token_log.record'):
                self.assertEqual(sanity.general([doc],'fake-test-only',materials=[]),[])
                sdk.assert_called_once_with(api_key='fake-test-only',max_retries=0)
                self.assertEqual(client.messages.create.call_count,1)
                budget.reserve('other-check')
                with self.assertRaises(budget.Exhausted): sanity.general([doc],'fake-test-only',materials=[])
                self.assertEqual(client.messages.create.call_count,1)

    def test_backstage_correction_is_counted_and_keeps_the_original_guard(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')):
            doc=Path(tmp)/'doc.json'; retry.write(doc,dict(segments=[dict(text='事実です。')]))
            bad=SimpleNamespace(content=[SimpleNamespace(type='text',text='rejected')])
            good=SimpleNamespace(content=[SimpleNamespace(type='text',text='[]')])
            client=Mock(); client.messages.create.side_effect=[bad,good]
            with patch('anthropic.Anthropic',return_value=client),patch('token_log.record'), \
                 patch('token_log.allowed',return_value=True), \
                 patch('backstage_guard.violations',side_effect=lambda text:['bad'] if text=='rejected' else []):
                self.assertEqual(sanity.general([doc],'fake-test-only',materials=[]),[])
            self.assertEqual(client.messages.create.call_count,2)
            self.assertEqual(budget.state()['calls'],['sanity','sanity'])
            self.assertFalse(budget.available())

    def test_recheck_reserves_from_same_file_and_other_kinds_remain_unlimited_by_it(self):
        import token_log
        import llm_models
        model=llm_models.params('translate',700)['model']
        response=SimpleNamespace(content=[SimpleNamespace(type='text',text='[]')],
                                 usage=SimpleNamespace(input_tokens=1,output_tokens=1))
        client=Mock(); client.messages.create.return_value=response
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,
                COLLESPO_SANITY_BUDGET_FILE=str(Path(tmp)/'budget.json')), \
             patch('anthropic.Anthropic',return_value=client),patch('token_log.record'), \
             patch('token_log.allowed',return_value=True),patch('token_log.cost',return_value=.001), \
             patch.dict(token_log.PRICES,{model:dict(input=1,output=1)}):
            budget.reserve('sanity')
            _,info=sanity_recheck.ai_review([],[],[],'fake-test-only')
            self.assertEqual(info['calls'],1)
            self.assertEqual(budget.state()['calls'],['sanity','sanity_recheck'])
            _,info=sanity_recheck.ai_review([],[],[],'fake-test-only')
            self.assertEqual(info['calls'],0); self.assertEqual(client.messages.create.call_count,1)
            before=budget.path().read_bytes()
            with patch.dict(os.environ,COLLESPO_SANITY_BUDGET_FILE=''):
                _,info=sanity_recheck.ai_review([],[],[],'fake-test-only')
                self.assertEqual(info['calls'],1)
            self.assertEqual(budget.path().read_bytes(),before)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
