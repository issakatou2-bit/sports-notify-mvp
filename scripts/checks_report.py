#!/usr/bin/env python3
"""検査の結果の出し方を1か所に。**通ったものは黙る。**

なぜ要るのか:
  検査45本の出力を合わせると83KBあった。その大半は「ok」の行で、
  しかも比べた値を丸ごと写していた。長編の材料は1件で4千字あり、
  それを含む検査が2つあるだけで1万字近くになる。

  この出力は3か所に流れる。

    1. CIの実行ページ（毎回のpushで）
    2. 手元で走らせたときの画面
    3. **失敗を調べるときに読む側**（人でも、私でも）

  3が一番高くつく。9/22に長編が落ちたとき、原因を知るために
  実行ログのzipを落として展開して検索した。最後の1行だけでは
  「ok ties>1 は出さない: []」としか出ておらず、
  **例外で死んだこと自体が見えなかった**。

  検査の力は1つも落とさない。同じことを同じだけ調べて、
  **落ちたものだけ**を出す。値は先頭160字で切る。
  それより長い値は、全文があってもどこが違うかは分からない。

使い方:
    from checks_report import check, has, hasnt, section, done

    section("投手と打者を取り違えない")
    check("pitcher は投手", is_pitcher({"type": "pitcher"}), True)
    ...
    sys.exit(done())
"""

LIMIT = 160          # 値を写す長さ。これより長ければ切る

_ok = 0
_ng = 0
_section = None      # まだ出していない見出し


def _short(v) -> str:
    """値を短く。**長い値を全文出しても、どこが違うかは分からない。**"""
    s = repr(v)
    if len(s) <= LIMIT:
        return s
    return s[:LIMIT] + "…（全%d字）" % len(s)


def section(name: str) -> None:
    """区画の名前。**落ちたときだけ出す。**

    通った検査の見出しは読む人に何も伝えない。落ちた行の上に
    出れば「どのあたりの話か」が分かる。
    """
    global _section
    _section = name


def _fail(line: str) -> None:
    global _ng, _section
    _ng += 1
    if _section:
        print("--- %s ---" % _section)
        _section = None
    print(line)


def check(label, got, want) -> bool:
    """等しいか。"""
    global _ok
    if got == want:
        _ok += 1
        return True
    _fail("NG %s: %s   (期待 %s)" % (label, _short(got), _short(want)))
    return False


def has(label, got, part) -> bool:
    """含むか。"""
    global _ok
    if part in (got or ""):
        _ok += 1
        return True
    _fail("NG %s: %s を含むはず / %s" % (label, _short(part), _short(got)))
    return False


def hasnt(label, got, part) -> bool:
    """含まないか。"""
    global _ok
    if part not in (got or ""):
        _ok += 1
        return True
    _fail("NG %s: %s を含んではいけない / %s"
          % (label, _short(part), _short(got)))
    return False


def near(label, got, want, tol=0.001) -> bool:
    """近いか。小数の指標（打率・率の類）で使う。"""
    global _ok
    if got is not None and abs(got - want) <= tol:
        _ok += 1
        return True
    _fail("NG %s: %s   (期待 %s±%s)" % (label, _short(got), _short(want), tol))
    return False


def passed() -> None:
    """自前で判定して通ったとき。数えるだけで何も出さない。

    近さを見る `near` のように、この3つの形に収まらない判定が
    各所にある。そこから呼べるようにしておく。
    """
    global _ok
    _ok += 1


def fail(line: str) -> None:
    """自前で判定して落ちたとき。"""
    _fail("NG " + line)


def note(text: str) -> None:
    """検査ではない一言。材料が無くて飛ばしたときなどに。"""
    print("（%s）" % text)


def failures() -> int:
    return _ng


def done() -> int:
    """締めの1行を出して、終了コードを返す。

    run_checks は**最後の1行**を一覧に並べるので、ここが要約になる。
    """
    if _ng:
        print("%d件失敗 / %d件中" % (_ng, _ok + _ng))
        return 1
    print("%d件すべて通過" % _ok)
    return 0
