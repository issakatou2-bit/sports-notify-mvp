#!/usr/bin/env python3
"""欧州の日本人選手の週末で、言えないことを言わないか。

いちばん避けたいのは、**クラブが勝ったことを選手が活躍したように
読ませること。**選手本人の出場・得点が公式に取れるのはプレミアだけ。
他のリーグの選手については、本人のことを1文字も書かない。

材料は作り物で固定する（football-data の形を写したもの）。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import soccer_jp_week as w  # noqa: E402
from checks_report import check, has, hasnt, section, done  # noqa: E402

ROSTER = {
    "Brighton & Hove Albion FC": [{"name_jp": "三笘薫", "league": "PL",
                                   "team_jp": "ブライトン",
                                   "name_en": "Kaoru Mitoma"}],
    "Crystal Palace FC": [{"name_jp": "鎌田大地", "league": "PL",
                           "team_jp": "クリスタル・パレス",
                           "name_en": "Daichi Kamada"}],
    "Real Sociedad de Fútbol": [{"name_jp": "久保建英", "league": "PD",
                                 "team_jp": "レアル・ソシエダ",
                                 "name_en": "Takefusa Kubo"}],
}
JP = {"Chelsea FC": "チェルシー", "Everton FC": "エバートン",
      "Getafe CF": "ヘタフェ", "Brighton & Hove Albion FC": "ブライトン",
      "Crystal Palace FC": "クリスタル・パレス",
      "Real Sociedad de Fútbol": "レアル・ソシエダ"}


def m(code, home, away, h, a, md=5, utc="2026-09-20T14:00:00Z"):
    return {"homeTeam": {"name": home}, "awayTeam": {"name": away},
            "score": {"fullTime": {"home": h, "away": a}},
            "matchday": md, "utcDate": utc}


MATCHES = {
    "PL": [m("PL", "Brighton & Hove Albion FC", "Chelsea FC", 2, 1),
           m("PL", "Everton FC", "Crystal Palace FC", 1, 1)],
    "PD": [m("PD", "Getafe CF", "Real Sociedad de Fútbol", 0, 2,
             utc="2026-09-21T19:00:00Z")],
}
FPL = {("三笘薫", 5): {"minutes": 0, "goals": 0, "assists": 0},
       ("鎌田大地", 5): {"minutes": 90, "goals": 1, "assists": 0}}


def build(**kw):
    return w.build(MATCHES, FPL, players_for=lambda t: ROSTER.get(t, []),
                   club_jp=lambda n: JP.get(n, n), **kw)


rows = {r["name"]: r for r in build(out_now={"三笘薫"})}

section("クラブの結果は向きを取り違えない")
check("アウェーの勝ちは勝ち", (rows["久保建英"]["gf"], rows["久保建英"]["ga"],
                          rows["久保建英"]["result"]), (2, 0, "勝ち"))
check("アウェーと書く", rows["久保建英"]["home"], False)
check("引き分け", rows["鎌田大地"]["result"], "引き分け")

section("選手本人のことは、プレミアの公式データがあるときだけ")
has("得点した選手はそう書く", w.line(rows["鎌田大地"]), "90分出場・1得点")
has("離脱中の選手は離脱中と書く", w.line(rows["三笘薫"]), "（三笘薫は負傷で離脱中）")
line_kubo = w.line(rows["久保建英"])
check("他リーグは本人のことを書かない", line_kubo,
      "久保建英のレアル・ソシエダ、アウェーでヘタフェに2-0の勝利")
for word in ("出場", "得点", "活躍", "ゴール"):
    hasnt("久保に「%s」と書かない" % word, line_kubo, word)
none = w.build(MATCHES, {}, players_for=lambda t: ROSTER.get(t, []),
               club_jp=lambda n: JP.get(n, n))
hasnt("公式データが取れない日はプレミアでも本人のことを書かない",
      w.line({r["name"]: r for r in none}["鎌田大地"]), "出場")
check("離脱の印が無ければ「出場なし」",
      w.player_part({"stats": {"minutes": 0, "goals": 0, "assists": 0}}),
      "出場なし")

section("並びと見出し")
order = [r["name"] for r in build()]
check("得点した選手が先頭", order[0], "鎌田大地")
check("見出しは本人の得点", w.headline(build()), "鎌田大地が1得点、クリスタル・パレスは引き分け")
check("得点が無い日はクラブの勝ち（プレミアが先）",
      w.headline(none), "三笘薫のブライトンが勝利")
check("出ていないと分かっている選手は見出しにしない",
      w.headline([x for x in build(out_now={"三笘薫"})
                  if x["name"] != "鎌田大地"]),
      "久保建英のレアル・ソシエダが勝利")
check("誰もいない日は空", w.headline([]), "")

section("直近の1試合だけ")
two = {"PD": MATCHES["PD"] + [m("PD", "Real Sociedad de Fútbol", "Getafe CF",
                                0, 1, md=4, utc="2026-09-14T19:00:00Z")]}
r = w.build(two, {}, players_for=lambda t: ROSTER.get(t, []),
            club_jp=lambda n: JP.get(n, n))
check("古い試合は出さない", (r[0]["gf"], r[0]["ga"]), (2, 0))
check("スコアの無い試合は数えない",
      w.build({"PL": [m("PL", "Brighton & Hove Albion FC", "Chelsea FC",
                        None, None)]}, {},
              players_for=lambda t: ROSTER.get(t, [])), [])

section("同じ姓の選手がいたら引かない")
els = [{"id": 1, "web_name": "Tanaka", "second_name": "Tanaka",
        "first_name": "Ao"},
       {"id": 2, "web_name": "Tanaka", "second_name": "Tanaka",
        "first_name": "Other"}]
check("名で絞れれば引く", w.resolve(els, "Ao Tanaka"), 1)
check("絞れなければ引かない", w.resolve(els, "Hiroshi Tanaka"), None)
check("1人なら姓だけで引く", w.resolve(els[:1], "Ao Tanaka"), 1)

sys.exit(done())
