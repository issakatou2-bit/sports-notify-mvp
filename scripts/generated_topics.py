#!/usr/bin/env python3
"""
公式APIから自動で作った資産動画のトピックを、1か所から読む。

なぜ1か所なのか:
  トピックの材料を作るスクリプト(venue_topics.py / team_topics.py)が
  増えると、それを読む側も増える。動画の生成、タイトル、説明文、
  サムネイル、在庫の検査。5か所が別々にファイル名を並べていると、
  次に材料を足したとき必ずどこか1つを直し忘れる。

  そういう直し忘れで、朝の投稿記録が2日ぶん消えたことがある。
  読む口は1つにしておく。

使い方(他のスクリプトから):
  import generated_topics as gt
  gt.all_topics()            # {キー: 材料} をまとめて
  gt.get("venue_comerica_park")
  gt.keys()
"""

import json
import pathlib

# 材料を持つファイル。増えるときはここだけに足す。
SOURCES = (
    "data/venue_topics.json",   # 球場 (venue_topics.py)
    "data/team_topics.json",    # 球団 (team_topics.py)
)

_CACHE = None


def all_topics(sources=SOURCES, refresh: bool = False) -> dict:
    """{キー: 材料}。読めないファイルは黙って飛ばす。"""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    out = {}
    for path in sources:
        try:
            d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for spec in d.get("topics") or []:
            key = spec.get("key")
            if key and key not in out:
                out[key] = spec
    _CACHE = out
    return out


def get(key: str) -> dict:
    return all_topics().get(key) or {}


def keys() -> set:
    return set(all_topics())
