"""同じ日次実行の初回検査＋追加1回を、APIの直前で数える。秘密は保存しない。"""
import json
import os
from pathlib import Path


class Exhausted(RuntimeError):
    pass


def path():
    value = os.getenv('COLLESPO_SANITY_BUDGET_FILE')
    return Path(value) if value else None


def state():
    target = path()
    if target is None or not target.exists():
        return dict(limit=2, calls=[])
    try:
        value = json.loads(target.read_text(encoding='utf8'))
    except (OSError, ValueError) as error:
        raise Exhausted('常識点検の回数記録を読めません') from error
    if not isinstance(value, dict) or value.get('limit') != 2 or not isinstance(value.get('calls'), list):
        raise Exhausted('常識点検の回数記録が不正です')
    return value


def available():
    return path() is None or len(state()['calls']) < 2


def reserve(label):
    target = path()
    if target is None:
        return
    value = state()
    if len(value['calls']) >= 2:
        raise Exhausted('追加の有料検査は実行全体で1回までです')
    # 通信失敗も消費済み。SDKの自動再試行は呼出し側で無効にする。
    value['calls'].append(label)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
