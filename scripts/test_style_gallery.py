"""種類の抜けを止める試験。描画は行わない。"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / ".github" / "workflows"

# style_gallery.py から KINDS を読み込む。
_spec = importlib.util.spec_from_file_location(
    "style_gallery", str(ROOT / "scripts" / "style_gallery.py")
)
style_gallery = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(style_gallery)
KINDS = style_gallery.KINDS


class WorkflowCoverage(unittest.TestCase):
    def test_all_style_workflows_are_in_kinds(self):
        """COLLESPO_STYLE を渡す全ワークフローが KINDS のどれかに入っている。"""
        style_workflows = [
            p.stem
            for p in WF_DIR.glob("*.yml")
            if "COLLESPO_STYLE" in p.read_text(encoding="utf-8")
        ]
        covered = {name for info in KINDS.values() for name in info["workflows"]}
        missing = [w for w in style_workflows if w not in covered]
        self.assertEqual(
            missing,
            [],
            f"KINDS の workflows に含まれていないワークフロー: {missing}",
        )

    def test_all_workflow_files_in_kinds_exist(self):
        """KINDS に書かれたワークフローが実在する。"""
        covered = {name for info in KINDS.values() for name in info["workflows"]}
        for name in covered:
            path = WF_DIR / f"{name}.yml"
            self.assertTrue(
                path.is_file(),
                f"KINDS に書かれたワークフローが実在しません: {name}.yml",
            )

    def test_workflow_env_resolves_soccer_daily(self):
        """ワークフローの env を本番のリポジトリ変数で解決する。"""
        env = style_gallery.workflow_env(
            "soccer_daily.yml",
            {"COLLESPO_SOCCER_LOOK": "v6", "COLLESPO_STYLE": "v2"},
        )
        self.assertEqual(env["COLLESPO_SHORT_LOOK"], "v6")
        self.assertEqual(env["COLLESPO_STYLE"], "v2")
        self.assertEqual(env["COLLESPO_GLASS_BACKGROUND"], "stripes")
        self.assertNotIn("COLLESPO_SAMPLE_ONLY", env)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
