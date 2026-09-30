#!/usr/bin/env python3
"""視聴者の立場で見つけた引っかかりを、直した形で押さえる（9/28）。

  17:00  1位が無安打の日は、何が良かったかから言う。独自の点数は声で言わない
  18:00  番記者の投稿の訳の、PSの言い方と球団の勝敗
  21:00  表紙の引用は、その日いちばん珍しい数字から
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import generate_morning_short as ms  # noqa: E402
import local_reporters as lr  # noqa: E402
import numbers_material as nm  # noqa: E402
from checks_report import check, section, done  # noqa: E402

section("17:00 無安打で1位の日")
check("四球で出塁した日は出塁で言う",
      ms.on_base_lead({"name": "ヌートバー", "type": "batter", "hits": 0,
                       "bb": 2, "hbp": 0}),
      "ヌートバーは無安打ながら、四球2つで2度出塁。")
check("死球も数える",
      ms.on_base_lead({"name": "A", "type": "batter", "hits": 0, "bb": 1,
                       "hbp": 1}), "Aは無安打ながら、四球1つ・死球1つで2度出塁。")
check("安打があれば使わない",
      ms.on_base_lead({"name": "A", "type": "batter", "hits": 1, "bb": 2}), "")
check("投手には使わない",
      ms.on_base_lead({"name": "A", "type": "pitcher", "hits": 0, "bb": 2}), "")
check("出塁が無ければ使わない",
      ms.on_base_lead({"name": "A", "type": "batter", "hits": 0, "bb": 0}), "")

section("18:00 番記者の投稿の訳")
check("第何戦", lr.baseball_jp("パドレス戦のゲーム1-2からは外れる。ゲーム3に登板"),
      "パドレス戦の第1・2戦からは外れる。第3戦に登板")
check("レギュラーシーズン最終戦", lr.baseball_jp("ゲーム162で先発"),
      "レギュラーシーズン最終戦で先発")
check("球団の勝敗", lr.baseball_jp("78-82。"), "78勝82敗。")
check("スコアは勝敗にしない", lr.baseball_jp("6-5で勝利"), "6-5で勝利")
check("対戦成績（小さい数）もそのまま", lr.baseball_jp("対戦成績12-7"), "対戦成績12-7")

section("21:00 表紙の引用")
_m = {"players": [{"name": "ヌートバー", "line": "3打数0安打", "team": "カージナルス"}],
      "rare": [{"name": "村上宗隆", "stat": "アダム・ダン率", "value": "58.4%",
                "rank": "135人中1位"}]}
check("リーグ1位の指標があればそれを引用",
      nm.meta(_m)["pick"], "村上宗隆 アダム・ダン率 58.4%（135人中1位）")
_m["rare"] = [{"name": "山本由伸", "stat": "WHIP", "value": "0.87",
               "rank": "44人中2位"}]
check("1位が無ければ主役の成績", nm.meta(_m)["pick"], "ヌートバー 3打数0安打")

section("9/30 PSの試合の成績")
import json as _json  # noqa: E402
import tempfile as _tf  # noqa: E402
import morning_recap as mr  # noqa: E402
import player_profile as pp  # noqa: E402
_seen = []


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"stats": []}


def _fake_get(url, params=None, **kw):
    _seen.append(params or {})
    return _Resp()


_real = mr.requests.get
mr.requests.get = _fake_get
try:
    mr.fetch_day_hitting("1", "2026-09-29", "2026")
    mr.fetch_day_pitching("1", "2026-09-29", "2026")
finally:
    mr.requests.get = _real
check("打撃も投球もPSの試合を含めて取る",
      [x.get("gameType") for x in _seen], ["R,F,D,L,W", "R,F,D,L,W"])

with _tf.NamedTemporaryFile("w", suffix=".json", delete=False,
                            encoding="utf-8") as _f:
    _json.dump({"date_jst": "2026-09-30", "players": [
        {"name": "Cam Schlittler", "type": "pitcher", "score": 146,
         "headline": "6.1回", "team": "ヤンキース"}]}, _f)
check("1位が投手なら投手として紹介する",
      pp.pick_from_best(_f.name, {}).get("type"), "pitcher")
check("指名でも種類を引き継ぐ",
      pp.pinned_player("Cam Schlittler", _f.name).get("type"), "pitcher")

sys.exit(done())
