import sys
from pathlib import Path
sys.path[:0]=['scripts','.']
import review_render_v3 as r3
import characters
shared=Path.cwd().parents[1]
r3.ROOT=shared
characters.PORTRAIT_DIR=str(shared/'assets/portraits')
import unittest
suite=unittest.TestSuite()
for pattern in ('test_market_art.py','test_offseason_market.py','test_offseason_public.py','test_offseason_outro.py'):
    suite.addTests(unittest.defaultTestLoader.discover('scripts',pattern=pattern))
with Path('build_reports/market_art_20261106/related_tests.log').open('w',encoding='utf-8') as log:
    sys.stdout=sys.stderr=log
    result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
