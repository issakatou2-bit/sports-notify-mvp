#!/usr/bin/env python3
"""ポストシーズンの回が、勝敗と向きを取り違えないか。

なぜ要るのか:
  20:00の「進出争い」は、レギュラーシーズンが終わると出なくなる作り
  だった。その翌日からの短期決戦を、シリーズごとの勝敗で話すように
  した（9/28開始）。短期決戦で間違えると痛いのは3つ。

    1. 勝敗の向き。「2勝0敗」がどちらの話か
    2. 行わなかった「必要なら第5戦」を数える
    3. 日本人選手のいる球団が負けている日に、勝っている側から話す

材料は作り物で固定する。去年の実データでも確かめてある
（2025年の11シリーズがすべて公式の結果と一致）。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import backfill_records as br  # noqa: E402
import generate_morning_short as ms  # noqa: E402
import ps_series as ps  # noqa: E402
import race_words as rw  # noqa: E402
from checks_report import check, has, hasnt, section, done  # noqa: E402

LAD, PHI, CHC, MIL = 119, 143, 112, 158


def game(pk, gt, away, home, winner=None, n=1, of=5, day="2026-10-05"):
    fin = winner is not None
    return {"gamePk": pk, "gameType": gt, "gamesInSeries": of,
            "seriesGameNumber": n, "gameDate": day + "T22:00:00Z",
            "status": {"abstractGameState": "Final" if fin else "Preview"},
            "teams": {
                "away": {"team": {"id": away, "league": {"id": 104}},
                         "isWinner": fin and winner == away},
                "home": {"team": {"id": home, "league": {"id": 104}},
                         "isWinner": fin and winner == home}}}


NAMES = {LAD: "ドジャース", PHI: "フィリーズ", CHC: "カブス", MIL: "ブリュワーズ"}
JP = {LAD: ["大谷翔平", "山本由伸"], CHC: ["今永昇太", "鈴木誠也"]}

# 地区シリーズ（5回戦制）。ドジャース2勝0敗、カブス0勝2敗。
# 残り試合も日程には載っている。
DAY2 = [game(1, "D", PHI, LAD, LAD, 1), game(2, "D", PHI, LAD, LAD, 2),
        game(3, "D", LAD, PHI, None, 3, day="2026-10-08"),
        game(11, "D", CHC, MIL, MIL, 1), game(12, "D", CHC, MIL, MIL, 2),
        game(13, "D", MIL, CHC, None, 3, day="2026-10-08")]
DAY1 = DAY2[:1] + DAY2[3:4]


def by(series, a):
    return next(s for s in series if a in [t["id"] for t in s["teams"]])


section("勝敗は、終わった試合の勝者を数える")
now = ps.build(DAY2, NAMES, JP)
dodgers = by(now, LAD)
check("5回戦制は3勝で勝ち抜け", dodgers["need"], 3)
check("ドジャース2勝", [(t["name"], t["wins"]) for t in dodgers["teams"]],
      [("ドジャース", 2), ("フィリーズ", 0)])
check("まだ終わっていない", dodgers["over"], False)
check("次の試合", dodgers["next"], {"day": "10月9日", "game": 3})
check("同じ試合が2度載っても数えない",
      by(ps.build(DAY2 + DAY2[:1], NAMES, JP), LAD)["teams"][0]["wins"], 2)

# 3連勝で決着。行わない第4・5戦も日程に載っている。
SWEEP = DAY2[:2] + [game(3, "D", LAD, PHI, LAD, 3),
                    game(4, "D", LAD, PHI, None, 4),
                    game(5, "D", PHI, LAD, None, 5)]
swept = by(ps.build(SWEEP, NAMES, JP), LAD)
check("行わない試合は数えない", swept["played"], 3)
check("決着", (swept["over"], swept["winner"]), (True, LAD))
check("決着したら次の試合は無い", swept["next"], None)

section("言い方の向き")
check("勝っている側から", ps.text(dodgers),
      "地区シリーズ ドジャースが2勝0敗とし、突破に王手")
check("見出しで回戦を言った画面では省く", ps.text(dodgers, with_round=False),
      "ドジャースが2勝0敗とし、突破に王手")
check("決着", ps.text(swept),
      "ドジャースが3勝0敗でフィリーズを破り、リーグ優勝決定シリーズへ")
cubs = by(now, CHC)
check("日本人選手の側から。負けているなら負けている数字で",
      ps.jp_text(cubs),
      "今永昇太・鈴木誠也のカブスは地区シリーズでブリュワーズに0勝2敗、負ければ敗退")
has("勝っている日本人選手の球団は王手", ps.jp_text(dodgers), "2勝0敗、突破に王手")
lost = by(ps.build(DAY2[3:5] + [game(13, "D", MIL, CHC, MIL, 3)], NAMES, JP),
          CHC)
check("敗退", ps.jp_text(lost),
      "今永昇太・鈴木誠也のカブスは地区シリーズでブリュワーズに0勝3敗で敗れ、敗退")
ws = ps.build([game(21, "W", LAD, 141, LAD, 1, of=7)], NAMES, JP)[0]
check("ワールドシリーズはリーグを付けない", ws["league_jp"], "")

section("昨日から動いたもの")
moved = ps.changes(now, ps.build(DAY1, NAMES, JP))
check("2つ動いた", len(moved), 2)
check("日本人選手のいるシリーズはその球団の側から",
      [c["text"] for c in moved if "カブス" in c["text"]][0].startswith(
          "今永昇太・鈴木誠也のカブス"), True)
check("動いていなければ何も出さない", ps.changes(now, now), [])
check("初めて見るシリーズは開幕", ps.changes(now, [])[0]["kind"], "start")
check("決着は先頭", ps.changes(ps.build(SWEEP, NAMES, JP), now)[0]["kind"],
      "advance")

section("話すことがあるか・呼び名")
check("PS中は動いた日だけ話す",
      rw.race_is_over({"phase": "postseason", "changes": []}), True)
check("動いた日は話す",
      rw.race_is_over({"phase": "postseason", "changes": moved}), False)
check("PS中の呼び名", rw.ps_label({"phase": "postseason"}), "ポストシーズン")
check("レギュラーシーズンの呼び名", rw.ps_label({}), "ポストシーズン進出争い")
check("台帳はPS中の題も見分ける",
      br.kind_of("【MLB】X｜10月8日 ポストシーズン #Shorts"), "morning_postseason")
check("台帳は進出争いの題も見分ける",
      br.kind_of("【MLB】X｜9月23日 ポストシーズン進出争い #Shorts"),
      "morning_postseason")
check("PSの始まり", ps.in_postseason({"start": "2026-09-28"},
                                     ps.date(2026, 9, 28)), True)
check("始まる前", ps.in_postseason({"start": "2026-09-28"},
                                   ps.date(2026, 9, 27)), False)
check("日付が無ければ始まっていない", ps.in_postseason({}), False)

section("20:00の回の本編")
data = {"phase": "postseason", "series": now, "changes": moved}
segs = ms.ps_series_segments(data)
check("1枚目は日本人選手のいるシリーズ", segs[0]["meta"]["head"],
      "日本人選手のいるシリーズ")
check("同じシリーズを2度読まない（全部が日本人選手のシリーズの日）",
      len(segs), 1)
im = ms.render_ps_series(0.5, data, segs[0]["meta"]["keys"],
                         segs[0]["meta"]["head"])
check("画面が描ける", im.size, (1080, 1920))
# 決着して翌日になったシリーズは、もう並べない
old = {"phase": "postseason", "series": ps.build(SWEEP, NAMES, JP),
       "changes": []}
hasnt("昨日より前に決着したシリーズは並べない",
      " ".join(s["text"] for s in ms.ps_series_segments(old)), "フィリーズ")

sys.exit(done())
