"""11/8の講評を、捏造・重複・引用の混同を防ぐ試験へ戻す。通信なし。"""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT)]
import morning_content as content
import soccer_result_facts as facts
import soccer_stats
import notability_engine as ne
import phrase_readings


class ResultContent(unittest.TestCase):
    def test_only_registered_japanese_names_and_no_minutes_inference(self):
        goal = dict(scorer='Unregistered Fixture Scorer',side='away',minute='57',
                    japanese_goal=False,japanese_assists=[],own_goal=False)
        game = dict(away=dict(name_jp='バイエルン'))
        self.assertEqual(facts.scorer_name(goal), '')
        self.assertEqual(facts.goal_line(goal,game), '57分にバイエルンが得点。')
        goal['scorer'] = '久保建英';goal['japanese_goal'] = True
        self.assertEqual(facts.scorer_name(goal), '久保建英')
        player = dict(name='検査選手',status='starter',subbed_out=False,red_cards=0,goals=0,assists=0)
        self.assertNotIn('90', soccer_stats.result_narration(player))
        self.assertIn('約90分出場', soccer_stats.minutes_label(dict(player,minutes=90)))

    def test_both_goal_screens_do_not_fall_back_to_raw_english(self):
        from PIL import Image
        import soccer_readable as readable
        goal = dict(scorer='Unregistered Fixture Scorer',side='away',minute='57',
                    japanese_goal=False,japanese_assists=[],own_goal=False)
        game = dict(home=dict(name_jp='マインツ'),away=dict(name_jp='バイエルン'),
                    score=dict(home=0,away=1),goals=[goal],goals_complete=True,league_jp='検査大会')
        for focus in (False, True):
            screen=readable.Screen.__new__(readable.Screen)
            screen.t=.5;screen.clubs={};screen.im=Image.new('RGB',(1080,1920))
            shown=[]
            def text(x,y,value,*args,**kwargs):
                shown.append(str(value));return y+60
            with patch.object(screen,'text',side_effect=text),patch.object(screen,'name',side_effect=text), \
                 patch.object(screen,'lines',side_effect=text),patch.object(screen,'title'), \
                 patch.object(screen,'panel'),patch.object(screen,'finish'), \
                 patch.object(readable.c,'lines',side_effect=lambda value,*args:[value]), \
                 patch('soccer_look.focus',return_value=focus):
                screen.goals(game,[goal],{})
            self.assertIn('バイエルン',shown)
            self.assertFalse(any('Unregistered' in value for value in shown))
            self.assertEqual(goal['scorer'],'Unregistered Fixture Scorer')


class PressContent(unittest.TestCase):
    def reporters(self):
        return dict(headlines=[dict(jp='気になる見出し',url='fixture:headline')],
            posts=[dict(jp='検査選手が受賞。球団では2人目です。もう一方のリーグは別の選手が受賞。',
                        uri='fixture:post',outlet='検査媒体',author='記者')])

    def test_one_source_its_contents_and_exact_quote_alignment(self):
        import press_v3
        reporters = self.reporters();data = dict(reporters=reporters)
        segs = content.press_segments(data,{})
        self.assertEqual(len(segs),3)
        self.assertEqual(segs[0]['text'],'検査選手が受賞。')
        self.assertNotIn('現地の報道です',''.join(s['text'] for s in segs))
        for seg in segs:
            self.assertEqual(content.selected_press(seg,reporters)[0][0]['uri'],'fixture:post')
            self.assertEqual(press_v3.bubbles(seg,reporters)[0]['said'],seg['text'])
        bad = copy.deepcopy(segs[1]);bad['text'] = '材料にない99人目です。'
        with self.assertRaises(ValueError):press_v3.bubbles(bad,reporters)

    def test_headline_alone_is_not_an_article_and_summary_is_allowed(self):
        self.assertIsNone(content.press_story(dict(headlines=self.reporters()['headlines'])))
        self.assertEqual(content.press_segments(dict(reporters=dict(posts=[dict(jp='詳しくは記事へ。',uri='fixture:p')])),{}),[])
        data = dict(headlines=[dict(jp='見出し',summary_jp='検査選手が移籍。契約は2年です。',url='fixture:article')])
        self.assertEqual(content.press_story(data)['parts'],['検査選手が移籍。','契約は2年です。'])
        data['headlines'][0]['summary_jp']='Read the article. More details.'
        self.assertIsNone(content.press_story(data))


