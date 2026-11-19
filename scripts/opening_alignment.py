"""投稿前に題・冒頭の札・最初の2区間を照合する。公開判断は変えない。"""
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import re
import sys
import unicodedata
from uuid import uuid4

import club_display_names
from number_readings import integer
from render_timeline import opening_card_lines


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def mapping(value):
    return value if isinstance(value, dict) else {}


def text_fields(data, keys):
    return ' '.join(str(data[key]) for key in keys
                    if type(data.get(key)) in (str, int, float) and str(data[key]).strip())


def saved_match_card(first, meta, doc):
    """旧台本に札の文字が無い場合、描画で使う最初の試合だけを読む。"""
    national = mapping(doc.get('national_material'))
    game = mapping(national.get('game'))
    panel = meta.get('panel')
    if game.get('opponent') and panel in ('match', 'score'):
        opponent = game['opponent']
        score = mapping(game.get('score'))
        if panel == 'score' and {'japan', 'opponent'} <= score.keys():
            return f"日本 {score['japan']}-{score['opponent']} {opponent}"
        if panel == 'match' and game.get('kickoff_jst'):
            kickoff = datetime.fromisoformat(game['kickoff_jst'])
            return f'日本対{opponent} {kickoff:%H:%M}'
    data = mapping(doc.get('soccer_material'))
    if first.get('kind') not in ('intro', 'followup') or not meta.get('event_id'):
        return ''
    if meta.get('title_focus_v2') and data.get('games'):
        from soccer_title_v2 import result_focus
        return text_fields(result_focus(data) or {}, ('head', 'score'))
    game = next((g for g in data.get('games', []) if str(g.get('id')) == str(meta['event_id'])), {})
    score = mapping(game.get('score'))
    if {'home', 'away'} <= score.keys():
        home = mapping(game.get('home')).get('name_jp', '')
        away = mapping(game.get('away')).get('name_jp', '')
        return f"{home} {score['home']}-{score['away']} {away}"
    return ''


def opening_text(first, *, layout=None, material=None, document=None, recorded=None):
    """先頭に描く欄だけを使う。題や発話を札の代わりにはしない。"""
    meta = mapping(first.get('meta'))
    document, material = mapping(document), mapping(material)
    for hook in (meta.get('opening_hook'), meta.get('hook'), document.get('opening_hook'),
                 meta.get('press_hook'), material.get('hook')):
        if isinstance(hook, str) and hook.strip():
            return hook, 'hook'
        if isinstance(hook, dict):
            value = text_fields(hook, ('big',)) or text_fields(hook, ('value',))
            if value:
                value += text_fields(hook, ('unit',))
            label = text_fields(hook, ('score', 'subject', 'name', 'head', 'heading', 'sub',
                                       'sub_jp', 'result', 'text', 'note', 'context'))
            if value or label:
                return f'{label} {value}'.strip(), 'hook'
    if recorded:
        return ' '.join(recorded), 'render_timeline'
    if isinstance(layout, list):
        for frame in layout:
            if not isinstance(frame, dict) or frame.get('scene') != 0:
                continue
            parts = opening_card_lines(frame.get('layout', []))
            if parts:
                return ' '.join(parts), 'layout'
    title_focus = mapping(meta.get('title_focus'))
    head = text_fields(meta, ('head', 'heading', 'title', 'name', 'club', 'label'))
    focus = text_fields(title_focus, ('head', 'subject'))
    big = text_fields(meta, ('big',))
    if big:
        big += text_fields(meta, ('unit',))
    saved = ' '.join(part for part in (head, focus, big) if part)
    if saved:
        return saved, 'first_card'
    panel = mapping(mapping(document.get('panels')).get(first.get('panel')))
    if panel:
        saved = text_fields(panel, ('head', 'heading', 'title', 'name', 'subhead'))
        if saved:
            return saved, 'first_card'
    if document.get('kind') == 'dialogue' and first.get('kind') == 'intro' and document.get('top'):
        return text_fields(document, ('top',)), 'first_card'
    match = saved_match_card(first, meta, document)
    if match:
        return match, 'first_card'
    card = mapping(meta.get('card'))
    saved = text_fields(card, ('headline', 'subhead'))
    if saved:
        items = ' '.join(text_fields(mapping(row), ('home', 'away', 'when'))
                         for row in card.get('items', []))
        return (saved + ' ' + items).strip(), 'first_card'
    match = text_fields(mapping(meta.get('top_game')), ('matchup', 'time'))
    if match:
        return match, 'first_card'
    if meta.get('mode'):
        from generate_morning_short import INTRO_HEADINGS
        heading, _ = INTRO_HEADINGS.get(meta['mode'], ('', ''))
        if heading:
            return heading, 'first_card'
    return text_fields(material, ('heading', 'label')), 'material' if material else 'missing'


def normalized(text):
    return unicodedata.normalize('NFKC', text).casefold()


