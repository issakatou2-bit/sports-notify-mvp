"""球団名の置換と両翻訳経路の適用を、APIを呼ばず検査する。"""

from types import SimpleNamespace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import local_reporters as lr
import local_voices as lv
from notability_engine import MLB_TEAM_NAME_EN, MLB_TEAM_NAME_JP
from team_names import team_names_jp


class TeamNames(unittest.TestCase):
    def test_all_full_names_and_nicknames(self):
        for team_id, full_name in MLB_TEAM_NAME_EN.items():
            with self.subTest(team=full_name):
                expected = MLB_TEAM_NAME_JP[team_id]
                self.assertEqual(team_names_jp(full_name), expected)
                nickname = full_name.rsplit(" ", 1)[-1]
                if nickname in ("Sox", "Jays"):
                    nickname = " ".join(full_name.split()[-2:])
                self.assertEqual(team_names_jp(nickname.upper() + "が勝った"), expected + "が勝った")

    def test_multiple_names_and_boundaries(self):
        self.assertEqual(team_names_jp("Los Angeles Dodgers対Yankees、Astrosも"),
                         "ドジャース対ヤンキース、アストロズも")
        original = "Dodgerson YankeesFan Astros123 Blue Jaysfan Shohei Ohtani Aaron Judge 大谷翔平"
        self.assertEqual(team_names_jp(original), original)
        self.assertEqual(team_names_jp("ドジャースとレッドソックス"), "ドジャースとレッドソックス")
        self.assertEqual(team_names_jp(""), "")

    def test_voices_main_and_replies(self):
        response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="1|称賛|DodgersのShohei Ohtani！\n2|中立|Yankees対Astros")],
        )
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: response))
        items = [{"title": "Dodgers' Shohei Ohtani!", "reply_texts": ["Yankees vs Astros"]}]
        with patch.object(lv.token_log, "allowed", return_value=True), patch.object(lv.token_log, "record"):
            result = lv.translate(client, items)
        self.assertEqual(result[0]["ja"], "ドジャースのShohei Ohtani！")
        self.assertEqual(result[0]["reply_ja"][0]["ja"], "ヤンキース対アストロズ")
        self.assertEqual(result[0]["title"], items[0]["title"])
        self.assertEqual(result[0]["reply_ja"][0]["original"], "Yankees vs Astros")

    def test_reporters_preserves_existing_guards_and_names(self):
        response = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
            text="1. Dodgersの大谷翔平の2点二塁打。Aaron Judgeも出場")])
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: response))
        source = "Dodgers' Shohei Ohtani's RBI double. Aaron Judge plays."
        with patch.dict(sys.modules, {"anthropic": SimpleNamespace(Anthropic=lambda **kwargs: client)}), \
                patch.object(lr.token_log, "allowed", return_value=True), patch.object(lr.token_log, "record"):
            result = lr.translate([{"text": source}], "test-only")
        self.assertEqual(result[0]["jp"], "ドジャースの大谷翔平の適時二塁打。Aaron Judgeも出場")
        self.assertEqual(result[0]["text"], source)


if __name__ == "__main__":
    unittest.main(argv=["test_team_names"])
