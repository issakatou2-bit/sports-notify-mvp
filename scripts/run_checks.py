#!/usr/bin/env python3
"""
押す前に通す検査をまとめて走らせる。

なぜ要るのか:
  テストは書いてあったが、CIで一度も走っていなかった。手元で気づいた
  ときだけ実行する運用で、実際そのまま壊れたものが本番へ出た。

  直近の例:
    ・実行ページへ出す処理で、変数を定義せずに参照していた
      (未定義名。動かせば必ず落ちるが、手元にGoogleの
       ライブラリが無くて実行できず、そのまま押した)
    ・サッカーの採点が本番で1つも発火しなかった
      (テストは通っていたが、渡す値が実物と違った)

  ここで見るのは「動かさなくても分かること」に絞る。
  APIキーが要るものは対象にしない。

見るもの:
  1. 構文
  2. 未定義名・到達しないコード(pyflakes)
  3. ワークフローのYAML
  4. テスト一式
  5. 資産動画の登録漏れ

使い方:
  py -3 scripts/run_checks.py
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 落ちたら止めるもの。警告どまりのものと分けて扱う。
FATAL_PYFLAKES = ("undefined name", "syntax error",
                  "redefinition of unused")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=ROOT, **kw)


def step(name):
    print(f"\n--- {name} ---")


def check_syntax() -> int:
    step("構文")
    bad = 0
    files = sorted(ROOT.glob("scripts/*.py")) + [ROOT / "notability_engine.py"]
    for f in files:
        r = run([sys.executable, "-m", "py_compile", str(f)])
        if r.returncode:
            bad += 1
            print(f"NG {f.name}\n{r.stderr.strip()[:300]}")
    print(f"{'ok ' if not bad else 'NG '} {len(files)}ファイル / 失敗 {bad}")
    return bad


def check_pyflakes() -> int:
    step("未定義名など")
    targets = [str(p) for p in sorted(ROOT.glob("scripts/*.py"))]
    targets.append(str(ROOT / "notability_engine.py"))
    r = run([sys.executable, "-m", "pyflakes"] + targets)
    if "No module named" in (r.stderr or ""):
        print("[info] pyflakes が無いため飛ばします "
              "(py -3 -m pip install pyflakes)")
        return 0
    fatal, warn = [], []
    for line in (r.stdout or "").splitlines():
        low = line.lower()
        if any(k in low for k in FATAL_PYFLAKES):
            fatal.append(line)
        elif line.strip():
            warn.append(line)
    for line in warn:
        print(f"   {line}")
    for line in fatal:
        print(f"NG {line}")
    print(f"{'ok ' if not fatal else 'NG '} 重大 {len(fatal)}件 / 軽微 {len(warn)}件")
    return len(fatal)


def check_yaml() -> int:
    step("ワークフローのYAML")
    try:
        import yaml
    except ImportError:
        print("[info] pyyaml が無いため飛ばします")
        return 0
    bad = 0
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        try:
            yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            bad += 1
            print(f"NG {f.name}: {str(e)[:200]}")
    print(f"{'ok ' if not bad else 'NG '} 失敗 {bad}件")
    return bad


def check_tests(tmp: str) -> int:
    step("テスト")
    bad = 0
    for f in sorted(ROOT.glob("scripts/test_*.py")):
        r = run([sys.executable, str(f), tmp])
        last = (r.stdout or "").strip().splitlines()
        mark = last[-1] if last else "(出力なし)"
        if r.returncode:
            bad += 1
            print(f"NG {f.stem:<22} {mark}")
            for line in (r.stdout or "").splitlines():
                if line.startswith("NG "):
                    print(f"      {line}")
        else:
            print(f"ok {f.stem:<22} {mark}")
    return bad


def check_inventory() -> int:
    step("資産動画の登録漏れ")
    r = run([sys.executable, str(ROOT / "scripts" / "inventory.py"), "--check"])
    print((r.stdout or "").strip().splitlines()[-1] if r.stdout else "(出力なし)")
    return r.returncode


def main() -> int:
    import tempfile

    tmp = tempfile.mkdtemp(prefix="collespo-checks-")
    failed = 0
    failed += check_syntax()
    failed += check_pyflakes()
    failed += check_yaml()
    failed += check_tests(tmp)
    failed += check_inventory()

    print()
    if failed:
        print(f"===== {failed}件の問題があります =====")
    else:
        print("===== すべて通過 =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
