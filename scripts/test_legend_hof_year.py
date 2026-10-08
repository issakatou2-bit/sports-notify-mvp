"""Election year and induction ceremony are distinct; only verified cases change."""
import unittest
import legend_topics as legends


class HallYear(unittest.TestCase):
    def test_verified_december_elections_use_class_2022(self):
        for name in ("Jim Kaat", "Tony Oliva", "Gil Hodges", "Minnie Minoso"):
            for year in (2021, "2021"):
                self.assertEqual(legends.hof_label(dict(name=name, hof_year=year)),
                                 "2021年に選出、2022年に殿堂入り式典")

    def test_unrelated_or_unverified_years_are_not_shifted(self):
        for name, year in (("Joe Mauer", 2024), ("Larry Walker", 2020),
                           ("Unknown Player", 2021), ("Jim Kaat", 2022)):
            self.assertEqual(legends.hof_label(dict(name=name, hof_year=year)),
                             "%s年に殿堂入り" % year)
        self.assertEqual(legends.hof_label(dict(name="Jim Kaat")), "")

    def test_public_items_keep_statistics_and_correct_years(self):
        source = {"teams": {"142": {"team": "ツインズ", "players": [
            dict(name="Jim Kaat", position="Pitcher", hof_year="2021", line="通算 283勝"),
            dict(name="Tony Oliva", position="Outfield", hof_year="2021", line="通算 1917安打")]}}}
        topic = legends.build(source)[0]
        self.assertEqual(topic["items"], [
            ["Jim Kaat", "2021年に選出、2022年に殿堂入り式典。通算 283勝"],
            ["Tony Oliva", "2021年に選出、2022年に殿堂入り式典。通算 1917安打"]])
        self.assertEqual(topic["style"], "v3")


if __name__ == "__main__":
    unittest.main()
