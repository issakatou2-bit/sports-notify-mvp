#!/usr/bin/env python3
"""台詞に出た数字が、渡した材料と一致するか。

なぜ要るのか:
  9/8の長編は「カブスは20本以上が5人」で公開の直前まで行った。
  正しくは4人。移籍した選手の成績を二重に数えていたためだった。

  **値の大小では捕まらない。**56本も176打点も、シーズンの数字と
  してはありえる範囲なので、検算(`sanity.py`)は通ってしまう。
  二段目のAIはむしろ**正しいほう**(41本)を「不自然です」と指摘して、
  間違った22本を素通りさせた。**言語模型に数字を照合させない。**

  読み方を1か所に寄せ(`mlb_splits`)、寄せ忘れを検査で見て
  (`run_checks`)、そのうえで**出す直前に、言ったことと材料を
  突き合わせる。**ここが最後の一枚になる。

  新しくAPIは叩かない。台本(`dialogue.json`)の `facts` に、
  渡した数字がそのまま入っている。読むだけ。費用は0。

何を見るか:
  「Ben Riceが36本」のように、**名前と数字が同じ文にある**ところ。
  材料に載っていない選手や、名前の無い数字は見ない。
  照合できないものを疑うと、正しい日に出せなくなる。

使い方:
  python3 scripts/verify_numbers.py --dialogue build/lf/dialogue.json
  python3 scripts/verify_numbers.py --dialogue ... --strict   # 異常終了
"""

import argparse
import json
import pathlib
import re
import sys

# 見る単位。台本の `facts` に入っている名前と同じにする。
#
# **長いものから先に見る必要はない。**「5被安打」に対して
# 「安打」のパターンは数字の直後を要求するので、間に「被」が
# 入るとマッチしない。奪三振と三振、打点と点も同じ。
UNITS = ("本", "打点", "勝", "奪三振", "打数", "安打", "被安打",
         "二塁打", "三塁打", "四球", "盗塁", "自責", "回",
         "セーブ", "ホールド", "本塁打")

# 名前と数字が、どれだけ離れていても同じ話と見なすか。
#
# 「Pete Crow-Armstrongが41本、Bregmanが24本」のように、1つの文に
# 何人も並ぶ。間を広く取ると、隣の選手の数字を拾って誤って止める。
# 句読点をまたがない範囲だけを見る。
NEAR = 12

# この語が同じ文にあるときは見ない。
#
# 材料は**今季の数字**しか持っていない。通算や去年の話、
# 「あと3本で30本」のような目標の数字を今季の値と突き合わせると、
# 正しい台詞を止めることになる。
#
# 止める側が間違っていると、正しい日に何も出ない。
# 検算(sanity)はそれを4回やっている。ここでは繰り返さない。
SKIP_WORDS = ("通算", "キャリア", "昨季", "去年", "昨年", "来季", "一昨年",
              "あと", "まで", "目標", "ペース", "記録は", "歴代",
              "自己最多", "自己最高", "球団記録", "月間", "先月",
              # 成績の回の「ここ7日」「直近3試合」は、その日の
              # 成績とは別の材料。合計なので必ず食い違う。
              "ここ7日", "直近", "この7日", "7日間")


def load(path: str) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[info] 台本を読めません: {e}")
        return {}


def check(d: dict) -> list:
    """食い違いの一覧。空なら問題なし。"""
    facts = d.get("facts") or {}
    if not facts:
        return []
    bad = []
    for seg in (d.get("segments") or []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if any(w in text for w in SKIP_WORDS):
            continue                 # 今季の材料と突き合わせられない文
        for name, stats in facts.items():
            if name not in text:
                continue
            for unit in UNITS:
                want = stats.get(unit)
                if want is None:
                    continue
                # 読点は越える（「4位、鈴木誠也、5打数1安打」）。
                # 句点は越えない。文をまたぐと隣の選手の数字を拾う。
                # 投球回は小数で出る（1.0回、0.2回）。
                pat = (re.escape(name) + "[^。]{0,%d}?([0-9]+(?:[.][0-9]+)?)"
                       % NEAR + re.escape(unit))
                for m in re.finditer(pat, text):
                    got = float(m.group(1))
                    if abs(got - float(want)) > 1e-9:
                        bad.append(
                            "%s: 「%s」と言っていますが、材料は%s%s です"
                            % (name, m.group(0)[:40], want, unit))
                        break        # 同じ単位で何度も言わない
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogue", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="食い違いがあれば異常終了する")
    args = ap.parse_args()

    d = load(args.dialogue)
    if not d:
        return 0                     # 読めない日は判定しない
    facts = d.get("facts") or {}
    bad = check(d)

    print("--- 言ったことと、渡した材料 ---")
    if not facts:
        print("  材料が添えられていません（古い台本）。見ません")
        return 0
    if not bad:
        print("  食い違い なし（%d人ぶんの数字を照合）" % len(facts))
        return 0
    for b in bad:
        print("  NG " + b)
    print("  **数字が材料と違います。**読み方か組み立てのどちらかです")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
