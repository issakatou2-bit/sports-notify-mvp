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

import re
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


def check_shell_in_yaml() -> int:
    """
    ワークフローの run: が、シェルとして読める形になっているか。

    YAMLとして正しくても、シェルとして壊れていることがある。
    行継続のバックスラッシュを書こうとして、バックスラッシュとnの2文字が
    そのまま入り、コマンドの引数に化けたことがある。
    YAMLの検査は通るので、動かして初めて分かる種類の壊れ方。
    """
    step("ワークフローの run: がシェルとして読めるか")
    try:
        import yaml
    except ImportError:
        print("[info] pyyaml が無いため飛ばします")
        return 0
    bad = 0
    marker = chr(92) + "n"          # 「\」+「n」
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue  # YAMLの検査が別に見る
        for job in (d.get("jobs") or {}).values():
            for stepd in (job.get("steps") or []):
                run = stepd.get("run")
                if not isinstance(run, str):
                    continue
                # 1行の中にバックスラッシュ+nがあれば、書き損じ
                for line in run.splitlines():
                    if marker in line:
                        bad += 1
                        print(f"NG {f.name} / {stepd.get('name','(名前なし)')}: "
                              f"行継続が文字列になっています")
                        print(f"     {line.strip()[:90]}")
    print(f"{'ok ' if not bad else 'NG '} 壊れた行 {bad}件")
    return bad


def check_imports() -> int:
    """
    本番と同じ起動の仕方で、各スクリプトが立ち上がるか。

    構文検査もpyflakesも、import が実際に解決できるかまでは見ない。
    generate_narration.py がリポジトリ直下の notability_engine を
    sys.path を通さずに import しており、本番では毎回
    ModuleNotFoundError で落ちていた。ナレーションが作れないので
    音声も動画もポッドキャストも作られず、それが何日も気付かれなかった。

    --help を渡して起動するだけなので、APIも叩かず、ファイルも書かない。
    それでも import は全部走るので、この種の欠落はここで捕まる。
    """
    step("スクリプトが起動できるか(本番と同じ呼び方)")
    bad = 0
    for f in sorted(ROOT.glob("scripts/*.py")):
        if f.name.startswith(("test_", "run_checks")):
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        if "argparse" not in src:
            continue  # --help を受け付けないものは、起動＝実行になるので飛ばす
        r = run([sys.executable, str(f), "--help"])  # run() が cwd=ROOT で起動する
        err = (r.stderr or "")
        if "ModuleNotFoundError" in err or "ImportError" in err:
            bad += 1
            line = [x for x in err.splitlines() if "Error" in x]
            print(f"NG {f.name}: {line[-1] if line else err[:120]}")
    print(f"{'ok ' if not bad else 'NG '} 起動できないもの {bad}件")
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


def check_commit_list() -> int:
    """
    その回で作ったファイルを、コミットの一覧へ渡し忘れていないか。

    なぜ要るのか:
      朝の回は8/16を最後に、投稿の記録が1件も残っていなかった。
      動画は毎日出ている。best_of_day.json と player_profile.json を
      新しく作るようにしたのに、commit_data.sh へ渡していなかったので、
      作業ツリーが汚れたまま push が競合し、rebase が拒まれて終わっていた。

      ワークフローは緑で終わる。動画も出る。記録だけが消える。
      実行ログを見ても気づけない類の穴なので、機械に見張らせる。

    見るもの:
      --out data/x.json で作っていて、gitが追跡していて、
      同じワークフローの commit_data.sh の引数に無いもの。
    """
    step("作ったのにコミットしていないもの")
    tracked = set((run(["git", "ls-files", "data"]).stdout or "").split())
    bad = 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        if "commit_data.sh" not in text:
            continue  # 記録を残さない回。渡し忘れも起きない。
        made = set(re.findall(r"--out\s+(data/[\w./-]+\.json)", text))

        # commit_data.sh の呼び出しから、続く行の引数を拾う。
        # 行末が \ で続いている間だけが、その呼び出しの引数。
        listed = set()
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "commit_data.sh" not in line:
                continue
            j = i
            while j < len(lines):
                listed |= set(re.findall(r"(data/[\w./-]+)", lines[j]))
                if not lines[j].rstrip().endswith(chr(92)):
                    break
                j += 1

        miss = sorted(f for f in made
                      if f in tracked and f not in listed
                      and not any(f.startswith(d + "/") for d in listed))
        if miss:
            bad += 1
            print(f"NG {wf.name}: {' '.join(miss)} を残していません")
        else:
            print(f"ok {wf.name}")
    return bad


def main() -> int:
    import tempfile

    tmp = tempfile.mkdtemp(prefix="collespo-checks-")
    failed = 0
    failed += check_syntax()
    failed += check_pyflakes()
    failed += check_yaml()
    failed += check_shell_in_yaml()
    failed += check_imports()
    failed += check_tests(tmp)
    failed += check_inventory()
    failed += check_commit_list()

    print()
    if failed:
        print(f"===== {failed}件の問題があります =====")
    else:
        print("===== すべて通過 =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
