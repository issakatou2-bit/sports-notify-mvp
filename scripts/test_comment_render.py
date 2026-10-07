#!/usr/bin/env python3
"""案D「コメント欄ライブ」（comment_render.py）の検査。外部APIは呼ばない（材料は写しの data/ だけ）。

確かめること（指示書 Opus-13）:
  - 絵の大きさが 1080×1920。背景が動き続ける
  - 時刻表と cues（効果音の時刻）が同じ定数から出ていて、音の時刻に絵が実際に動く
  - マーカーの語が said の部分文字列であること（said に無い語は引かない）
  - 吹き出しの文は材料の訳文そのまま（1文字も捨てない・変えない）
  - 材料に無い数字を描かない
  - 大事な文字が安全域（右・下）に入らない

「架空」と書いた文は、形を確かめるための作りものです（実在のコメントではありません）。

動かし方: collespo/ で
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider test_comment_render.py
"""
import json
from unittest.mock import patch
import pathlib
import re
import socket
import sys
import time
import unittest
import urllib.request

from PIL import ImageChops

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import comment_render as cr  # noqa: E402
import review_render_v3 as r3  # noqa: E402
import sfx  # noqa: E402  （comment_render が写しの scripts/ を探す場所に入れている）

NUM = re.compile(r"\d+")
_URLOPEN = urllib.request.urlopen
_CONNECT = socket.socket.connect
FIXTURE = HERE / "fixtures/comment"
_LOAD = patch.object(cr, "load_json", side_effect=lambda name: json.loads((FIXTURE / name).read_text(encoding="utf-8")))
CWS = 145
# 架空の文（検査用の作りもの。数字を含まない）
FAKE_LONG = "架空のコメントです。とても長い文で、吹き出しが画面に入りきらないときの動きを確かめるために書いています。" * 2


def setUpModule():
    cr._no_network()
    _LOAD.start()


def tearDownModule():
    _LOAD.stop()
    urllib.request.urlopen = _URLOPEN
    socket.socket.connect = _CONNECT


def voices_data():
    return cr.load_json("local_voices.json")


def raw(name):
    return (FIXTURE / name).read_text(encoding="utf-8")


def segments():
    return {s["kind"]: s for s in cr.sample_segments(voices_data())}


def topic():
    return next(t for t in cr.load_json("ps_game_topics.json")["topics"]
                if any(h == cr.COMMENT_HEAD for h, _ in t["items"]))


def diff(a, b, box=None):
    a, b = (a.crop(box), b.crop(box)) if box else (a, b)
    d = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v else 0)
    return d.histogram()[255]


AREA = (0, cr.AREA_TOP, cr.W, cr.AREA_BOTTOM)


