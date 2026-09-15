#!/usr/bin/env python3
"""何もない期間に、空の動画が出ないか。

なぜ検査が要るのか:
  ユーザーの指摘（9/15）:「シーズン終了時や、PS終了時、またその後
  なにも問題ないか確認してください。何もない期間もからの動画が出ると
  行った不具合は怖いので。」

  確かめたら、**実際に2つ出た。**

    1. ポストシーズンが終わっても、進出争いの回は画面を8枚作った。
       決着した順位表がそのまま残るので、「レイズ 進出決定」と
       言うだけの動画が11月から3月まで毎日出る形だった。
    2. 長編（数字の回）は材料の日付を見ていなかった。更新が止まった
       morning_recap.json を「きょうの成績」として読み続ける。

  どちらも**材料は正しい。古いだけ。**中身の検算では捕まらない。

  もう1つ、逆向きの不具合も直した。サッカーの順位争いは出した節を
  大会コードだけで覚えていたので、来季の第1節が「もう出した」ことに
  なってシーズンが丸ごと飛ぶところだった。
"""

import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numbers_material as nm  # noqa: E402
import race_words as rw  # noqa: E402
import soccer_race as sr  # noqa: E402

DATA = HERE.parent / "data"
fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


print("--- ポストシーズンが終わったあと ---")
_over = {"changes": [],
         "teams": {"1": {"clinched": True}, "2": {"wc_gb": "E"},
                   "3": {"eliminated": True}}}
check("全球団の行き先が決まっていれば終わり", rw.race_is_over(_over), True)
check("材料そのものが無い日も終わり扱い", rw.race_is_over({}), True)
check("まだ決まっていない球団があれば続いている",
      rw.race_is_over({"changes": [],
                       "teams": {"1": {"clinched": True},
                                 "2": {"magic": 3}}}), False)
check("昨日から動いていれば続いている",
      rw.race_is_over({"changes": [{"text": "マジックが3から2へ"}],
                       "teams": {"1": {"clinched": True}}}), False)

print()
print("--- 実データは、まだ争っている ---")
_real = json.loads((DATA / "postseason.json").read_text(encoding="utf-8"))
check("9月のいまは終わっていない", rw.race_is_over(_real), False)

print()
print("--- 長編は、古い材料で作らない ---")
_today = date.today()


def _stamp(days_ago: int) -> dict:
    return {"date_jst": (_today - timedelta(days=days_ago)).isoformat()}


check("きょうの材料は使う", nm.fresh(_stamp(0), _today), True)
check("昨日の材料も使う（枠が日をまたぐことがある）",
      nm.fresh(_stamp(1), _today), True)
check("一昨日までは使う", nm.fresh(_stamp(2), _today), True)
check("3日前は使わない", nm.fresh(_stamp(3), _today), False)
check("2か月前は使わない", nm.fresh(_stamp(60), _today), False)
check("日付が読めないものは使わない",
      nm.fresh({"date_jst": "こわれている"}, _today), False)
check("日付が無いものは使わない", nm.fresh({"players": [1, 2]}, _today), False)
# **未来の日付も使わない。**時計がずれた材料を新しいと読むと、
# 止まった材料を一生使い続けることになる。
check("未来の日付は使わない", nm.fresh(_stamp(-5), _today), False)

print()
print("--- シーズンが終われば、長編も止まる ---")
_after = nm.load(str(DATA), today=_today + timedelta(days=90))
check("3か月後は選手がいない", _after["players"], [])
check("3か月後は進出争いも無い", _after["race"]["changes"], [])
check("3か月後は作らない", nm.has_enough(_after), False)
_now = nm.load(str(DATA), today=_today)
check("いまは作れる", nm.has_enough(_now), True)

print()
print("--- サッカーの季 ---")
_comp = {"code": "PL", "season": {"year": 2026, "end": "2027-05-30"}}
check("覚える鍵に季が入る", sr.state_key(_comp), "PL:2026")
check("季が取れなければ大会コードのまま",
      sr.state_key({"code": "PL"}), "PL")
check("季の途中は終わっていない",
      sr.season_over(_comp, date(2027, 3, 1)), False)
check("最終日は終わっていない",
      sr.season_over(_comp, date(2027, 5, 30)), False)
check("翌日から終わり", sr.season_over(_comp, date(2027, 5, 31)), True)
check("夏は終わっている", sr.season_over(_comp, date(2027, 7, 15)), True)
check("終わりの日が無ければ、終わっていないものとして扱う",
      sr.season_over({"code": "CL"}), False)

print()
print("--- 来季の第1節が飛ばないか ---")
# 今季38節まで出したあと。**鍵が大会コードだけだと、来季の1節が
# 「もう出した」ことになってシーズンが丸ごと飛ぶ。**
_next = {"competitions": [{
    "code": "PL", "season": {"year": 2027, "end": "2028-05-28"},
    "name_jp": "プレミアリーグ",
    "table": [{"position": i, "played": 6, "points": 10,
               "name": "Club %d" % i} for i in range(1, 21)]}]}
check("今季の記録は来季をふさがない",
      [d["round"] for d in sr.due(_next, {"PL:2026": 38})], [6])
check("同じ季の同じ節は二度出さない",
      sr.due(_next, {"PL:2027": 6}), [])
check("季が終わっていれば出さない",
      sr.due({"competitions": [dict(_next["competitions"][0],
                                    season={"year": 2027,
                                            "end": "2020-01-01"})]}, {}), [])

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
