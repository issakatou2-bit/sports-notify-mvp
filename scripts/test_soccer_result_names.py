"""日本人以外の得点者を英字のまま画面・声に出さないための検査。

10/21の朝の原稿に「チャンピオンズリーグ。57分にGuus Tilが得点。」と出て、
声がそのまま英字を読んでいた。画面にも英字が出た。

方針：日本語の表記が確かな辞書（当日名簿で確かめた日本人選手）に載って
いる者だけを名前で言い、載っていない者はクラブ名だけで言う。推測で
カタカナにしない（読み違いの元）。
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['COLLESPO_SHORT_LOOK']='v4'

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import club_display_names as names
import soccer_now as now
import soccer_result_facts as facts
import soccer_result_story as story
import soccer_results_render as render

FIX=ROOT/'scripts/fixtures/soccer-results/run-38817456251.json'
# 2文字以上の英字の並び（人名の候補）。
LATIN=re.compile(r'[A-Za-z]{2,}[A-Za-z0-9\.\-]*')
# このプロジェクトが全体で使っている固定の表記。
LABELS={'MLB','OG'}


def fixed():
    return json.loads(FIX.read_text(encoding='utf8'))


def latin(texts):
    """文字の行きから英字の並びを取り出す（行をまたいでつなげない）。"""
    if isinstance(texts,str):texts=[texts]
    found=set()
    for text in texts:found.update(LATIN.findall(str(text)))
    return found


def club_tokens(data):
    """画面・声に出してよい英字（クラブの表示名・英語名・略号だけ）。"""
    clubs=[]
    for game in data['games']:
        for side in ('home','away'):clubs.append(game[side])
    for row in (data.get('preview_followup') or {}).get('games',[]):
        nxt=row.get('next_game')
        if nxt:
            for side in ('home','away'):
                clubs.append(dict(name_jp=names.display(nxt[side]),name_en=nxt[side],abbr=''))
    tokens=set()
    for club in clubs:
        for value in (club.get('name_jp') or '',club.get('name_en') or '',club.get('abbr') or ''):
            tokens.update(latin(value))
        tokens.update(latin(names.display(club)))
    return tokens


def foreign_scorers(data):
    """辞書に無い（英語名のままの）得点者の名前。"""
    return {goal['scorer'] for game in data['games'] for goal in game['goals']
            if not goal['japanese_goal'] and LATIN.search(goal['scorer'])}


def script_texts(narration):
    """原稿（読み上げ・字幕・画面用の材料）の全部の文字。"""
    texts=[]
    for seg in narration['segments']:
        texts.append(seg.get('text') or '')
        texts.extend(seg.get('caption_units') or [])
        for line in seg.get('meta',{}).get('details') or []:
            texts.append(line.get('club') or '')
            texts.append(line.get('text') or '')
    return texts


def screen_texts(image):
    """画面に描いた文字（クラブの札の略号と出典のクレジットは除く）。"""
    return [str(entry.get('text')) for entry in image.info.get('v3_layout',[])
            if entry.get('text') and entry.get('role') not in ('badge','source')]


class SoccerResultNames(unittest.TestCase):
    def test_only_confirmed_dictionary_names_are_used(self):
        goal=dict(minute='57',scorer='未確認カタカナ',side='away',own_goal=False,japanese_goal=False)
        game=dict(away=dict(name_jp='PSV'))
        self.assertEqual(facts.goal_line(goal,game),'57分にPSVが得点。')
        with patch.object(facts,'player_names',return_value={'Confirmed Player':'確認済み選手'}):
            goal['scorer']='Confirmed Player'
            self.assertEqual(facts.goal_line(goal,game),'57分に確認済み選手が得点。')
            self.assertEqual(facts.screen_goal_line(goal,game)['text'],'57分に確認済み選手が得点')

    def test_japanese_assist_keeps_name_and_foreign_assist_is_hidden(self):
        data=fixed()
        game=data['games'][0]
        goal=game['goals'][0]
        goal.update(scorer='Guus Til',japanese_goal=False,japanese_assists=['鎌田大地','Unknown Assistant'])
        self.assertEqual(facts.assist_names(goal),['鎌田大地'])
        self.assertNotIn('Guus Til',facts.goal_line(goal,game))
        for look in ('v4','v5'):
            with self.subTest(look=look),patch.dict(os.environ,COLLESPO_SOCCER_LOOK=look):
                im=render.timeline(1.4,game,story.clubs_for(data),render.program_spec(data),[goal])
                shown=''.join(screen_texts(im))
                self.assertIn('鎌田大地',shown)
                self.assertNotRegex(shown,r'Guus|Til|Unknown|Assistant')
        player=dict(name='鎌田大地',status='starter',minutes=90,goals=0,assists=1)
        self.assertIn('鎌田大地は',facts.player_line(player))
        self.assertIn('1アシスト',facts.player_line(player))

    def test_unlisted_scorer_becomes_club_name(self):
        """10/21の例。英語名のままだった得点者はクラブ名に変わる。"""
        game={'id':'fixture','league_jp':'チャンピオンズリーグ','goals_complete':True,
              'home':{'name_jp':'ポルト'},'away':{'name_jp':'PSV'},
              'goals':[{'minute':'57','scorer':'Guus Til','side':'away','own_goal':False,
                        'japanese_goal':False,'japanese_assists':[]}]}
        line=facts.goal_line(game['goals'][0],game)
        self.assertEqual(line,'57分にPSVが得点。')
        self.assertNotIn('Guus Til',line)
        self.assertIn('PSV',line)
        # 画面用はクラブ名と文を分けて返す（クラブ名は札つきで描くため）。
        screen=facts.screen_goal_line(game['goals'][0],game)
        self.assertEqual(screen['club'],'PSV')
        self.assertNotIn('Guus Til',screen['text'])

    def test_japanese_scorer_keeps_name(self):
        """日本人の得点者は今までどおり名前で言う。"""
        game={'id':'fixture','league_jp':'チャンピオンズリーグ','goals_complete':True,
              'home':{'name_jp':'ポルト'},'away':{'name_jp':'PSV'},
              'goals':[{'minute':'81','scorer':'佐野航大','side':'away','own_goal':False,
                        'japanese_goal':True,'japanese_assists':[]}]}
        line=facts.goal_line(game['goals'][0],game)
        self.assertEqual(line,'81分に佐野航大が得点。')
        self.assertIn('佐野航大',line)
        self.assertFalse(LATIN.search(line))
        screen=facts.screen_goal_line(game['goals'][0],game)
        self.assertIsNone(screen['club'])
        self.assertIn('佐野航大',screen['text'])

    def test_own_goal_by_foreigner_uses_club_name(self):
        """オウンゴールも同じ扱い。得点したクラブ名で言う。"""
        game={'id':'fixture','league_jp':'ヨーロッパリーグ','goals_complete':True,
              'home':{'name_jp':'ニース'},'away':{'name_jp':'リール'},
              'goals':[{'minute':'22','scorer':'Nathan Ngoy','side':'home','own_goal':True,
                        'japanese_goal':False,'japanese_assists':[]}]}
        line=facts.goal_line(game['goals'][0],game)
        self.assertNotIn('Nathan Ngoy',line)
        self.assertIn('ニース',line)
        self.assertIn('オウンゴール',line)

    def test_script_has_no_english_player_names(self):
        """保存材料の原稿（読み上げ・字幕）に英字の人名が残らない。"""
        data=fixed();foreign=foreign_scorers(data)
        self.assertTrue(foreign,'保存材料に英語名の得点者がいないと検査できない')
        narration=story.narration(data)
        texts=script_texts(narration)
        blob='\n'.join(texts)
        for name in foreign:self.assertNotIn(name,blob)
        # 出てよい英字はクラブ名と略号だけ。
        unknown=latin(texts)-club_tokens(data)-LABELS
        self.assertEqual(unknown,set(),'原稿に説明できない英字が出ています: '+str(sorted(unknown)))
        # 日本人選手の得点は名前がそのまま出ている。
        self.assertIn('81分に鎌田大地が得点',blob)
        self.assertIn('87分に町田浩樹が得点',blob)
        # 辞書に無い 得点はクラブ名になっている。
        detail=next(s for s in narration['segments'] if s['kind']=='followup-detail')
        clubs=[line.get('club') for line in detail['meta']['details']]
        self.assertIn('リヨン',clubs)

    def test_screen_has_no_english_player_names(self):
        """描いた画面（v4/v5）に英字の人名が残らない。"""
        data=fixed();foreign=foreign_scorers(data)
        self.assertTrue(foreign)
        narration=story.narration(data)
        plain=render.narration(data)
        allowed=club_tokens(data)|LABELS
        for look in ('v4','v5'):
            with self.subTest(look=look),patch.dict(os.environ,dict(COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_LOOK=look)):
                clubs=story.clubs_for(data)
                for seg in narration['segments']+plain['segments']:
                    render.r3.set_program_clock(0)
                    render.r3.set_caption(seg.get('text',''),10,60,caption_units=seg.get('caption_units'))
                    render.r3.set_program_clock(1.4)
                    image=render.frame(1.4,seg,data,clubs)
                    shown=screen_texts(image)
                    for name in foreign:self.assertNotIn(name,''.join(shown))
                    unknown=latin(shown)-allowed
                    self.assertEqual(unknown,set(),'画面の説明できない英字: '+str(sorted(unknown)))
        render.r3.set_program_clock(None)

    def test_match_flash_narration_has_no_english_player_names(self):
        """試合速報（soccer_now）の決勝点も、英語名を読み上げない。"""
        boards=json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf8'))
        summaries=json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf8'))
        built,errors=now.build(boards,summaries,now.results.utc('2026-09-20T17:15:00Z'))
        self.assertFalse(errors)
        data=built[0];game=data['games'][0]
        scorer=game['winner_goal']['scorer']
        self.assertTrue(LATIN.search(scorer),'保存材料の決勝点が英語名ではないと検査できない')
        segments=now.narration(data)['segments']
        blob=''.join(s['text'] for s in segments)
        self.assertNotIn(scorer,blob)
        self.assertIn(game[game['winner_goal']['side']]['name_jp']+'が得点',blob)
        unknown=latin([s['text'] for s in segments])-club_tokens(data)-LABELS
        self.assertEqual(unknown,set(),'試合速報に説明できない英字: '+str(sorted(unknown)))


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
