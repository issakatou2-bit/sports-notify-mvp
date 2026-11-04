"""11/4の28人を招集回に限定し、既存の名前/読みの守りと日程を検証。通信なし。"""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import soccer_national as n
import name_reading_guard as guard
import name_accent_guard as accents
import notability_engine as ne
from test_soccer_national import event
from test_name_reading_guard import query


class OfficialSquad(unittest.TestCase):
    def setUp(self):
        self.roster=n.read(ROOT/'data/soccer_national_squad.json')
        self.now=n.instant('2026-11-05T10:15:00+09:00')
        self.games=[n.match(event('brazil',complete=False)),n.match(event('paraguay',complete=False,date='2026-11-17T13:10Z',opp='210'))]

    def material(self,page=0):
        return n.squad(self.roster,{},self.now.isoformat(),page,upcoming=self.games)

    def document(self,page=0):
        return n.narration(self.material(page))

    def test_all_28_kept_in_order_with_two_last_pages_of_two(self):
        pages=[self.material(i) for i in range(10)]
        self.assertEqual([len(p['players']) for p in pages],[3]*8+[2,2])
        self.assertEqual([p['name'] for page in pages for p in page['players']], [p['name_jp'] for p in self.roster['players']])
        self.assertIsNone(self.material(10))
        for page in pages:self.assertEqual(n.check(n.narration(page)),[])

    def test_dictionary_names_and_readings_must_match(self):
        p=next(p for p in self.roster['players'] if p['name_en']=='Zion Suzuki')
        for key,value in [('name_jp','鈴木試験'),('reading','スズキサイエン')]:
            broken=dict(p,**{key:value})
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'既存辞書'):n.squad_player(broken)
        self.assertEqual(sum(p['name_en'] in {r['name_en'] for r in n.read(ROOT/'data/soccer_player_names.json')['players']} for p in self.roster['players']),18)

    def test_required_fields_and_duplicate_english_stop(self):
        for key in ('name_en','name_jp','reading','club','position'):
            broken=copy.deepcopy(self.roster);broken['players'][0].pop(key)
            with self.subTest(key=key),self.assertRaises(ValueError):n.squad(broken,{},self.now.isoformat())
        for key,value in [('reading','ハヤカワ トモキ'),('reading','Hayakawa'),('name_jp','Hayakawa'),('first_call','yes')]:
            broken=copy.deepcopy(self.roster);broken['players'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):n.squad(broken,{},self.now.isoformat())
        broken=copy.deepcopy(self.roster);broken['players'][1]['name_en']=broken['players'][0]['name_en']
        with self.assertRaises(ValueError):n.squad(broken,{},self.now.isoformat())

    def test_source_sample_and_future_announcement(self):
        for url in ('https://www.jfa.jp.example.com/news/1/','https://example.com/jfa.jp/','https://jfa.jp/news/1/'):
            with self.subTest(url=url),self.assertRaises(ValueError):n.squad(dict(self.roster,source_url=url),{},self.now.isoformat())
        with self.assertRaises(ValueError):n.squad(dict(self.roster,sample=True),{},self.now.isoformat())
        self.assertIsNone(n.squad(self.roster,{},'2026-11-03T10:15:00+09:00'))
        self.assertIsNone(n.squad(self.roster,{},'2026-12-05T10:15:00+09:00'))

    def test_first_call_only_fukuda(self):
        marked=[]
        for page in range(10):
            doc=self.document(page)
            marked.extend(s['text'] for s in doc['segments'] if '初めての招集です' in s['text'])
        self.assertEqual(len(marked),1);self.assertIn('福田師王',marked[0])
        data=self.material(9);data['next_game']=None
        facts=n.information(n.narration(data))
        self.assertEqual(len(facts),3)
        self.assertTrue(any(r['subject']=='福田師王' and r['fact']=='日本代表初招集' for r in facts))

    def test_daily_selection_and_match_day_exclusion_without_completion(self):
        ledger={'soccer_national':{}}
        for day in range(5,20):
            now=n.instant(f'2026-11-{day:02d}T10:15:00+09:00')
            chosen=n.choose(self.games,{},None,now,ledger,Mock(side_effect=AssertionError('結果取得禁止')),self.roster,{})
            # 11/19 は2試合とも終わった後なので、最後のページが残っていても出さない。
            wanted=day-5 if day<=12 else 8 if day==15 else None
            with self.subTest(day=day):
                self.assertEqual(chosen['page'] if chosen else None,wanted)
                if chosen:
                    self.assertEqual(chosen['publish_at'],f'2026-11-{day:02d}T12:00:00+09:00')
                    ledger['soccer_national'][now.date().isoformat()]={'national_squad_page':chosen['page']}
        # ページが余っている場合でも指定の5日は停止する。
        for day in (13,14,16,17,18):
            self.assertIsNone(n.choose(self.games,{},None,n.instant(f'2026-11-{day}T10:15:00+09:00'),{},Mock(),self.roster,{}))

    def test_one_per_day_and_outside_slot(self):
        for hour in (9,12):
            self.assertIsNone(n.choose(self.games,{},None,self.now.replace(hour=hour),{},Mock(),self.roster,{}))
        self.assertIsNone(n.choose(self.games,{},None,self.now,{'soccer_national':{'2026-11-05':{'national_squad_page':0}}},Mock(),self.roster,{}))

    def test_normal_tracking_and_result_names_still_42_and_reject_new_players(self):
        self.assertEqual(len(ne.JP_PLAYERS_SOCCER),42)
        self.assertEqual(len(n.read(ROOT/'data/soccer_player_names.json')['players']),42)
        with self.assertRaises(ValueError):n.player_name('Tomoki Hayakawa',True)
        self.assertIsNone(guard.player_reading('早川友基'))

    def test_scope_covers_every_name_club_and_both_import_paths(self):
        from scripts import name_reading_guard as other_guard
        for page in range(10):
            doc=self.document(page)
            guard.validate_dialogue(doc)
            with guard.dialogue_scope(doc):
                for p in doc['national_material']['players']:
                    self.assertEqual(guard.player_reading(p['name']),p['reading'])
                    self.assertEqual(other_guard.player_reading(p['name']),p['reading'])
                    self.assertIn(p['reading'],ne.apply_readings(p['name']+'です。'))
                    club=ne.apply_readings(p['club'])
                    self.assertRegex(club,r'^[ァ-ヶー]+$')
                    rows=guard.assert_known(p['name']+'は'+p['club']+'所属です。')
                    self.assertEqual({r['kind'] for r in rows},{'player','club'})
            self.assertIsNone(guard.player_reading('早川友基'))

    def test_scope_resets_after_error_and_does_not_trust_other_programs(self):
        with self.assertRaises(RuntimeError),guard.dialogue_scope(self.document()):raise RuntimeError()
        self.assertIsNone(guard.player_reading('早川友基'))
        doc=self.document();doc['program']='soccer_results'
        with guard.dialogue_scope(doc):self.assertIsNone(guard.player_reading('早川友基'))

    def test_squad_check_and_scope_reject_tampered_source_or_known_reading(self):
        for kind in ('source','reading','text','sample'):
            doc=self.document();data=doc['national_material']
            if kind=='source':data['source_url']='https://example.com/'
            elif kind=='reading':data['players'][2]['reading']='スズキサイエン'
            elif kind=='sample':data['sample']=True
            else:doc['segments'][1]['text']='改変です。'
            self.assertTrue(n.check(doc))
            with self.assertRaises(ValueError),guard.dialogue_scope(doc):pass

    def test_missing_club_reading_fails_before_engine(self):
        doc=self.document()
        actual=n.read
        def missing(path):return {} if Path(path).name=='soccer_national_club_readings.json' else actual(path)
        with patch.object(n,'read',side_effect=missing),self.assertRaisesRegex(ValueError,'クラブの読み'):guard.validate_dialogue(doc)

    def test_query_misreading_and_internal_name_break_still_fail(self):
        with guard.dialogue_scope(self.document()):
            self.assertEqual(guard.validate_query('早川友基',query('ハヤカワトモキ'))['status'],'PASS')
            with self.assertRaisesRegex(guard.NameReadingError,'読み不一致'):guard.validate_query('早川友基',query('ハヤカワユウキ'))
            split=query('ハヤカワ');split['accent_phrases']+=query('トモキ')['accent_phrases']
            with self.assertRaisesRegex(guard.NameReadingError,'複数句'):guard.validate_query('早川友基',split)
            row=next(r for r in accents.entries() if r['name']=='早川友基')
            self.assertEqual(row['status'],'UNVERIFIED')

    def test_synthesis_main_scopes_actual_synth_call_without_network(self):
        import synthesize_narration as synth
        doc=self.document();seen=[]
        def fake_synth(text,speaker,path,**kwargs):
            seen.append((text,guard.player_reading('早川友基'),ne.apply_readings(text)))
            return False
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'narration.json';n.save(path,doc)
            with patch.dict('os.environ',{'COLLESPO_SOLO_HOST':'metan','COLLESPO_HOST_SPLIT':'off'}),patch.object(synth,'engine_available',return_value=True),patch.object(synth,'synth_one',side_effect=fake_synth):
                synth.main(['--narration',str(path),'--out-dir',str(Path(directory)/'audio')])
        self.assertEqual(len(seen),len(doc['segments']))
        self.assertTrue(all(row[1]=='ハヤカワトモキ' for row in seen))
        self.assertIsNone(guard.player_reading('早川友基'))

    def test_intro_keeps_full_names_and_individual_screen_keeps_jfa_club(self):
        import soccer_national_render as render
        import review_render_v3 as r3
        with patch.dict('os.environ',{'COLLESPO_SOCCER_LOOK':'v6','COLLESPO_SOCCER_FOCUS':'on','COLLESPO_SHORT_LOOK':'v4'}):
            data=self.material();doc=n.narration(data);clubs=render.clubs_for(data)
            r3.set_caption('',0,0)
            intro=render.frame(2,doc['segments'][0],data,clubs)
            labels=[e['text'] for e in intro.info['v3_layout'] if e['role']=='national_fact']
            for p in data['players']:self.assertIn(p['name'],labels)
            for i,p in enumerate(data['players']):
                im=render.frame(2,doc['segments'][i+1],data,clubs)
                labels=[e['text'] for e in im.info['v3_layout'] if e['role']=='national_fact']
                self.assertIn(p['club'],labels)
                self.assertEqual(render.validate_frame(im,clubs,data),[])

    def test_stats_registered_alias_only_and_no_inferred_match(self):
        row=dict(name='鈴木彩艶',club='Aston Villa',scope='season',as_of='2026-11-04T12:00:00+09:00',source='saved',goals=0,season='2026/27')
        material={'games':[{'league':'PL','season_players':[row]}]}
        self.assertIsNotNone(n.season_rows(material,'アストン・ビラ','Zion Suzuki',self.now.isoformat(),'2026/27'))
        row.update(name='早川友基',club='鹿島アントラーズ')
        self.assertIsNotNone(n.season_rows(material,'鹿島アントラーズ','Tomoki Hayakawa',self.now.isoformat(),'2026/27',name_jp='早川友基'))
        row.update(name='坂元達裕',club='コベントリー')
        self.assertIsNone(n.season_rows(material,'コベントリー・シティ','Tatsuhiro Sakamoto',self.now.isoformat(),'2026/27'))
        row.update(name='鈴木彩艶',club='Aston Villa',as_of='2026-11-06T00:00:00+09:00')
        self.assertIsNone(n.season_rows(material,'アストン・ビラ','Zion Suzuki',self.now.isoformat(),'2026/27'))


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
