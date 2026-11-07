"""欧州順位と国内順位のID照合・同季・予算。偽応答だけ、通信禁止。"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import soccer_preview_espn as espn
import soccer_preview_angles as angles
import soccer_selected_preview as preview
import test_soccer_preview_angles as common
NOW = common.NOW


def game():
    return dict(game_id='espn-99',espn_event_id='99',competition_code='EL',league='ヨーロッパリーグ',
                home_team_id='espn-10',away_team_id='espn-20',home_team_name='Real Sociedad',away_team_name='Olympique Lyonnais',
                start_time_utc='2026-11-06T20:00:00+00:00',start_time_jst='11/07 05:00',
                jp_by_side=dict(home=['久保建英'],away=[]),home_standing=None,away_standing=None,reasons=[],is_notable=True)


def entry(ident, rank, points, name='intentionally wrong name'):
    return dict(team=dict(id=str(ident),displayName=name),stats=[dict(name=k,value=v) for k,v in [('rank',rank),('points',points),('gamesPlayed',3)]])


def table(code='EL'):
    # 他のクラブの勝点は重ねない（並んだ順位は言わない決まりの試験は別に持つ）。
    rows=[entry(10,4,7),entry(20,9,6)]+[entry(100+i,i+1,100-i) for i in range(36) if i+1 not in (4,9)]
    return dict(source=espn.BASE+'/'+espn.LEAGUES[code][0]+'/standings',slug=espn.LEAGUES[code][0],retrieved_at=NOW,
                payload=dict(season=dict(year=2026),children=[dict(standings=dict(type=0,entries=rows))]))


class Tests(unittest.TestCase):
    setUp = common.Angles.setUp
    # 共通の通信禁止・表示設定だけ継承し、既存11件を再登録しない。
    def test_european_and_domestic_scope_and_scores(self):
        g=game();tables={c:table(c) for c in ('EL','PD','FL1')}
        raw=dict(generated_at=NOW,games=[g],preview_selection=dict(selected_ids=['espn-99']))
        result=angles.attach(raw,results={},espn_tables=tables);target=result['games'][0]
        rows=angles.angles(target,NOW)
        self.assertEqual(rows[0]['kind'],'european_points')
        self.assertEqual(rows[0]['values']['gap'],1)
        domestic=[r for r in rows if r['kind'].startswith('domestic_')]
        self.assertEqual(len(domestic),2);self.assertTrue(all(r['score']<rows[0]['score'] for r in domestic))
        self.assertTrue(any('ラ・リーガで現在4位' in r['text'] for r in domestic))
        plan=preview.program(result);doc=plan['narration']
        self.assertIn('ヨーロッパリーグで勝点1差の9位',doc['title'])
        self.assertEqual(angles.check(doc),[])
        self.assertTrue(any('16強' in r['text'] or 'プレーオフ' in r['text'] for r in rows))
        for bad_value in ('本文','題','表紙'):
            bad=copy.deepcopy(doc)
            if bad_value=='本文':bad['segments'][1]['text']=bad['segments'][1]['text'].replace('勝点7','勝点77')
            if bad_value=='題':bad['title']=bad['title'].replace('勝点1差','勝点99差')
            if bad_value=='表紙':bad['segments'][0]['text']+='99位'
            self.assertTrue(angles.check(bad),bad_value)

    def test_tied_points_drop_rank_but_keep_points_and_shared_zone(self):
        # 11/5 UECL：勝点の並ぶトラブゾンスポルが ESPN 4位・UEFA 3位で食い違った。
        t=table();entries=t['payload']['children'][0]['standings']['entries']
        entries.append(entry(999,10,6));entries[:]=[e for e in entries if e['team']['id']!='109']
        g=game();g['preview_angle_context']=dict(espn=espn.attach([g],{'EL':t})['espn-99'])
        rows=espn.facts(g,NOW);points=next(r for r in rows if r['kind']=='european_points')
        self.assertIn('リヨンは勝点6で',points['text']);self.assertNotIn('9位',points['text'])
        self.assertIn('レアル・ソシエダは4位で勝点7',points['text'])
        g['preview_angle_context']['espn']['tables']['EL']=t
        raw=dict(generated_at=NOW,games=[game()],preview_selection=dict(selected_ids=['espn-99']))
        data=angles.attach(raw,results={},espn_tables={'EL':t})
        title=angles.headline(data['games'][0],NOW)
        self.assertIn('勝点1差のリヨン',title);self.assertNotIn('9位',title)
        # 9位と10位が並ぶ：同じ範囲なので範囲だけ言える。8位と9位が並ぶ：範囲が分かれるので言わない。
        lyon=[r for r in rows if r['kind']=='european_zone' and r['values']['side']=='away']
        self.assertEqual(len(lyon),1);self.assertIn('リヨンは今、',lyon[0]['text']);self.assertIsNone(lyon[0]['values']['rank'])
        entries[:]=[e for e in entries if e['team']['id']!='999'];entries.append(entry(999,8,6))
        entries[:]=[e for e in entries if e['team']['id']!='107']
        g['preview_angle_context']=dict(espn=espn.attach([g],{'EL':t})['espn-99'])
        self.assertFalse([r for r in espn.facts(g,NOW) if r['kind']=='european_zone' and r['values']['side']=='away'])

    def test_one_side_facts_use_the_japanese_club(self):
        g=game();tables={c:table(c) for c in ('EL','PD','FL1')}
        raw=dict(generated_at=NOW,games=[g],preview_selection=dict(selected_ids=['espn-99']))
        target=angles.attach(raw,results={},espn_tables=tables)['games'][0]
        picked=angles.chosen(target,NOW)
        self.assertTrue(picked)
        self.assertFalse([r for r in picked if r['values'].get('side')=='away'])

    def test_id_binding_not_team_name(self):
        g=game();tables={'EL':table()}
        ctx=espn.attach([g],tables)['espn-99'];g['preview_angle_context']=dict(espn=ctx)
        self.assertTrue(espn.facts(g,NOW)) # 偽の名前でもIDを使う。
        for field,value in [('espn_event_id','100'),('home_team_id','espn-12345')]:
            bad=copy.deepcopy(g);bad[field]=value
            self.assertEqual(espn.facts(bad,NOW),[])
        for e in tables['EL']['payload']['children'][0]['standings']['entries']:e['team']['id']='no match'
        g['preview_angle_context']['espn']=espn.attach([g],tables)['espn-99']
        self.assertEqual(espn.facts(g,NOW),[])

    def test_wrong_year_stale_group_duplicates_and_bad_numbers_omitted(self):
        for bad in ('season','stale','split','duplicate','bool','negative','missing','inf','zero_games'):
            t=table();p=t['payload'];entries=p['children'][0]['standings']['entries']
            if bad=='season':p['season']['year']=2025
            if bad=='stale':t['retrieved_at']='2026-10-01T10:00:00Z'
            if bad=='split':p['children']=[dict(standings=dict(entries=[entries[0]])),dict(standings=dict(entries=entries[1:]))]
            if bad=='duplicate':entries.append(copy.deepcopy(entries[0]))
            if bad=='bool':entries[0]['stats'][0]['value']=True
            if bad=='negative':entries[0]['stats'][1]['value']=-1
            if bad=='missing':entries[0]['stats'].pop()
            if bad=='inf':entries[0]['stats'][0]['value']=float('inf')
            if bad=='zero_games':entries[0]['stats'][2]['value']=0
            g=game();g['preview_angle_context']=dict(espn=espn.attach([g],{'EL':t})['espn-99'])
            self.assertEqual(espn.facts(g,NOW),[],bad)

    def test_budget_one_per_competition_and_domestic_league_even_on_failure(self):
        g=game();g2=copy.deepcopy(g);g2.update(game_id='espn-100',espn_event_id='100')
        get=Mock(return_value=table()['payload']);tables=espn.fetch_tables([g,g2],get)
        self.assertEqual(get.call_count,3);self.assertEqual(set(tables),{'EL','PD','FL1'})
        self.assertEqual(len({c.args[0] for c in get.call_args_list}),3)
        get=Mock(side_effect=ValueError('bad'))
        self.assertEqual(espn.fetch_tables([g,g2],get),{});self.assertEqual(get.call_count,3)
        g.pop('away_team_id');get=Mock()
        self.assertEqual(espn.fetch_tables([g],get),{});get.assert_not_called()

    def test_knockout_and_future_season_do_not_use_league_phase_zone(self):
        for year in (2026,2027):
            g=game();g['phase']='knockout';t=table();t['payload']['season']['year']=year
            g['preview_angle_context']=dict(espn=espn.attach([g],{'EL':t})['espn-99'])
            self.assertEqual(espn.facts(g,NOW),[])

    def test_fpl_provider_absent_from_title_body(self):
        import soccer_daily_retry
        # 本番の材料は毎日変わるので、試験を足した11/5の写しで見る（11/7 当日の材料で赤）。
        data=soccer_daily_retry.read(Path(__file__).resolve().parent/'fixtures/soccer-preview/soccer_games_20261105.json')
        data=angles.attach(data)
        doc=preview.program(data)['narration']
        spoken=doc['title']+''.join(s['text'] for s in doc['segments'])
        for name in ('FPL','ESPN','football-data'):self.assertNotIn(name,spoken)
        self.assertIn('今季のプレミアリーグで1得点3アシスト',spoken)

    def test_season_at_standings_level_and_missing_season_is_not_assumed(self):
        t=table();t['payload'].pop('season')
        standing=t['payload']['children'][0]['standings'];standing['season']=2026
        g=game();g['preview_angle_context']=dict(espn=espn.attach([g],{'EL':t})['espn-99'])
        self.assertTrue(espn.facts(g,NOW))
        standing.pop('season')
        self.assertEqual(espn.facts(g,NOW),[])

    def test_upload_title_keeps_the_same_angle_with_title_v2_on_or_off(self):
        import os
        import upload_youtube
        g=game();raw=dict(generated_at=NOW,games=[g],preview_selection=dict(selected_ids=['espn-99']))
        data=angles.attach(raw,results={},espn_tables={'EL':table()})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'material.json';path.write_text(json.dumps(data),encoding='utf8')
            for value in ('on','off'):
                with patch.dict(os.environ,COLLESPO_SOCCER_TITLE_V2=value):
                    doc=angles.preview_title(data)
                    narr=Path(folder)/'narration.json';narr.write_text(json.dumps(dict(title=doc)),encoding='utf8')
                    meta=upload_youtube.build_metadata(str(path),'11月5日','daily',sport='soccer',narration_path=str(narr))['snippet']
                self.assertEqual(meta['title'],doc)
                # 切替が入なら題は今の題と同じ短い名前、切なら正式名。
                self.assertIn('久保ソシエダが' if value=='on' else '久保建英のレアル・ソシエダが',doc)


if __name__=='__main__':
    unittest.main(argv=[__file__])
