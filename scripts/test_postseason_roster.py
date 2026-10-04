#!/usr/bin/env python3
"""PSの日本人選手は、ベンチ入り（active roster）している選手だけ（postseason.japanese）。

10/4、本人「西田はPSのロースターに入っていないなら言及も消す。メンバー入りしたらまた言う」。
APIは使わず、名簿と active の結果を差し替えて確かめる。
"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import postseason as ps  # noqa: E402
import textkey  # noqa: E402

DATA = {"103": {"leaders": [{"id": 145, "name": "ホワイトソックス", "league": 103,
                             "league_jp": "ア・リーグ", "w": 90, "l": 72}]}}


def run(active):
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "roster.json"
        path.write_text(json.dumps({"players": {
            "1": {"name": "Munetaka Murakami", "team_id": "145"},
            "2": {"name": "Rikuu Nishida", "team_id": "145"}}}), encoding="utf-8")
        return ps.japanese(DATA, roster_path=str(path), active=active)


class ActiveRoster(unittest.TestCase):
    def test_player_off_the_active_roster_is_not_mentioned(self):
        got = run(lambda tid: {textkey.key("Munetaka Murakami")})
        self.assertEqual(got[0]["players"], ["村上宗隆"])

    def test_added_to_the_roster_is_mentioned_again(self):
        got = run(lambda tid: {textkey.key("Munetaka Murakami"), textkey.key("Rikuu Nishida")})
        self.assertEqual(got[0]["players"], ["村上宗隆", "西田陸浮"])

    def test_roster_unavailable_keeps_affiliation(self):
        got = run(lambda tid: None)
        self.assertEqual(got[0]["players"], ["村上宗隆", "西田陸浮"])

    def test_team_with_nobody_active_is_dropped(self):
        self.assertEqual(run(lambda tid: set()), [])


if __name__ == "__main__":
    unittest.main(argv=["test_postseason_roster"])
