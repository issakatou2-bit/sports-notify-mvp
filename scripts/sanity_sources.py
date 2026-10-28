"""原稿の種類によらない材料の保存・範囲指定。通信やモデルの推測は使わない。"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def key(document):
    original = {k: v for k, v in document.items() if k != '_sanity_document_key'}
    return document.get('_sanity_document_key') or hashlib.sha256(
        json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def for_document(document, materials):
    import sanity_material
    day = sanity_material.document_day(document)
    return [s for s in materials or [] if usable(s) and (
            s.get('document_key') == key(document) or
            (not s.get('document_key') and (not day or
             s.get('used_for_date', s.get('date_jst')) in (day, None))))]


def capture(document, material=None):
    """生成時の入力を保存。空も保存して、後日のファイルで補わない。"""
    import sanity_material
    import soccer_sanity_material
    material = material or {}
    day = sanity_material.document_day(document) or material.get('date')
    sources = list(material.get('_sanity_sources') or [])
    attached_soccer = bool(document.get('soccer_material') or material.get('soccer')
                           or any(s.get('sport') == 'soccer' for s in sources))
    if material.get('race') and '_sanity_sources' not in material:
        sources.append(dict(source='generation.race', date_jst=day,
                            series=material['race'].get('series') or [],
                            source_url='https://statsapi.mlb.com/api/v1/schedule'))
    if material.get('soccer') and '_sanity_sources' not in material:
        sources.append(dict(soccer_sanity_material.compact(dict(
            date_jst=day, competitions=[material['soccer']])), sport='soccer',
            source='generation.soccer'))
    # PS/サッカー専用原稿、試合結果、数字の材料も同じ入口に集める。
    legacy = sanity_material._legacy_grounding([document])
    for source in legacy:
        if source.get('sport') == 'soccer' and any(s.get('sport') == 'soccer' for s in sources):
            continue
        if source.get('series') and any(s.get('series') for s in sources):
            # 原稿添付のPSと当日snapshotの矛盾は従来どおり検出する。
            if '_sanity_sources' in material:
                continue
        sources.append(source)
    for field in ('game_material', 'facts', 'material'):
        if document.get(field):
            sources.append(dict(source='narration.'+field, date_jst=day,
                                **{field: document[field]}))
    for filename in ('soccer_race.json', 'soccer_games.json', 'soccer_results.json',
                     'soccer_preview.json', 'roster_snapshot.json'):
        if filename.startswith('soccer_') and attached_soccer:
            continue
        try:
            data = json.loads((Path('data')/filename).read_text(encoding='utf-8'))
            stamp = data.get('date_jst') or data.get('date') or (data.get('updated_at') or data.get('generated_at') or '')[:10]
            if not day or stamp != day:
                continue
            if filename.startswith('soccer_'):
                source = dict(soccer_sanity_material.compact(data), sport='soccer')
            else:
                text = ' '.join(s.get('text') or '' for s in document.get('segments') or [])
                try:
                    names = json.loads(Path('data/player_kana.json').read_text(encoding='utf-8')).get('names') or {}
                except (OSError, ValueError):
                    names = {}
                import notability_engine
                names = dict(names, **{p['name_en']: p['name_jp'] for p in notability_engine.JP_PLAYERS_MLB})
                players = [dict(p, id=p.get('id') or ident, name_jp=names.get(p.get('name')))
                           for ident, p in (data.get('players') or {}).items()
                           if any(n and n in text for n in (p.get('name'), names.get(p.get('name'))))]
                if not players:
                    continue
                source = dict(players=players, sport='baseball', date_jst=stamp,
                              retrieved_at=data.get('updated_at'),
                              source_url='https://statsapi.mlb.com/api/v1/teams/roster')
            sources.append(dict(source, source='data/'+filename))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return [dict(s, used_for_date=day) for s in sources if usable(s)]


def usable(source):
    if any(source.get(k) for k in ('series', 'games', 'players', 'rows', 'facts')):
        return True
    if any(any(c.get(k) for k in ('jp', 'table', 'lines')) for c in source.get('competitions') or []):
        return True
    for field in ('game_material', 'material'):
        data = source.get(field) or {}
        if any(data.get(k) for k in ('players', 'series', 'rare', 'percentiles')):
            return True
    return False


def collect(documents):
    sources = []
    for document in documents:
        # 明示した空配列は「渡せなかった」。別ファイルを根拠にしない。
        rows = document.get('sanity_materials') if 'sanity_materials' in document else capture(document)
        for source in rows or []:
            if usable(source):
                sources.append(dict(source, document_key=key(document)))
    return sources


def availability(documents, materials):
    return [dict(document_key=key(d), status='材料あり' if for_document(d, materials) else '材料が空',
                 categories={kind: '材料あり' if kind in categories(for_document(d, materials)) else '材料が空'
                             for kind in ('PS', '順位表', '名簿', '試合結果')})
            for d in documents]


def categories(materials):
    result = set()
    for source in materials or []:
        if source.get('series'):
            result.add('PS')
        if source.get('players') or source.get('rows'):
            result.add('名簿')
        if source.get('games') or any(s.get('games') or s.get('results') for s in source.get('series') or []):
            result.add('試合結果')
        for comp in source.get('competitions') or []:
            if any(comp.get(k) for k in ('jp', 'table', 'lines')):
                result.add('順位表')
            if comp.get('jp'):
                result.add('名簿')
        for game in source.get('games') or []:
            if game.get('home_standing') or game.get('away_standing'):
                result.add('順位表')
            if any(game.get(k) for k in ('players', 'jp_players', 'season_players')):
                result.add('名簿')
        if source.get('game_material'):
            result.add('試合結果')
            if source['game_material'].get('players'):
                result.add('名簿')
    return result


def missing_for(issue, document, materials):
    rows = for_document(document, materials)
    if not rows:
        return True
    text, why = issue.get('where') or '', issue.get('why') or ''
    required = set()
    if re.search(r'ワールドシリーズ|\bWS\b|地区シリーズ|リーグ優勝決定|ワイルドカード', text):
        required.add('PS')
    if re.search(r'所属|移籍|選手.*クラブ', why):
        required.add('名簿')
    if re.search(r'順位|勝(?:ち)?点|圏内|圏外|\d+位', text):
        required.add('順位表')
    if not required and re.search(r'スコア|\d+対\d+|勝敗', text+why):
        required.add('試合結果')
    return bool(required - categories(rows))


def attach(document, data, sport=None):
    """各生成器の出口から、実際に使った入力を共通の形で添付する。"""
    import soccer_sanity_material
    import sanity_material
    day = (sanity_material.document_day(document) or data.get('date_jst') or
           data.get('date') or (data.get('generated_at') or data.get('updated_at') or '')[:10])
    if day:
        # 話者の曜日割当へ影響させず、点検用の日付として保存する。
        document['sanity_date_jst'] = day
    if sport == 'soccer':
        document['soccer_material'] = soccer_sanity_material.compact(data)
    embedded = []
    if data.get('games') or data.get('players'):
        embedded.append(dict(source='generation.input', date_jst=day,
            sport=sport or data.get('sport') or 'baseball',
            retrieved_at=data.get('generated_at') or data.get('updated_at'),
            source_url=data.get('source'), games=soccer_sanity_material.compact(data)['games'],
            players=data.get('players') or []))
    document['sanity_materials'] = capture(document) + embedded
    return document
