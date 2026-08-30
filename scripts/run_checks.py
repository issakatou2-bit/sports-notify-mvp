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

import ast
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


def check_secrets_passed() -> int:
    """
    台本が読む鍵を、ワークフローが渡しているか。

    なぜ要るのか:
      「現地で話題のチーム」は回数を数えるだけの画面になっていた。
      何を言われているのかを足す仕掛け(summarize_teams)は書いてあり、
      呼ばれてもいた。ただ ANTHROPIC_API_KEY を渡していなかったので、
      鍵が空のときの分岐に落ちて、静かに数字だけを返していた。

      鍵が無いときに落ちない作りは正しい。落ちれば動画ごと止まる。
      だが「落ちない」と「効いている」は別で、実行ログは同じ顔をする。

    見るもの:
      run: が起動する台本が os.environ から読む秘密の名前が、
      その step / job / workflow の env に無いもの。
    """
    step("鍵を渡し忘れていないか")
    try:
        import yaml
    except ImportError:
        print("[info] pyyaml が無いため飛ばします")
        return 0

    pat = re.compile(r"environ(?:\.get)?[\(\[][\"']"
                     r"(\w*(?:API_KEY|TOKEN|SECRET|CLIENT_ID|CLIENT_KEY))"
                     r"[\"']")
    need = {}
    for f in (ROOT / "scripts").glob("*.py"):
        keys = set(pat.findall(f.read_text(encoding="utf-8")))
        if keys:
            need[f.name] = keys

    bad = 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        try:
            d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for job in (d.get("jobs") or {}).values():
            for st in (job.get("steps") or []):
                run = st.get("run")
                if not isinstance(run, str):
                    continue
                given = (set(st.get("env") or {}) | set(job.get("env") or {})
                         | set(d.get("env") or {}))
                for m in re.finditer(r"python\s+scripts/([\w_]+\.py)", run):
                    for k in sorted(need.get(m.group(1), ())):
                        if k not in given:
                            bad += 1
                            print(f"NG {wf.name} / {st.get('name', '?')}: "
                                  f"{m.group(1)} が {k} を読むのに渡していません")
    print(f"{'ok ' if not bad else 'NG '} 渡し忘れ {bad}件")
    return bad


# 標準で入っているものの名前。3.10以降が持っている一覧をそのまま使う。
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


def _third_party(script: str, seen=None) -> set:
    """その台本が要る、標準で入っていない物の名前。

    自作の取り込み(scripts/ の中にある名前)は、そちらが要る物も
    数えに行く。probe_jp_highlight は requests を直に使うだけでなく、
    morning_recap と mlb_buzz も引き込んでいて、そちらも requests に
    依っている。直の import だけ見ても足りない。
    """
    seen = seen if seen is not None else set()
    if script in seen:
        return set()
    seen.add(script)
    path = ROOT / "scripts" / script
    if not path.exists():
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split(".")[0]]
        for n in names:
            if n in STDLIB:
                continue
            if (ROOT / "scripts" / (n + ".py")).exists():
                out |= _third_party(n + ".py", seen)
            elif (ROOT / (n + ".py")).exists():
                continue          # 直下の自作(notability_engine など)
            else:
                out.add(n)
    return out


# 正規表現の中の逆斜線。書き換えの経路で \n が実際の改行に潰れるため、
# 組み立てて使う(同じことが local_voices.py の単語境界でも起きている)。
BS = chr(92)


def _choices_of(script: str) -> dict:
    """その台本の argparse が受け付ける値。{"--mode": {...}}"""
    path = ROOT / "scripts" / script
    if not path.exists():
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}
    out = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        ch = None
        for kw in node.keywords:
            if kw.arg == "choices" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                vals = [e.value for e in kw.value.elts
                        if isinstance(e, ast.Constant)]
                if vals:
                    ch = set(vals)
        if ch:
            for f in flags:
                if f.startswith("--"):
                    out[f] = ch
    return out


def check_shared_owned() -> int:
    """video_common が持っているものを、自前で持ち直していないか。

    なぜ要るのか（3回起きた）:
      ・wrap … 4本が自前で持っていて、禁則を入れたのは1本だけ
      ・font … 8本が自前で持っていて、キャッシュが付いたのは3本だけ
      ・build_narration_track … 5本が少しずつ違い、無音の埋めは1本だけ

      どれも「直したものが他へ届かない」という同じ形。
      片方を直しても、もう片方は古いまま公開され続ける。

      1か所に寄せても、次に誰かが書き足せば同じことが起きる。
      **寄せたことを検査で押さえる。**
    """
    print("\n--- 共通のものを自前で持ち直していないか ---")
    src = ROOT / "scripts" / "video_common.py"
    if not src.exists():
        print("[skip] video_common.py がありません")
        return 0
    owned = set(re.findall(r"^def (\w+)", src.read_text(encoding="utf-8"),
                           re.M))
    owned -= {"main"}
    bad = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        if p.name == "video_common.py":
            continue
        t = p.read_text(encoding="utf-8-sig", errors="replace")
        if "import video_common" not in t:
            continue                 # 使っていないファイルは対象外
        for name in sorted(owned):
            if re.search(r"^def " + name + re.escape("("), t, re.M):
                bad.append("%s: %s" % (p.name, name))
    if bad:
        print("NG  video_common にあるものを自前で持っています: %d件"
              % len(bad))
        for b in bad:
            print("      " + b)
        print("      片方だけ直すと、もう片方は古いまま公開されます")
        return 1
    print("ok  持ち直し 0件（video_common の %d個）" % len(owned))
    return 0


