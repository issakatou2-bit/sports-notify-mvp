"""保存材料と固定時点のみ。申請/通信/OS書体/Git履歴に依存しない。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import topic_hub as h
import topic_hub_reddit as reddit
import player_story as s

NOW=s.stamp('2026-10-14T04:00:00Z')
FIX=Path(__file__).resolve().parent/'fixtures/player_story'


def row(text,source='MLB.com',at='2026-10-13T14:00:00Z',url='https://example.test/story'):
    return dict(text=text,source=source,outlet=source,at=at,url=url,query='Shohei Ohtani')


def build(rows,**kw):
    return h.build(dict(posts=rows,updated_at=NOW.isoformat()),{}, {},as_of=NOW,**kw)


class HubTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'COLLESPO_TOPIC_HUB':'on','COLLESPO_REDDIT':''}); self.env.start()
    def tearDown(self): self.env.stop()

    def test_saved_topic_is_single_then_superseded(self):
        hub=h.build(s.read(FIX/'reporters_20261014.json'),{},s.read(FIX/'voices_20261014.json'),as_of=NOW)
        rest=next(e for e in hub['events'] if e['kind']=='rest')
        self.assertEqual(rest['certainty'],'single'); self.assertEqual(rest['status'],'superseded'); self.assertFalse(rest['usable'])
        latest=next(e for e in hub['events'] if e['id']==rest['updated_by'])
        self.assertEqual(latest['certainty'],'multiple')
        self.assertNotEqual(latest['certainty'],'official')
        with self.assertRaises(ValueError): h.phrase(rest)

    def test_single_cannot_be_an_assertion(self):
        hub=build([row('The Dodgers reportedly will discuss sitting Shohei Ohtani in Game 3.')])
        event=hub['events'][0]
        self.assertTrue(h.phrase(event).startswith('MLB.comによると、'))
        bad=deepcopy(event);bad['certainty']='official'
        with self.assertRaises(ValueError):h.phrase(bad)
        p=s.build({}, {'_topic_hub':hub}, {}, {}, {}, NOW, publication_ledgers=({}, {}))
        self.assertIn('MLB.comによると、',p['segments'][1]['text']); s.validate(p)

    def test_distinct_outlets_and_syndication(self):
        text="Shohei Ohtani will be in Dodgers' Game 3 lineup"
        first=row(text); same=row(text,url='https://example.test/other')
        event=build([first,same])['events'][0];self.assertEqual(event['certainty'],'single')
        second=row(text,'ESPN',url='https://example.test/espn')
        self.assertEqual(build([first,second])['events'][0]['certainty'],'multiple')
        second['origin_source']='MLB.com'
        self.assertEqual(build([first,second])['events'][0]['certainty'],'single')

    def test_official_denial_survives_history_and_later_rumor(self):
        text='The Dodgers will discuss sitting Shohei Ohtani in NLCS Game 3'
        deny=row('The Dodgers will not discuss sitting Shohei Ohtani in NLCS Game 3','Dodgers','2026-10-14T01:00:00Z','https://www.mlb.com/dodgers/press-release/no-rest')
        official=dict(updated_at=NOW.isoformat(),documents=[deny])
        hub=build([row(text)],official=official)
        event=hub['events'][0];self.assertEqual(event['status'],'refuted')
        self.assertEqual(h.active(hub,now=NOW),[])
        again=build([row(text,at='2026-10-14T02:00:00Z')],history=hub)
        self.assertEqual(h.active(again,now=NOW),[])

    def test_article_on_mlb_is_still_a_report(self):
        r=row('The Dodgers will discuss sitting Shohei Ohtani in Game 3',url='https://www.mlb.com/news/a-story')
        hub=build([r],official={'documents':[r]})
        self.assertEqual(hub['events'][0]['certainty'],'single')
        self.assertTrue(hub['rejected'])

    def test_official_lineup_and_three_distinct_times(self):
        snap=dict(url='https://statsapi.mlb.com/api/v1/game/123/boxscore',observed_at='2026-10-14T03:00:00Z',fetched_at='2026-10-14T03:05:00Z',
                  data={'teams':{'home':{'players':{'ID1':{'person':{'fullName':'Shohei Ohtani'},'battingOrder':'100'},
                  'ID2':{'person':{'fullName':'Seiya Suzuki'},'battingOrder':'101'}}}}},
                  schedule={'dates':[{'games':[{'gamePk':123,'seriesGameNumber':3,'season':'2026','seriesDescription':'National League Championship Series',
                    'officialDate':'2026-10-14','gameDate':'2026-10-15T00:00:00Z'}]}]})
        hub=build([row("Shohei Ohtani will be in NLCS Game 3 lineup")],official={'snapshots':[snap]})
        event=hub['events'][0];self.assertEqual(event['certainty'],'official')
        self.assertNotIn('によると',h.phrase(event));self.assertIn('入っています',h.phrase(event))
        o=next(o for o in event['observations'] if o['channel']=='official_data')
        self.assertIsNone(o['event_at']);self.assertIsNone(o['published_at'])
        self.assertNotEqual(o['observed_at'],o['collected_at']);self.assertEqual(o['game_date'],'2026-10-14')
        self.assertFalse(any(e['player_en']=='Seiya Suzuki' for e in hub['events']))

    def test_fan_only_anonymous_and_not_japanese_by_translation(self):
        v=dict(voices=[dict(title='Ohtani should rest!',ja='大谷翔平は休んでほしい',author='secret_user',jp_players=['Shohei Ohtani'],at=NOW.isoformat(),url='https://www.youtube.com/watch?v=test')],updated_at=NOW.isoformat())
        hub=h.build({}, {}, v,as_of=NOW)
        self.assertEqual(h.active(hub,now=NOW),[])
        self.assertNotIn('secret_user',json.dumps(hub))
        self.assertEqual(h.reaction_material(hub,'Shohei Ohtani',now=NOW),[])
        with self.assertRaises(ValueError):h.phrase(hub['events'][0])

    def test_reddit_off_failed_and_unapproved_do_not_stop_others(self):
        text='The Dodgers will discuss sitting Shohei Ohtani in Game 3'
        with patch.dict(os.environ,{'COLLESPO_REDDIT':'off'}):
            result=reddit.collect([], 'Shohei Ohtani', NOW.isoformat(),now=NOW,get=lambda *a,**k:self.fail('通信した'))
            hub=build([row(text)],reddit=result);self.assertEqual(result['state'],'off');self.assertTrue(h.active(hub,now=NOW))
        result=reddit.collect([], 'Shohei Ohtani', NOW.isoformat(),now=NOW,get=lambda *a,**k:self.fail('通信した'))
        self.assertEqual(result['state'],'rss_only')
        def fail(*a,**k):raise ConnectionError('offline')
        with patch.dict(os.environ,{'REDDIT_OAUTH_TOKEN':'test-placeholder'}):
            result=reddit.collect(['https://www.reddit.com/r/baseball/comments/test/game'], 'Shohei Ohtani', NOW.isoformat(),now=NOW,get=fail,approved=True)
        self.assertEqual(result['state'],'rss_only');self.assertTrue(h.active(build([row(text)],reddit=result),now=NOW))

    def test_reddit_small_high_score_and_no_author(self):
        payload=[{},dict(data=dict(children=[dict(kind='t1',data=dict(body='Ohtani should bounce back',author='hidden',score=i,created_utc=NOW.timestamp())) for i in range(10)]))]
        result=reddit.saved(payload,'https://www.reddit.com/r/baseball/comments/test/game','Shohei Ohtani',NOW.isoformat())
        self.assertEqual(len(result['voices']),3);self.assertEqual(result['voices'][0]['score'],9)
        self.assertNotIn('hidden',json.dumps(result));self.assertIn('全員の意見ではありません',result['voices'][0]['translation_note'])

    def test_existing_buzz_skip_and_three_consumers_remain_usable(self):
        import local_buzz
        seen=[]
        def fetch(name,url): seen.append(url); return ['Dodgers Shohei Ohtani']
        with patch.dict(os.environ,{'COLLESPO_REDDIT':'off','ANTHROPIC_API_KEY':''}), patch.object(local_buzz,'fetch_titles',side_effect=fetch), patch.object(local_buzz.time,'sleep'):
            local_buzz.build()
        self.assertTrue(seen);self.assertFalse(any('reddit.com' in url for url in seen))
        text='The Dodgers will discuss sitting Shohei Ohtani in Game 3'
        v={'voices':[dict(title='大谷翔平は応援しています',jp_players=['Shohei Ohtani'],url='https://www.youtube.com/watch?v=test',at=NOW.isoformat())]}
        hub=h.build({'posts':[row(text)]},{},v,reddit={'state':'failed','voices':[]},as_of=NOW)
        self.assertTrue(h.reporter_material(hub,now=NOW)['headlines'])
        self.assertTrue(h.player_reports(hub,s.JP_PLAYERS_MLB[0],NOW))
        self.assertTrue(h.reaction_material(hub,'Shohei Ohtani',now=NOW))

    def test_official_self_label_is_not_enough(self):
        fake=row('The Dodgers will discuss sitting Shohei Ohtani in Game 3')
        fake.update(handle='unverified',role='official',official=True)
        result=build([],official={'posts':[fake]})
        self.assertEqual(h.active(result,now=NOW),[])

    def test_multi_player_fan_retains_each_subject(self):
        voices=s.read(FIX/'voices_20261014.json')
        result=h.build({}, {}, voices,as_of=NOW)
        self.assertEqual({e['player_en'] for e in result['events']},{'Shohei Ohtani','Yoshinobu Yamamoto'})

    def test_cached_certainty_downgrades_and_conflicting_report_blocks(self):
        text="Shohei Ohtani will be in NLCS Game 3 lineup"
        result=build([row(text,'MLB.com','2026-10-12T05:00:00Z'),row(text,'ESPN','2026-10-13T20:00:00Z')])
        self.assertEqual(result['events'][0]['certainty'],'multiple')
        events=h.active(result,now=s.stamp('2026-10-14T06:00:00Z'))
        self.assertEqual(events[0]['certainty'],'single');self.assertTrue(h.phrase(events[0]).startswith('ESPNによると'))
        result=build([row('The Dodgers will discuss sitting Shohei Ohtani in NLCS Game 3'),
                      row('The Dodgers will not discuss sitting Shohei Ohtani in NLCS Game 3','ESPN','2026-10-14T01:00:00Z')])
        self.assertEqual(result['events'][0]['status'],'disputed');self.assertEqual(h.active(result,now=NOW),[])

    def test_old_transaction_does_not_become_current_on_fetch(self):
        snapshot=dict(url='https://statsapi.mlb.com/api/v1/transactions',observed_at=NOW.isoformat(),fetched_at=NOW.isoformat(),
                      data={'transactions':[{'person':{'fullName':'Shohei Ohtani'},'effectiveDate':'2026-09-01','description':'Activated'}]})
        result=build([],official={'snapshots':[snapshot]})
        self.assertEqual(h.active(result,now=NOW),[])

    def test_bad_channel_input_and_missing_attribution_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'reddit.json';path.write_text('{broken',encoding='utf8')
            bad=h.load(path)
            result=build([row('The Dodgers will discuss sitting Shohei Ohtani in Game 3')],reddit=bad)
            self.assertEqual(result['channel_states']['reddit'],'failed');self.assertTrue(h.active(result,now=NOW))
        missing=row('The Dodgers will discuss sitting Shohei Ohtani in Game 3');missing['source']='';missing['outlet']=''
        self.assertEqual(h.active(build([missing]),now=NOW),[])

    def test_denied_lineup_is_not_reused(self):
        rows=[row("Shohei Ohtani will be in NLCS Game 3 lineup")]
        official={'documents':[row("Shohei Ohtani will not be in NLCS Game 3 lineup",at='2026-10-14T03:00:00Z',url='https://www.mlb.com/dodgers/press-release/update')]}
        result=build(rows,official=official)
        self.assertEqual(result['events'][0]['status'],'refuted');self.assertEqual(h.active(result,now=NOW),[])

    def test_separate_rounds_stale_future_and_missing_hub(self):
        a=row('The Dodgers will discuss sitting Shohei Ohtani in NLCS Game 3')
        b=row("Shohei Ohtani will be in World Series Game 3 lineup",'ESPN','2026-10-14T01:00:00Z')
        hub=build([a,b]);self.assertEqual(len(hub['events']),2);self.assertTrue(all(e['usable'] for e in hub['events']))
        stale=build([dict(a,at='2026-10-10T00:00:00Z')])
        self.assertEqual(h.active(stale,now=NOW),[]);self.assertEqual(stale['events'][0]['certainty'],'single')
        self.assertEqual(h.active(build([dict(a,at='2026-10-15T00:00:00Z')]),now=NOW),[])
        self.assertEqual(h.reporter_material({})['headlines'],[])


if __name__=='__main__':unittest.main(argv=['test_topic_hub'])
