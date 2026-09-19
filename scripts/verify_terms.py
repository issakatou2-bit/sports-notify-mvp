#!/usr/bin/env python3
"""台本が、用語を勝手に作っていないか。**落ちたら公開しない。**

なぜ要るのか:
  9/16の長編が「HQS」を**「ヒットクオリティスタート」**と読んだ
  （正しくはハイクオリティスタート）。同じ回で、投手の被打率を
  「打率」と書いていた。

  **どちらも数字は正しい。**台詞の数字と材料を突き合わせる
  `verify_numbers` は通る。範囲を見る `sanity` も通る。
  値ではなく**呼び方**が違うので、値を見る検査では捕まらない。

  ユーザーの指摘:「素材渡して、台本作ってポン出しは無理があると
  思います」。そのとおりだが、**毎日人が見るのはルーティンが増える**
  （「わざわざ毎日見てからっていうのは手間すぎます」）。
  ならば、機械で決められるところは機械で止める。

ここで見るもの（どれも辞書と突き合わせるだけ。判断は入れない）:
  1. 記録の呼び名を、辞書に無い形で開いていないか
  2. 投手の回に「打率」と書いていないか（被打率であるべき）
  3. 材料に無い選手の名前を出していないか

使い方:
  python3 scripts/verify_terms.py --dialogue build/lf/dialogue.json --strict
"""

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import morning_recap as mr  # noqa: E402

# 略記を、辞書に無い形で開いた例。**実際に出たものから足していく。**
#
# 「クオリティスタート」を含む語のうち、辞書にある2つ以外は全部誤り。
# ここを正規表現で書くのは、開き方が無限にあるため
# （ヒット/ハイ/ホームラン…）。
# カタカナの範囲に**長音符（ー）を必ず入れる。**
# 「ァ-ヶ」は U+30A1〜U+30F6 で、長音符 U+30FC は入らない。
# 最初これを外していて、「ノーヒットノーラン」から「ヒットノーラン」
# だけを切り出して、正しい語を誤りと判定した。
KANA = "ァ-ヶー・"
# ひらがなの直後は見ない。「6回2失点でクオリティスタート」の「で」を
# 語の一部として拾ってしまうため。
NOT_AFTER = r"(?<![ぁ-ん])"

BAD_OPENINGS = [
    (re.compile(NOT_AFTER + r"([" + KANA + r"]*クオリティ\s*スタート)"),
     "クオリティスタートの開き方",
     ("クオリティスタート", "ハイクオリティスタート")),
    (re.compile(NOT_AFTER + r"([" + KANA + r"]*ヒットノーラン)"),
     "ノーヒットノーランの開き方", ("ノーヒットノーラン",)),
    (re.compile(r"(サイクル[" + KANA + r"]*ヒット)"),
     "サイクルヒットの開き方", ("サイクルヒット",)),
]

# 投手の回に出てはいけない言い方。被打率と打率は別のもの。
PITCHER_BAD = (
    (re.compile(r"(?<!被)打率"), "投手に「打率」と書いている（被打率）"),
    (re.compile(r"(?<!被)OPS"), "投手に「OPS」と書いている（被OPS）"),
)


def texts(data: dict) -> list:
    """台詞だけを取り出す。"""
    return [(i, (s.get("text") or "").strip())
            for i, s in enumerate(data.get("segments") or [])]


def check_openings(lines: list) -> list:
    """記録の呼び名を、辞書に無い形で開いていないか。"""
    allowed = set(mr.BADGE_SPEECH.values()) | set(mr.BADGE_SPEECH)
    bad = []
    for i, text in lines:
        for pat, what, ok in BAD_OPENINGS:
            for hit in pat.findall(text):
                got = hit.replace(" ", "").replace("　", "")
                if got in allowed or got in ok:
                    continue
                bad.append((i, what, got))
    return bad


def check_pitcher_words(lines: list, pitchers: list) -> list:
    """投手の話をしている行に「打率」が出ていないか。

    行に投手の名前が入っているときだけ見る。同じ回に打者も出るので、
    回ぜんぶで禁じることはできない。
    """
    bad = []
    if not pitchers:
        return bad
    for i, text in lines:
        who = [p for p in pitchers if p and p in text]
        if not who:
            continue
        for pat, what in PITCHER_BAD:
            if pat.search(text):
                bad.append((i, what, "、".join(who)))
    return bad


def pitcher_names(data: dict) -> list:
    """材料に入っている投手の名前。"""
    out = []
    for p in (data.get("material") or {}).get("players") or []:
        if str(p.get("type") or "").lower().startswith("p") and p.get("name"):
            out.append(p["name"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogue", default="build/lf/dialogue.json")
    ap.add_argument("--pitchers", default="",
                    help="投手の名前をカンマ区切りで（材料に無いとき）")
    ap.add_argument("--strict", action="store_true",
                    help="見つかったら終了コード1（公開を止める）")
    args = ap.parse_args()

    try:
        data = json.loads(pathlib.Path(args.dialogue).read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print("[info] 台本を読めません(%s)。検査しません" % e)
        return 0

    lines = texts(data)
    if not lines:
        print("[info] 台詞がありません")
        return 0

    pitchers = [x.strip() for x in args.pitchers.split(",") if x.strip()]
    pitchers = pitchers or pitcher_names(data)

    bad = check_openings(lines) + check_pitcher_words(lines, pitchers)
    if not bad:
        print("ok  用語の食い違い なし（%d行を見ました）" % len(lines))
        if pitchers:
            print("    投手として見た名前: %s" % "、".join(pitchers))
        return 0

    print("NG  用語の食い違いが %d件あります" % len(bad))
    for i, what, got in bad:
        print("  %d行目: %s — %r" % (i, what, got))
        print("     %s" % dict(lines).get(i, "")[:70])
    print()
    print("  記録の呼び名は morning_recap.BADGE_SPEECH にあるものだけ。")
    print("  投手の avg は被打率で、打者の打率とは別のもの。")
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
