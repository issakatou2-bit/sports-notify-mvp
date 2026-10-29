"""APIの人数が変わっても球団・球場の材料は同じ公式照合表を使う。"""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import team_topics
import venue_topics
from venue_capacity import CAPACITIES, SOURCE, apply_capacity


class VenueCapacityTest(unittest.TestCase):
    def test_both_fetchers_use_verified_capacity(self):
        raw = [{"id": i, "name": name,
                "fieldInfo": {"capacity": record["previous_material_values"][-1],
                              "center": 400}}
               for i, (name, record) in enumerate(CAPACITIES.items(), 1)]
        before = copy.deepcopy(raw)
        teams = [{"id": i, "name": name, "venue": {"id": i}}
                 for i, name in enumerate(CAPACITIES, 1)]
        for module in (team_topics, venue_topics):
            with self.subTest(module=module.__name__), patch.object(
                    module.requests, "get", side_effect=[
                        Mock(json=lambda: {"teams": teams}),
                        Mock(json=lambda: {"venues": raw})]):
                result = module.fetch()
                if module is team_topics:
                    values = {v["name"]: v["fieldInfo"]["capacity"]
                              for v in result[1].values()}
                else:
                    values = {v["name"]: v["field"]["capacity"] for v in result}
                self.assertEqual(values, {k: v["capacity"] for k, v in CAPACITIES.items()})
        self.assertEqual(raw, before)

    def test_unverified_venue_keeps_api_value(self):
        raw = {"name": "Other Park", "fieldInfo": {"capacity": 12345}}
        self.assertEqual(apply_capacity(raw), raw)

    def test_generated_materials_match_verified_source(self):
        root = SOURCE.parent
        for path in (root / "team_topics.json", root / "venue_topics.json"):
            text = path.read_text(encoding="utf-8")
            for name, record in CAPACITIES.items():
                for old in record["previous_material_values"]:
                    if old != record["capacity"]:
                        self.assertTrue(f"{old:,}人" not in text, (path, name, old))
            self.assertEqual(json.loads(text)["capacity_source"], "data/venue_capacities.json")


if __name__ == "__main__":
    unittest.main(argv=[__file__])
