"""題の付け直しの範囲と、街名以外を保持する検査（外部APIなし）。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import retitle


class RetitleTest(unittest.TestCase):
    def test_six_published_asset_topics(self):
        topics = 'legend_116,legend_137,season_team_116,team_det,team_sfn,venue_oracle'
        rows = retitle.asset_targets(topics)
        self.assertEqual({topic for topic, _ in rows}, set(topics.split(',')))
        self.assertEqual(dict(rows)['season_team_116'], 'RegoJCkIY7w')

    def test_topic_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'assets.json'
            path.write_text(json.dumps({'assets': {
                'a': {'video_id': 'A'}, 'b': {'video_id': 'B'},
                'c': {'video_id': 'C'}, 'empty': {},
            }}), encoding='utf-8')
            with patch.object(retitle, 'ASSETS', str(path)):
                self.assertEqual(retitle.asset_targets(), [('a', 'A'), ('b', 'B'), ('c', 'C')])
                self.assertEqual(retitle.asset_targets('b'), [('b', 'B')])
                self.assertEqual(retitle.asset_targets(' b, a, b, '), [('a', 'A'), ('b', 'B')])
                self.assertEqual(retitle.asset_targets('unknown'), [])

    def test_only_city_preserves_snippet_and_dry_run(self):
        for dry in (True, False):
            with self.subTest(dry=dry):
                yt = Mock()
                snippet = {'title': '【MLB】タイガース｜収容41,083人・選手の名前 #Shorts',
                           'description': '説明', 'tags': ['既存タグ'], 'categoryId': '17'}
                yt.videos().list().execute.return_value = {'items': [{'snippet': snippet}]}
                with patch.object(retitle.uy, 'club_display_title', side_effect=AssertionError):
                    changed = retitle.apply(yt, 'A', '', dry, only_team_city=True)
                self.assertEqual(changed, not dry)
                if dry:
                    yt.videos().update.assert_not_called()
                else:
                    yt.videos().update.assert_called_once_with(part='snippet', body={
                        'id': 'A', 'snippet': {**snippet,
                            'title': snippet['title'].replace('タイガース', 'デトロイト・タイガース')}})

    def test_unchanged_and_missing_video(self):
        for items in ([], [{'snippet': {'title': 'デトロイト・タイガース｜タイガースの記録'}}]):
            yt = Mock()
            yt.videos().list().execute.return_value = {'items': items}
            self.assertFalse(retitle.apply(yt, 'A', '', False, only_team_city=True))
            yt.videos().update.assert_not_called()

    def test_asset_mode_skips_rebuild_and_keeps_views_guard(self):
        for force in (False, True):
            argv = ['retitle', '--kind', 'asset', '--topic', 'a,b', '--only-team-city', '--write']
            if force:
                argv.append('--force')
            yt = Mock()
            with patch.object(sys, 'argv', argv), patch.object(retitle, 'client', return_value=yt), \
                    patch.object(retitle, 'asset_targets', return_value=[('a', 'A'), ('b', 'B')]) as targets, \
                    patch.object(retitle, 'view_counts', return_value={'B': retitle.SAFE_VIEWS + 1}), \
                    patch.object(retitle, 'wanted_asset_title', side_effect=AssertionError), \
                    patch.object(retitle, 'apply', return_value=True) as apply:
                self.assertEqual(retitle.main(), 0)
                targets.assert_called_once_with('a,b')
                self.assertEqual(apply.call_count, 2 if force else 1)
                apply.assert_any_call(yt, 'A', '', False, only_team_city=True)

    def test_default_asset_mode_still_rebuilds(self):
        with patch.object(sys, 'argv', ['retitle', '--kind', 'asset']), \
                patch.object(retitle, 'client'), patch.object(retitle, 'view_counts', return_value={}), \
                patch.object(retitle, 'asset_targets', return_value=[('a', 'A')]) as targets, \
                patch.object(retitle, 'wanted_asset_title', return_value='新しい題') as rebuild, \
                patch.object(retitle, 'apply', return_value=False) as apply:
            self.assertEqual(retitle.main(), 0)
            targets.assert_called_once_with('')
            rebuild.assert_called_once_with('a')
            apply.assert_called_once_with(retitle.client(), 'A', '新しい題', True, only_team_city=False)

    def test_invalid_mode_fails_before_client(self):
        for args in (['--only-team-city'],
                     ['--kind', 'asset', '--only-team-city', '--title', '題']):
            with patch.object(sys, 'argv', ['retitle', *args]), \
                    patch.object(retitle, 'client') as client:
                with self.assertRaises(SystemExit) as error:
                    retitle.main()
                self.assertEqual(error.exception.code, 2)
                client.assert_not_called()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
