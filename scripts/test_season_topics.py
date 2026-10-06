#!/usr/bin/env python3
"""シーズンまとめの材料（season_topics.py）の、APIを使わない部分。"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import season_topics as st  # noqa: E402
from checks_report import check, section, done  # noqa: E402

section("終わった球団だけ")
_teams = {"112": {"name": "カブス", "seed": 5}, "135": {"name": "パドレス", "seed": 4},
          "119": {"name": "ドジャース", "seed": 2}, "121": {"name": "メッツ"},
          "147": {"name": "ヤンキース", "seed": 4}, "111": {"name": "レッドソックス", "seed": 5}}
_series = [
    {"key": "F:112-135", "round": "F", "round_jp": "ワイルドカードシリーズ",
     "over": True, "winner": 135,
     "teams": [{"id": 135, "name": "パドレス", "wins": 2},
               {"id": 112, "name": "カブス", "wins": 0}]},
    {"key": "D:135-158", "round": "D", "round_jp": "地区シリーズ",
     "over": False, "winner": None,
     "teams": [{"id": 135, "name": "パドレス", "wins": 0},
               {"id": 158, "name": "ブリュワーズ", "wins": 0}]},
    {"key": "F:111-147", "round": "F", "round_jp": "ワイルドカードシリーズ",
     "over": True, "winner": 147,
     "teams": [{"id": 147, "name": "ヤンキース", "wins": 2},
               {"id": 111, "name": "レッドソックス", "wins": 0}]},
]
_ended = st.finished_teams({"phase": "postseason", "teams": _teams,
                            "series": _series})
check("敗退した球団は結末つき", _ended.get(112),
      "ワイルドカードシリーズで敗退（パドレスに0勝2敗）")
check("進出しなかった球団", _ended.get(121), "ポストシーズン進出ならず")
check("勝ち残っている球団は作らない", 135 in _ended, False)
check("免除されて待っている球団も作らない", 119 in _ended, False)
check("勝って次の回が組まれる前の球団も作らない", 147 in _ended, False)
check("レギュラーシーズン中は何も作らない",
      st.finished_teams({"phase": "regular", "teams": _teams}), {})

section("読み上げで崩れない書き方")
check("投球回の3分の1", st.innings("174.1"), "174回と3分の1")
check("投球回の3分の2", st.innings("76.2"), "76回と3分の2")
check("投球回のちょうど", st.innings("180.0"), "180回")
_x = {"key": "k_percent", "kind": "batter", "label": "三振率",
      "percentile": 1, "high": False, "side": ""}
check("三振の多い打者は「三振率の高さ」で言う", st.statcast_phrase(_x),
      "三振率はリーグで高い方から1%（Savantの評価は下位）")
_x = {"key": "bb_percent", "kind": "pitcher", "label": "与四球率",
      "percentile": 95, "high": True, "side": ""}
check("与四球の少ない投手は「与四球率の低さ」", st.statcast_phrase(_x),
      "与四球率はリーグで低い方から5%（Savantの評価は上位）")
_x = {"key": "brl_percent", "kind": "batter", "label": "バレル率",
      "percentile": 96, "high": True, "side": "リーグ上位4%"}
check("値が大きいほど良い項目はそのまま", st.statcast_phrase(_x), "バレル率はリーグ上位4%")

section("球団内の1位")
_rows = [{"player": {"fullName": "A"}, "stat": {"homeRuns": 30, "avg": ".300"}},
         {"player": {"fullName": "B"}, "stat": {"homeRuns": 30, "avg": ".250"}},
         {"player": {"fullName": "C"}, "stat": {"homeRuns": 10, "avg": ".---"}}]
check("同率1位は名前を出さない", st.top(_rows, "homeRuns"), None)
check("1位", st.top(_rows, "avg")["player"]["fullName"], "A")
check("0は1位と呼ばない",
      st.top([{"player": {"fullName": "A"}, "stat": {"saves": 0}}], "saves"), None)

section("出す順番")
import next_asset as na  # noqa: E402
_specs = {"season_team_121": {"japanese": [{"name": "千賀滉大"}]},
          "season_team_110": {},
          "season_player_684007": {"jp": "今永昇太", "ps_ended": True},
          "season_team_112": {"japanese": [{"name": "今永昇太"}], "ps_ended": True},
          "season_player_673540": {"jp": "千賀滉大"}}
check("リーグの部門1位は日本人選手の球団と同じ段",
      na.season_order("season_league_103_hitting", {})[:2], (1, 1))
check("PSで終わったばかり → 日本人選手 → その他",
      sorted(_specs, key=lambda k: na.season_order(k, _specs[k])),
      ["season_player_684007", "season_team_112", "season_player_673540",
       "season_team_121", "season_team_110"])

# 球団の回の日本人選手: 打撃の一覧に入っている投手は、投球の成績で（10/6 千賀）
_senga_h = {"player": {"fullName": "Kodai Senga"}, "stat": {"gamesPlayed": 31, "plateAppearances": 0,
            "avg": ".000", "homeRuns": 0, "rbi": 0, "ops": ".000"}}
_senga_p = {"player": {"fullName": "Kodai Senga"}, "stat": {"gamesPlayed": 31, "wins": 0, "losses": 9,
            "era": "7.34", "inningsPitched": "61.1", "strikeOuts": 75, "saves": 8}}
_lines = st.jp_lines([_senga_h], [_senga_p], {"Kodai Senga": "千賀滉大"})
check("打席のない投手は投球の成績", "防御率" in _lines[0]["line"] and "打率" not in _lines[0]["line"], True)

sys.exit(done())