class Size(unittest.TestCase):
    def test_1080x1920_all_entry_points(self):
        vd = voices_data()
        for seg in segments().values():
            for t in (0.0, 1.0, 3.3, 9.0):
                im = cr.voices_screen(t, seg, vd, 12.0)
                self.assertEqual((im.size, im.mode), ((1080, 1920), "RGB"))
        spec = topic()
        items = [tuple(x) for x in spec["items"]]
        for start in range(0, len(items), 2):
            im = cr.list_page(1.0, spec, items, start, 2, start // 2 + 1, 3, "PSの話題")
            self.assertEqual((im.size, im.mode), ((1080, 1920), "RGB"))
        im = cr.comments(0.5, [], None, "")
        self.assertEqual(im.size, (1080, 1920))

    def test_background_keeps_moving(self):
        vs = [{"said": "架空のコメント", "who": "架空"}]
        a = cr.comments(10.0, vs, CWS, "架空の帯")
        b = cr.comments(10.5, vs, CWS, "架空の帯")
        self.assertGreater(diff(a, b), 1000)          # 帯・輪・立ち絵が動く
        self.assertGreater(diff(a, b, (0, cr.STRIP_Y, cr.W, cr.STRIP_Y + cr.STRIP_H)), 100)

    def test_frame_time(self):
        vd = voices_data()
        seg = segments()["voices"]
        cr.voices_screen(0.0, seg, vd, 30.0)               # 1回目は部品を作る
        ts = []
        for k in range(30):
            a = time.perf_counter()
            cr.voices_screen(k / 24 * 4, seg, vd, 30.0)
            ts.append(time.perf_counter() - a)
        self.assertLess(sum(ts) / len(ts), 0.15)         # 目安は50ms。ゆるい上限


class Cues(unittest.TestCase):
    def test_kinds_exist(self):
        vd = voices_data()
        for seg in segments().values():
            for at, kind, var, db in cr.voices_cues(seg, vd, 20.0):
                self.assertIn(kind, sfx.KINDS)
                self.assertIn(var, ("a", "b"))
                self.assertLessEqual(db, 0)
                self.assertGreaterEqual(at, 0)

    def test_same_timetable_as_drawing(self):
        vs = [{"said": "60年間 Sox ファン", "who": "x", "mark": "60年間 Sox ファン"},
              {"said": "架空の返信", "who": "返信", "mark": "", "reply": True},
              {"said": "架空の事実", "who": "x", "fact": True}]
        c = cr.cues(vs)
        at = cr.start_times(vs)
        self.assertEqual(at, list(cr.BUBBLE_AT))
        self.assertIn((at[0], "notify", "a", -3), c)
        self.assertIn((at[0] + cr.MARK_AFTER, "marker", "a", -4), c)
        self.assertIn((at[1], "notify", "b", -3), c)
        self.assertIn((at[2], "pop", "a", -3), c)
        self.assertEqual(len(c), 4)                       # マーカーの無い吹き出しには marker を鳴らさない

    def test_bubble_appears_at_its_cue(self):
        vs = [{"said": "架空のコメント", "who": "架空"}, {"said": "架空の二つ目", "who": "架空"}]
        for at in cr.start_times(vs):
            before = cr.comments(at - 0.01, vs, CWS, "")
            after = cr.comments(at + cr.RISE, vs, CWS, "")
            self.assertGreater(diff(before, after, AREA), 2000)

    def test_marker_moves_at_its_cue(self):
        vs = [{"said": "架空の語に印を引く", "who": "架空", "mark": "架空の語"}]
        at = cr.start_times(vs)[0] + cr.MARK_AFTER
        a = cr.comments(at - 0.02, vs, CWS, "")
        b = cr.comments(at + cr.MARK_IN, vs, CWS, "")
        c = cr.comments(at + cr.MARK_IN, [dict(vs[0], mark="")], CWS, "")
        self.assertGreater(diff(a, b, AREA), 500)
        self.assertGreater(diff(b, c, AREA), 500)        # 引き終わりは、引かない絵と違う

    def test_timed_follows_narration(self):
        vd = voices_data()
        for seg in segments().values():
            dur = 25.0
            vs = cr.timed(cr.voices_for_segment(seg, vd), seg["text"], dur)
            at = cr.start_times(vs)
            self.assertEqual(at, sorted(at))
            self.assertTrue(all(0 <= a <= dur - cr.RISE for a in at))
            for v, a in zip(vs, at):
                k = seg["text"].find(v["said"].rstrip("。！!、.")[:12])
                if k >= 0:                               # 読み始めるより前に出ている
                    self.assertLessEqual(a, max(cr.BUBBLE_AT[0], dur * k / len(seg["text"])))

    def test_list_cues(self):
        spec = topic()
        items = [tuple(x) for x in spec["items"]]
        self.assertEqual(cr.list_cues(spec, items, 0, 2), r3.cues("list", spec, items, 0, 2))
        k = next(i for i, (h, _) in enumerate(items) if h == cr.COMMENT_HEAD)
        c = cr.list_cues(spec, items, k - k % 2, 2)
        self.assertEqual(c[0], (0.0, "transition", "b", -6))
        self.assertTrue(any(x[1] == "notify" for x in c))


class Marker(unittest.TestCase):
    def all_saids(self):
        vd = voices_data()
        out = []
        for v in vd["voices"]:
            out.append(v["ja"])
            out += [r["ja"] for r in v.get("reply_ja") or []]
        out += [p["jp"] for p in cr.load_json("local_reporters.json")["posts"] if p.get("jp")]
        for t in cr.load_json("ps_game_topics.json")["topics"]:
            out += [cr.unquote(b) for _, b in t["items"]]
        return out

    def test_mark_is_substring_of_said(self):
        for said in self.all_saids():
            m = cr.pick_mark(said)
            if m:
                self.assertIn(m, said)
                self.assertEqual(m, m.strip())
        vd = voices_data()
        for seg in segments().values():
            for v in cr.voices_for_segment(seg, vd):
                if v["mark"]:
                    self.assertIn(v["mark"], v["said"])

    def test_real_comments(self):
        vs = voices_data()["voices"]
        self.assertEqual(cr.pick_mark(vs[0]["ja"]), "3年連続")
        self.assertEqual(cr.pick_mark(vs[1]["ja"]), "60年間 Sox ファン")
        self.assertEqual(cr.pick_mark(vs[2]["ja"]), "White Sox")        # 球団名が数字より前
        self.assertEqual(cr.pick_mark(vs[3]["ja"]), "Sean Burke")       # 選手名（player_kana.json にある）

    def test_rules(self):
        self.assertEqual(cr.pick_mark("シリーズはまだ終わったわけじゃないよ。"), "")
        # 返信先の表示名（@…）の中の数字は語句にしない
        self.assertEqual(cr.pick_mark("@abc3def は Cleveland の終わりで"), "")
        self.assertEqual(cr.pick_mark("11-1で勝ち進んだ"), "11-1")
        self.assertEqual(cr.pick_mark("きのうは村上宗隆が打った"), "村上宗隆")
        self.assertEqual(cr.pick_mark("架空の語", names=("架空の語",)), "架空の語")
        self.assertEqual(cr.pick_mark("地区シリーズ第1戦🧈 架空"), "地区シリーズ第1戦")   # 絵文字で切る
        self.assertEqual(cr.mark_span("abc", "x"), None)
        self.assertEqual(cr.mark_span("abc", ""), None)

    def test_mark_not_in_said_is_not_drawn(self):
        v = {"said": "架空のコメント", "who": "架空"}
        a = cr.comments(5.0, [dict(v, mark="ここに無い語")], CWS, "")
        b = cr.comments(5.0, [dict(v, mark="")], CWS, "")
        self.assertEqual(diff(a, b), 0)
        self.assertEqual([c[1] for c in cr.cues([dict(v, mark="ここに無い語")])], ["notify"])


class Words(unittest.TestCase):
    def test_said_is_the_stored_translation(self):
        vd = voices_data()
        segs = segments()
        picked = segs["voices"]["meta"]["picked"]
        got = [v["said"] for v in cr.voices_for_segment(segs["voices"], vd)]
        self.assertEqual(got, [vd["voices"][i]["ja"].strip() for i in picked][:cr.VOICES_SHOWN])
        th = cr.voices_for_segment(segs["thread"], vd)
        v = vd["voices"][segs["thread"]["meta"]["index"]]
        parent=[] if segs['thread']['meta'].get('parent_read') else [v['ja']]
        self.assertEqual([x["said"] for x in th], parent + [r["ja"] for r in v["reply_ja"][:3]])

    def test_layout_keeps_every_character(self):
        vd = voices_data()
        saids = [v["ja"] for v in vd["voices"]] + [r["ja"] for v in vd["voices"] for r in v.get("reply_ja") or []]
        for said in saids + [FAKE_LONG]:
            for size in cr.SAID_SIZES:
                lines = cr.layout_text(said, size, 600)
                drawn = {i for ln in lines for start, tok, *_ in ln for i in range(start, start + len(tok))}
                for i, ch in enumerate(said):
                    if not ch.isspace():
                        self.assertIn(i, drawn, (said, ch))
                self.assertEqual("".join(tok for ln in lines for _, tok, *_ in ln).replace(" ", ""),
                                 said.replace(" ", "").replace("\n", ""))

    def test_full_width_space_breaks_first(self):
        lines = cr.layout_text("ホワイトソックス ケイ 3分の1回を2失点　ガーディアンズ ウィリアムズ 5回を2失点", 36, 760)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1][0][1], "ガ")

    def test_unquote(self):
        self.assertEqual(cr.unquote("「あ「い」う」"), "あ「い」う")
        self.assertEqual(cr.unquote("「あ"), "「あ")

    def test_items_to_voices(self):
        spec = topic()
        items = [tuple(x) for x in spec["items"]]
        vs = cr.voices_from_items(items, spec)
        for (h, b), v in zip(items, vs):
            self.assertEqual(v["said"], cr.unquote(b))
            self.assertTrue(h.startswith(v["who"].split("　")[0]))
            self.assertEqual(bool(v.get("fact")), not b.startswith("「"))

    def test_no_numbers_outside_material(self):
        vd = voices_data()
        material = raw("local_voices.json")
        for seg in segments().values():
            vs = cr.voices_for_segment(seg, vd)
            for s in cr.texts(vs, cr.strip_for_voices(vd, seg), source_lines=cr._voices_source(vd)):
                for n in NUM.findall(s.replace(",", "")):
                    self.assertIn(n, material, s)
        spec = topic()
        items = [tuple(x) for x in spec["items"]]
        material = raw("ps_game_topics.json")
        for start in range(0, len(items), 2):
            page = items[start:start + 2]
            if not cr.uses_comments(page):
                continue
            for s in cr.texts(cr.voices_from_items(page, spec), cr._strip_of(spec),
                              source_lines=cr._page_source(spec, page)):
                for n in NUM.findall(s):
                    self.assertIn(n, material, s)

    def test_strip_for_voices_is_material(self):
        vd = voices_data()
        s = cr.strip_for_voices(vd, segments()["voices"])
        self.assertIn("ホワイトソックス", s)
        self.assertIn(vd["source"], s)
        self.assertFalse(NUM.search(s))


