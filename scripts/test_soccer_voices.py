"""Opus183の18検査を本番へ。通信不要、架空の材料と壊した訳で検査する。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import wave

import soccer_voices as sv
import soccer_voices_render as render
import local_voices as lv

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'scripts/fixtures/soccer-voices/fictional.json'
NAMES=sv.load_names()


def players(*names):
    return [p for p in NAMES if p['name_jp'] in names]


def sample(): return render.prepare(sv.sample_input(FIX))


def fake_client(text,stop='end_turn'):
    create=lambda **kwargs:NS(content=[NS(text=text,type='text')],stop_reason=stop)
    from unittest.mock import Mock
    return NS(messages=NS(create=Mock(side_effect=create)))


class Names(unittest.TestCase):
    def test_roster_and_affiliations_are_current(self):
        self.assertEqual({p['name_jp'] for p in NAMES},{p['name_jp'] for p in sv.ne.JP_PLAYERS_SOCCER})
        video=json.loads(FIX.read_text(encoding='utf-8'))['video']
        self.assertEqual([p['name_jp'] for p in sv.players_in_match(video,NAMES)],['菅原由勢'])
        video['clubs']=['Leeds United','Juventus'];video['jp_players']=['菅原由勢','田中碧']
        self.assertEqual([p['name_jp'] for p in sv.players_in_match(video,NAMES)],['田中碧'])

    def test_accent_kanji_case(self):
        for text in ('Dōan was brilliant','Was für ein Spiel von DOAN heute','堂安すごい'):
            self.assertEqual(sv.names_in(text,players('堂安律')),['堂安律'])

    def test_possessive_nicknames_and_partial_words(self):
        for text,person in (("Sugawara's crosses were great",'菅原由勢'),('Take Kubo is magic','久保建英'),('Zion saved us again','鈴木ザイオン')):
            self.assertEqual(sv.names_in(text,players(person)),[person])
        self.assertFalse(sv.names_in('Kuboviak scored',players('久保建英')))

    def test_common_surname_not_generic_word(self):
        ps=players('宇野禅斗')
        for text in ('Solo uno ha giocato bene','Uno de los mejores partidos'):
            self.assertFalse(sv.names_in(text,ps))
        self.assertEqual(sv.names_in('Heute war Uno überall',ps),['宇野禅斗'])
        self.assertEqual(sv.names_in('Zento Uno!',ps),['宇野禅斗'])

    def test_same_surname_is_ambiguous_and_foreign_full_name_not_counted(self):
        both=players('田中碧','田中聡')
        self.assertFalse(sv.names_in('Tanaka played well',both))
        self.assertEqual(sv.names_in('Ao Tanaka played well',both),['田中碧'])
        self.assertEqual(sv.names_in('Satoshi Tanaka played well',both),['田中聡'])
        self.assertFalse(sv.names_in('Satoshi Tanaka played well',players('田中碧')))
        self.assertFalse(sv.names_in('田中聡はいい',players('田中碧')))
        self.assertFalse(sv.names_in('Yuito Suzuki played well',players('鈴木ザイオン')))


class Selection(unittest.TestCase):
    def test_abusive_non_named_duplicates_and_likes(self):
        raw=json.loads(FIX.read_text(encoding='utf-8'))
        picked,why=sv.select(raw['comments'],sv.players_in_match(raw['video'],NAMES))
        self.assertGreaterEqual(why['named'],3)
        self.assertEqual([v['likes'] for v in picked],sorted([v['likes'] for v in picked],reverse=True))
        self.assertFalse(any('trash' in v['title'] or 'atmosphere' in v['title'] for v in picked))
        for text in ('Sugawara is trash','Sugawara sei uno scemo','@marco Sugawara played well','Sugawara go back to Japan'):
            self.assertTrue(sv.is_abusive(text))
        self.assertFalse(sv.is_abusive('Sugawara was the best player'))

    def test_less_than_three_after_translation_does_not_make(self):
        data=sample()
        self.assertFalse(sv.build_script(data['video'],data['voices'][:2],sample=True)['can_make'])
        items=copy.deepcopy(data['voices'])
        for item in items[1:]:item['tone']='批判'
        self.assertFalse(sv.build_script(data['video'],items,sample=True)['can_make'])

    def test_unknown_tone_unreviewed_and_tampered_translations_are_dropped(self):
        data=sample();items=copy.deepcopy(data['voices'])
        for item in items:item['tone']='不明'
        self.assertFalse(sv.build_script(data['video'],items,sample=True)['can_make'])
        items=copy.deepcopy(data['voices'])
        for item in items:item.pop('semantic_review')
        self.assertFalse(sv.build_script(data['video'],items,sample=True)['can_make'])
        items=copy.deepcopy(data['voices'])
        for item in items:item['ja']+='すごい'
        self.assertFalse(sv.build_script(data['video'],items,sample=True)['can_make'])


class Translation(unittest.TestCase):
    def item(self,original,ja):return dict(title=original,ja=ja)

    def test_no_added_numbers_kanji_goals_assists_or_players(self):
        ps=players('菅原由勢','田中碧')
        for original,ja in [('Sugawara was great','菅原は90分プレー'),('Sugawara was great','菅原は二得点'),
                            ('Sugawara made an assist','菅原がゴール'),('Sugawara scored a goal','菅原がアシスト'),
                            ('Sugawara was great','菅原と田中碧のパス')]:
            self.assertTrue(sv.check_translation(self.item(original,ja),ps),(original,ja))
        self.assertFalse(sv.check_translation(self.item('Sugawara 10/10 tonight','菅原は10点満点'),ps))

    def test_numbers_use_counts_and_decimal_values(self):
        self.assertTrue(sv.check_translation(self.item('Sugawara 1-0','菅原は1-1'),players('菅原由勢')))
        self.assertTrue(sv.check_translation(self.item('Sugawara 1.1','菅原は1.2'),players('菅原由勢')))

    def test_parent_is_only_context_not_permission_to_add_its_events(self):
        p=players('菅原由勢')
        self.assertFalse(sv.check_translation(dict(original='Yes, absolutely!',ja='菅原は本当にそう！'),p,'Sugawara is great'))
        self.assertTrue(sv.check_translation(dict(original='Yes, absolutely!',ja='菅原は2得点！'),p,'Sugawara scored 2 goals'))

    @patch.object(lv.token_log,'allowed',return_value=True)
    @patch.object(lv.token_log,'record')
    def test_existing_translator_keeps_reply_context_and_mlb_default(self,*_):
        inputs=[dict(title='Sugawara thanked the fans',reply_texts=['They sang all night'])]
        client=fake_client('1|称賛|Sugawaraはファンに感謝した\n2|称賛|彼らは一晩中歌った')
        got=lv.translate(client,inputs,sport='soccer')
        prompt=client.messages.create.call_args.kwargs['messages'][0]['content']
        self.assertIn('（1への返信）',prompt);self.assertIn('選手・ファン・監督',prompt)
        self.assertIn('欧州のサッカー',prompt);self.assertEqual(got[0]['reply_ja'][0]['original'],'They sang all night')
        lv.translate(client,inputs)
        self.assertIn('アメリカの野球',client.messages.create.call_args.kwargs['messages'][0]['content'])
        self.assertIn('ファン（観客）',prompt)

    @patch.object(lv.token_log,'allowed',return_value=True)
    @patch.object(lv.token_log,'record')
    def test_soccer_unknown_or_missing_tone_is_fail_closed(self,*_):
        client=fake_client('1|不明|訳です\n2. 訳です')
        self.assertFalse(lv.translate(client,[dict(title='a'),dict(title='b')],sport='soccer'))
        self.assertEqual(len(lv.translate(client,[dict(title='a'),dict(title='b')])),2)

    @patch.object(lv.token_log,'allowed',return_value=True)
    @patch.object(lv.token_log,'record')
    def test_independent_review_rejects_actor_swap_criticism_missing_or_fake_boolean(self,*_):
        item=dict(title='Sugawara thanked the fans',ja='菅原は選手に感謝した',tone='称賛')
        row=dict(id=0,noncritical=True,no_abuse=True,faithful=True,actors=False,names=True)
        for text in (json.dumps([row]),'not json','[]',json.dumps([dict(row,actors=1)]),json.dumps([row,row])):
            checked=sv.review_translations(fake_client(text),[item],players('菅原由勢'))
            self.assertFalse(sv.eligible(checked,players('菅原由勢')))
        good=dict(row,actors=True)
        checked=sv.review_translations(fake_client(json.dumps([good])),[item],players('菅原由勢'))
        self.assertTrue(sv.approved(checked[0]))
        bad=dict(good,noncritical=False)
        checked=sv.review_translations(fake_client(json.dumps([bad])),[item],players('菅原由勢'))
        self.assertFalse(sv.approved(checked[0]))

    @patch.object(lv.token_log,'allowed',return_value=True)
    @patch.object(lv.token_log,'record')
    def test_semantic_review_reply_has_parent_and_can_be_excluded_alone(self,*_):
        v=dict(title='Sugawara thanked the fans',ja='菅原はファンに感謝した',tone='称賛',
               reply_ja=[dict(original='They sang all night',ja='選手は一晩中歌った',tone='中立')])
        ok=dict(noncritical=True,no_abuse=True,faithful=True,actors=True,names=True)
        client=fake_client(json.dumps([dict(ok,id=0),dict(ok,id=1,actors=False)]))
        checked=sv.review_translations(client,[v],players('菅原由勢'))
        self.assertTrue(sv.approved(checked[0]));self.assertFalse(checked[0]['reply_ja'])
        self.assertIn('Sugawara thanked the fans',client.messages.create.call_args.kwargs['messages'][0]['content'])


class Script(unittest.TestCase):
    def test_title_labels_pairs_readings_outro_and_budget(self):
        data=sample();sv.validate_data(data);narr=sv.narration(data)
        self.assertTrue(data['can_make']);self.assertTrue(data['sample_fictional'])
        self.assertIn('菅原由勢に現地ファンは何と言ったか',data['title'])
        self.assertIn('カリアリ 対 ユベントス',data['title']);self.assertIn('翻訳',data['label'])
        self.assertIn('記録ではありません',data['source']);self.assertFalse(data['video_url'])
        self.assertLessEqual(sum(len(s['text']) for s in narr['segments']),sv.SPEECH_LIMIT)
        self.assertEqual(narr['segments'][-1]['text'],render.r3.OUTRO_TEXT)
        self.assertNotIn('Sugawara',''.join(s['text'] for s in narr['segments']))
        self.assertNotIn('コレスポの見解ではありません',''.join(s['text'] for s in narr['segments']))
        quotes=[v['ja'] for v in data['voices']]+[r['ja'] for v in data['voices'] for r in v['reply_ja']]
        self.assertFalse(render.rules.check_quotes(quotes))
        self.assertFalse(sv.numbers(narr['segments'][0]['text']))

    def test_sample_cannot_be_uploaded_even_if_input_flag_removed(self):
        data=sample()
        with self.assertRaisesRegex(ValueError,'架空'):sv.validate_data(data,publish=True)
        with tempfile.TemporaryDirectory() as directory:
            raw=json.loads(FIX.read_text(encoding='utf-8'));raw.pop('sample_fictional')
            file=Path(directory)/'fixture.json';file.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
            self.assertTrue(sv.sample_input(file)['sample_fictional'])

    def test_uploader_guards_fiction_and_uses_soccer_source_and_voice(self):
        import upload_youtube as upload
        data=sample()
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'data.json';file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'架空'):
                upload.build_metadata(str(file),data['date_jst'],kind='soccer_voices',sport='soccer')
            # Structurally live material for metadata only; never call the uploader or make it a fixture.
            data['sample_fictional']=False;data['video']['video_id']='abc123_DEF4'
            data['video_url']='https://www.youtube.com/watch?v=abc123_DEF4'
            data['title']=sv.title_for(data['star'],data['video'])
            file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            meta=upload.build_metadata(str(file),data['date_jst'],kind='soccer_voices',sport='soccer')['snippet']
            self.assertEqual(meta['title'],data['title'])
            self.assertIn(data['screen_source'],meta['description'])
            self.assertIn('VOICEVOX:四国めたん',meta['description'])
            self.assertNotIn('ESPN',meta['description']);self.assertNotIn('MLB Stats API',meta['description'])
            self.assertIn('コレスポの見解ではありません',meta['description'])

    def test_actual_voice_duration_matching_and_strict_limit(self):
        narr=sv.narration(sample())
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'a.wav'
            with wave.open(str(file),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\x00\x00'*24000)
            audio=[dict(s,file=str(file),duration=1) for s in narr['segments']]
            self.assertLessEqual(sum(render.slots.durations(narr['segments'],audio)),40)
            audio[0]['text']='wrong'
            with self.assertRaises(ValueError):render.slots.durations(narr['segments'],audio)
            audio=[dict(s,file=str(file),duration=41) for s in narr['segments']]
            with patch('synthesize_narration.audio_duration',return_value=41):
                with self.assertRaisesRegex(ValueError,'40秒'):render.slots.durations(narr['segments'],audio)

    def test_workflow_only_manual_off_font_order_and_guard(self):
        import yaml
        src=(ROOT/'.github/workflows/soccer_voices.yml').read_text(encoding='utf-8')
        wf=yaml.safe_load(src);on=wf.get('on') or wf.get(True)
        self.assertEqual(set(on),{'workflow_dispatch'})
        self.assertIs(on['workflow_dispatch']['inputs']['publish']['default'],False)
        self.assertLess(src.index('bash scripts/install_video_tools.sh'),src.index('python scripts/test_soccer_voices.py'))
        self.assertLess(src.index('publish=True'),src.index('--kind soccer_voices'))

    def test_live_path_uses_existing_fetch_and_translate_and_checks_next_video(self):
        raw=json.loads(FIX.read_text(encoding='utf-8'));video=raw['video']
        prepared=sample()['voices'];prepared=copy.deepcopy(prepared)
        fake_video=dict(video,video_id='abc123_DEF4')
        with patch.object(lv,'translate',return_value=prepared) as tr,patch.object(sv,'review_translations',return_value=prepared):
            calls=[]
            def fetch(path):
                packet=json.loads(Path(path).read_text(encoding='utf-8'));calls.append(packet)
                return [] if len(calls)==1 else raw['comments']
            got=sv.build({'videos':[fake_video,fake_video]},NS(),fetch=fetch)
            self.assertTrue(got['can_make']);self.assertEqual(len(calls),2)
            self.assertEqual(calls[1]['videos'],[fake_video]);self.assertFalse(got['sample_fictional'])
            tr.assert_called_once();self.assertEqual(tr.call_args.kwargs['sport'],'soccer')

    def test_missing_keys_overwrites_stale_material_with_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'data.json';out.write_text('{"can_make":true}',encoding='utf-8')
            with patch.dict(os.environ,{'YOUTUBE_API_KEY':'','ANTHROPIC_API_KEY':''}),patch.object(sys,'argv',['soccer_voices','--out',str(out)]):
                self.assertEqual(sv.main(),0)
            self.assertFalse(json.loads(out.read_text(encoding='utf-8'))['can_make'])


class Screens(unittest.TestCase):
    def test_punctuation_uses_the_same_baseline_as_words(self):
        if render.r3.LOOK!='v4':return
        im=render.cards.canvas(3,{},sv.LABEL)
        render.draw_lines(im,100,400,[[('Sugawara',None),("'",None),('s crosses.',None)]],32,render.r3.INK)
        entries=[e for e in im.info['v3_layout'] if e['role']=='text']
        f=render.r3.font(32);row_dy=f.getbbox("Sugawara's crosses.")[1]
        for e in entries:
            self.assertAlmostEqual(e['box'][1],400-row_dy+f.getbbox(e['text'])[1])

    def test_all_frames_safe_material_bound_and_clubs_inline(self):
        if render.r3.LOOK!='v4':return
        check_material(sample())

    def test_quote_and_reply_do_not_repeat_and_track_current_reading(self):
        if render.r3.LOOK!='v4':return
        data=sample();club=render.clubs_for(data)
        v=next((v for v in data['voices'] if v['reply_ja']),None)
        self.assertIsNotNone(v,'固定材料に返信が必要')
        early=render.voice_screen(0,data,v,club,20);late=render.voice_screen(19,data,v,club,20)
        self.assertEqual(early.info['soccer_shown_quotes'],[v['ja']])
        self.assertEqual(late.info['soccer_shown_quotes'],[v['ja'],v['reply_ja'][0]['ja']])
        self.assertEqual(late.info['soccer_reading'],'reply')

    def test_wrong_missing_or_floating_club_badge_rejected(self):
        if render.r3.LOOK!='v4':return
        data=sample();clubs=render.clubs_for(data);im=render.cover(3,data,clubs)
        self.assertFalse(render.cards.check_club_badges(im,clubs))
        bad=copy.deepcopy(im);bad.info['v4_badges'][0]['club_id']='wrong'
        self.assertTrue(render.cards.check_club_badges(bad,clubs))
        bad=copy.deepcopy(im);bad.info['v4_badges'][0]['box'][2]-=40
        self.assertTrue(render.cards.check_club_badges(bad,clubs))


def check_material(data):
    sv.validate_data(data)
    if not data['can_make']:return
    if render.r3.LOOK!='v4':return
    clubs=render.clubs_for(data);narr=sv.narration(data)
    try:
        for seg in narr['segments']:
            render.r3.set_caption(seg['text'],20,120,speaker=2,hide_caption=seg['kind']=='outro')
            for t in (0,.5,3,19):
                render.r3.set_program_clock(t)
                im=render.frame(t,seg,data,clubs,20)
                errors=render.check_frame(im,data,clubs)
                if errors:raise AssertionError((seg['kind'],t,errors))
                if seg['kind']=='outro' and not im.info.get('v3_outro'):raise AssertionError('共通の締めではない')
    finally:
        render.r3.set_caption('',0,0);render.r3.set_program_clock(None)


if __name__=='__main__':
    if '--material' in sys.argv:
        file=Path(sys.argv[sys.argv.index('--material')+1]);check_material(json.loads(file.read_text(encoding='utf-8')))
        print('ok soccer voices material/drawing')
    elif '--child' in sys.argv:
        unittest.main(argv=[sys.argv[0]],verbosity=1)
    else:
        fail=0
        for look in ('v3','v4'):
            proc=subprocess.run([sys.executable,'-X','utf8',__file__,'--child'],env=dict(os.environ,COLLESPO_SHORT_LOOK=look),capture_output=True,text=True,encoding='utf-8',errors='replace')
            print(look,proc.stderr[-4500:]);fail+=bool(proc.returncode)
            if proc.returncode:print('NG '+look+' '+proc.stderr[-1600:].replace('\n',' / '))
        print('ok soccer voices v3/v4' if not fail else 'NG soccer voices');raise SystemExit(bool(fail))
