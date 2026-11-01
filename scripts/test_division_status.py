#!/usr/bin/env python3
"""地区の争いが終わっているのに「直接争う」と書かないか。

なぜ要るのか:
  9/22、地区優勝を決めたドジャースと2位パドレスの対戦を、Webの
  「明日の注目試合」で「地区順位を直接争う」「9ゲーム差を巡る」と書いた。
  同じ地区というだけで「順位を直接争う関係にある」とAIへ渡していた。
  **差の9.0は正しい数字だった**ので、数字の照合では止まらない。

  MLBの順位表は divisionChamp / clinched / eliminationNumber を返して
  いたのに、読み込んでいなかった。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import notability_engine as ne  # noqa: E402
from checks_report import check, has, hasnt, section, done  # noqa: E402

GAME = {"home_team_id": "119", "away_team_id": "135",
        "home_team_name": "ドジャース", "away_team_name": "パドレス"}
DIV = "ナ・リーグ西地区"


def st(tid, rank, gb, **kw):
    return ne.Standing(team_id=tid, division_rank=rank, games_back=gb,
                       win_streak=0, wins=90, losses=66, **kw)


# 9/22の実際の形（APIの返り値をそのまま置いた）
LAD = st("119", 1, 0.0, division_champ=True, clinched=True)
SD = st("135", 2, 9.0, division_out=True)

section("決まったことの言い方")
check("地区優勝", ne.standing_status(LAD), "地区優勝を決めている")
has("地区は消えたがワイルドカードは続く", ne.standing_status(SD),
    "ワイルドカードの争いは続く")
check("進出だけ決めた・地区はまだ生きている",
      ne.standing_status(st("1", 2, 3.0, clinched=True)),
      "ポストシーズン進出を決めている(地区優勝はまだ決まっていない)")
check("進出は決めたが地区は消えた",
      ne.standing_status(st("1", 2, 9.0, clinched=True, division_out=True)),
      "ポストシーズン進出を決めている(地区優勝の可能性は消えた)")
check("両方消えた",
      ne.standing_status(st("1", 5, 20.0, division_out=True,
                            playoff_out=True)),
      "ポストシーズン進出の可能性は消えている")
check("まだ何も決まっていない", ne.standing_status(st("1", 2, 1.5)), "")
check("順位表が無くても落ちない", ne.standing_status(None), "")

section("地区優勝が決まった同地区対決")
note = ne.division_note(GAME, DIV, {"119": LAD, "135": SD})
has("決まったことを渡す", note, "ドジャースがすでに地区優勝を決めている")
hasnt("「直接争う関係にある」と渡さない", note, "直接争う関係にある")
has("書いてはいけない言い方を名指す", note, "地区順位を争っている")

# 優勝した側がビジターでも同じ
away = ne.division_note(
    {**GAME, "home_team_id": "135", "away_team_id": "119",
     "home_team_name": "パドレス", "away_team_name": "ドジャース"},
    DIV, {"119": LAD, "135": SD})
has("ビジター側が優勝していても拾う", away, "ドジャースがすでに地区優勝")

section("両方とも地区の可能性が消えた同地区対決")
both = ne.division_note(GAME, DIV, {
    "119": st("119", 3, 12.0, division_out=True),
    "135": st("135", 4, 15.0, division_out=True)})
has("首位争いと書かせない", both, "地区の首位争いとは書かないこと")
hasnt("「直接争う関係にある」と渡さない", both, "直接争う関係にある")

section("まだ争っている同地区対決はこれまでどおり")
live = ne.division_note(GAME, DIV, {"119": st("119", 1, 0.0),
                                    "135": st("135", 2, 1.5)})
has("直接争う関係と書く", live, "順位を直接争う関係にある")
has("順位表が無い日もこれまでどおり", ne.division_note(GAME, DIV, {}),
    "順位を直接争う関係にある")
has("None でも落ちない", ne.division_note(GAME, DIV, None),
    "順位を直接争う関係にある")

section("1チームの行にも決まったことを載せる")
has("ドジャースの行", ne._team_context_line("119", "ドジャース",
                                            {"119": LAD}), "地区優勝を決めている")
hasnt("まだ争っている球団には何も足さない",
      ne._team_context_line("119", "ドジャース", {"119": st("119", 1, 0.0)}),
      "決めている")

sys.exit(done())
