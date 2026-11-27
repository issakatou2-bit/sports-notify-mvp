import unittest

from shorts_safe_area import problems


class ShortsSafeAreaTest(unittest.TestCase):
    def test_bounds_cover_text_cards_and_faces(self):
        safe = dict(role='caption', box=(0, 160, 930, 1440))
        high = dict(role='text', text='札', box=(50, 159, 150, 200))
        right = dict(role='card', box=(5, 200, 931, 230))
        low = dict(role='face', box=(5, 1400, 100, 1441))
        self.assertEqual([p['outside_shorts_safe_area'] for p in problems([safe, high, right, low])],
                         [high, right, low])

    def test_corner_face_may_reach_1480_only(self):
        # 11/27 ずんだもんをめたんと同じ大きさにし、足を下端に付けると顎が1471になる
        corner = dict(role='face', box=(110, 1340, 243, 1474), corner_face=True)
        too_low = dict(role='face', box=(110, 1340, 243, 1481), corner_face=True)
        plain = dict(role='face', box=(110, 1340, 243, 1474))
        caption = dict(role='caption', box=(64, 990, 930, 1474), corner_face=True)
        self.assertEqual([p['outside_shorts_safe_area'] for p in problems([corner, too_low, plain, caption])],
                         [too_low, plain, caption])

    def test_both_corner_busts_are_the_same_size(self):
        import characters
        self.assertEqual(characters.CORNER_HEIGHTS['zundamon'], characters.CORNER_HEIGHTS['metan'])
