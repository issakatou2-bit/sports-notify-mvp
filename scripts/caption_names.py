"""英語字幕の固有名詞表。MLB公式表記は既存の共通名簿を参照する。
出典: https://www.mlb.com/team / https://www.mlb.com/players
名簿の更新元: notability_engine.MLB_TEAM_NAME_EN / JP_PLAYERS_MLB。
"""
import json
import re
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import notability_engine as ne


def names():
    table = {ne.MLB_TEAM_NAME_JP[key]: value for key, value in ne.MLB_TEAM_NAME_EN.items()}
    # Keys originate from MLB Stats API; kana is only an alias, never the English source.
    p = pathlib.Path(__file__).resolve().parents[1]/'data/player_kana.json'
    for english, kana in json.loads(p.read_text(encoding='utf-8')).get('names', {}).items():
        if kana and re.fullmatch(r"[A-Za-z .’'\-]+", english):
            table[kana] = english
    for player in ne.JP_PLAYERS_MLB:
        table[player['name_jp']] = player['name_en']
        if player.get('kana'):
            table[player['kana']] = player['name_en']
    return table


def required(text):
    return {ja: en for ja, en in names().items() if ja in text}
