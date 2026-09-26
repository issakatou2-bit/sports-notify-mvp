#!/usr/bin/env python3
"""殿堂の回で、監督や経営者を「でプレーした選手」と呼ばないか。

なぜ要るのか:
  9/21のレッズの回で、**監督として**殿堂入りしたスパーキー・アンダーソンを
  選手として並べ、選手時代（1959年フィリーズの1年だけ）の打率.218を出した
  （Codexの内容点検。YouTube側の題と説明だけ手で直してあった）。

  殿堂のAPIは選出の区分を返さない。選手以外として選ばれた人は守備位置が
  「Unknown」になるので、それで分ける。同じ材料にはラソーダ（ドジャース）、
  ハーゾグ（カージナルス）、ディック・ウィリアムズ（アスレチックス）も
  入っていて、その3本はまだ公開されていなかった。
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import legend_topics as lt  # noqa: E402
import team_legends as tl  # noqa: E402
from checks_report import check, section, done  # noqa: E402

section("選手として選ばれたか")
# APIの形（primaryPosition の入れ子）
check("監督は選手ではない",
      tl.is_player({"primaryPosition": {"code": "X", "name": "Unknown"}}), False)
check("投手は選手", tl.is_player({"primaryPosition": {"name": "Pitcher"}}), True)
check("守備位置が無ければ選手としない", tl.is_player({"primaryPosition": {}}), False)
# 材料の形（position の平文）
check("材料の形でも監督を落とす", tl.is_player({"position": "Unknown"}), False)
check("材料の形の遊撃手", tl.is_player({"position": "Shortstop"}), True)


def reds(*people):
    return {"teams": {"113": {"team": "レッズ", "players": list(people)}}}


LARKIN = {"name": "Barry Larkin", "position": "Shortstop", "hof_year": "2012",
          "line": "通算 打率.295　198本塁打　2340安打"}
ANDERSON = {"name": "Sparky Anderson", "position": "Unknown", "hof_year": "2000",
            "line": "通算 打率.218　0本塁打　104安打"}

section("話題にするときも止める（古い材料が残っていても）")
topics = lt.build(reds(LARKIN, ANDERSON))
names = [i[0] for t in topics for i in t["items"]]
check("監督は並ばない", "Sparky Anderson" in names, False)
check("選手は並ぶ", names, ["Barry Larkin"])
check("1人なら「殿堂入りした1人」とは言わない", topics[0]["hook"],
      "レッズの殿堂入り選手")
check("選手が1人もいない球団は話題にしない", lt.build(reds(ANDERSON)), [])

section("手元の材料")
# 材料はコミットされたファイルなので、日によって変わらない。
data = json.loads((HERE.parent / "data" / "team_legends.json")
                  .read_text(encoding="utf-8"))
mixed = [(v["team"], r["name"]) for v in data["teams"].values()
         for r in v["players"] if not tl.is_player(r)]
check("選手以外が混ざっていない", mixed, [])

sys.exit(done())
