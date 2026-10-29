"""保存漏れの検査（run_checks.check_commit_list）が、読むだけの入力を書き込みと取り違えない。"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_checks  # noqa: E402


class WritesTo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        self.saved = run_checks.ROOT
        run_checks.ROOT = self.root

    def tearDown(self):
        run_checks.ROOT = self.saved
        self.tmp.cleanup()

    def script(self, src):
        (self.root / "scripts" / "x.py").write_text(src, encoding="utf-8")

    def test_read_then_unrelated_write_is_not_a_write(self):
        # 10/28 topic_hub.py の形。reddit は読むだけで、書くのは out。
        self.script(
            "result=build(load(args.a),\n"
            "             load(args.reddit) if args.reddit else {},now)\n"
            "target=Path(args.out); target.parent.mkdir(parents=True,exist_ok=True)\n"
            "target.write_text('x')\n")
        self.assertFalse(run_checks._writes_to("x.py", "reddit"))
        self.assertTrue(run_checks._writes_to("x.py", "out"))

    def test_write_spanning_open_parenthesis_is_still_found(self):
        self.script(
            "json.dump(data,\n"
            "          open(args.log, 'w'))\n")
        self.assertTrue(run_checks._writes_to("x.py", "log"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])  # run_checks は一時置場を引数で渡す
