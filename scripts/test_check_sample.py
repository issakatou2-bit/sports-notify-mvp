import unittest

import numpy as np

import check_sample


class CheckSampleTest(unittest.TestCase):
    def test_tone_echo_and_prediction(self):
        rows = [
            dict(speaker=2, text='勝点は28です。'),
            dict(speaker=3, text='勝点28なのですね。'),
            dict(speaker=3, text='並べて見えてきたのだ。'),
            dict(speaker=2, text='勝点差は2よ。'),
            dict(speaker=3, text='次で入れ替わるかもしれないのだ？'),
        ]
        self.assertEqual(len(check_sample.script_issues(rows)), 3)

    def test_geometry_rejects_face_overlap_outward_and_listener_motion(self):
        face = [30, 1200, 120, 1280]
        frame = dict(layout=[dict(role='face', box=face),
                             dict(role='caption', box=[0, 1300, 931, 1440]),
                             dict(role='symbol', box=[110, 1200, 140, 1230])],
                     portraits=[dict(who='zundamon', face=face, side='left', facing='left', dy=1)])
        self.assertEqual(len(check_sample.geometry_issues(frame, [1080, 1920])), 4)

    def test_fixed_regions_reject_coherent_shake_but_allow_lighting_change(self):
        rng = np.random.default_rng(1)
        frame = rng.integers(0, 200, (480, 270)).astype('float32')
        self.assertTrue(check_sample.translation(frame, np.roll(frame, 2, axis=1)))
        self.assertFalse(check_sample.translation(frame, frame + 8))


if __name__ == '__main__':
    unittest.main(argv=[__file__])
