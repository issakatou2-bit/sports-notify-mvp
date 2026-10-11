"""実際のJose台詞、偽応答、全呼出し境界。外部通信・課金なし。"""
import ast
import contextlib
import io
import pathlib
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import backstage_guard as guard
import generate_dialogue as dialogue

BAD = 'Joseが誰かは材料にないから、そこは深追いしないのだ'


def response(text):
    return NS(content=[NS(type='text', text=text)], stop_reason='end_turn',
              usage=NS(input_tokens=10, output_tokens=20))


class Tests(unittest.TestCase):
    def test_dictionary_real_failure_and_variants(self):
        for text in [BAD, '材料には無い', 'データにないので省く', '情報が無いので',
                     '渡された事実のみなのだ', '原文に記載がない', '材料が不足',
                     '材料にありません', '材料 に な い', 'not in the provided data']:
            with self.subTest(text=text):
                self.assertTrue(guard.violations(text))
        for text in ['材料費が上がった', '打球速度のデータに注目する',
                     '情報が少ない試合でも観客は声援を送った',
                     '記録がない時代の試合', '故障の情報は球団が発表した']:
            with self.subTest(text=text):
                self.assertFalse(guard.violations(text))

    @patch('token_log.allowed', return_value=True)
    @patch('token_log.record')
    def test_retry_and_costs(self, record, allowed):
        client = NS(messages=Mock())
        client.messages.create.side_effect = [response(BAD), response('大谷は1得点です。')]
        kw = {'model':'fixture', 'messages':[{'role':'user','content':'元の材料'}]}
        result = guard.create(client, label='narration', **kw)
        self.assertEqual(guard.response_text(result), '大谷は1得点です。')
        self.assertEqual(client.messages.create.call_count, 2)
        self.assertEqual(record.call_count, 1)  # 不採用1回、採用分は従来の呼出元で記録
        self.assertEqual(len(kw['messages']), 1)
        self.assertIn(guard.rules()[0], client.messages.create.call_args.kwargs['messages'][-1]['content'])

    @patch('token_log.allowed', return_value=True)
    @patch('token_log.record')
    def test_drop_only_independent_lines(self, record, allowed):
        client = NS(messages=Mock())
        dirty = response('1|中立|'+BAD+'\n2|称賛|大谷が最高だ')
        client.messages.create.side_effect = [dirty, dirty]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = guard.create(client, label='voices', mode='lines', model='fixture', messages=[])
        self.assertEqual(guard.response_text(result), '2|称賛|大谷が最高だ')
        self.assertIn(BAD, guard.response_text(dirty))  # 原応答を壊さない
        self.assertIn('1行目', err.getvalue())
        self.assertEqual(record.call_count, 1)  # 2回目の費用は返したコピーで従来どおり記録

    def test_whole_or_no_lines_fail_closed(self):
        for mode in ['whole', 'lines']:
            first, retry = Mock(return_value=response(BAD)), Mock(return_value=response(BAD))
            with self.assertRaises(guard.BackstageError):
                guard.guard_response(first, retry, label='fixture', mode=mode)
            self.assertEqual(retry.call_count, 1)

    def test_budget_or_network_does_not_restore_dirty_draft(self):
        retry = Mock()
        with self.assertRaises(guard.BackstageError):
            guard.guard_response(lambda:response(BAD), retry, label='fixture', allowed=lambda:False)
        retry.assert_not_called()
        retry.side_effect = RuntimeError('fixture failure')
        with self.assertRaises(RuntimeError):
            guard.guard_response(lambda:response(BAD), retry, label='fixture')

    def test_budget_drop_records_initial_usage_only_once(self):
        dirty=response(BAD+'\n2|中立|安全な行')
        retry, recorded=Mock(), Mock()
        clean=guard.guard_response(lambda:dirty,retry,label='fixture',mode='lines',
                                   rejected=recorded,allowed=lambda:False)
        recorded.assert_called_once_with(dirty)
        retry.assert_not_called()
        self.assertEqual(clean.usage.input_tokens,0)
        self.assertEqual(dirty.usage.input_tokens,10)

    @patch('token_log.allowed', return_value=True)
    @patch('token_log.record')
    def test_batch_is_checked_and_retry_is_direct(self, record, allowed):
        with patch('dialogue_batch.run', return_value=response('ずんだもん：'+BAD)) as batch, \
             patch.object(dialogue, '_create', return_value=response('めたん：大谷は1得点です。')) as direct:
            result = dialogue._ask(object(), 'draft', messages=[], max_tokens=100)
        self.assertFalse(guard.violations(guard.response_text(result)))
        self.assertEqual(batch.call_count, 1)
        self.assertEqual(direct.call_count, 1)
        self.assertIn(guard.rules()[0], batch.call_args.args[2]['messages'][-1]['content'])

    def test_all_production_message_paths_guarded(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        found = []
        for path in [root/'notability_engine.py', *sorted((root/'scripts').glob('*.py'))]:
            if path.name.startswith('test_') or path.name in ('backstage_guard.py', 'dialogue_batch.py'):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ('create', 'stream') and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'messages':
                        found.append(path.name)
        self.assertEqual(found, ['generate_dialogue.py', 'generate_dialogue.py'])
        # _create は _ask のBatchと共通検査だけから使われる。
        source = (root/'scripts/generate_dialogue.py').read_text(encoding='utf-8')
        self.assertIn('backstage_guard.guard_response(first, retry', source)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