def check_render_coverage() -> int:
    """描く関数が、全部いちど試験を通っているか。

    なぜ要るのか:
      8/28に「7日間の合計」の画面を足したが、test_render.py へ
      足すのを忘れていた。8/29がその画面の初日で、その日は
      動画が1本も出ていない。原因かどうかは切り分けが要るが、
      **一度も描いたことのない画面を本番に出していた**のは確か。

      画面は動かさないと壊れが出ない種類のもので、
      それが test_render.py を置いた理由だった。
      足し忘れると、その理由ごと無効になる。
    """
    step("描く関数が試験を通っているか")
    src = ROOT / "scripts" / "generate_morning_short.py"
    test = ROOT / "scripts" / "test_render.py"
    if not (src.exists() and test.exists()):
        print("[info] 台本が見つからないため飛ばします")
        return 0
    body = test.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except SyntaxError:
        return 0
    missing = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("render_"):
            continue
        if node.name in body:
            continue
        missing.append(node.name)
    for m in missing:
        print(f"NG {m} が test_render.py で一度も呼ばれていません")
    print(f"{'ok ' if not missing else 'NG '} 試験の抜け {len(missing)}件")
    return len(missing)


def check_arg_choices() -> int:
    """
    ワークフローが渡す値を、台本が受け付けるか。

    なぜ要るのか:
      同じ壊れ方が2回起きている。

        1回目 upload_youtube.py の --morning-mode に press が無く、
              現地の声の動画が2日ぶん作られては捨てられていた
        2回目 generate_thumbnail.py の --mode に player と voices が無く、
              その2枠には最初からサムネイルが1枚も付いていなかった

      どちらも argparse が終了コード2で落ちるだけで、ループは
      set +e で回っているから次へ進む。投稿側は「サムネイル画像が
      無いためスキップします」と1行出して、そのまま公開する。
      回は緑、動画は出る、絵だけが無い。

    見るもの:
      run: の中の `python scripts/X.py ... --flag 値`。
      値が "$VAR" のときは、同じ run: の中の `for VAR in a b c` を
      探して、その候補それぞれを見る。
    """
    step("渡している値を台本が受け付けるか")
    try:
        import yaml
    except ImportError:
        print("[info] pyyaml が無いため飛ばします")
        return 0

    bad = 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        try:
            d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for job in (d.get("jobs") or {}).values():
            for st in (job.get("steps") or []):
                run = st.get("run")
                if not isinstance(run, str):
                    continue
                loops = {m.group(1): m.group(2).split()
                         for m in re.finditer(
                             r"for\s+(\w+)\s+in\s+\$\{[\w:+-]*?"
                             r"([\w ]+?)\}", run)}
                # 起動から、行末の \ で続く行までをひとまとまりで見る。
                #
                # 「行末の \ と改行」を先に試させる。逆にすると、
                # 改行でない何か([^\n])が先に \ を食い、次の改行で
                # 繰り返しが終わる。そこで正規表現としては成立して
                # しまうので後戻りが起きず、2行目以降を見ないまま
                # 「引数は \ だけ」という結果になる。
                cmd_re = ("python" + BS + "s+scripts/([" + BS + "w_]+"
                          + BS + ".py)((?:" + BS + BS + BS + "n|[^"
                          + BS + "n])*)")
                for m in re.finditer(cmd_re, run):
                    ch = _choices_of(m.group(1))
                    if not ch:
                        continue
                    arg_re = ("(--[" + BS + "w-]+)" + BS + 's+"?([^'
                              + BS + 's"' + BS + BS + ']+)"?')
                    for fm in re.finditer(arg_re, m.group(2)):
                        flag, val = fm.group(1), fm.group(2)
                        if flag not in ch:
                            continue
                        # ${{ }} はGitHubが実行時に埋めるので判定しない。
                        # workflow_dispatch の入力がここに入る。
                        if val.startswith("${{") or "${{" in fm.group(0):
                            continue
                        # "$mode" は for の候補に展開する。
                        # "${PRIVACY:-public}" は既定値のほうを見る。
                        # どちらでもない変数は、中身が分からないので触らない。
                        vals = [val]
                        dm = re.fullmatch(r"\$\{(\w+):-([^}]*)\}", val)
                        vm = re.fullmatch(r"\$\{?(\w+)\}?", val)
                        if dm:
                            vals = loops.get(dm.group(1)) or [dm.group(2)]
                        elif vm:
                            vals = loops.get(vm.group(1), [])
                        for v in vals:
                            if v not in ch[flag]:
                                bad += 1
                                print(f"NG {wf.name} / {st.get('name', '?')}: "
                                      f"{m.group(1)} {flag} に {v} を渡していますが、"
                                      f"受け付けるのは "
                                      f"{'、'.join(sorted(ch[flag]))} です")
    print(f"{'ok ' if not bad else 'NG '} 受け付けない値 {bad}件")
    return bad


