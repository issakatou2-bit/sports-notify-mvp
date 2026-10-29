"""新聞式の題で、名前と球団の境目・複数人の列挙を保つ。"""
import unittest

from press_names import press_title


class PressNamesTest(unittest.TestCase):
    def test_kana_surname(self):
        for name, team in [("ヌートバー", "ダイヤモンドバックス"),
                           ("ダルビッシュ有", "パドレス")]:
            surname = name.replace("有", "")
            for link in ("の", "が所属する"):
                with self.subTest(name=name, link=link):
                    title = f"【MLB】{name}{link}{team}が先勝"
                    expected = f"【MLB】{surname}の{team}が先勝"
                    self.assertEqual(press_title(title), expected)
                    self.assertEqual(press_title(expected), expected)

    def test_existing_join_and_player_subject(self):
        self.assertEqual(press_title("ヌートバーダイヤモンドバックス"),
                         "ヌートバーのダイヤモンドバックス")
        self.assertEqual(press_title("パドレス ダルビッシュ有、好投"),
                         "パドレス ダルビッシュ、好投")
        self.assertEqual(press_title("カージナルスのヌートバー"),
                         "カージナルス ヌートバー")

    def test_multiple_players(self):
        for names in ("大谷翔平・山本由伸", "大谷翔平と山本由伸",
                      "大谷翔平、山本由伸", "鈴木誠也・ヌートバー",
                      "ヌートバーと鈴木誠也", "大谷翔平、 山本由伸",
                      "大谷翔平 ・ 山本由伸", "鈴木誠也・ ヌートバー",
                      "トラウト・大谷翔平", "トラウト・ 大谷翔平"):
            title = f"{names}のカブスが先勝"
            with self.subTest(names=names):
                self.assertEqual(press_title(title), title)

    def test_kanji_and_long_title(self):
        self.assertEqual(press_title("村上宗隆のホワイトソックス"), "村上ホワイトソックス")
        self.assertEqual(press_title("ホワイトソックス村上宗隆"), "ホワイトソックス村上宗隆")
        title = "ヌートバーのダイヤモンドバックス" + "あ" * 100
        self.assertTrue(press_title(title).startswith("ヌートバーのDバックス"))


if __name__ == "__main__":
    unittest.main(argv=[__file__])
