"""旧い見た目が流れ・投稿に戻らないことを確かめる（描画なし・速い）。"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import design_lock  # noqa: E402

WORKFLOWS = HERE.parent / '.github' / 'workflows'


class WorkflowsUseCurrentLook(unittest.TestCase):
    def test_every_workflow_sets_only_current_look_values(self):
        found = []
        for path in sorted(WORKFLOWS.glob('*.yml')):
            found.extend(design_lock.workflow_problems(path))
        self.assertEqual(found, [])

    def test_short_rendering_workflows_set_style_and_short_look(self):
        # 投稿するショートの流れは、見た目を必ず書き込む（書かないと旧い既定で描かれる）
        missing = []
        for path in sorted(WORKFLOWS.glob('*.yml')):
            text = path.read_text(encoding='utf-8')
            if 'upload_youtube' not in text or 'COLLESPO_SHORT_LOOK' in text:
                continue
            if 'COLLESPO_LONGFORM_STYLE' in text or path.stem in ('weekly_summary', 'related_videos'):
                continue  # 長編・週のまとめ
            missing.append(path.name)
        self.assertEqual(missing, [])


class UploadStopsOnOldLook(unittest.TestCase):
    def test_old_values_are_refused(self):
        for env in ({'COLLESPO_STYLE': 'v1'}, {'COLLESPO_SHORT_LOOK': 'v3'},
                    {'COLLESPO_SOCCER_LOOK': 'v5'}, {'COLLESPO_SOCCER_FOCUS': 'off'},
                    {'COLLESPO_LONGFORM_STYLE': 'v2'}):
            with self.subTest(env=env):
                self.assertTrue(design_lock.problems(env))
                with self.assertRaises(SystemExit):
                    design_lock.check(env)

    def test_current_values_pass(self):
        env = {'COLLESPO_STYLE': 'v2', 'COLLESPO_SHORT_LOOK': 'v6', 'COLLESPO_SOCCER_LOOK': 'v6',
               'COLLESPO_SOCCER_FOCUS': 'on', 'COLLESPO_LONGFORM_STYLE': 'v3'}
        self.assertEqual(design_lock.problems(env), [])
        design_lock.check(env)

    def test_workflow_check_catches_old_and_switchable_values(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'x.yml'
            p.write_text("env:\n  COLLESPO_SHORT_LOOK: v3\n  COLLESPO_STYLE: ${{ vars.COLLESPO_STYLE || 'v1' }}\n"
                         "  # COLLESPO_SOCCER_LOOK=v4 は説明\n", encoding='utf-8')
            self.assertEqual(len(design_lock.workflow_problems(p)), 2)

    def test_upload_calls_the_check(self):
        source = (HERE / 'upload_youtube.py').read_text(encoding='utf-8')
        self.assertIn('design_lock.check()', source)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