def check_root_imports() -> int:
    """
    直下の自作モジュールを使う台本が、そこへの経路を足しているか。

    なぜ要るのか:
      notability_engine.py はリポジトリ直下にある。だが
      `python scripts/local_voices.py` で起動すると、Python が
      経路に入れるのは台本のある scripts/ だけで、直下は入らない。
      手元で `python -c` から呼ぶと、そちらは作業場所が経路に入るので
      通ってしまう。手元で通って本番で落ちる。

      実際に起きたこと:
        jp_mentioned() の中で notability_engine を取り込んでいた。
        関数の中なので、起動時には落ちない。翻訳が終わって、
        呼ばれた瞬間に ModuleNotFoundError で止まる。
        continue-on-error なので回は緑、ファイルは前日のまま。
        3日間「ファンのコメント欄」が出なかった。

      22本は経路を足していて、抜けていたのは3本だけだった。
      作法は決まっているのに、1本抜けるだけで枠が1つ止まる。

    見るもの:
      scripts/ の台本のうち、直下の .py を取り込むのに
      parent.parent を経路へ足していないもの。
    """
    step("直下のモジュールへの経路")
    roots = {f.stem for f in ROOT.glob("*.py")}
    bad = 0
    for f in sorted((ROOT / "scripts").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                used |= {a.name.split(".")[0] for a in node.names}
            elif (isinstance(node, ast.ImportFrom) and node.level == 0
                    and node.module):
                used.add(node.module.split(".")[0])
        need = used & roots
        if not need:
            continue
        if ("parent.parent" in src or "parents[1]" in src
                or "HERE.parent" in src):
            continue
        bad += 1
        print(f"NG {f.name}: {'、'.join(sorted(need))} を使うのに "
              f"sys.path へ直下を足していません")
    print(f"{'ok ' if not bad else 'NG '} 経路の抜け {bad}件")
    return bad


def check_deps_installed() -> int:
    """
    ワークフローが起動する台本の必要な物を、そのワークフローが入れているか。

    なぜ要るのか:
      「新しい材料が取れるか試す」は、最初の2本が urllib だけで
      書かれていたので pip install の段が無かった。そこへ requests を
      使う3本目を足したら、import の時点で落ちた。

      厄介なのは出方で、落ちたのが import なので実行前。
      要約に1行も出ず、artifact も前の2本ぶんだけ残る。
      「日本人選手のハイライトにコメントが付いていなかった」のか
      「そもそも動かなかった」のか、見た目で区別が付かない。
      材料が無いという結論を、間違って持ち帰るところだった。

    見るもの:
      run: が起動する台本が要る物のうち、その job のどこでも
      入れていないもの。requirements.txt を読む段があれば、
      そこに書いてあるものは入っているとみなす。
    """
    step("必要な物を入れ忘れていないか")
    try:
        import yaml
    except ImportError:
        print("[info] pyyaml が無いため飛ばします")
        return 0

    req = set()
    rp = ROOT / "scripts" / "requirements.txt"
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                req.add(re.split(r"[<>=\[]", line)[0].strip())

    # 配布名と取り込み名が違うもの
    ALIAS = {"pillow": "PIL", "google-api-python-client": "googleapiclient",
             "google-auth": "google", "pyyaml": "yaml",
             "beautifulsoup4": "bs4"}

    bad = 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        try:
            d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for job in (d.get("jobs") or {}).values():
            runs = [st.get("run") for st in (job.get("steps") or [])
                    if isinstance(st.get("run"), str)]
            body = chr(10).join(runs)
            have = set()
            for m in re.finditer(r"pip install\s+(.+)", body):
                arg = m.group(1)
                if "requirements.txt" in arg:
                    have |= req
                else:
                    have |= set(re.findall(r"[\w.-]+", arg))
            have |= {ALIAS[h] for h in have if h in ALIAS}
            for st in (job.get("steps") or []):
                run = st.get("run")
                if not isinstance(run, str):
                    continue
                for m in re.finditer(r"python\s+(?:-m\s+)?scripts/([\w_]+\.py)",
                                     run):
                    for n in sorted(_third_party(m.group(1))):
                        if n in have or n in {ALIAS.get(x, x) for x in have}:
                            continue
                        bad += 1
                        print(f"NG {wf.name} / {st.get('name', '?')}: "
                              f"{m.group(1)} が {n} を要るのに"
                              f"入れる段がありません")
    print(f"{'ok ' if not bad else 'NG '} 入れ忘れ {bad}件")
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
    failed += check_secrets_passed()
    failed += check_render_coverage()
    failed += check_shared_owned()
    failed += check_arg_choices()
    failed += check_root_imports()
    failed += check_deps_installed()
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