class Layout(unittest.TestCase):
    def test_safe_area(self):
        vd = voices_data()
        cases = [cr.voices_for_segment(s, vd) for s in segments().values()]
        cases.append(cr.voices_from_items([tuple(x) for x in topic()["items"]], topic()))
        for vs in cases:
            rows, steps = cr.stack(vs)
            for x, y, b in rows:
                self.assertGreaterEqual(x, cr.LEFT)
                self.assertLessEqual(x + b["width"], cr.SAFE_RIGHT)
        self.assertLessEqual(cr.AREA_BOTTOM, cr.SAFE_BOTTOM)
        self.assertLessEqual(cr.SOURCE_Y + 2 * round(cr.SOURCE_SIZE * 1.5), cr.SAFE_BOTTOM)

    def test_real_screens_fit_without_scrolling(self):
        vd = voices_data()
        for seg in segments().values():
            rows, steps = cr.stack(cr.voices_for_segment(seg, vd))
            self.assertEqual(sum(steps), 0)               # 全部が並びに入る（字の大きさで合わせる）
            self.assertEqual(len({b["size"] for _, _, b in rows}), 1)

    def test_too_many_scroll_up(self):
        vs = [{"said": FAKE_LONG, "who": "架空"} for _ in range(5)]
        rows, steps = cr.stack(vs)
        self.assertEqual(rows[0][2]["size"], cr.SAID_SIZES[-1])
        self.assertGreater(sum(steps), 0)
        at = cr.start_times(vs)
        self.assertEqual(cr.scroll_at(0.0, vs), 0)
        self.assertAlmostEqual(cr.scroll_at(at[-1] + cr.SCROLL_IN, vs), sum(steps))
        im = cr.comments(at[-1] + 1.0, vs, CWS, "架空の帯")
        self.assertEqual(im.size, (1080, 1920))

    def test_v3_page_without_comments_is_unchanged(self):
        spec = topic()
        items = [tuple(x) for x in spec["items"]]
        a = cr.list_page(1.0, spec, items, 0, 2, 1, 3, "PSの話題")
        b = r3.list_page(1.0, spec, items, 0, 2, 1, 3, "PSの話題")
        self.assertEqual(diff(a, b), 0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
