#!/usr/bin/env python3
"""ぶつかった記録を、両方残して解けるか。

実際にgitでぶつけて確かめる。**外部にも本番データにも触らない。**

なぜ実物でやるのか:
  混ぜる関数だけを試しても、肝心の「rebaseの途中で呼ばれて、
  git add まで済ませて、--continue に進める」ところが確かめられない。
  8/17と9/6に記録が消えたのは、まさにその流れの途中だった。
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import merge_json_conflict  # noqa: E402  (混ぜる関数の単体確認に使う)

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def git(folder, *args, **kw):
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                "GIT_EDITOR": "true"})
    return subprocess.run(["git"] + list(args), cwd=folder, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          **kw)


def write(folder, obj):
    # 1行で書く。行単位の突き合わせで必ずぶつかる形にするため。
    (folder / "data" / "rec.json").write_text(
        json.dumps(obj, ensure_ascii=False), encoding="utf-8")


print("--- 混ぜ方 ---")
check("別の枠と別の日が増えただけなら、両方残す",
      merge_json_conflict.merge(
          {"morning": {"9/6": "A"}, "daily": {"9/6": "B"}},
          {"morning": {"9/7": "C"}}),
      {"morning": {"9/6": "A", "9/7": "C"}, "daily": {"9/6": "B"}})
check("同じ鍵で食い違うときは、押そうとしている側",
      merge_json_conflict.merge({"a": 1}, {"a": 2}), {"a": 2})
try:
    merge_json_conflict.merge({"x": [1, 2]}, {"x": [3]})
    check("配列は諦める", "混ぜてしまった", "ValueError")
except ValueError:
    check("配列は諦める", "ValueError", "ValueError")

print(chr(10) + "--- 実際にぶつけて解く ---")
with tempfile.TemporaryDirectory() as tmp:
    d = pathlib.Path(tmp)
    (d / "data").mkdir()
    (d / "scripts").mkdir()
    # 解く道具を、そのままの名前で置く（commit_data.sh と同じ呼び方をする）
    (d / "scripts" / "merge_json_conflict.py").write_text(
        (HERE / "merge_json_conflict.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    git(d, "init", "-q", "-b", "main")
    write(d, {"morning": {"2026-09-05": "old"}})
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "start")

    # 相手（先に押した側）: daily の記録が増えた
    write(d, {"morning": {"2026-09-05": "old"}, "daily": {"2026-09-06": "B"}})
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "daily")
    git(d, "branch", "-f", "upstream")

    # 自分: 同じ場所に morning の記録が増えた
    git(d, "reset", "-q", "--hard", "HEAD~1")
    write(d, {"morning": {"2026-09-05": "old", "2026-09-06": "A"}})
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "morning")

    r = git(d, "rebase", "upstream")
    check("取り込みでぶつかる", r.returncode != 0, True)

    r = subprocess.run([sys.executable, "scripts/merge_json_conflict.py"],
                       cwd=d, capture_output=True, text=True,
                       encoding="utf-8")
    check("解けた", r.returncode, 0)
    r = git(d, "rebase", "--continue")
    check("続けられた", r.returncode, 0)

    got = json.loads((d / "data" / "rec.json").read_text(encoding="utf-8"))
    check("相手の記録が残っている", got.get("daily"), {"2026-09-06": "B"})
    check("自分の記録も残っている", got.get("morning", {}).get("2026-09-06"), "A")
    check("もとからあった記録も無事",
          got.get("morning", {}).get("2026-09-05"), "old")

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
