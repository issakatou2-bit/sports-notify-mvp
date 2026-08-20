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


def _writes_to(script: str, dest: str) -> bool:
    """その台本が args.<dest> の指す先へ書き込むか。

    書き方は二通りある。args.x を直に渡す形と、いったん
    Path(args.x) を変数に入れてから書く形。後者が
    featured_players.json の書き方で、直の検索では見つからない。
    """
    path = ROOT / "scripts" / script
    if not path.exists():
        return False
    src = path.read_text(encoding="utf-8")
    ref = "args." + dest
    if ref not in src:
        return False

    lines = src.splitlines()
    aliases = {ref}
    for line in lines:
        m = re.match(r"\s*(\w+)\s*=\s*(?:pathlib\.)?Path\(" + re.escape(ref),
                     line)
        if m:
            aliases.add(m.group(1))

    for i, line in enumerate(lines):
        if not any(a in line for a in aliases):
            continue
        # 書き込みは同じ行か、続く数行に現れる
        if _is_write(" ".join(lines[i:i + 3])):
            return True
        # 他の関数へ渡している形。ニュースの履歴はこれで、
        # append_news_log(Path(args.log), ...) と渡した先で書いていた。
        # 呼び先を一段だけ辿る。名前で当てると当て損なう。
        for cm in re.finditer(r"\b(\w+)\(([^\n]*)\)", line):
            fn, argstr = cm.group(1), cm.group(2)
            if not any(a in argstr for a in aliases):
                continue
            pos = _arg_position(argstr, aliases)
            if pos is None:
                continue
            dm = re.search(r"^def " + re.escape(fn) + r"\(([^)]*)\)",
                           src, re.M)
            if not dm:
                continue
            params = [p.split(":")[0].split("=")[0].strip()
                      for p in dm.group(1).split(",")]
            if pos < len(params) and _writes_to_var(src, fn, params[pos]):
                return True
    return False


def _arg_position(argstr: str, aliases: set):
    """呼び出しの何番目の引数に入っているか。"""
    depth = 0
    start = 0
    parts = []
    for i, ch in enumerate(argstr):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(argstr[start:i])
            start = i + 1
    parts.append(argstr[start:])
    for i, p in enumerate(parts):
        if any(a in p for a in aliases):
            return i
    return None


def _is_write(text: str) -> bool:
    """この断片は書き込みか。

    open() は開く向きまで見る。読むだけの open(path, "r") を
    書き込みと数えると、読み専用の入力まで「コミット漏れ」に見えて、
    検査そのものが信用されなくなる。
    """
    if re.search(r"\.(write_text|write_bytes|mkdir)\b", text):
        return True
    if re.search(r"json\.dump\(", text):
        return True
    return bool(re.search(r"open\([^)]*[\"'][wax]b?\+?[\"']", text))


def _writes_to_var(src: str, fn: str, param: str) -> bool:
    """関数 fn の本体で、引数 param へ書いているか。"""
    m = re.search(r"^def " + re.escape(fn) + r"\(.*?\n(.*?)(?=^def |\Z)",
                  src, re.M | re.S)
    if not m:
        return False
    for line in m.group(1).splitlines():
        if param in line and _is_write(line):
            return True
    return False


def _defaults_written(script: str) -> set:
    """台本が既定値で書きにいく data/*.json。

    渡していないから安全、とはならない。ニュースの履歴は
    argparse の既定値で data/news_log.json を書いていて、
    ワークフローの行には現れないまま、一度もコミットされていなかった。
    """
    path = ROOT / "scripts" / script
    if not path.exists():
        return set()
    src = path.read_text(encoding="utf-8")
    out = set()
    for m in re.finditer(r"add_argument\(\s*[\"']--([\w-]+)[\"'][^)]*?"
                         r"default\s*=\s*[\"'](data/[\w./-]+\.json)[\"']",
                         src, re.S):
        if _writes_to(script, m.group(1).replace("-", "_")):
            out.add(m.group(2))
    # 既定値を持たず、定数で直に書いているものも拾う
    for m in re.finditer(r"^[A-Z_]+\s*=\s*[\"'](data/[\w./-]+\.json)[\"']",
                         src, re.M):
        name = src[:m.start()].rsplit("\n", 1)[-1] or ""
        const = re.match(r"([A-Z_]+)", m.group(0)).group(1)
        if re.search(re.escape(const) + r"[^\n]*write_text|"
                     r"write_text[^\n]*" + re.escape(const), src):
            out.add(m.group(1))
        del name
    return out