class VoiceContent(unittest.TestCase):
    def data(self):
        return dict(buzz=[dict(video_id='one',topic_jp='検査選手が35セーブ',views=100)],voices=dict(voices=[
            dict(url='https://www.youtube.com/watch?v=one',ja='最高の投手だ！',title='Great pitcher!'),
            dict(url='https://www.youtube.com/watch?v=other',ja='守備もよい',title='Great defense'),
            dict(url='https://www.youtube.com/watch?v=one',ja='ブルワーズに来たらハマる',title='Would be a great Brewer')]))

    def test_topic_first_then_metan_quote_zunda_reaction(self):
        data=self.data();segs=content.voices_segments(data,{})
        self.assertEqual(segs[0]['text'],'検査選手が35セーブ。')
        self.assertEqual([s['speaker'] for s in segs],[2,2,3,2,3])
        text=''.join(s['text'] for s in segs)
        self.assertNotIn('守備もよい',text)
        self.assertIn('ファンの移籍への期待',text)
        self.assertNotIn('移籍しました',text)
        self.assertTrue(all((s['meta'].get('reaction') is True)==(s['speaker']==3) for s in segs))
        import comment_render
        for seg in segs:
            comment_render.voices_for_segment(seg,data['voices'])

    def test_production_does_not_merge_speakers_and_skips_unknown_topic(self):
        import generate_morning_short as g
        import review_render_v3 as r3
        data=dict(self.data(),date_jst='2026-11-08',players=[])
        with patch.dict(os.environ,dict(COLLESPO_COMMENTS_DESIGN='comments',COLLESPO_HOST_SPLIT='')),patch.object(r3,'LOOK','v4'):
            doc=g.build_narration(dict(data,short_content_version='1108'),'voices')
        self.assertEqual(doc['segments'][0]['kind'],'intro')
        self.assertEqual(sum(s.get('speaker')==3 for s in doc['segments']),2)
        data['buzz']=[]
        self.assertEqual(content.voices_segments(data,{}),[])


class RaceContent(unittest.TestCase):
    def test_only_the_nearest_boundary_and_one_table(self):
        import soccer_slots_v4 as slots
        from test_soccer_race_length import material
        import review_render_v3 as r3
        with patch.dict(os.environ,dict(COLLESPO_SOCCER_LOOK='v6',COLLESPO_HOST_SPLIT='')),patch.object(r3,'LOOK','v4'):
            doc=slots.race_program(dict(material(28),short_content_version='1108'))['narration']
        self.assertEqual(sum(s['kind']=='cover' for s in doc['segments']),1)
        self.assertEqual(sum(s['kind']=='standings' for s in doc['segments']),1)
        self.assertEqual(sum('勝点5差' in s['text'] for s in doc['segments']),1)
        self.assertNotIn('CL圏内の境目',''.join(s['text'] for s in doc['segments']))


class ReadingContent(unittest.TestCase):
    def test_requested_dictionary_and_same_kind_of_ue(self):
        self.assertEqual(ne.apply_readings('語る上で、MLB.com。'),'かたるうえで、エムエルビー・ドットコム。')
        for text in ('考える上で','確認した上で','比較する上で','試す上で','使う上で','書く上で'):
            with self.subTest(text=text):
                result=ne.apply_readings(text)
                self.assertIn('うえで',result)
                self.assertEqual(phrase_readings.unresolved(result),[])
        for text in ('机の上で','マウンド上で','事実上で'):
            self.assertEqual(ne.apply_readings(text),text)
        self.assertEqual(phrase_readings.unresolved('検討する上で'),['検討する上で'])


if __name__ == '__main__':
    unittest.main(argv=[__file__])
