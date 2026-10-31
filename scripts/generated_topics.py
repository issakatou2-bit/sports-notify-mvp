#!/usr/bin/env python3
"""
公式APIから自動で作った資産動画のトピックを、1か所から読む。

なぜ1か所なのか:
  トピックの材料を作るスクリプト(venue_topics.py / team_topics.py)が
  増えると、それを読む側も増える。動画の生成、タイトル、説明文、
  サムネイル、在庫の検査。5か所が別々にファイル名を並べていると、
  次に材料を足したとき必ずどこか1つを直し忘れる。

  そういう直し忘れで、夕方の投稿記録が2日ぶん消えたことがある。
  読む口は1つにしておく。

使い方(他のスクリプトから):
  import generated_topics as gt
  gt.all_topics()            # {キー: 材料} をまとめて
  gt.get("venue_comerica_park")
  gt.keys()
"""

import json
import pathlib
import sys
from datetime import datetime, timezone
import ps_offseason

# 材料を持つファイル。増えるときはここだけに足す。
SOURCES = (
    "data/venue_topics.json",   # 球場 (venue_topics.py)
    "data/team_topics.json",    # 球団 (team_topics.py)
    "data/rare_topics.json",    # 名前のある指標 (rare_topics.py)
    "data/legend_topics.json",  # 球団の殿堂入り選手 (legend_topics.py)
    "data/season_topics.json",  # シーズンを終えた球団・選手のまとめ (season_topics.py)
    "data/ps_story_topics.json",  # PSの話題：決着したシリーズで何が起きたか (ps_story.py)
    "data/ps_game_topics.json",   # PSの話題：その日に終わった試合で何が起きたか (ps_game_story.py)
    "data/ps_odds_topics.json",   # PSの話題：2勝0敗・0勝2敗を過去の同じ状況から (ps_odds.py)
    "data/ps_momentum_topics.json",  # PSの話題：連勝・敵地での勝ちの流れ (ps_momentum.py)
    "data/ps_spotlight_topics.json",  # PSの話題：日本人投手の圧巻の投球 (ps_spotlight.py)
    "data/ws_topics.json",         # WSの話題：球団史・日程と本拠地 (ws_topics.py)
    "data/offseason_topics.json",  # オフの公式発表。専用の公開変数がonの時だけ。
)

_CACHE = None
DAILY_PS_SOURCES = frozenset({'ps_game_topics.json', 'ps_odds_topics.json',
    'ps_momentum_topics.json', 'ps_spotlight_topics.json', 'ws_topics.json'})


def all_topics(sources=SOURCES, refresh: bool = False) -> dict:
    """{キー: 材料}。読めないファイルは黙って飛ばす。"""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    out = {}
    seasons = {}
    try:
        snapshot = json.loads(pathlib.Path('data/postseason.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        snapshot = {}
    ended = ps_offseason.completed_before(snapshot, datetime.now(timezone.utc))
    for path in sources:
        if pathlib.Path(path).name == 'offseason_topics.json':
            import offseason_switches
            if not offseason_switches.enabled():
                continue
        if ended and pathlib.Path(path).name in DAILY_PS_SOURCES:
            print(f'[info] {path}: WS決着後の当日向け材料は見送り', file=sys.stderr)
            continue
        try:
            d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for spec in d.get("topics") or []:
            if spec.get('offseason'):
                import offseason_switches
                if not offseason_switches.enabled() or not offseason_switches.available(spec):
                    continue
            key = spec.get("key")
            if key and key not in out:
                out[key] = spec
                seasons[key] = d.get('season')
    import short_context
    for key, spec in list(out.items()):
        if key.startswith('rare_'):
            out[key] = short_context.rare(spec, out, seasons.get(key))
    _CACHE = out
    return out


def get(key: str) -> dict:
    return all_topics().get(key) or {}


def keys() -> set:
    return set(all_topics())