def _written_via_flags(text: str) -> set:
    """ワークフローが動かす台本が書き戻す data/*.json。"""
    out = set()
    # 「python scripts/x.py」から、次の python 行までを1つの呼び出しとみなす
    for m in re.finditer(r"python\s+scripts/([\w_]+\.py)((?:.|\n)*?)"
                         r"(?=\n\s*(?:python|-\s*name:|#|\Z))", text):
        script, tail = m.group(1), m.group(2)
        for fm in re.finditer(r"--([\w-]+)\s+[\"']?(data/[\w./-]+\.json)",
                              tail):
            flag, path = fm.group(1), fm.group(2)
            if _writes_to(script, flag.replace("-", "_")):
                out.add(path)
        out |= _defaults_written(script)
    return out


def check_commit_list() -> int:
    """
    その回で作ったファイルを、コミットの一覧へ渡し忘れていないか。

    なぜ要るのか:
      夕方の回は8/16を最後に、投稿の記録が1件も残っていなかった。
      動画は毎日出ている。best_of_day.json と player_profile.json を
      新しく作るようにしたのに、commit_data.sh へ渡していなかったので、
      作業ツリーが汚れたまま push が競合し、rebase が拒まれて終わっていた。

      ワークフローは緑で終わる。動画も出る。記録だけが消える。
      実行ログを見ても気づけない類の穴なので、機械に見張らせる。

      --out だけ見ていたら、二度目を素通りさせた。
      「今日の1人」の重複除けの履歴は --history data/featured_players.json
      で渡していて、player_profile.py はそこへ書き戻す。だが
      commit_data.sh に無かったので、履歴は毎回まっさらに戻り、
      14日の間隔は一度も効いていなかった。Pete Crow-Armstrong が
      8/18と8/19に続けて出たのはそのため。

      なので旗の名前では判断しない。ワークフローが渡している
      data/*.json を全部拾って、渡された先の台本がそこへ書くかどうかを
      台本自身に見にいく。書くなら、コミットに要る。

    見るもの:
      ワークフローが台本に渡していて、その台本が書き込んでいて、
      gitが追跡していて、commit_data.sh の引数に無いもの。
    """
    step("作ったのにコミットしていないもの")
    tracked = set((run(["git", "ls-files", "data"]).stdout or "").split())
    bad = 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        if "commit_data.sh" not in text:
            continue  # 記録を残さない回。渡し忘れも起きない。
        made = set(re.findall(r"--out\s+(data/[\w./-]+\.json)", text))
        made |= _written_via_flags(text)

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


def check_workflow_links() -> int:
    """
    workflow_run で名前を指しているワークフローが、実際にあるか。

    なぜ要るのか:
      サッカー・週次・見張りの3つは「Daily notable games が終わったら」で
      起動する。指しているのはワークフローの name で、ファイル名ではない。
      つまり name を1文字変えるだけで、3本が静かに動かなくなる。
      止まっても赤くならない。呼ばれないだけなので、ログにも残らない。
    """
    step("ワークフローどうしの参照")
    import re as _re
    quoted = _re.compile("[" + chr(34) + chr(39) + "]([^" + chr(34) + chr(39)
                         + "]+)[" + chr(34) + chr(39) + "]")
    d = ROOT / ".github" / "workflows"
    names, refs = set(), []
    for f in sorted(d.glob("*.yml")):
        t = f.read_text(encoding="utf-8")
        m = _re.search(r"^name:\s*(.+)$", t, _re.M)
        if m:
            names.add(m.group(1).strip().strip(chr(34)).strip(chr(39)))
        for block in _re.findall(r"workflows:\s*\[(.*?)\]", t, _re.S):
            for q in quoted.findall(block):
                refs.append((f.name, q.strip()))
    bad = 0
    for src, want in refs:
        if want in names:
            print(f"ok {src} -> {want}")
        else:
            bad += 1
            print(f"NG {src} が指している「{want}」が見つかりません")
    if not refs:
        print("(参照なし)")
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
    failed += check_workflow_links()

    print()
    if failed:
        print(f"===== {failed}件の問題があります =====")
    else:
        print("===== すべて通過 =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
