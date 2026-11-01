import os
import sys
import unittest
from unittest.mock import patch
import outro_next as n

class OutroTest(unittest.TestCase):
    def test_off_exact(self):
        with patch.dict(os.environ, {'COLLESPO_OUTRO_NEXT':'off'}):
            self.assertEqual(n.speech('前半。'+n.LEGACY, '2026-11-02'),'前半。'+n.LEGACY)
    def test_alternate_and_missing(self):
        lineup=[('daily_soccer','欧州サッカー','カード','19:30')]
        with patch.dict(os.environ, {'COLLESPO_OUTRO_NEXT':'on'}):
            plans=[n.choice(day,lineup) for day in ('2026-11-01','2026-11-02')]
            self.assertEqual({p['variant'] for p in plans},{'generic','next'})
            self.assertEqual(n.choice('2026-11-02',[])['variant'],'generic')
            concrete=next(p for p in plans if p['variant']=='next')
            self.assertEqual(n.card(concrete['speech'],'old'),concrete['card'])
            self.assertIn('19時30分',concrete['speech'])
    def test_publication_uses_video_bound_actual_and_excludes_special_outro(self):
        import hashlib, json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'COLLESPO_OUTRO_NEXT':'on'}):
            video=Path(directory)/'test.mp4';video.write_bytes(b'video')
            receipt=video.with_suffix('')/'render_timeline.json';receipt.parent.mkdir()
            with self.assertRaises(ValueError):
                n.publication(video,'2026-11-02',{'segments':[dict(kind='outro',text='コレスポでは毎日、話題を届けています。'+n.LEGACY)]})
            def save(text):
                receipt.write_text(json.dumps(dict(video_sha256=hashlib.sha256(b'video').hexdigest(),lines=[dict(kind='outro',text=text)])),encoding='utf-8')
            plan=n.choice('2026-11-02')
            save('コレスポでは毎日、話題を届けています。'+plan['speech'])
            self.assertEqual(n.publication(video,'2026-11-02')['outro_next']['variant'],'next')
            with self.assertRaises(ValueError):n.publication(video,'2026-11-03')
            save('コレスポでは、オフの動きを追っています。'+n.LEGACY)
            self.assertFalse(n.publication(video,'2026-11-02')['outro_next']['eligible'])
            video.write_bytes(b'changed')
            with self.assertRaises(ValueError):n.publication(video,'2026-11-02')

    def test_existing_outro_unchanged_off(self):
        import review_render_v3 as r
        with patch.dict(os.environ, {'COLLESPO_OUTRO_NEXT':'off'}):
            self.assertEqual(r.outro_text({'ws_completed':False},__import__('datetime').date(2026,7,1)),r.INSEASON_OUTRO_TEXT)

if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
