#!/usr/bin/env python3
"""日次記録に最後に載った日を調べる内部資料。

記録にない日は欠場とは限らず、日数から復帰は予測できない。
この記録だけで見出しを作る旧機能は9/12に撤廃した。
"""

import datetime
import json
import pathlib

# 内部比較の対象範囲。ILや復帰可能日の判定には使用しない。
MIN_GAP = 3
MAX_GAP = 10

HISTORY = "data/recap_history"


def last_seen(folder: str = HISTORY) -> dict:
    """日本人選手ごとの、最後に出場した日。

    返すのは {名前: {"date": 日付, "player_id": ..., "type": ...}}。
    """
    out = {}
    for f in sorted(pathlib.Path(folder).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = d.get("date_jst") or f.stem
        for p in (d.get("players") or []):
            name = p.get("name")
            if not name:
                continue
            out[name] = {"date": day,
                         "player_id": p.get("player_id"),
                         "type": p.get("type") or ""}
    return out


def _parse(day: str):
    try:
        return datetime.date.fromisoformat(day)
    except (TypeError, ValueError):
        return None


def gaps(target_day, folder: str = HISTORY) -> dict:
    """その日に出れば「何日ぶり」になるかを、打者について返す。

    target_day は日付か "2026-09-08" の文字列。
    明日の回で使うので、渡すのは**明日**の日付。
    """
    if isinstance(target_day, str):
        target_day = _parse(target_day)
    if not target_day:
        return {}
    out = {}
    for name, info in last_seen(folder).items():
        if info.get("type") == "pitcher":
            continue
        seen = _parse(info.get("date"))
        if not seen:
            continue
        gap = (target_day - seen).days
        if MIN_GAP <= gap <= MAX_GAP:
            out[name] = {"gap": gap, "since": info["date"],
                         "player_id": info.get("player_id")}
    return out


def hook_for(names, target_day, folder: str = HISTORY) -> dict:
    """Deprecated: appearance gaps alone never justify a return preview."""
    return {}
