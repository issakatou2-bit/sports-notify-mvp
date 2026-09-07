#!/usr/bin/env python3
"""「◯日ぶりの出場なるか」の数え方を見る。

なぜ検査が要るのか:
  ここは**外すと嘘になる**。「5日ぶり」と書いた翌日にその選手が
  出ていたら、前の日の題が間違っていたことになる。数え方と、
  触れない範囲(投手・長期離脱)を固定しておく。
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import jp_absence  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def build(folder, days):
    """{日付: [(名前, 種別), ...]} から、日次記録を書き出す。"""
    for day, rows in days.items():
        (folder / (day + ".json")).write_text(json.dumps(
            {"date_jst": day,
             "players": [{"name": n, "type": t, "player_id": "1"}
                         for n, t in rows]}, ensure_ascii=False),
            encoding="utf-8")


with tempfile.TemporaryDirectory() as tmp:
    f = pathlib.Path(tmp)
    build(f, {
        "2026-08-20": [("吉田正尚", "batter")],          # 19日前。長すぎる
        "2026-09-01": [("大谷翔平", "batter")],          # 7日前
        "2026-09-03": [("佐々木朗希", "pitcher")],       # 投手は見ない
        "2026-09-05": [("村上宗隆", "batter")],          # 3日前
        "2026-09-07": [("鈴木誠也", "batter")],          # 1日前。休養の範囲
    })
    got = jp_absence.gaps("2026-09-08", str(f))

    check("大谷は7日ぶり", got.get("大谷翔平", {}).get("gap"), 7)
    check("村上は3日ぶり（下限ちょうど）", got.get("村上宗隆", {}).get("gap"), 3)
    check("1日空いただけの選手は入れない", "鈴木誠也" in got, False)
    check("19日空いた選手は入れない（故障者リスト）", "吉田正尚" in got, False)
    check("投手は入れない（中5日があるため）", "佐々木朗希" in got, False)

    # 同じ試合に2人いる日は、空きが長いほうを採る。
    h = jp_absence.hook_for(["村上宗隆", "大谷翔平"], "2026-09-08", str(f))
    check("長く空いているほうを選ぶ", h.get("name"), "大谷翔平")
    check("言い回し", h.get("text"), "7日ぶりの出場なるか")

    check("誰も当てはまらない日は何も返さない",
          jp_absence.hook_for(["鈴木誠也"], "2026-09-08", str(f)), {})
    check("名前が空でも落ちない",
          jp_absence.hook_for([], "2026-09-08", str(f)), {})
    check("日付が読めなくても落ちない",
          jp_absence.hook_for(["大谷翔平"], "きのう", str(f)), {})

# 記録が1つも無い環境でも落ちない（新しい手元にコピーした直後など）。
with tempfile.TemporaryDirectory() as tmp:
    check("記録が無くても落ちない",
          jp_absence.gaps("2026-09-08", tmp), {})

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
