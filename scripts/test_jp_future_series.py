from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import offseason_news as news
import jp_future_series as series

class FutureTest(unittest.TestCase):
    def rows(self):
        payload=json.loads(Path('scripts/fixtures/offseason-real/transactions.json').read_text(encoding='utf-8'))
        jp,kana=series.targets()
        return news.transaction_rows(payload,date(2025,10,29),date(2025,12,21),jp,kana,set())
    def test_number_seen_and_no_filler(self):
        rows=self.rows()
        spec=series.topic(rows,date(2025,12,21),2025,{})
        self.assertEqual(spec['offseason']['series_number'],1)
        state={'events':[r['event_id'] for r in rows],'topics':{'first':{'series_number':1}}}
        self.assertIsNone(series.topic(rows,date(2025,12,21),2025,state))
        self.assertEqual(series.number(state),2)
        self.assertIsNone(series.topic([],date(2025,12,21),2025,{}))
        with self.assertRaises(ValueError):series.validate_pending(spec,state)
    def test_foreign_and_missing_kana_stop(self):
        rows=self.rows()
        self.assertTrue(all(r['japanese'] for r in rows))
        jp,kana=series.targets();kana.pop(rows[0]['raw']['person']['fullName'])
        with patch.object(series,'targets',return_value=(jp,kana)),self.assertRaises(ValueError):
            series.topic(rows,date(2025,12,21),2025,{})
    def test_posting_requires_explicit_official_record(self):
        row=dict(id=1, date='2025-12-21', typeCode='unknown',
                 person={'id':808959,'fullName':'Munetaka Murakami'},
                 fromTeam={'name':'Tokyo Yakult Swallows'},
                 description='Tokyo Yakult Swallows posted Munetaka Murakami.')
        jp,kana=series.targets()
        args=(date(2025,12,21),date(2025,12,21),jp,kana,set())
        self.assertEqual(len(news.transaction_rows({'transactions':[row]},*args)),1)
        for wording in ('Tokyo Yakult Swallows may post Munetaka Murakami.',
                        'Tokyo Yakult Swallows has not posted Munetaka Murakami.'):
            row['description']=wording
            self.assertEqual(news.transaction_rows({'transactions':[row]},*args),[])

    def test_series_material_roundtrip(self):
        import generate_asset_video as g
        rows=self.rows()
        spec=series.topic(rows,date(2025,12,21),2025,{})
        spec['offseason']['window_start']='2025-10-29'
        spec['offseason_sample']=True
        spec['intro']=news.sample_intro('transactions',2025)
        g.LIST_TOPICS[spec['key']]=spec
        doc=g.build_narration(spec['key'])
        self.assertEqual(news.check(doc),[])
        doc['segments'][1]['text']+='契約金は100億円です。'
        self.assertTrue(news.check(doc))

if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
