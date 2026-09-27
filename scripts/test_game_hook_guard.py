import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import game_hook_guard as guard


NOOTBAAR_HOOK = 'ワイルドカード争い続行の守護神ヌートバー、ポストシーズン決定パドレスに挑む'
DODGERS_HOOK = 'ドジャース99勝vs4連敗中のジャイアンツ、伝統の好カードが決定戦'


def fixture(game_id='823246', hook=NOOTBAAR_HOOK, league='MLB'):
    return {'game_id': game_id, 'league': league, 'notification_hook': hook,
            'jp_players': ['松井裕樹', 'ヌートバー'], 'jp_starters': [],
            'reasons': [{'tag': 'jp_team', 'text': 'ダイヤモンドバックスにはヌートバーが所属'},
                        {'tag': 'ps_race', 'text': 'パドレス はポストシーズン圏内'}],
            'ai_summary': 'パドレスはポストシーズン進出を決めている。',
            'result': {'home': 2, 'away': 1}}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


class GameHookGuard(unittest.TestCase):
    def test_published_september_27_failures(self):
        for hook, term in [(NOOTBAAR_HOOK, '守護神'), (DODGERS_HOOK, '決定戦')]:
            with self.subTest(term=term):
                game = fixture(hook=hook)
                if term == '決定戦':
                    game['game_id'] = '823164'
                    game['reasons'] = [
                        {'tag': 'ps_race', 'text': 'ドジャース はポストシーズン圏内'},
                        {'tag': 'rivalry', 'text': 'ドジャース vs ジャイアンツ は伝統の好カード'}]
                    game['ai_summary'] = 'ドジャースは地区優勝を既に決めている。'
                original = copy.deepcopy(game)
                self.assertEqual(guard.validated_hook(game), '')
                self.assertEqual(len(guard.rejection_reasons(game)), 1)
                self.assertIn(term, guard.rejection_reasons(game)[0])
                self.assertEqual(game, original)

    def test_safe_hook_is_preserved_verbatim(self):
        game = fixture(hook='  菊池雄星、1勝6敗の状況でマリナーズと対戦へ\n')
        self.assertEqual(guard.validated_hook(game), game['notification_hook'])
        self.assertEqual(guard.rejection_reasons(game), [])

    def test_each_term_needs_explicit_rule_evidence(self):
        for term in guard.GUARDED_TERMS:
            with self.subTest(term=term):
                game = fixture(hook=f'{term}に注目')
                self.assertEqual(guard.validated_hook(game), '')
                game['reasons'].append({'tag': 'manual', 'text': f'公式確認済みの{term}'})
                self.assertEqual(guard.validated_hook(game), game['notification_hook'])

    def test_names_ai_summary_and_other_labels_do_not_prove_role(self):
        game = fixture()
        game['jp_players'] = ['守護神ヌートバー']
        game['jp_starters'] = [{'name': '守護神ヌートバー'}]
        game['ai_summary'] = '守護神ヌートバーが登板する。'
        game['reasons'].extend([{'tag': '守護神', 'text': '所属選手'},
                                {'text': {'caption': '守護神'}}])
        self.assertEqual(guard.validated_hook(game), '')

    def test_all_claimed_terms_need_evidence_not_just_one(self):
        game = fixture(hook='守護神が決定戦に臨む')
        game['reasons'] = [{'text': '守護神についての確認済み資料'}]
        self.assertEqual(guard.validated_hook(game), '')
        self.assertIn('決定戦', guard.rejection_reasons(game)[0])

    def test_empty_or_malformed_optional_values_are_safe(self):
        for value in [None, '', 7]:
            self.assertEqual(guard.validated_hook({'notification_hook': value}), '')
        for reasons in [None, '守護神', [{'text': None}], [None]]:
            game = fixture()
            game['reasons'] = reasons
            self.assertEqual(guard.validated_hook(game), '')

    def test_soccer_uses_the_same_guard(self):
        game = fixture(game_id='soccer-1', hook='今日の一戦で優勝決定戦', league='SOCCER')
        self.assertEqual(guard.validated_hook(game), '')
        game['reasons'] = [{'text': '優勝決定戦に該当することを確認'}]
        self.assertEqual(guard.validated_hook(game), game['notification_hook'])

    def test_cli_json_report_and_exact_archive_changes_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            games_path, archive_dir, report_path = root/'games.json', root/'archive', root/'report.json'
            unsafe = fixture()
            soccer_bad = fixture('soccer-1', '根拠のない決定戦', 'SOCCER')
            safe = fixture('823084', '菊池雄星が先発予定')
            payload = {'generated_at': '2026-09-27T18:53:55+09:00',
                       'games': [unsafe, safe, soccer_bad], 'ai_status': {'succeeded': 3},
                       'results': [copy.deepcopy(unsafe)]}
            other_game = fixture('other-id')
            other_league = fixture('823246', NOOTBAAR_HOOK, 'SOCCER')
            different_hook = fixture('823246', '以前の守護神という文面')
            archive = {'generated_at': '2026-09-27T18:52:00+09:00',
                       'games': [copy.deepcopy(unsafe), other_game, other_league,
                                 different_hook, copy.deepcopy(soccer_bad)],
                       'results': [copy.deepcopy(unsafe)]}
            write_json(games_path, payload)
            write_json(archive_dir/'2026-09-27.json', archive)
            write_json(archive_dir/'2026-09-26.json', archive)
            original_sha = hashlib.sha256(games_path.read_bytes()).hexdigest()
            older_bytes = (archive_dir/'2026-09-26.json').read_bytes()
            command = [sys.executable, '-B', str(Path(guard.__file__)), '--games', str(games_path),
                       '--archive-dir', str(archive_dir), '--report', str(report_path)]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                    env={**os.environ, 'PYTHONUTF8': '1'})
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(json.loads(report_path.read_text(encoding='utf-8')), report)
            self.assertEqual(report['input']['sha256'], original_sha)
            self.assertEqual((report['checked_games'], report['rejected_count']), (3, 2))
            self.assertEqual(report['archive']['modified_games'], 2)
            expected = copy.deepcopy(payload)
            del expected['games'][0]['notification_hook']
            del expected['games'][2]['notification_hook']
            self.assertEqual(json.loads(games_path.read_text(encoding='utf-8')), expected)
            expected_archive = copy.deepcopy(archive)
            del expected_archive['games'][0]['notification_hook']
            del expected_archive['games'][4]['notification_hook']
            self.assertEqual(json.loads((archive_dir/'2026-09-27.json').read_text(encoding='utf-8')),
                             expected_archive)
            self.assertEqual((archive_dir/'2026-09-26.json').read_bytes(), older_bytes)
            first_games = games_path.read_bytes()
            first_archive = (archive_dir/'2026-09-27.json').read_bytes()
            again = guard.sanitize_files(games_path, archive_dir)
            self.assertEqual(again['modified_games'], 0)
            self.assertEqual(again['archive']['modified_games'], 0)
            self.assertEqual(games_path.read_bytes(), first_games)
            self.assertEqual((archive_dir/'2026-09-27.json').read_bytes(), first_archive)

    def test_other_date_inside_named_archive_is_not_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            games = root/'games.json'
            archive = root/'archive'/'2026-09-27.json'
            write_json(games, {'generated_at': '2026-09-27T18:00:00+09:00', 'games': [fixture()]})
            write_json(archive, {'generated_at': '2026-09-26T18:00:00+09:00', 'games': [fixture()]})
            before = archive.read_bytes()
            report = guard.sanitize_files(games, archive.parent)
            self.assertEqual(report['archive']['status'], 'skipped_generated_date_mismatch')
            self.assertEqual(archive.read_bytes(), before)

    def test_bad_archive_cannot_partially_change_main_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            games = root/'games.json'
            write_json(games, {'generated_at': '2026-09-27T18:00:00+09:00', 'games': [fixture()]})
            write_json(root/'2026-09-27.json', {'games': 'not a list'})
            before = games.read_bytes()
            with self.assertRaises(ValueError):
                guard.sanitize_files(games, root)
            self.assertEqual(games.read_bytes(), before)

    def test_report_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            games = Path(tmp)/'games.json'
            write_json(games, {'games': [fixture()]})
            before = games.read_bytes()
            with self.assertRaises(ValueError):
                guard.sanitize_files(games, report_path=games)
            self.assertEqual(games.read_bytes(), before)


if __name__ == '__main__':
    unittest.main(argv=['test_game_hook_guard'])