@lru_cache(maxsize=1)
def name_groups():
    import name_reading_guard as names
    from press_names import SHORT_TEAM, SURNAME

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    import notability_engine as ne
    from soccer_national import TEAM_NAMES, squad_source
    from soccer_title_v2 import names as soccer_names

    players = names.player_data()
    reg = {name: {name} for name in set(players['japanese_players']) | set(names.managers())}
    for item in [*ne.JP_PLAYERS_MLB, *ne.JP_PLAYERS_SOCCER]:
        reg.setdefault(item['name_jp'], {item['name_jp']}).add(item.get('name_en'))
    for alias, name in players.get('reading_aliases', {}).items():
        reg.setdefault(name, {name}).add(alias)
    for name, surname in {**soccer_names()['players'], **SURNAME}.items():
        reg.setdefault(name, {name}).add(surname)
    reads = {**names.player_readings(), **names.managers()}
    # 追跡対象の選手以外も、代表回では公式招集名簿と確認済みの表を使う。
    confirmed = mapping(read(names.ROOT / 'data/soccer_player_names.json')).get('players', [])
    squad = mapping(read(names.ROOT / 'data/soccer_national_squad.json'))
    try:
        squad_source(squad)
    except ValueError:
        squad = {}
    for player in [*(row for row in confirmed if row.get('status') == 'confirmed'),
                   *squad.get('players', [])]:
        if name := player.get('name_jp'):
            reg.setdefault(name, {name}).add(player.get('name_en'))
            if player.get('reading'):
                reads.setdefault(name, player['reading'])
    opponents = mapping(read(names.ROOT / 'data/soccer_national_opponent_names.json'))
    for english, row in opponents.items():
        name = row['name']
        reg.setdefault(name, {name}).update((english, row.get('short')))
        reads.setdefault(name, row.get('reading'))
    groups = [(name, aliases, {reads.get(name)}) for name, aliases in reg.items()]
    groups += [(name, {name, english, SHORT_TEAM.get(name)}, set())
               for english, name in ne.MLB_TEAM_NAME_JP.items()]
    club_aliases = soccer_names()['clubs']
    groups += [(row['display'], {row['current'], row['display'], row['legacy'],
                row['short'], club_aliases.get(row['display']), *row.get('aliases', [])}, {row.get('reading')})
               for row in club_display_names.rows()]
    groups += [(name, {name, english}, set()) for english, name in TEAM_NAMES.items()]
    return groups


def mentions(label, text):
    label = normalized(label)
    if label == '日本':
        return re.search(r'日本(?!人|時間|語)', text)
    if label.isascii():
        return re.search(r'(?<![a-z0-9])' + re.escape(label) + r'(?![a-z0-9])', text)
    pattern = re.escape(label).replace('・', '[・ ]?').replace(r'\ ', '[・ ]?')
    if re.fullmatch(r'[ァ-ヿー ]+', label):
        pattern = rf'(?<![ァ-ヿー]){pattern}(?![ァ-ヿー])'
    return re.search(pattern, text)


def subjects(title, opening, voice, extra=()):
    hits = []
    for name, labels, readings in [*name_groups(), *((name, {name}, set()) for name in extra)]:
        matches = [m for label in labels if label and len(label) >= 2
                   and (not label.isascii() or len(label) >= 4 or label == name) and (m := mentions(label, title))]
        if not matches:
            continue
        match = max(matches, key=lambda m: (m.end() - m.start(), -m.start()))
        hits.append((match.start(), match.end(), name, labels, readings))
    result, used, occupied = [], set(), set()
    for start, end, name, labels, readings in sorted(hits, key=lambda x: (-(x[1] - x[0]), x[0], x[2])):
        span = set(range(start, end))
        if name in used or span & occupied:
            continue
        result.append(dict(subject=name, opening=any(mentions(label, opening) for label in labels if label),
                           voice=any(mentions(label, voice) for label in labels | readings if label)))
        used.add(name)
        occupied.update(span)
    return result


SCORE = re.compile(r'(?<![\d-])(\d{1,2})\s*(?:対|[-–−])\s*(\d{1,2})(?![\d-])')
CLOCK = re.compile(r'(\d{1,2})(?::([0-5]\d)|時(?:\s*([0-5]?\d)分)?)')
DATE = re.compile(r'\d{4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,2}|(?<!\d)\d{1,2}/\d{1,2}(?!\d)'
                  r'|(?<!\d)\d{4}年(?!ぶり|間|連続)|(?<!\d)\d{1,2}(?:月|日)(?!ぶり|間|連続)')
UNIT = (r'アシスト|ホームラン|本塁打|奪三振|三振|打点|安打|盗塁|イニング|試合|連続|連勝|連敗'
        r'|チーム|カード|人|得点|点|勝|敗|位|戦|部|回|本|号|分間|分|秒|日ぶり|年ぶり|日間|年間|%|億円|万円|円')
METRIC = re.compile(r'(勝点|勝ち点|防御率|打率|出塁率|ops|whip|era|投球数|ゲーム差)\s*$')
DIGITS = re.compile(rf'(?<![a-z0-9])((?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?|\.\d+)\s*({UNIT})?')
KANJI = re.compile(rf'([〇零一二三四五六七八九十百千万]+)\s*({UNIT})')


