"""台本入口の依頼内容と単価だけを比較。実APIは呼ばない。"""
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dialogue_batch as db
import generate_dialogue as gd
import token_log as tl


class Integration(unittest.TestCase):
    def test_same_payload_as_existing_create(self):
        resp = types.SimpleNamespace(stop_reason="end_turn")
        client = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: resp))
        kw = {"max_tokens": 16000, "messages": [{"role": "user", "content": "同一の材料とプロンプト"}]}
        with patch.object(client.messages, "create", return_value=resp) as create:
            gd._create(client, **kw)
        self.assertEqual(create.call_args.kwargs, db.params_of(kw, gd.MODEL, gd.EFFORT))

    def test_ask_preserves_request_and_normal_fallback(self):
        client, expected = object(), object()
        kw = {"max_tokens": 16000, "messages": [{"role": "user", "content": "本文"}]}
        with patch.object(db, "run") as run, patch.object(gd, "_create", return_value=expected) as create:
            gd._ask(client, "draft", **kw)
            args = run.call_args
            self.assertEqual(args.args, (client, "draft", kw))
            self.assertEqual(args.kwargs["model"], gd.MODEL)
            self.assertEqual(args.kwargs["effort"], gd.EFFORT)
            self.assertIs(args.kwargs["direct"](), expected)
            create.assert_called_once_with(client, **kw)

    def test_batch_cost_uses_same_price_table(self):
        for model in tl.PRICES:
            self.assertEqual(tl.cost(model, 1000, 2000, batch=True), tl.cost(model, 1000, 2000) / 2)

    def test_record_count_and_price(self):
        with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1] / "build") as d:
            path = pathlib.Path(d) / "usage.json"
            resp = types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=1000, output_tokens=2000))
            tl.record("dialogue", gd.MODEL, resp, path=str(path), batch=True)
            tl.record("dialogue", gd.MODEL, resp, path=str(path))
            day = next(iter(json.loads(path.read_text(encoding="utf-8"))["days"].values()))
            self.assertEqual(day["calls"], 2)
            self.assertEqual(day["by"]["dialogue"]["batch"], 1)
            self.assertAlmostEqual(day["usd"], tl.cost(gd.MODEL, 1000, 2000) * 1.5)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
