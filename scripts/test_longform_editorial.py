"""過去の失敗を止め、正しい比較・別枠の引用は通す。"""
import unittest
from unittest.mock import patch

import longform_editorial as editorial
import numbers_material as nm
import rarity
import upload_youtube as upload
import verify_numbers


def dialogue(*lines):
    return {"mode": "numbers", "material": {"daily_player_count": 0, "rare": [
        {"name": "山本由伸", "value": "0.87"},
        {"name": "村上宗隆", "value": "58.4%"}]}, "segments": [
            {"text": text, "panel": panel} for panel, text in lines],
        "panels": {"rare1": {"name": "山本由伸"}, "rare2": {"name": "村上宗隆"}}}


class EditorialTests(unittest.TestCase):
    def test_orphan_rank(self):
        self.assertTrue(editorial.check(dialogue((None, "1位じゃないのだ。誰が上にいるのだ？"))))

    def test_value_and_name_first(self):
        self.assertFalse(editorial.check(dialogue(
            ("rare1", "山本由伸のWHIPは0.87で46人中2位。"),
            (None, "1位はミジオロウスキの0.80なのだ。"))))

    def test_other_subject_not_enough(self):
        self.assertTrue(editorial.check(dialogue(
            ("rare1", "山本由伸のWHIPは0.87で2位。"),
            ("rare2", "こちらは1位なのだ。"))))

    def test_number_without_name(self):
        self.assertTrue(editorial.check(dialogue(("rare1", "WHIPは0.87で2位なのだ。"))))

    def test_other_ranking_subject_is_outside_rare_scope(self):
        self.assertFalse(editorial.check(dialogue((None, "ガーディアンズは地区1位で終えたわ。"))))

    def test_production_excuses_without_numeric_facts(self):
        for text in ("材料が渡されていないから何とも言えない。", "データが無いわ。", "分からないのだ。"):
            self.assertTrue(verify_numbers.check(dialogue((None, text))))

    def test_comment_mode_is_outside_scope(self):
        d = dialogue((None, "誰のことか分からないというコメントです。"))
        d["mode"] = "voices"
        self.assertFalse(editorial.check(d))

    def test_qualified_scope_is_not_invented(self):
        self.assertTrue(editorial.check(dialogue(("rare1", "山本由伸のWHIPは0.87で規定到達46人中2位。"))))
        self.assertFalse(editorial.check(dialogue(("rare1", "山本由伸のWHIPは0.87で60回以上の46人中2位。"))))

    def test_zero_players_title(self):
        d = dialogue(); d["title"] = "日本人選手の成績"
        self.assertTrue(editorial.check(d))

    def test_neighbor_material_and_leader(self):
        metric = {"fn": lambda s: s["v"], "high": True, "fmt": "ratio"}
        rows = [{"player_id": str(i), "name": name, "stat": {"v": v}}
                for i, name, v in ((1, "首位", 9), (2, "対象", 8), (3, "次点", 7))]
        ranked = rarity.rank(rows, metric, "2")
        self.assertEqual(ranked["leader"]["name"], "首位")
        self.assertEqual(ranked["below"]["name"], "次点")

    def test_no_game_metadata_uses_record(self):
        m = {"players": [], "rare": [{"name": "村上宗隆", "stat": "アダム・ダン率",
            "value": "58.4%", "rank": "135人中1位"}], "race": {}}
        meta = nm.meta(m)
        self.assertIn("村上宗隆", meta["title"])
        self.assertNotIn("成績", meta["title"])

    def test_upload_preserves_subject_and_scope(self):
        with patch.object(upload, "_postseason_data", return_value={"phase": "postseason"}):
            body = upload.build_metadata("no-such-file.json", "10/4", "longform",
                longform_mode="numbers", jp_names=[], longform_subject="村上宗隆 アダム・ダン率58.4%")
        title = body["snippet"]["title"]
        self.assertIn("村上宗隆", title)
        self.assertNotIn("きょうの日本人", title)
        self.assertNotIn("その日の日本人選手の成績", body["snippet"]["description"])

    def test_title_does_not_advertise_unused_record(self):
        m = {"players": [], "rare": [{"name": "村上宗隆", "stat": "アダム・ダン率",
            "value": "58.4%", "rank": "135人中1位"}], "race": {"headline": "地区シリーズの結果"}}
        self.assertNotIn("村上宗隆", nm.meta(m, [{"text": "地区シリーズの結果よ。"}])["title"])


if __name__ == "__main__":
    unittest.main(argv=[__file__])
