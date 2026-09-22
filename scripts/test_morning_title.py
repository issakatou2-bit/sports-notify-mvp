#!/usr/bin/env python3
"""朝の成績ショートの題と説明文が、人数と合っているか。

なぜ要るのか:
  9/22は岡本和真1人だけの日だったのに、題が
  「【MLB】岡本和真 ほか｜9月22日 日本人選手 勝利貢献スコア ランキング」、
  説明が「岡本和真ほか。」になった（Codexの内容点検で見つかり、
  YouTube側の文面だけ手で直した）。題と説明の2か所が、どちらも人数を
  見ずに「ほか」を付けていた。

  もう1つ、説明に「数字はMLB公式データをそのまま集計したもの」と書き、
  独自指標の点数まで公式に見えていた。
"""

import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import upload_youtube as uy  # noqa: E402
from checks_report import check, has, hasnt, section, done  # noqa: E402

OKAMOTO = {"name": "岡本和真", "team_jp": "ブルージェイズ",
           "headline": "4打数1安打", "type": "batter"}


def players(n):
    base = [OKAMOTO,
            {"name": "山本由伸", "team_jp": "ドジャース", "headline": "7回無失点"},
            {"name": "村上宗隆", "team_jp": "ホワイトソックス", "headline": "1本塁打"},
            {"name": "鈴木誠也", "team_jp": "カブス", "headline": "2安打"},
            {"name": "今永昇太", "team_jp": "カブス", "headline": "6回2失点"}]
    return base[:n]


def snippet(rows):
    with tempfile.TemporaryDirectory() as tmp:
        games = pathlib.Path(tmp) / "games.json"
        games.write_text(json.dumps({"games": []}), encoding="utf-8")
        return uy.build_metadata(str(games), "9月22日", kind="morning",
                                 morning_players=rows)["snippet"]


section("並べ方は1か所で決める")
check("1人", uy.morning_who(players(1)), (["岡本和真"], False, 1))
check("3人なら残りはいない", uy.morning_who(players(3))[1], False)
check("5人なら残りがいる", uy.morning_who(players(5))[1], True)
check("名前の無い行は数えない",
      uy.morning_who([{"name": ""}, OKAMOTO])[2], 1)
check("空でも落ちない", uy.morning_who(None), ([], False, 0))

section("1人の日")
one = snippet(players(1))
hasnt("題に「ほか」を付けない", one["title"], "ほか")
hasnt("題に「ランキング」と書かない", one["title"], "ランキング")
has("題に球団名", one["title"], "ブルージェイズ 岡本和真")
has("題にきょうの成績", one["title"], "4打数1安打")
hasnt("説明にも「ほか」を付けない", one["description"].split("\n")[0], "ほか")

section("3人の日")
three = snippet(players(3))
hasnt("全員出ているなら「ほか」を付けない", three["title"], "ほか")
has("並べているのでランキング", three["title"], "ランキング")

section("5人の日")
five = snippet(players(5))
has("出しきれない人がいるなら「ほか」", five["title"], "村上宗隆 ほか")
has("説明も同じ", five["description"].split("\n")[0], "村上宗隆ほか。")

section("独自の点数を公式と書かない")
for label, s in (("1人", one), ("5人", five)):
    hasnt("%s: 公式データをそのまま集計、と書かない" % label,
          s["description"], "そのまま集計")
    has("%s: 点数は独自と書く" % label, s["description"],
        "公式の記録ではありません")

section("選手がいない日")
none = snippet([])
check("落ちずに題を作る", bool(none["title"]), True)
hasnt("「ほか」を付けない", none["title"], "ほか")

sys.exit(done())
