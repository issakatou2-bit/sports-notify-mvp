#!/usr/bin/env python3
"""案B「数字ドーン」（bignumber_render.py）の検査。外部APIは呼ばない（材料は写しの data/ だけ）。

確かめること（指示書 Opus-11）:
  - 絵の大きさが 1080×1920
  - 時刻表と cues（効果音の時刻）が同じ定数・同じ配置から出ている
  - 材料に無い数字を描かない（描く数字はすべて、読み上げ・材料の行・順位・日付のどれかにある）
  - 場面の列が、いまの読み上げの順番・数字と1対1に対応している（check_scenes）
  - 大事な文字が安全域（右13%・下18%）と立ち絵の場所に入らない

動かし方: collespo/ で
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider test_bignumber_render.py
"""
import json
import os
import pathlib
import re
import sys
import time
import unittest
import urllib.request

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bignumber_render as bn  # noqa: E402

DATA = HERE / "fixtures/bignumber"
MATERIALS = [DATA / "morning_recap.json"] + sorted((DATA / "recap_history").glob("*.json"))
NUM = re.compile(r"\d+(?:\.\d+)?")
_URLOPEN = urllib.request.urlopen


def setUpModule():
    bn._no_network()


def tearDownModule():
    urllib.request.urlopen = _URLOPEN


