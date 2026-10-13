"""保存出力の数え上げと、実際に見つかった二つの誤検出を再現。"""
import copy
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import audit_saved_outputs as audit
import game_fact_guard as gg
import soccer_venue as venue

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAVED = json.loads((ROOT/'scripts/fixtures/saved-output/dialogues.json').read_text(encoding='utf-8'))


class SavedAudit(unittest.TestCase):
    def test_actual_visitor_at_named_home_stadium(self):
        g={'home_team_name':'ナポリ','away_team_name':'フロジノーネ'}
        for line in ['首位と3勝ち点差のフロジノーネがナポリ本拠地で対戦、上位争い揺さぶるか',
                     'フロジノーネはナポリのホームで対戦する。']:
            self.assertFalse(venue.check(line,g))
        self.assertTrue(venue.check('フロジノーネがホームでナポリを迎える。',g))
        self.assertTrue(venue.check('フロジノーネがナポリを本拠地で迎える。',g))

    def test_other_series_following_sentence_keeps_its_owner(self):
        d=copy.deepcopy(SAVED[1]['document'])
        line=d['segments'][33]
        self.assertIn('10月12日に第1戦',line['text'])
        d['segments']=[line]
        self.assertFalse(gg.check(d))
        d['segments'][0]['text']+='地区シリーズの第5戦で村上が先制した。'
        self.assertTrue(gg.check(d))  # 元のカードを明記した矛盾は引き続き検出

    def test_actual_errors_remain_detectable_with_whole_dialogue(self):
        a=gg.review(SAVED[0]['document']);b=gg.review(SAVED[1]['document'])
        self.assertTrue(any(s.startswith('14行目:') for s in a['errors']))
        self.assertTrue(any(s.startswith('8行目:') for s in b['errors']))
        self.assertTrue(any(s.startswith('31行目:') for s in b['errors']))
        self.assertFalse(any(s.startswith('34行目:') for s in b['errors']))

    def test_history_reads_changed_blobs_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            def git(*args):
                return subprocess.check_output(['git',*args],cwd=root)
            git('init','-q');git('config','user.name','audit-test');git('config','user.email','audit@example.invalid')
            (root/'data').mkdir();p=root/'data/local_voices.json'
            p.write_text(json.dumps({'date':'2026-10-09','voices':[{'title':'Thanks to that Yankee',
                'ja':'ヤンキースの選手さんが勝たせた。','reply_texts':['The fan was escorted out.']}]},ensure_ascii=False),encoding='utf-8')
            git('add','.');git('commit','-qm','saved output');git('update-ref','refs/remotes/origin/main','HEAD')
            rows,coverage=audit.collect(root,'2000-01-01','2099-01-01')
            self.assertEqual(coverage['texts'],1)
            self.assertEqual(len(rows[0]['sources']),2)
            self.assertEqual(audit.inspect(rows[0])[0]['guard'],'comment_actor')

    def test_annotations_never_assume_unreviewed_is_false(self):
        row=next(audit.texts({'ja':'渡された事実では分からない。'}))
        row.update(id='example',sources=[])
        with patch.object(audit,'collect',return_value=([row],{})):
            result=audit.audit(ROOT,'2026-09-13','2026-10-12',False)
            self.assertEqual(result['counts']['backstage']['unreviewed'],1)
            result=audit.audit(ROOT,'2026-09-13','2026-10-12',False,
                               {'example:backstage':{'status':'true_error','rationale':'制作事情'}})
            self.assertEqual(result['counts']['backstage']['true_error'],1)

    def test_multiline_dialogue_context_and_metadata_exclusion(self):
        rows=list(audit.texts(SAVED[1]['document'],day='2026-10-09'))
        by_path={r['path']:r for r in rows}
        self.assertTrue(audit.inspect(by_path['/segments/30/text']))
        self.assertFalse(audit.inspect(by_path['/segments/33/text']))
        self.assertNotIn('/material/players/0/name',by_path)
        self.assertFalse(list(audit.texts({'input':{'ja':'材料にないので'}})))

    def test_subtitle_counter_excludes_timestamps_and_catches_backstage(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);(root/'data').mkdir()
            (root/'data/test.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\n材料にないから省く。\n',encoding='utf-8')
            with patch.object(audit,'git',return_value=b'data/test.srt\n'):
                rows,coverage=audit.collect(root,'2026-09-13','2026-10-12',False)
            self.assertEqual(coverage['texts'],1)
            self.assertEqual(audit.inspect(rows[0])[0]['guard'],'backstage')


if __name__=='__main__':
    unittest.main(argv=[__file__])