def numbers(text):
    """試合の数字を比較するためのキーと表示を返す。日付・年代・U21等を外す。"""
    text = DATE.sub(' ', text)
    result = {}
    for rx, kind in ((SCORE, 'score'), (CLOCK, 'time')):
        for match in rx.finditer(text):
            value = (int(match[1]), int(match[2] or (match[3] if kind == 'time' else 0) or 0))
            result.setdefault((kind, value, ''), match[0])
        text = rx.sub(' ', text)
    for rx in (DIGITS, KANJI):
        for match in rx.finditer(text):
            raw, unit = match.groups()
            if raw in ('一',) and unit in ('戦', '部'):
                # 「一戦」「一部」は多くが一般語。第/リーグで明示した場合には数える。
                if not text[:match.start()].endswith(('第', 'リーグ')):
                    continue
            if unit is None and (len(raw) == 4 and raw.isdecimal() or
                                 re.match(r'[a-z0-9]', text[match.end():])):
                continue
            value = integer(raw) if rx is KANJI else float(raw.replace(',', ''))
            metric = METRIC.search(text[:match.start()])
            if metric and not unit:
                unit = {'勝ち点': '勝点', 'era': '防御率'}.get(metric[1], metric[1])
            unit = {'ホームラン': '本塁打', '点': '得点', '分間': '分'}.get(unit, unit or '')
            result.setdefault(('amount', value, unit), text[metric.start():match.end()].strip()
                              if metric else match[0].strip())
    return result


def has_number(key, evidence):
    kind, value, unit = key
    return key in evidence or (not unit and any(other[:2] == (kind, value) for other in evidence))


def inspect(title, document, *, layout=None, material=None, recorded=None):
    segments = mapping(document).get('segments') or []
    lines = [mapping(seg).get('text') for seg in segments[:2]]
    voice = ' '.join(x for x in lines if isinstance(x, str))
    first = mapping(segments[0]) if segments else {}
    opening, source = opening_text(first, layout=layout, material=material, document=document, recorded=recorded)
    title = str(title or '')
    head = normalized(re.sub(r'#shorts\b', '', title, flags=re.I))
    meta = mapping(first.get('meta'))
    hook = mapping(meta.get('opening_hook') or meta.get('hook'))
    extras = [value for data in (hook, meta) for key in ('subject', 'name', 'club')
              if isinstance((value := data.get(key)), str) and value and not re.search(r'\d|[。、]', value)]
    entities = subjects(head, normalized(opening), normalized(voice), extras) if head else []
    visual, spoken = numbers(normalized(opening)), numbers(normalized(voice))
    facts = [dict(number=label, opening=has_number(key, visual), voice=has_number(key, spoken))
             for key, label in numbers(head).items()]
    warnings = []
    if opening:
        warnings.extend(dict(code='subject_missing_from_opening', value=row['subject'])
                        for row in entities if not row['opening'])
    if opening and voice:
        warnings.extend(dict(code='number_missing_from_opening_and_voice', value=row['number'])
                        for row in facts if not (row['opening'] or row['voice']))
    missing = [label for label, value in (('title', title), ('opening', opening), ('voice', voice)) if not value.strip()]
    return dict(title=title, opening=opening, opening_source=source, speech=lines, subjects=entities,
                numbers=facts, missing=missing, warnings=warnings)


def before_upload(title, narration, video, kind, *, asset_topic=None, prefer_adjacent=False):
    """書き込みや照合が失敗しても、既存の投稿処理へ戻る。"""
    try:
        video, narration = Path(video), Path(narration)
        local_narration = video.parent / 'narration.json'
        if prefer_adjacent and local_narration.is_file():
            narration = local_narration
        layout = read(video.parent / 'layout_checks.json')
        # 動画ごとの時刻表を使い、出力フォルダを共用する別回と混ぜない。
        recorded = mapping(read(video.with_suffix('') / 'render_timeline.json')).get('opening_card')
        material = None
        if asset_topic:
            import generate_asset_video
            material = generate_asset_video.LIST_TOPICS.get(asset_topic)
            if not material:
                import generated_topics
                material = generated_topics.get(asset_topic)
        report = inspect(title, read(narration), layout=layout, material=material, recorded=recorded)
        report.update(kind=kind, narration=str(narration), video=str(video))
        for warning in report['warnings']:
            print(f"[warn] 題と冒頭の照合 [{kind}] {warning['code']}: {warning['value']}")
        if report['missing']:
            print(f"[info] 題と冒頭の照合 [{kind}] 未確認: {', '.join(report['missing'])}")
        folder = Path('build/opening_alignment')
        from voice_manifest import write_json
        write_json(folder / f'{video.stem}-{uuid4().hex[:12]}.json', report)
    except Exception as exc:
        print(f'[warn] 題と冒頭の照合を記録できませんでした [{kind}] {type(exc).__name__}')
