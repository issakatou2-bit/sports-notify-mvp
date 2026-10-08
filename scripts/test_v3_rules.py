"""今後に生きる決まり。6種類のv3を固定材料で毎回検査する。"""
import copy
from datetime import datetime
import json
import os
import subprocess
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bignumber_render as bn
import daily_v3
import generate_asset_video as asset
import generate_morning_short as g
import ps_program as ps
import ps_unified_v3 as unified
import review_render_v3 as r3
import v3_rules as rules
import v3_slot_render as common

ROOT=Path(__file__).resolve().parents[1]
ENV={'COLLESPO_PLAYERS_DESIGN':'bignumber','COLLESPO_COMMENTS_DESIGN':'comments',
     'COLLESPO_PRESS_DESIGN':'v3','COLLESPO_PS_DESIGN':'v3'}


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def daily_cases():
    cases=[]
    data=read('scripts/fixtures/bignumber/morning_recap.json')
    data['players']=g.sort_players(data['players'])
    with patch.dict(os.environ,ENV),patch.object(g,'week_line',return_value=('',[])):
        nar=g.build_narration(data,'players')
    scenes=bn.scenes_from_morning(data,nar)
    cases.append(dict(name='players',exclude='morning',segments=nar['segments'],multi=True,
                      frames=[lambda t,s=s:bn.scene(t,s) for s in scenes],quotes=[]))
    if r3.LOOK=='v4':
        data=read('scripts/fixtures/bignumber/recap_history/2026-09-25.json')
        data['players']=g.sort_players(data['players'])
        with patch.dict(os.environ,ENV),patch.object(g,'week_line',return_value=('',[])):
            nar=g.build_narration(data,'players')
        scenes=bn.scenes_from_morning(data,nar)
        if bn.check_scenes(scenes,nar,data):raise ValueError('7人の成績の読み上げ照合が失敗')
        cases.append(dict(name='players-seven',exclude='morning',segments=nar['segments'],multi=True,
                          frames=[lambda t,s=s:bn.scene(t,dict(s,dur=20)) for s in scenes],quotes=[]))
    for mode,filename in [('voices','local_voices-preview.json'),('press','local_reporters-preview.json')]:
        material=read('scripts/fixtures/comment/'+filename)
        data={'players':[],mode if mode=='voices' else 'reporters':material,'date_jst':material['updated_at'][:10]}
        with patch.dict(os.environ,ENV):
            nar=g.build_narration(data,mode);design=daily_v3.prepare(data,nar,mode)
        quotes=[v['said'] for s in nar['segments'] for v in s['meta'].get('quote_rows',[]) if v.get('read') and not v.get('fact')]
        cases.append(dict(name=mode,exclude='morning_'+mode,segments=nar['segments'],multi=True,
                          frames=[lambda t,s=s,d=design:daily_v3.frame(t,s,d,20) for s in nar['segments']],quotes=quotes))
    saved=read('scripts/fixtures/ps-design/2026-10-07.json')
    for slot in ('forecast','situation'):
        with patch.dict(os.environ,ENV):
            program=ps.prepare(saved['snapshot'],saved['evidence'],slot,datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
        ps.check_program(program)
        cards=[s['meta']['card'] for s in program['segments']]
        cases.append(dict(name=slot,exclude='daily' if slot=='forecast' else 'postseason',segments=program['segments'],multi=True,
                          frames=[lambda t,c=c:unified.frame(t,c) for c in cards],quotes=[v['quote'] for c in cards for v in c.get('items',[]) if 'quote' in v]))
    return cases


def asset_cases():
    cases=[]
    materials=read('scripts/fixtures/v3-rules/assets.json')['topics']+read('scripts/fixtures/v3-rules/game-v4.json')['topics']
    for spec in materials:
        key=spec['key'];spec=copy.deepcopy(spec)
        with patch.dict(asset.LIST_TOPICS,{key:spec}):
            nar=asset.build_narration(key)
        frames=[]
        for seg in nar['segments']:
            def render(t,s=seg,v=spec,k=key):
                with patch.dict(asset.LIST_TOPICS,{k:v}):
                    return asset.render_v3(t,s['kind'],s['meta'],v,k)
            frames.append(render)
        cases.append(dict(name='asset:'+key,exclude=spec.get('lineup_kind',''),segments=nar['segments'],multi=bool(spec.get('teams') or spec.get('series_key') or spec.get('game') or not spec.get('team_id')),
                          frames=frames,quotes=[b for _,b in spec['items'] if str(b).startswith('「')],spec=spec))
    return cases


class V3Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=daily_cases()+asset_cases()

    def test_multiple_clubs_use_brand_background(self):
        for case in self.cases:
            if not case['multi']:continue
            for draw in case['frames']:
                with self.subTest(slot=case['name']),patch.object(r3,'background',wraps=r3.background) as background:
                    draw(3)
                    self.assertTrue(background.call_args_list)
                    self.assertTrue(all(c.args[1] is None for c in background.call_args_list),background.call_args_list)

    def test_quotes_appear_once_and_disclaimer_is_not_spoken(self):
        for case in self.cases:
            with self.subTest(slot=case['name']):
                self.assertFalse(rules.check_quotes(case['quotes']))
                self.assertNotIn('コレスポの見解ではありません',''.join(s['text'] for s in case['segments']))
        self.assertTrue(rules.check_quotes(['「同じ引用」','同じ引用']))

    def test_every_frame_and_card_has_safe_positions(self):
        for case in self.cases:
            for index,draw in enumerate(case['frames']):
                for t in (.1,3,7,11,15,19):
                    with self.subTest(slot=case['name'],screen=index,time=t):
                        self.assertFalse(rules.check_layout(draw(t)))
        bad=r3.background(0,None)
        r3.record_box(bad,'text',(0,300,1000,1300),'はみ出し')
        self.assertTrue(rules.check_layout(bad))

    def test_all_pages_keep_complete_cards_and_text(self):
        rows=[('長い引用','「'+'全文を残して安全域でページを分ける。'*18+'」')]+[(f'DS 第{i}戦','2勝　大谷翔平・佐々木朗希・山本由伸') for i in range(1,6)]
        spec={'heading':'全画面の検査'};pages=common.paginate(spec,rows)
        self.assertGreater(len(pages),1)
        self.assertEqual({cell['row'] for p in pages for cell in p},set(range(len(rows))))
        for i in range(len(pages)):
            self.assertFalse(rules.check_layout(common.frame(i*4+3,spec,rows,'検査')))
        self.assertFalse(common.check_pages(spec,rows))

    def test_marks_require_an_explanation(self):
        for case in self.cases:
            with self.subTest(slot=case['name']):
                if r3.LOOK=='v4' and case['name'] in ('forecast','situation'):
                    for draw in case['frames']:
                        image=draw(3)
                        for mark in image.info.get('v4_marks',[]):
                            self.assertEqual(mark['explanation'],f'{mark["need"]}勝で決着')
                            self.assertTrue(0<=mark['wins']<=mark['need'])
                            self.assertTrue(any(mark['explanation'] in e['text'] for e in image.info['v3_layout']))
                else:
                    with patch.object(r3.ImageDraw.ImageDraw,'ellipse') as ellipse:
                        for draw in case['frames']:draw(3)
                        ellipse.assert_not_called()
            if case.get('spec'):
                self.assertFalse(rules.check_marks(case['spec']))
        spec={'v3':{'chips':[{'label':'ドジャース','score':'2勝','win':True}]}}
        with patch.object(r3.ImageDraw.ImageDraw,'ellipse') as ellipse:
            r3.intro(3,spec,'予告');ellipse.assert_not_called()
        self.assertFalse(any(c[1]=='pop' for c in r3.cues('intro',spec)))
        self.assertTrue(rules.check_marks({'v3':{'chips':[{'label':'○','score':'2勝'}]}}))

    def test_each_slot_uses_shared_outro_text_renderer_and_cues(self):
        for case in self.cases:
            self.assertEqual(case['segments'][-1]['text'],r3.OUTRO_TEXT,case['name'])
            with patch.object(r3,'outro',return_value=object()) as outro:
                case['frames'][-1](3)
                outro.assert_called_once()
                self.assertEqual(outro.call_args.args[2],case['exclude'])
                self.assertIn('VOICEVOX',outro.call_args.args[3])
        sentinel=[(0,'transition','b',-6)]
        with patch.object(r3,'outro_cues',return_value=sentinel) as cues:
            self.assertEqual(bn.cues({'kind':'outro'}),sentinel);cues.assert_called_with('morning')
            for exclude in ('daily','postseason'):
                self.assertEqual(unified.cues({'outro':True,'lineup_kind':exclude}),sentinel);cues.assert_called_with(exclude)
            for mode in ('voices','press'):
                with patch('sound_mix.mix_file',return_value='mixed'):
                    daily_v3.mix('audio',[{'kind':'outro','speaker':2}],[5],{'mode':mode},ROOT/'build')
                cues.assert_called_with('morning_'+mode)
            r3.cues('outro',{'lineup_kind':'asset'});cues.assert_called_with('asset')
        # 動画のPS切替処理が、共通の締めへ日程の帯を重ねない。
        closing=r3.outro(3,{},'daily')
        with patch.object(r3,'ticker') as ticker:
            raw=unified.transition(closing.tobytes(),closing,6,6,30,'明日の試合')
            ticker.assert_not_called()
        self.assertEqual(raw,closing.tobytes())

    def test_material_speech_numbers_match_its_items(self):
        for case in self.cases:
            if case.get('spec'):
                self.assertFalse(rules.check_speech(case['spec'],case['spec']['items']))
        spec=copy.deepcopy(next(c['spec'] for c in self.cases if c.get('spec',{}).get('spotlight')))
        spec['speech']['この試合の投球']='99奪三振でした。'
        self.assertTrue(rules.check_speech(spec,spec['items']))

    def test_asset_v4_all_items_pages_and_players_fit_and_keep_material(self):
        if r3.LOOK!='v4':return
        import asset_v4_cards as cards
        for spec in read('scripts/fixtures/v3-rules/game-v4.json')['topics']:
            for i,(head,body) in enumerate(spec['items']):
                total=cards.item_pages(spec,head,body)
                for page in range(total):
                    with self.subTest(topic=spec['key'],item=i,page=page):
                        im=cards.item(3,spec,'試合の話題',head,body,page)
                        self.assertFalse(rules.check_layout(im))
                        self.assertEqual(im.info['asset_v4'].get('pages',1),total)
                        if im.info['asset_v4']['kind']=='quote':
                            self.assertEqual(im.info['asset_v4']['said'],body.strip('「」'))
            for index,row in enumerate(spec.get('japanese') or []):
                duration=20
                weights=[len(r['name']+'が'+r['line']+'、') for r in spec['japanese'][:3]]
                at=duration*(sum(weights[:index])+weights[index]*.5)/sum(weights)
                im=cards.people(at,spec,spec['japanese'],'日本人選手','試合の話題')
                self.assertFalse(rules.check_layout(im))
                self.assertEqual(im.info['asset_v4']['name'],row['name'])
        pairs=cards.stat_pairs('4回と3分の1を2失点')
        self.assertEqual(pairs,[('4','回3分の1'),('2','失点')])
        self.assertEqual(cards.stat_pairs('3分の1回を無失点'),[('1/3','回')])

    def test_asset_v4_order_follows_the_unchanged_spoken_items(self):
        if r3.LOOK!='v4':return
        import asset_v4_cards as cards
        spec=read('scripts/fixtures/v3-rules/game-v4.json')['topics'][0]
        for start in range(0,len(spec['items']),2):
            selected=spec['items'][start:start+2]
            weights=[len(f'{h}。{b}。') for h,b in selected]
            with patch.dict(r3._CAPTION,{'duration':20}):
                for j,w in enumerate(weights):
                    t=20*(sum(weights[:j])+w*.5)/sum(weights)
                    im=r3.list_page(t,spec,spec['items'],start,len(selected),1,1,'試合の話題')
                    self.assertEqual(im.info['asset_v4']['item'],start+j)

    def test_linescore_keeps_unknown_bottom_and_rejects_missing_or_wrong_totals(self):
        import ps_game_story as story
        feed=read('scripts/fixtures/v3-rules/linescore-849826.json')
        board=story.inning_score(feed)
        self.assertEqual(board['innings'][-1]['home'],None)
        self.assertEqual(board['home']['total'],4)
        self.assertEqual(board['away']['total'],3)
        for side in ('away','home'):
            self.assertEqual(sum(i[side] or 0 for i in board['innings']),board[side]['total'])
        bad=copy.deepcopy(feed);bad['liveData']['linescore']['teams']['home']['runs']=5
        self.assertIsNone(story.inning_score(bad))
        bad=copy.deepcopy(feed);bad['liveData']['linescore']['innings'][1]['away']={}
        self.assertIsNone(story.inning_score(bad))
        bad=copy.deepcopy(feed);bad['liveData']['linescore']['innings']=[]
        self.assertIsNone(story.inning_score(bad))
        if r3.LOOK=='v4':
            import asset_v4_cards as cards
            spec=read('scripts/fixtures/v3-rules/game-v4.json')['topics'][0]
            spec['game_v4']['score']=None
            im=cards.item(3,spec,'試合の話題',*spec['items'][0])
            self.assertEqual(im.info['asset_v4']['kind'],'stats')
            self.assertFalse(rules.check_layout(im))
            # 延長戦でも各回を消さず、2画面へ送る（数は固定検査材料）。
            extra=copy.deepcopy(spec)
            extra['game_v4']['score']=copy.deepcopy(board)
            extra['game_v4']['score']['innings'] += [{'num':i,'away':0,'home':0} for i in (10,11,12)]
            for page in range(2):
                im=cards.score(3,extra,'試合の話題',page)
                self.assertFalse(rules.check_layout(im))
                self.assertEqual(im.info['asset_v4']['pages'],2)

    def test_error_card_has_opponent_as_subject(self):
        import asset_v4_cards as cards
        self.assertEqual(cards.decisive({},'6回裏　打者の打球で相手の送球失策')['subject'],'相手の送球失策')
        self.assertEqual(cards.decisive({},'6回裏　打者の打球で相手の失策')['subject'],'相手の失策')
        import test_ps_game_story as fixed
        import ps_game_story as story
        f=fixed.feed(1,0)
        play=fixed.play('bottom',6,'Field Error',0,0,1,'Munetaka Murakami')
        play['result']['description']='Reaches on a throwing error.'
        f['liveData']['plays']={'allPlays':[play],'scoringPlays':[0]}
        f['liveData']['linescore']['teams']={'away':{'runs':0},'home':{'runs':1}}
        spec=story.story(fixed.GAME,f,fixed.KANA,fixed.JP,{},[])
        self.assertEqual(spec['game_v4']['decisive']['subject'],'相手の送球失策')


    def test_ticker_runs_on_one_program_clock(self):
        """帯は番組全体で1本の時計。画面の頭（画面内の t=0）でも、番組の時刻の位置にある。"""
        from PIL import Image
        def band(local, clock):
            im=Image.new('RGB',(1080,1920))
            r3.set_program_clock(clock)
            try:
                r3.ticker(im,local,'きょうの日本人選手　1位 村上宗隆　2位 ヌートバー')
            finally:
                r3.set_program_clock(None)
            return im.crop((0,1486,1080,1574)).tobytes()
        self.assertEqual(band(0.0,12.5),band(7.0,12.5))
        self.assertNotEqual(band(0.0,12.5),band(0.0,0.0))
        for path in ('scripts/generate_morning_short.py','scripts/generate_asset_video.py'):
            self.assertIn('set_program_clock(total / FPS)',(ROOT/path).read_text(encoding='utf-8'),path)

    def test_caption_follows_the_sentence_being_read(self):
        """字幕（v4）は読み上げている文。文字数の割合で今の文を選ぶ。"""
        text='1位は村上宗隆。4打数3安打、2本塁打、3打点です。'
        self.assertEqual(r3.current_sentence(0.5,text,10),'1位は村上宗隆。')
        self.assertEqual(r3.current_sentence(9.5,text,10),'4打数3安打、2本塁打、3打点です。')
        from PIL import Image, ImageDraw
        d=ImageDraw.Draw(Image.new('RGB',(8,8)))
        rows=r3._caption_lines(d,'4打数3安打、2本塁打、3打点です。きょうは7人が出場しました。',42,560)
        self.assertTrue(all(row[0][0] not in '、。' for row in rows[1:]))
        self.assertIn(('3',True),[part for row in rows for part in row])
        rows=r3._caption_lines(d,'24年のワールドシリーズからDodgersのスカウティングレポートがそのまま活きてる😅',42,300)
        flat=''.join(part for row in rows for part,_ in row)
        self.assertNotIn('😅',flat)
        self.assertTrue(any('Dodgers' in part for row in rows for part,_ in row))

    def test_v4_slot_cards_and_material_metadata(self):
        if r3.LOOK!='v4':return
        import short_v4_cards as v4
        from PIL import Image
        row={'said':'幅で折って全文を残す引用です。'*40,'tone':'批判','likes':808,'replies':30,'at':0,'end':20}
        pages,size=v4.quote_pages(row)
        self.assertEqual(size,54)
        self.assertEqual(''.join(line for page in pages for line in page),row['said'])
        self.assertGreater(len(pages),1)
        for t in (0,7,14,19):
            self.assertFalse(rules.check_layout(v4.quotes(t,[row],'現地の声','','','出典：固定材料')))
        count=0
        for index,page in enumerate(pages):
            length=sum(map(len,page))
            at=(count+length/2)/len(row['said'])*row['end']
            self.assertEqual(v4.quotes(at,[row],'現地の声','','','').info['v4_quote']['page'],index)
            count+=length
        self.assertEqual([s for s,_ in v4.metadata(row)],['批判','高評価 808','返信 30'])
        self.assertEqual(v4.metadata({'said':'属性なし'}),[])
        with self.assertRaises(ValueError):v4.wins(Image.new('RGB',(1080,1920)),100,400,4,3)

        voices=read('scripts/fixtures/comment/local_voices-preview.json')
        import comment_render as cr
        parent=voices['voices'][0]
        seg={'kind':'intro','meta':{'used_voice':0}}
        shown=cr.voices_for_segment(seg,voices)[0]
        for key in ('tone','likes','replies'):self.assertEqual(shown[key],parent[key])
        saved=read('scripts/fixtures/ps-design/2026-10-07.json')
        with patch.dict(os.environ,ENV):
            program=ps.prepare(saved['snapshot'],saved['evidence'],'situation',datetime.fromisoformat(saved['evidence']['retrieved_at']),saved['ledger'])
        card=program['segments'][0]['meta']['card']
        self.assertEqual(len(card['v4_series']),4)
        image=unified.frame(3,card)
        numbers=['-'.join(str(r['wins']) for r in c['scoreboard']['rows']) for c in card['v4_series']]
        self.assertTrue(all(n in [e['text'] for e in image.info['v3_layout']] for n in numbers))
        corrupted=copy.deepcopy(program)
        corrupted['segments'][0]['meta']['card']['v4_series'][0]['scoreboard']['rows'][0]['wins']=99
        with self.assertRaisesRegex(ValueError,'全シリーズ'):ps.check_program(corrupted)

    def test_v4_reading_and_past_quote_brightness(self):
        if r3.LOOK!='v4':return
        import short_v4_cards as v4
        rows=[{'said':'読み終えた親の引用です。','read':False,'at':0,'end':0},
              {'said':'今読む返信です。','reply':True,'at':0,'end':20}]
        image=v4.quotes(3,rows,'現地の声','','','')
        self.assertTrue(image.info['v4_quote']['active'])
        self.assertFalse(rules.check_layout(image))
        self.assertTrue(any(e['text']=='読み終えた親の引用です。' for e in image.info['v3_layout']))

    def test_v4_five_player_rows_and_integer_stat_cards(self):
        if r3.LOOK!='v4':return
        import short_v4_cards as v4
        rows=[dict(rank=i,name='検査用選手'+str(i),abbr='LAD',team_id=119,score='12本塁打') for i in range(1,6)]
        self.assertFalse(rules.check_layout(common.ranking(3,{},rows,'')))
        # 固定の検査材料。小数の回を主数字に選ばず、整数の成績だけ。
        spec=dict(rank=1,roster_count=5,head='検査用選手',head2='ドジャース',player_team_id=119,
                  big='2',unit='本塁打',sub='4打数3安打 2本塁打 3打点 1四球',kind='hero')
        image=v4.hero(3,spec)
        self.assertFalse(rules.check_layout(image))
        shown=[e['text'] for e in image.info['v3_layout']]
        for label in ('打数','安打','本塁打','打点','四球'):self.assertIn(label,shown)

    def test_v4_caption_in_reserved_area(self):
        if r3.LOOK!='v4':return
        with patch.dict(r3._CAPTION,dict(text='1位は村上宗隆。2本塁打、3打点です。',start=0,duration=20,total=120)):
            for case in self.cases:
                # 本体の締めの検査は別の検査で行い、字幕も省かず位置を確かめる。
                for draw in case['frames'][:-1]:
                    image=draw(3)
                    self.assertTrue(any(e['role']=='caption' for e in image.info['v3_layout']))
                    self.assertFalse(rules.check_layout(image))

    def test_v4_club_badges_choose_the_greater_contrast_for_all_clubs(self):
        if r3.LOOK!='v4':return
        import short_v4_cards as v4
        import notability_engine as ne
        from PIL import ImageColor
        self.assertEqual(len(ne.MLB_TEAM_ABBR),30)
        for tid,abbr in ne.MLB_TEAM_ABBR.items():
            # 成績の暗めの札と、PSの球団色そのものの札の両方。
            for base in (r3.colors(tid)[0],ImageColor.getrgb(ne.MLB_TEAM_COLOR[tid])):
                with self.subTest(team=abbr,base=base):
                    im=v4.canvas(0,'球団札の検査')
                    v4.club_tag(im,r3.LEFT,350,abbr,base,r3.colors(tid)[1])
                    mark=im.info['v4_badges'][0]
                    candidates=[v4.contrast(base,color) for color in (r3.INK,r3.DARK_INK)]
                    self.assertAlmostEqual(v4.contrast(base,mark['ink']),max(candidates))
                    self.assertGreaterEqual(v4.contrast(base,mark['ink']),3)
                    self.assertFalse(rules.check_layout(im))

    def test_v4_cover_and_remaining_players_keep_the_material_and_audio(self):
        if r3.LOOK!='v4':return
        data=read('scripts/fixtures/bignumber/recap_history/2026-09-25.json')
        roster=g.sort_players(data['players'])
        with patch.dict(os.environ,ENV),patch.object(g,'week_line',return_value=('',[])):
            nar=g.build_narration(dict(data,players=roster),'players')
        scenes=bn.scenes_from_morning(data,nar)
        self.assertFalse(bn.check_scenes(scenes,nar,data))
        cover=bn.scene(3,scenes[0])
        self.assertEqual(cover.info['v4_roster']['names'],[p['name'] for p in roster])
        drawn=[e['text'] for e in cover.info['v3_layout']]
        self.assertIn(str(len(roster)),drawn)
        for p in roster:self.assertIn(p['name'],drawn)
        lower=[s for s in scenes if s.get('player') and (s.get('rank') or 0)>1]
        for scene in lower:
            image=bn.scene(3,scene)
            self.assertEqual(image.info['v4_player']['name'],scene['player']['name'])
            self.assertEqual((image.info['v4_player']['big'],image.info['v4_player']['unit']),
                             bn.pick_big(scene['player']['headline'],next(p['type'] for p in roster if p['name']==scene['player']['name'])))
            if scene['player']['notes']:
                self.assertEqual(''.join(image.info['v4_annotation']['lines']),''.join(scene['player']['notes']))
        other=next(s for s in scenes if s.get('other_players'))
        first=bn.scene(0,dict(other,dur=20));last=bn.scene(19,dict(other,dur=20))
        self.assertEqual(first.info['v4_player']['name'],other['other_players'][0]['name'])
        self.assertEqual(last.info['v4_player']['name'],other['other_players'][-1]['name'])

if __name__=='__main__':
    if '--look-child' in sys.argv:
        unittest.main(argv=[__file__])
    else:
        # LOOK は import 時に決まる。別プロセスで両方を毎回検査する。
        failed=0
        for look in ('v3','v4'):
            env=dict(os.environ,COLLESPO_SHORT_LOOK=look)
            result=subprocess.run([sys.executable,'-X','utf8',__file__,'--look-child'],env=env,cwd=ROOT)
            print('test_v3_rules '+look+': '+('OK' if result.returncode==0 else 'NG'),flush=True)
            failed+=bool(result.returncode)
        sys.exit(bool(failed))
