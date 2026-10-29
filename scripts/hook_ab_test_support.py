"""A/B試験専用の作り物。日次data/・実時計・実行元の設定を使わない。"""
from datetime import datetime
import os
import unittest
from unittest.mock import patch

import hook_ab


DAY = '2026-10-23'


def press_data():
    # 先頭と同じ主役・論点を3件目にも置き、Bで順番が変わることを検査する。
    return {
        'date': '2026-10-22', 'date_jst': DAY, 'players': [],
        'reporters': {
            'headlines': [
                {'source': '試験媒体A', 'jp': '大谷翔平、チームの敗退を受けて2語の感謝メッセージを投稿'},
                {'source': '試験媒体B', 'jp': '山本由伸が今季の投球を振り返る'},
                {'source': '試験媒体C', 'jp': '大谷翔平がファンへの感謝を伝えた'},
            ],
            'posts': [
                {'outlet': '試験媒体A', 'author': '試験記者',
                 'jp': '大谷翔平がファンへの感謝を伝えた。1年前の今日も同じ思いを語った。'},
            ],
        },
    }


def season_spec():
    return {
        'label': '試験選手のシーズン', 'jp': '試験選手', 'style': 'v3',
        'hook': '10本塁打', 'intro_as_is': True, 'intro': '試験選手のシーズンを振り返ります。',
        'items': [('今季の成績', '10本塁打'), ('自己最多', '10本塁打　昨季は5本塁打')],
        'speech': {'今季の成績': '今季は10本塁打。'},
    }


class HookFixtureTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        # OS/Pythonの設定は残し、試作フラグだけを試験ごとに隔離・復元する。
        env = {k: v for k, v in os.environ.items() if not k.startswith('COLLESPO_')}
        env.update(COLLESPO_HOOK_AB='off', COLLESPO_PRESS_DESIGN='legacy',
                   COLLESPO_SHORT_LOOK='v3', COLLESPO_SOLO_HOST='metan')
        self.enterContext(patch.dict(os.environ, env, clear=True))
        self.enterContext(patch('review_render_v3.LOOK', 'v3'))
        # 環境から別日に差し替えられるのは試験だけ。本体に日付上書き口を作らない。
        self.now = datetime.fromisoformat(env.get('HOOK_AB_TEST_NOW', '2026-10-22T12:00:00+09:00'))
        if self.now.tzinfo is None:
            raise ValueError('HOOK_AB_TEST_NOWにはタイムゾーンを指定してください')
        now = self.now

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)

        self.enterContext(patch.object(hook_ab, 'datetime', Clock))
