import unittest

from shorts_safe_area import problems


class ShortsSafeAreaTest(unittest.TestCase):
    def test_bounds_cover_text_cards_and_faces(self):
        safe = dict(role='caption', box=(0, 160, 940, 1574))
        high = dict(role='text', text='札', box=(50, 159, 150, 200))
        right = dict(role='card', box=(5, 200, 941, 230))
        low = dict(role='face', box=(5, 1400, 100, 1575))
        self.assertEqual([p['outside_shorts_safe_area'] for p in problems([safe, high, right, low])],
                         [high, right, low])
