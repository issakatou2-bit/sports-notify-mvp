"""立ち絵に腕が描かれているか（11/22 本人「キャラに腕がないように見える」）。

部品式の立ち絵は、体・腕・眉・目・口が別の絵になっている。
組み立てで腕を重ね忘れると、腕の無い立ち絵のまま公開される。
人が見つける前に、ここで止める。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import characters  # noqa: E402
import video_common as vc  # noqa: E402


class PortraitArms(unittest.TestCase):
    def test_every_short_face_draws_both_arms(self):
        faces = sorted({k for k in vc.FACES if k.startswith("v4_")}) or ["v4_base"]
        for who in characters.NAMES.values():
            parts = vc._parts(who, characters.PORTRAIT_DIR)
            if not parts or "1枚" in parts:
                continue
            body = parts["体"]
            for side in ("右腕", "左腕"):
                arm = (parts.get(side) or {}).get("基本")
                self.assertIsNotNone(arm, f"{who} の {side}_基本 の部品がありません")
                mask = arm.getchannel("A").point(lambda v: 255 if v > 200 else 0)
                box = mask.getbbox()
                self.assertIsNotNone(box)
                for expr in faces[:12]:
                    with self.subTest(who=who, side=side, face=expr):
                        vc._FACE_CACHE.clear()
                        art = vc.face(who, body.height, expr, characters.PORTRAIT_DIR)
                        self.assertEqual(art.size, body.size)
                        # 腕の濃い所が、組み上がりにも同じ色で残っているか。
                        a = arm.crop(box).convert("RGBA")
                        b = art.crop(box).convert("RGBA")
                        m = mask.crop(box)
                        total = kept = 0
                        for pa, pb, pm in zip(a.getdata(), b.getdata(), m.getdata()):
                            if not pm:
                                continue
                            total += 1
                            if pb[3] > 200 and max(abs(pa[i] - pb[i]) for i in range(3)) < 40:
                                kept += 1
                        self.assertGreater(total, 0)
                        self.assertGreaterEqual(kept / total, 0.9,
                                                f"{who} の {side} が組み上がりにほとんど出ていません")


if __name__ == "__main__":
    unittest.main(argv=[__file__])
