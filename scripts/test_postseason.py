#!/usr/bin/env python3
"""
ポストシーズンの扱いを確かめる。

なぜ要るのか:
  9/28から10月末まで、試合数が1日1〜4に減る。ワールドシリーズは
  1日1試合しか無い。それまでの採点は順位争いと連勝記録でできていて、
  どちらも10月には発火しない。そのままだと全試合が0点になり、
  その日は動画が1本も出ない。

  レギュラーシーズン中は1日15試合あって必ず3試合が閾値を超えるので、
  この穴は9月末まで表に出てこない。だから今のうちに見張っておく。

使い方:
  python3 scripts/test_postseason.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import (  # noqa: E402
    MLB_MIN_NOTABLE,
    POSTSEASON_WEIGHT,
    Game,
    rule_postseason,
    score_game,
)

fails = 0


def check(label, got, want):
    global fails
    if got != want:
        fails += 1
    print(f"{'ok' if got == want else 'NG'}  {label}: {got}")


def make(gt, gn=None, gl=None, w=None, ll=None):
    return Game(game_id="", league="MLB", home_team_id="119",
                away_team_id="147", home_team_name="ドジャース",
                away_team_name="ヤンキース", game_type=gt,
                series_game=gn, series_length=gl,
                series_wins=w, series_losses=ll)


def main() -> int:
    print("--- 段ごとの重み ---")
    for gt in ("F", "D", "L", "W"):
        r = rule_postseason(make(gt))
        check(f"{gt} が閾値(3)を超える", score_game(r) >= 3, True)
    check("レギュラーでは何も返さない", rule_postseason(make("R")), [])
    check("ワールドシリーズがいちばん重い",
          max(POSTSEASON_WEIGHT, key=POSTSEASON_WEIGHT.get), "W")

    print("\n--- 王手の判定 ---")
    # 5戦制の第3戦。2勝0敗なら王手、1勝1敗ならまだ何も決まっていない。
    t1 = rule_postseason(make("D", 3, 5, 2, 0))[0].text
    t2 = rule_postseason(make("D", 3, 5, 1, 1))[0].text
    check("2勝0敗は王手と書く", "王手" in t1, True)
    check("1勝1敗は王手と書かない", "王手" in t2, False)
    t3 = rule_postseason(make("W", 7, 7, 3, 3))[0].text
    check("第7戦の3勝3敗は「勝った方が突破」", "勝った方が突破" in t3, True)
    # 勝敗が取れない日は、推測で書かない
    t4 = rule_postseason(make("W", 6, 7))[0].text
    check("勝敗が無ければ王手と書かない", "王手" in t4, False)

    print("\n--- 試合が少ない日 ---")
    check("MLBの下限が1本以上", MLB_MIN_NOTABLE >= 1, True)

    print("\nALL OK" if not fails else f"\n{fails} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