def build(path):
    """材料 → (並べた選手, 原稿, 場面)。本番の main と同じく、作業場所はリポジトリの根（写しの src/）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    gms = bn._gms()
    players = gms.sort_players(data.get("players") or [])
    data = dict(data, players=players)
    here = os.getcwd()
    os.chdir(bn.ROOT)
    try:
        narration = gms.build_narration(data, "players")
        scenes = bn.scenes_from_morning(data, narration)
    finally:
        os.chdir(here)
    return data, players, narration, scenes


def allowed_numbers(players, narration):
    """描いてよい数字: 読み上げ・選手の成績の行・順位（1〜人数）。"""
    out = set()
    for s in narration["segments"]:
        out |= set(NUM.findall(s.get("text", "")))
        # 投球回3.1の読み上げは「3回3分の1」。画面は週次材料の原表記を照合する。
        for row in (s.get("meta") or {}).get("week", []):
            out |= set(NUM.findall(row.get("line", "") + row.get("late", "")))
    for p in players:
        out |= set(NUM.findall(p.get("headline", "")))
    out |= {str(i) for i in range(1, len(players) + 1)}
    return out


class PickBig(unittest.TestCase):
    """大きな数字は、材料の行の文字をそのまま切り出す。"""

    def test_batter(self):
        self.assertEqual(bn.pick_big("4打数3安打　2本塁打　3打点", "batter"), ("2", "本塁打"))
        self.assertEqual(bn.pick_big("3打数2安打　2二塁打　3打点　1四球", "batter"), ("3", "打点"))
        self.assertEqual(bn.pick_big("4打数1安打", "batter"), ("1", "安打"))
        self.assertEqual(bn.pick_big("7打数2安打　2四球", "batter"), ("2", "安打"))

    def test_zero_is_not_the_featured_number(self):
        self.assertEqual(bn.pick_big("4打数0安打", "batter"), ("", ""))
        self.assertEqual(bn.pick_big("4打数0安打　2四球", "batter"), ("2", "四球"))
        self.assertEqual(bn.pick_big("0.0回　0奪三振", "pitcher"), ("", ""))
        self.assertEqual(bn.pick_big("0.1回　0奪三振", "pitcher"), ("0.1", "回"))

    def test_pitcher(self):
        self.assertEqual(bn.pick_big("1.1回　0奪三振　自責0　1被安打　ホールド", "pitcher"), ("1.1", "回"))
        self.assertEqual(bn.pick_big("6.2回　5奪三振　防御率5.40　6被安打", "pitcher"), ("6.2", "回"))
        self.assertEqual(bn.pick_big("7.0回　11奪三振　自責1", "pitcher"), ("11", "奪三振"))

    def test_hits_allowed_is_not_hits(self):
        # 投手の「被安打」を打者の「安打」と取り違えない
        self.assertEqual(bn.pick_big("1被安打", "batter"), ("", ""))

    def test_nonzero_alternative_and_rank_keep_the_zero_stat(self):
        p = {"name": "検査選手", "headline": "4打数0安打", "type": "batter"}
        sc = bn._player_scene(p, "4打数0安打。", rank=1)
        sc["segment"] = 0
        nar = {"segments": [{"text": sc["say"]}]}
        self.assertEqual((sc["big"], sc["unit"], sc["tag"]), ("1", "位", "勝利貢献順位"))
        self.assertIn("0安打", sc["sub"])
        self.assertEqual(bn.check_scenes([sc], nar, {"players": [p]}), [])
        self.assertNotEqual(bn.check_scenes([sc], nar), [])
        sc["big"] = "2"
        self.assertNotEqual(bn.check_scenes([sc], nar, {"players": [p]}), [])
        p["headline"] += "　2四球"
        sc = bn._player_scene(p, "4打数0安打、2四球。", rank=1)
        self.assertEqual((sc["big"], sc["unit"]), ("2", "四球"))

    def test_validation_rejects_featured_zero(self):
        nar = {"segments": [{"text": "0安打。"}]}
        self.assertTrue(bn.check_scenes([{"segment": 0, "big": "0", "unit": "安打", "say": "0安打。"}], nar))

    def test_big_is_in_the_line(self):
        for line in ("4打数3安打　2本塁打　3打点", "1.1回　0奪三振　自責0", "3打数1安打　1四球"):
            for kind in ("batter", "pitcher"):
                big, unit = bn.pick_big(line, kind)
                if big:
                    self.assertIn(big + unit, line)


class Numbers(unittest.TestCase):
    """回る・数える途中は画面だけ。止まったら材料の文字そのもの。"""

    def test_roll_ends_exact(self):
        for big in ("0", "3", "1.1", "6.2", "120"):
            spec = {"big": big, "unit": "回", "anim": "roll"}
            self.assertEqual(bn.number_text(bn.T_ROLL[1], spec), big)
            self.assertEqual(bn.number_text(bn.T_ROLL[1] + 3, spec), big)
            mid = bn.number_text((bn.T_ROLL[0] + bn.T_ROLL[1]) / 2, spec)
            self.assertEqual(len(mid), len(big))          # 桁・小数点の形は変わらない
            self.assertEqual(mid.count("."), big.count("."))

    def test_count_never_overshoots(self):
        spec = {"big": "113", "unit": "打点"}
        self.assertEqual(bn.anim_of(spec), "count")
        prev = -1
        for k in range(0, 41):
            t = bn.T_COUNT[0] + (bn.T_COUNT[1] - bn.T_COUNT[0]) * k / 40
            v = int(bn.number_text(t, spec))
            self.assertLessEqual(v, 113)
            self.assertGreaterEqual(v, prev)
            prev = v
        self.assertEqual(bn.number_text(bn.T_COUNT[1], spec), "113")

    def test_what_is_counted(self):
        self.assertEqual(bn.anim_of({"big": "3", "unit": "安打"}), "roll")        # 小さい数は数えない
        self.assertEqual(bn.anim_of({"big": "1.1", "unit": "回"}), "roll")        # 小数は数えない
        self.assertEqual(bn.anim_of({"big": "12", "unit": "位"}), "roll")         # 順位は数えない
        self.assertEqual(bn.anim_of({"big": "10", "unit": "奪三振"}), "count")
        self.assertEqual(bn.anim_of({"big": "1", "unit": "位", "anim": "stamp"}), "stamp")

    def test_stamp(self):
        spec = {"big": "1", "unit": "位", "anim": "stamp"}
        self.assertEqual(bn.number_text(bn.T_STAMP - 0.01, spec), "")
        self.assertEqual(bn.number_text(bn.T_STAMP, spec), "1")


class Morning(unittest.TestCase):
    """17:00 の成績の回の材料（写しの data/）から作った場面。"""

    @classmethod
    def setUpClass(cls):
        cls.built = {p.name: build(p) for p in MATERIALS}

    def test_materials_found(self):
        self.assertGreaterEqual(len(self.built), 3)

    def test_one_to_one_with_narration(self):
        for name, (data, _, narration, scenes) in self.built.items():
            with self.subTest(name):
                self.assertEqual(bn.check_scenes(scenes, narration, data=data), [])
                segs = sorted({s["segment"] for s in scenes})
                self.assertEqual(segs, list(range(len(narration["segments"]))))   # どの画面にも場面がある
                # 場面の順番は読み上げの順番
                self.assertEqual([s["segment"] for s in scenes], sorted(s["segment"] for s in scenes))

    def test_says_in_order(self):
        for name, (_, _, narration, scenes) in self.built.items():
            text = "".join(s["text"] for s in narration["segments"])
            self.assertEqual("".join(s["say"] for s in scenes), text, name)

    def test_no_number_outside_material(self):
        for name, (_, players, narration, scenes) in self.built.items():
            ok = allowed_numbers(players, narration)
            for sc in scenes:
                for text in bn.texts(sc):
                    for n in NUM.findall(text):
                        self.assertIn(n, ok, f"{name}: 「{text}」の {n} は材料に無い")

    def test_big_comes_from_the_line(self):
        for name, (_, players, _, scenes) in self.built.items():
            lines = {p["name"]: p["headline"] for p in players}
            for sc in scenes:
                if sc.get("layout") == "block" and sc.get("head") in lines and sc.get("kind") != "week":
                    self.assertIn(sc["big"] + sc["unit"], lines[sc["head"]], name)
                elif sc.get("kind") == "week" and sc.get("big"):
                    self.assertIn(sc["big"] + sc["unit"], sc["sub"], name)

    def test_top_player_first_then_count(self):
        _, players, _, scenes = self.built["2026-09-25.json"]
        self.assertEqual(scenes[0]["head"], players[0]["name"])
        self.assertEqual((scenes[0]["big"], scenes[0]["unit"]), ("2", "本塁打"))
        self.assertEqual((scenes[1]["big"], scenes[1]["unit"]), (str(len(players)), "人"))

    def test_nothing_dropped_and_safe_area(self):
        for name, (_, _, _, scenes) in self.built.items():
            for sc in scenes:
                L = bn.layout_of(sc)
                self.assertEqual(L["dropped"], [], f"{name}: 入りきらない文字")
                for text, (x0, y0, x1, y1) in bn.boxes(sc):
                    self.assertGreaterEqual(x0, bn.LEFT - 12, text)
                    self.assertLessEqual(x1, bn.SAFE_RIGHT, text)
                    self.assertLessEqual(y1, bn.CONTENT_BOTTOM, text)
                    self.assertLess(y1, bn.SAFE_BOTTOM, text)

    def test_presenter_below_content(self):
        # 立ち絵（左下、上下に揺れても）が文字の下端より下にある
        for who in ("metan", "zundamon"):
            top = bn.SAFE_BOTTOM - 4 - bn.r3._portrait(who).height - bn.BOB_PX
            self.assertGreater(top, bn.CONTENT_BOTTOM)

    def test_skipped_players_still_on_screen(self):
        # 声で成績を読まない選手も、画面には出す（いまの一覧と同じ）
        _, players, _, scenes = self.built["2026-09-25.json"]
        shown = " ".join(t for sc in scenes for t in bn.texts(sc))
        for p in players:
            self.assertIn(p["name"], shown)
            self.assertIn(p["headline"].split("　")[0], shown)


class Frames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, _, narration, scenes = build(DATA / "recap_history" / "2026-09-25.json")
        cls.plan = bn.timeline(scenes, bn.estimate_durations(narration))
        cls.narration = narration

    def test_size(self):
        for s in self.plan[:4]:
            for t in (0.0, 0.2, 0.9, s["dur"] - 0.1):
                im = bn.scene(t, s)
                self.assertEqual(im.size, (1080, 1920))
                self.assertEqual(im.mode, "RGB")
        self.assertEqual(bn.frame(3.0, self.plan).size, (1080, 1920))

    def test_spec_example_from_the_brief(self):
        im = bn.scene(1.0, {"big": "3", "unit": "安打", "head": "大谷翔平", "sub": "4打数3安打", "team_id": 119})
        self.assertEqual(im.size, (1080, 1920))

    def test_background_keeps_moving(self):
        s = self.plan[0]
        a, b = bn.background(2.0, s["team_id"]), bn.background(3.0, s["team_id"])
        self.assertNotEqual(a.tobytes(), b.tobytes())

    def test_timeline_covers_segments(self):
        durs = bn.estimate_durations(self.narration)
        self.assertAlmostEqual(sum(s["dur"] for s in self.plan), sum(durs), places=2)
        for i, d in enumerate(durs):
            got = sum(s["dur"] for s in self.plan if s["segment"] == i)
            self.assertAlmostEqual(got, d, places=2)
        with self.assertRaises(ValueError):
            bn.timeline(self.plan, durs[:1])

    def test_frame_fast_enough(self):
        s = self.plan[0]
        bn.scene(1.0, s)                                    # 部品を作る（1回だけ）
        t0 = time.perf_counter()
        for k in range(24):
            bn.scene(1.0 + k / 24, s)
        ms = (time.perf_counter() - t0) / 24 * 1000
        self.assertLess(ms, 150, f"1コマ {ms:.0f}ms（目安は50ms）")


class Cues(unittest.TestCase):
    """効果音は描画と同じ時刻表から。"""

    def test_kinds_exist(self):
        import sfx
        _, _, narration, scenes = build(DATA / "recap_history" / "2026-09-25.json")
        plan = bn.timeline(scenes, bn.estimate_durations(narration))
        for at, kind, variant, db in bn.plan_cues(plan):
            self.assertIn(kind, sfx.KINDS)
            self.assertIn(variant, ("a", "b"))
            self.assertGreaterEqual(at, 0)

    def test_hero_uses_the_shared_timetable(self):
        spec = {'big':'3','unit':'安打','sub':'4打数3安打'}
        self.assertEqual(bn.cues(spec), bn.r3.cues('intro', bn.unified_spec(spec)))

    def test_count_and_stamp_use_the_shared_reel(self):
        for anim in ('count','stamp','roll'):
            spec={'big':'3','unit':'安打','anim':anim}
            self.assertEqual(bn.cues(spec), bn.r3.cues('intro', bn.unified_spec(spec)))

    def test_chips_follow_shared_entry(self):
        spec={'big':'3','unit':'安打','chips':['検査A','検査B']}
        self.assertEqual(bn.cues(spec), bn.r3.cues('intro', bn.unified_spec(spec)))

    def test_cards_swish(self):
        spec={'cards':[{'title':'甲','body':'3安打'},{'title':'乙','body':'2安打'}]}
        rows=[(c['title'],c['body']) for c in spec['cards']]
        self.assertEqual(bn.cues(spec), bn.r3.cues('list', bn.unified_spec(spec), rows, 0, 2))

    def test_no_cue_after_scene_fades(self):
        spec = {"big": "3", "unit": "安打", "chips": ["マルチ安打"], "team_id": 119, "dur": 1.0}
        for at, *_ in bn.cues(spec):
            self.assertLess(at, 1.0 - bn.T_OUT)


class OtherSegments(unittest.TestCase):
    """ここ7日・あと少しで届く記録の画面（写しの材料では出ない日なので、原稿の形だけで確かめる）。

    下の行は検査のためだけの作り物。見本・本番には使わない。
    """

    def week_narration(self):
        rows = [{"name": "村上宗隆", "type": "batter", "line": "20打数7安打　2本塁打　5打点",
                 "late": "直近3試合は10打数4安打", "trend": "上げてきた"},
                {"name": "松井裕樹", "type": "pitcher", "line": "3登板　3.1回　自責0　4奪三振"}]
        gms = bn._gms()
        # week_line と同じ組み立て（rows を渡せないので、ここで原稿を作る）
        r = rows[0]
        text = (f"ここ7日では、{gms.speech_name(r['name'])}が{gms.yomi_stats(r['line'])}。"
                f"{gms.yomi_stats(r['late'])}で、{r['trend']}ところです。"
                f"{gms.speech_name(rows[1]['name'])}は{gms.yomi_stats(rows[1]['line'])}。")
        return {"label": "9月26日", "segments": [{"kind": "week", "text": text, "meta": {"week": rows}}]}

    def test_week(self):
        nar = self.week_narration()
        scenes = bn.scenes_from_morning({"players": []}, nar)
        self.assertEqual(bn.check_scenes(scenes, nar), [])
        self.assertEqual([(s["big"], s["unit"]) for s in scenes], [("2", "本塁打"), ("3.1", "回")])

    def test_reach(self):
        rows = [{"name": "大谷翔平", "text": "今季50本塁打まで あと2", "gap": 2, "big": "2", "prefix": "あと",
                 "goal_text": "50本塁打", "small": "いま48", "kind": "今季"}]
        text = "あと少しで届く記録です。" + "".join(f"{bn._gms().speech_name(r['name'])}は{r['text']}。" for r in rows)
        nar = {"label": "9月26日", "segments": [{"kind": "reach", "text": text, "meta": {"reach": rows}}]}
        scenes = bn.scenes_from_morning({"players": []}, nar)
        self.assertEqual(bn.check_scenes(scenes, nar), [])
        self.assertEqual(scenes[0]["layout"], "plain")
        self.assertEqual(scenes[0]["big"], "2")

    def test_mismatch_is_reported(self):
        nar = self.week_narration()
        scenes = bn.scenes_from_morning({"players": []}, nar)
        nar["segments"][0]["text"] += "（読み上げが変わった）"
        self.assertNotEqual(bn.check_scenes(scenes, nar), [])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
