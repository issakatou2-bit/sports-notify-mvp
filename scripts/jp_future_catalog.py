"""連載の対象名と成功番号。通信・描画の依存を持たない共通表。"""
import json
from pathlib import Path

TITLE = '日本人選手の来季'


def targets(root=Path('data')):
    kana = json.loads((root/'player_kana.json').read_text(encoding='utf-8'))['names']
    season = json.loads((root/'season_topics.json').read_text(encoding='utf-8'))['topics']
    candidates = json.loads((root/'offseason_players.json').read_text(encoding='utf-8'))['players']
    roster = json.loads((root/'roster_snapshot.json').read_text(encoding='utf-8'))['players']
    result = {roster[str(r['player_id'])]['name']: r['jp'] for r in season
              if r.get('jp') and str(r.get('player_id')) in roster}
    for row in candidates:
        if not kana.get(row['name_en']):
            raise ValueError('連載対象の名前がplayer_kanaにありません')
        result[row['name_en']] = kana[row['name_en']]
    return result, kana


def number(state):
    return 1 + max((r.get('series_number', 0) for r in state.get('topics', {}).values()), default=0)
