#!/usr/bin/env python3
"""資産動画v3のカード本文: 禁則の折り返し・球団札と文字の重なり・枠内への収まり。"""
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_asset_video as asset  # noqa: E402
import review_render_v3 as r3  # noqa: E402
import v3_rules as rules  # noqa: E402
import v3_slot_render as common  # noqa: E402

BODIES = [
    "ワールドシリーズ出場3回（今回を含む）　優勝0回",
    "レイズは6年ぶり3回目、ブリュワーズは44年ぶり2回目",
    "2008年　フィリーズに1勝4敗／2020年　ドジャースに2勝4敗",
    "2025年終了時点　今季の30球団中5球団（パドレス、マリナーズ、レイズ、ブリュワーズ、ホワイトソックス）",
]


def materials():
    data = json.loads((ROOT / "data/ws_topics.json").read_text(encoding="utf-8"))
    return data["topics"]


def wrapped(body, width=724):
    return r3.rich_lines(r3._runs(body), width, (196, 206, 212), size=r3.SIZE_M, badges=False)


def line_text(line):
    return "".join(text for _, text, _, _, _ in line)


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def render(topic, start=0, count=2, look="v4"):
    old = r3.LOOK
    r3.LOOK = look
    r3._item_card.cache_clear()
    common.item.cache_clear()
    try:
        spec = topic
        return asset.render_v3(3.0, "list", {"topic": spec["key"], "start": start, "count": count},
                               spec, spec["key"])
    finally:
        r3.LOOK = old
        r3._item_card.cache_clear()
        common.item.cache_clear()


class Kinsoku(unittest.TestCase):
    def test_narrow_width_preserves_kinsoku_and_all_characters(self):
        bodies = BODIES + ['説明「カタカナカタカナカタカナカタカナ」、次の文。',
                           '説明（補足（内側）も含む）です。']
        for body in bodies:
            for width in (180, 240, 360, 500, 724):
                lines = wrapped(body, width)
                self.assertEqual(''.join(line_text(ln) for ln in lines).replace('　', ''),
                                 body.replace('　', ''))
                for ln in lines:
                    value = line_text(ln).strip()
                    self.assertNotIn(value[-1], r3.OPEN_HEAD, (width, value))
                    self.assertNotIn(value[0], r3.CLOSE_HEAD + r3.NO_HEAD + r3.SMALL_HEAD,
                                     (width, value))
                    self.assertTrue(all(x + f.getlength(t) <= width
                                        for x, t, f, _, _ in ln), (width, value))

    def test_open_bracket_never_at_line_end(self):
        for body in BODIES:
            for line in wrapped(body):
                text = line_text(line).rstrip()
                self.assertNotIn(text[-1:], r3.OPEN_HEAD, body)

    def test_close_bracket_and_punctuation_never_at_line_start(self):
        blocked = r3.CLOSE_HEAD + r3.NO_HEAD + r3.SMALL_HEAD
        for body in BODIES:
            for line in wrapped(body):
                text = line_text(line)
                self.assertNotIn(text[:1], blocked, body)

    def test_full_width_space_is_used_as_the_break(self):
        lines = [line_text(line).strip() for line in wrapped(BODIES[2])]
        self.assertEqual(lines[0], "2008年", lines)
        self.assertNotIn("　", "".join(lines))

    def test_parenthetical_kept_together_when_it_fits(self):
        lines = [line_text(line) for line in wrapped(BODIES[0])]
        self.assertIn("（今回を含む）", lines[1], lines)


class Badges(unittest.TestCase):
    def test_badge_style_switch_does_not_reuse_previous_card(self):
        old = r3.LOOK
        r3.LOOK = 'v4'
        try:
            for style in ('', 'pinstripe', ''):
                with patch.dict('os.environ', {'COLLESPO_MLB_BADGE': style}):
                    card = common.item('球団', 'レイズとブリュワーズ', 796,
                                       *r3.colors(None)[:2])
                    badges = card.info['v4_badges']
                    self.assertEqual(len(badges), 2)
                    self.assertTrue(all((b.get('style') == 'pinstripe') == bool(style)
                                        for b in badges), badges)
        finally:
            r3.LOOK = old
            common.item.cache_clear()

    def test_inline_badge_does_not_overlap_text(self):
        for topic in materials():
            for start in range(0, len(topic["items"]), 2):
                im = render(topic, start)
                badges = [b for b in im.info.get("v4_badges", []) if b.get("inline")]
                texts = [e for e in im.info.get("v3_layout", []) if e["role"] == "text"]
                for badge in badges:
                    box = badge["box"]
                    for entry in texts:
                        tbox = entry["box"]
                        inside_badge = (entry["text"] == badge.get("abbr")
                                        and box[0] <= tbox[0] and tbox[2] <= box[2]
                                        and box[1] <= tbox[1] and tbox[3] <= box[3])
                        if inside_badge:
                            continue
                        self.assertFalse(overlap(box, tbox),
                                         (topic["key"], start, badge, entry))

    def test_team_name_starts_after_its_badge(self):
        topic = materials()[0]
        im = render(topic, 0)
        badges = [b for b in im.info.get("v4_badges", []) if b.get("inline")]
        named = [e for e in im.info.get("v3_layout", []) if e["role"] == "text" and e.get("team_id")]
        self.assertTrue(named)
        for entry in named:
            self.assertTrue(any(b.get("team_id") == entry["team_id"]
                                and b["box"][2] <= entry["box"][0] <= b["box"][2] + 24
                                for b in badges), entry)


