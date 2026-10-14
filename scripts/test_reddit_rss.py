from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import reddit_rss as r
import reddit_reaction as reaction
import topic_hub as h

FIX=Path(__file__).resolve().parent/'fixtures/reddit-rss'
RAW=(FIX/'preview.xml').read_text(encoding='utf8')
CONTEXT=h.load(FIX/'preview-source.json')
NOW=h.story.stamp('2026-10-14T06:00:00Z')
URL=CONTEXT['threads'][0]


class Response:
    def __init__(self,status=200,body=RAW):self.status_code=status;self.body=body;self.closed=False
    def iter_content(self,n):yield self.body.encode('utf8')
    def close(self):self.closed=True


class RSSTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'COLLESPO_REDDIT':'on'});self.env.start()
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name)/'state.json'
        self.config=dict(game_at=NOW.isoformat(),threads=[URL])
    def tearDown(self):self.temp.cleanup();self.env.stop()

    def test_saved_real_rss_and_no_score_invention(self):
        rows=r.parse_comments(RAW,URL,NOW)
        self.assertEqual(len(rows),2);self.assertTrue(all(v['score'] is None and not v['score_verified'] for v in rows))
        self.assertFalse(any('author' in row for row in rows))
        self.assertTrue(all(v['url']==r.thread_link(URL) for v in rows))

    def test_public_endpoints_only(self):
        self.assertIn('.rss',r.rss_url(r.thread_link(URL)+'.rss?sort=top'))
        for bad in ('https://oauth.reddit.com/r/baseball/a.rss','https://www.reddit.com/r/baseball/comments/id/.json','https://user:pass@www.reddit.com/r/baseball/search.rss','http://www.reddit.com/r/baseball/search.rss'):
            with self.assertRaises(ValueError):r.rss_url(bad)

    def test_quote_links_do_not_leak_quoted_authors(self):
        content=r.Content()
        content.feed('<blockquote><a href="https://example.org">quoted link</a>quoted text</blockquote><p>Actual short comment</p>')
        self.assertEqual(content.text(),'Actual short comment')

    def test_default_and_off_do_not_fetch(self):
        for flag in ('','off'):
            with patch.dict(os.environ,{'COLLESPO_REDDIT':flag}):
                out=r.collect(self.config,self.state,now=NOW,get=lambda *a,**k:self.fail('通信'))
            self.assertEqual(out['state'],'disabled');self.assertFalse(self.state.exists())

    def test_game_window_and_missing_time(self):
        out=r.collect(dict(self.config,game_at=(NOW-timedelta(hours=7)).isoformat()),self.state,now=NOW,get=lambda *a,**k:self.fail('通信'))
        self.assertEqual(out['state'],'outside_game_window')
        self.assertEqual(r.collect({},self.state,now=NOW)['state'],'missing_game_time')

    def test_three_per_hour_persist_across_runs(self):
        seen=[]
        def get(url,**kw):seen.append((url,kw));return Response()
        for minute in (0,10,20,30):
            result=r.collect(self.config,self.state,now=NOW+timedelta(minutes=minute),get=get,sleep=lambda n:None)
        self.assertEqual(len(seen),3);self.assertEqual(result['state'],'hourly_limit')
        self.assertTrue(all('.rss?' in url and not kw.get('allow_redirects') and 'Authorization' not in kw['headers'] for url,kw in seen))

    def test_spacing(self):
        waits=[]
        r.collect(dict(self.config,threads=[URL,URL]),self.state,now=NOW,get=lambda *a,**k:Response(),sleep=waits.append)
        self.assertEqual(waits,[10]);calls=h.load(self.state)['calls']
        self.assertEqual((h.story.stamp(calls[1])-h.story.stamp(calls[0])).total_seconds(),10)

    def test_429_stops_for_japanese_day(self):
        result=r.collect(self.config,self.state,now=NOW,get=lambda *a,**k:Response(429))
        self.assertEqual(result['state'],'stopped_429')
        result=r.collect(dict(self.config,game_at=(NOW+timedelta(hours=3)).isoformat()),self.state,now=NOW+timedelta(hours=3),get=lambda *a,**k:self.fail('再試行'))
        self.assertEqual(result['state'],'stopped_429')

    def test_redirect_and_errors_are_not_bypassed(self):
        for status in (301,403,500):
            self.state.unlink(missing_ok=True)
            result=r.collect(self.config,self.state,now=NOW,get=lambda *a,**k:Response(status))
            self.assertEqual(result['state'],'HTTP '+str(status));self.assertEqual(result['voices'],[])
        def fail(*a,**k):raise ConnectionError()
        self.state.unlink(missing_ok=True)
        self.assertEqual(r.collect(self.config,self.state,now=NOW,get=fail)['state'],'ConnectionError')

    def test_broken_budget_fails_closed(self):
        self.state.write_text('{bad')
        result=r.collect(self.config,self.state,now=NOW,get=lambda *a,**k:self.fail('通信'))
        self.assertEqual(result['state'],'failed')

    def test_fan_route_and_no_factual_use(self):
        material=dict(state='ready',voices=r.parse_comments(RAW,URL,NOW),updated_at=NOW.isoformat())
        hub=h.build({}, {}, {},reddit=material,as_of=NOW)
        self.assertEqual(h.active(hub,now=NOW),[]);self.assertEqual(len(h.active(hub,fans=True,now=NOW)),2)
        self.assertTrue(all(e['certainty']=='fan' and not e['usable'] for e in hub['events']))

    def test_preview_is_anonymous_attributed_and_not_published(self):
        material=dict(voices=r.parse_comments(RAW,URL,NOW),updated_at=NOW.isoformat())
        translations=json.loads((FIX/'preview-translations.json').read_text(encoding='utf8'))
        narr=reaction.program(material,translations,CONTEXT);reaction.validate(narr)
        self.assertEqual(narr['segments'][-1]['text'],h.FAN_NOTE)
        self.assertFalse(any('author' in s['meta'] for s in narr['segments']))
        bad=json.loads(json.dumps(narr));bad['segments'][1]['text']='これは全員の意見です'
        with self.assertRaises(ValueError):reaction.validate(bad)


if __name__=='__main__':unittest.main(argv=['test_reddit_rss'])
