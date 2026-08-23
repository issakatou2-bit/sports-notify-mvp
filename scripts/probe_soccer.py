#!/usr/bin/env python3
"""
サッカーの試合から、どこまで中身が取れるかを確かめる。

なぜ要るのか:
  MLBの枠(今日の日本人選手・貢献スコア・今日の1人)をサッカーへ
  広げられるかは、football-data.org の無料枠が何を返すかで決まる。

    得点者が取れる     -> 「今日のゴール」が作れる
    出場記録が取れる   -> 「今日の日本人選手」が作れる
    出場時間が取れる   -> 貢献スコアの物差しになる

  取れないなら、別のデータ元を探すところから始まる。
  想像で構想を書いても、作り始めてから覆る。

  手元からは鍵が無くて403になるので、ランナーで動かす。

使い方:
  FOOTBALL_DATA_API_KEY=... python3 scripts/probe_soccer.py
"""

import json
import os
import sys
import urllib.request

BASE = "https://api.football-data.org/v4"

# 欲しいものと、それで何が作れるか
WANT = [
    ("得点者", "goals", "今日のゴール(MLBの「今日の1人」に当たる枠)"),
    ("交代", "substitutions", "出場時間の手がかり"),
    ("先発", "lineup", "今日の日本人選手"),
    ("ベンチ", "bench", "出場したかの判定"),
    ("警告", "bookings", "荒れた試合の指標"),
    ("スタッツ", "statistics", "貢献スコアの物差し"),
]

# 無料枠で使えるリーグ。ここが空なら、そもそも取りに行けない。
COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1"]


def fetch(path: str, key: str):
    req = urllib.request.Request(
        BASE + path,
        headers={"X-Auth-Token": key, "User-Agent": "collespo/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def summary(text: str) -> None:
    s = os.environ.get("GITHUB_STEP_SUMMARY")
    if not s:
        return
    with open(s, "a", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        print("FOOTBALL_DATA_API_KEY がありません")
        summary("\n## サッカーの材料\n\n- 鍵が渡っていません\n")
        return 0

    lines = ["\n## サッカーの材料(football-data.org 無料枠)\n\n",
             "MLBと同じ枠をサッカーへ広げられるかは、ここで決まる。\n\n"]
    found = None
    for code in COMPETITIONS:
        try:
            d = fetch(f"/competitions/{code}/matches"
                      "?status=FINISHED&limit=1", key)
        except Exception as e:                       # noqa: BLE001
            print(f"  {code}: 取れません {type(e).__name__} {str(e)[:90]}")
            continue
        ms = d.get("matches") or []
        if ms:
            found = (code, ms[-1])
            break

    if not found:
        print("終了した試合が1つも返りませんでした")
        lines.append("- 終了した試合が返りませんでした\n")
        summary("".join(lines))
        return 0

    code, m = found
    print(f"[{code}] 返った項目: {sorted(m)}")
    lines.append(f"対象: {code} の直近の終了済み1試合\n\n")
    lines.append("|欲しいもの|項目|返ったか|それで何が作れるか|\n")
    lines.append("|---|---|--:|---|\n")
    for label, field, makes in WANT:
        got = m.get(field)
        if isinstance(got, list):
            n = f"{len(got)}件"
        elif isinstance(got, dict):
            n = f"{len(got)}項目"
        elif got:
            n = "あり"
        else:
            n = "なし"
        print(f"  {label:8s} {field:14s} -> {n}")
        lines.append(f"|{label}|`{field}`|{n}|{makes}|\n")

    lines.append(f"\n返った項目: `{'`, `'.join(sorted(m))}`\n")

    # 判定を書く。表を見て考えるのは読む側の仕事ではない。
    can_goal = bool(m.get("goals"))
    can_lineup = bool(m.get("lineup") or m.get("bench"))
    lines.append("\n### 判定\n\n")
    lines.append(f"- 「今日のゴール」: {'作れる' if can_goal else '作れない'}\n")
    lines.append(f"- 「今日の日本人選手」: "
                 f"{'作れる' if can_lineup else '作れない'}\n")
    if not (can_goal or can_lineup):
        lines.append("- 無料枠は日程と結果までのようです。"
                     "選手単位の枠を作るなら、別のデータ元が要ります\n")
    summary("".join(lines))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