class Fit(unittest.TestCase):
    def test_narrow_card_keeps_badge_with_team_and_reduces_whole_item(self):
        old = r3.LOOK
        r3.LOOK = 'v4'
        r3._item_card.cache_clear()
        try:
            card = r3._item_card('球団', 'ブリュワーズは44年ぶり2回目', 360,
                                 *r3.colors(None)[:2], quote_height=900)
            named = [e for e in card.info['v3_layout'] if e.get('team_id')]
            self.assertEqual([e['text'] for e in named], ['ブリュワーズ'])
            sizes = {e['v4_font'] for e in card.info['v3_layout'] if 'v4_font' in e}
            self.assertEqual(len(sizes), 1)
            self.assertLess(next(iter(sizes)), r3.SIZE_M)
            badge = card.info['v4_badges'][0]
            self.assertLessEqual(badge['box'][2], named[0]['box'][0])
            self.assertTrue(all(0 <= e['box'][0] <= e['box'][2] <= 360
                                for e in card.info['v3_layout']))
        finally:
            r3.LOOK = old
            r3._item_card.cache_clear()

    def test_quote_card_uses_kinsoku_without_losing_text(self):
        body = '「前半の説明（今回を含む）、さらに詳しい説明です。」'
        card = r3._item_card('番記者', body, 360, *r3.colors(None)[:2], quote_height=900)
        texts = [e['text'] for e in card.info['v3_layout'] if e['role'] == 'text'][1:]
        self.assertEqual(''.join(texts), body)
        for value in texts:
            self.assertNotIn(value[-1], r3.OPEN_HEAD)
            self.assertNotIn(value[0], r3.CLOSE_HEAD + r3.NO_HEAD + r3.SMALL_HEAD)
        self.assertLessEqual(card.height, 900)

    def test_more_lines_before_smaller_uniform_font(self):
        body = BODIES[-1]
        base, second, _ = r3.colors(None)
        for look in ('v3', 'v4'):
            old = r3.LOOK
            r3.LOOK = look
            r3._item_card.cache_clear()
            try:
                tall = r3._item_card('見出し', body, 796, base, second, quote_height=900)
                short = r3._item_card('見出し', body, 796, base, second, quote_height=310)
                tall_sizes = {e['v4_font'] for e in tall.info['v3_layout'] if 'v4_font' in e}
                short_sizes = {e['v4_font'] for e in short.info['v3_layout'] if 'v4_font' in e}
                self.assertEqual(tall_sizes, {r3.SIZE_M})
                self.assertEqual(len(short_sizes), 1)
                self.assertLess(next(iter(short_sizes)), r3.SIZE_M)
                self.assertLessEqual(short.height, 310)
                for card in (tall, short):
                    for entry in card.info['v3_layout']:
                        x, y, right, bottom = entry['box']
                        self.assertTrue(0 <= x <= right <= card.width
                                        and 0 <= y <= bottom <= card.height, entry)
            finally:
                r3.LOOK = old
                r3._item_card.cache_clear()

    def test_one_font_size_per_item(self):
        for body in BODIES:
            card = common.item("見出し", body, 796, *r3.colors(None)[:2], False, 900)
            sizes = {e["v4_font"] for e in card.info.get("v3_layout", []) if "v4_font" in e}
            self.assertEqual(len(sizes), 1, (body, sizes))

    def test_long_text_stays_inside_cards_and_frame(self):
        for topic in materials():
            for start in range(0, len(topic["items"]), 2):
                im = render(topic, start)
                self.assertFalse(rules.check_layout(im), (topic["key"], start))
                cards = [e["box"] for e in im.info.get("v3_layout", []) if e["role"] == "card"]
                texts = [e["box"] for e in im.info.get("v3_layout", []) if e["role"] == "text"]
                for box in texts:
                    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                    inside = [c for c in cards if c[0] <= cx <= c[2] and c[1] <= cy <= c[3]]
                    if not inside:
                        continue
                    card = inside[0]
                    self.assertTrue(card[0] <= box[0] and box[2] <= card[2]
                                    and card[1] <= box[1] and box[3] <= card[3],
                                    (topic["key"], start, card, box))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
