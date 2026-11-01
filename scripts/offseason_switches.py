"""制作器・通信・描画の依存を持たない、オフの公開条件。"""
from datetime import datetime, timedelta, timezone
import os


def enabled():
    return os.getenv('COLLESPO_OFFSEASON_NEWS') == 'on'


def available(spec, day=None):
    day = day or datetime.now(timezone(timedelta(hours=9))).date()
    return (spec.get('offseason') or {}).get('day') == str(day)
