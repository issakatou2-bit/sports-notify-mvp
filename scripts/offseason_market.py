"""手入力した市場材料。確定と報道を分け、保存行以外の数字を生成しない。"""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import TypedDict, NotRequired
from urllib.parse import urlsplit

PATH = Path('data/offseason_market.json')
PREFIX = 'offseason_market_'
JST = timezone(timedelta(hours=9))
DESCRIPTION = '連載「日本人選手の来季」では、確定した動きと媒体による報道を分けて追います。'
OUTRO_TEXT = __import__('short_common').OUTRO_TEXT


class Fact(TypedDict):
    id: str
    label: str
    text: str
    source_url: str
    illustration: NotRequired[str]


class Report(Fact):
    outlet: str


class Entry(TypedDict):
    id: str
    title: str
    name_en: str
    checked_on: str
    facts: list[Fact]
    reports: list[Report]
    illustration: NotRequired[str]
    market_kind: NotRequired[str]


def source(url, sample=False):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not host or parsed.username or parsed.password:
        raise ValueError('出典は資格情報なしのHTTPS URLが必要です')
    if (any(host == h or host.endswith('.' + h) for h in
            ('5ch.net', '2ch.net', '2ch.sc', 'reddit.com', 'redd.it'))
            or ('yahoo.' in host and re.search(r'comment|comments', url, re.I))):
        raise ValueError('コメント・掲示板は市場の材料にできません')
    if not sample and (host == 'example.com' or host.endswith('.example.com')):
        raise ValueError('試験用URLは本番に使えません')


def validate(entry, *, sample=False):
    import jp_future_catalog as series
    if not isinstance(entry, dict) or not {'id', 'title', 'name_en', 'checked_on', 'facts', 'reports'} <= set(entry) <= {'id', 'title', 'name_en', 'checked_on', 'facts', 'reports', 'illustration', 'market_kind'}:
        raise ValueError('市場項目の欄が書式と不一致です')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', entry['id']):
        raise ValueError('市場項目IDが不正です')
    jp, _ = series.targets()
    name = jp.get(entry['name_en'])
    title = entry['title']
    if not name or not isinstance(title, str) or not title.startswith(name + ' ') or len(title) > 36 or any(x in title for x in ('、', '？', '?', '\n')):
        raise ValueError('題は対象選手の日本語名＋短い結論にしてください')
    if re.search(r'予想|予測|見込み|見通し|可能性|有力|候補|ドル|億円|万円|\$|年俸|契約金|総額', title):
        raise ValueError('金額や行先予想は題で断定せず、媒体名つきの報道行で伝えてください')
    date.fromisoformat(entry['checked_on'])
    texts, ids = set(), set()
    for kind in ('facts', 'reports'):
        if not isinstance(entry[kind], list):
            raise ValueError('確定と報道は別の配列にしてください')
        for row in entry[kind]:
            fields = {'id', 'label', 'text', 'source_url'} | ({'outlet'} if kind == 'reports' else set())
            if not isinstance(row, dict) or not fields <= set(row) <= fields | {'illustration'} or not all(isinstance(v, str) and v.strip() == v and v for v in row.values()):
                raise ValueError('市場の行の欄が不正です')
            if row['id'] in ids or row['text'] in texts or not re.fullmatch(r'[a-z0-9_-]+', row['id']):
                raise ValueError('同じ情報の重複や不正な行IDです')
            if len(row['label']) > 24 or len(row['text']) > 150 or '\n' in row['text'] or not row['text'].endswith('。') or row['text'].endswith('。。'):
                raise ValueError('市場の行は短い見出しと句点つき本文が必要です')
            if (not re.search(r'(?:です|ます|でした|ました|ません)。$', row['text'])
                    or __import__('ui_tone').text(row['text']) != row['text']):
                raise ValueError('本文は口調の自動整形で変わらない敬語にしてください')
            source(row['source_url'], sample)
            if kind == 'reports':
                outlet = row['outlet']
                if (len(outlet) > 24 or re.search(r'5ch|Yahoo.*コメント|Reddit|コメント主|[。\n]', outlet, re.I)
                        or not re.fullmatch(r'.+と' + re.escape(outlet) + r'が報じています。', row['text'])
                        or '。' in row['text'][:-1]):
                    raise ValueError('報道は「〜と媒体名が報じています。」の1文にしてください')
            elif re.search(r'予想|予測|見込み|見通し|可能性|有力|候補|報じ|とみられ|ドル|億円|万円|\$|年俸|契約金|総額', row['text']):
                raise ValueError('金額や移籍先の予想・報道は報道の欄にしてください')
            if re.search(r'5ch|Yahoo.*コメント|Reddit|コメント主|u/', row['text'], re.I):
                raise ValueError('掲示板やコメント主を本文に出せません')
            ids.add(row['id'])
            texts.add(row['text'])
    if len(ids) < 3:
        raise ValueError('市場の材料は重複しない情報3つ以上が必要です')
    if set(re.findall(r'\d+', title)) - set(re.findall(r'\d+', ''.join(r['text'] for r in entry['facts']))):
        raise ValueError('題の数字が確定の材料行にありません')
    __import__('market_art').entry_rows(entry, sample=sample)
    return name


def topic(entry, day, state=None, *, episode=None, sample=False):
    import jp_future_catalog as series
    validate(entry, sample=sample)
    if entry['checked_on'] != str(day):
        return None
    digest = hashlib.sha256(json.dumps(entry, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    n = episode or series.number(state or {})
    events = [dict(event_id=f'market:{entry["id"]}:{kind}:{row["id"]}',
                   head=('確定｜' if kind == 'facts' else '報道｜') + row['label'],
                   body=row['text'], source=row['source_url'], market_type=kind,
                   **({'illustration': selected} if (selected := __import__('market_art').selected_name(entry, row)) is not None else {}))
              for kind in ('facts', 'reports') for row in entry[kind]]
    if any(r['event_id'] in set((state or {}).get('events', [])) for r in events):
        return None
    heading = f'{series.TITLE} 第{n}回'
    return dict(key=f'{PREFIX}{day.year}_{digest}', label=entry['title'], heading=heading,
                hook=entry['title'].replace(' ', '\n', 1), kind_label='MLB', style='v3', intro_as_is=True,
                intro=('これは架空の材料による動作見本です。実際の移籍情報ではありません。' if sample else entry['title'] + '。'),
                description_line=DESCRIPTION, data_credit='各行の出典 / 確定・報道を区別',
                source='確定情報・媒体報道 / 確認日 ' + entry['checked_on'], source_url=events[0]['source'],
                v3=dict(who=heading, source='出典: 各行の資料 / 確定・報道を区別'),
                items=[(r['head'], r['body']) for r in events],
                offseason=dict(kind='market', day=str(day), season=day.year, events=events,
                               entry=copy.deepcopy(entry), series_number=n, series_title=series.TITLE),
                **({'offseason_sample': True} if sample else {}))


def load(day=None, state=None, path=None):
    from offseason_switches import enabled
    if not enabled():
        return []
    day = day or datetime.now(JST).date()
    path = Path(path or PATH)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if set(data) != {'version', 'entries'} or data['version'] != 1 or not isinstance(data['entries'], list):
        raise ValueError('市場材料の書式が不正です')
    if state is None:
        saved = Path('data/offseason_published.json')
        state = json.loads(saved.read_text(encoding='utf-8')) if saved.exists() else {}
    ids, result = set(), []
    for entry in data['entries']:
        if entry['id'] in ids:
            raise ValueError('市場項目IDが重複しています')
        ids.add(entry['id'])
        spec = topic(entry, day, state)
        if spec:
            result.append(spec)
    return result


def posted_today(records, day=None):
    day = day or datetime.now(JST).date()
    for key, row in records.items():
        if not key.removeprefix('asset:').startswith(PREFIX):
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get('publish_at') or row['published_at']).replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('予約日時のタイムゾーンが不明です')
            if stamp.astimezone(JST).date() == day:
                return True
        except (ValueError, KeyError):
            return True  # 日時不明の市場公開を、未公開とは扱わない。
    return False


def validate_publication(spec, records, at):
    """予約の実際の公開日で鮮度と1日1本を再確認する。"""
    day = at.astimezone(JST).date()
    if spec['offseason']['day'] != str(day):
        raise ValueError('市場の確認日と実際の公開予定日が違います')
    if posted_today(records, day):
        raise ValueError('移籍市場の回は1日1本までです')


def order(spec):
    return ((spec.get('offseason') or {}).get('kind') != 'market', spec.get('key', ''))


def check(document):
    evidence = document['offseason']
    try:
        spec = topic(evidence['entry'], date.fromisoformat(evidence['day']),
                     episode=evidence['series_number'], sample=bool(document.get('offseason_sample')))
        if not spec or evidence != spec['offseason']:
            return ['市場の材料行と原稿添付が不一致']
        if [s.get('offseason') for s in document.get('sanity_materials', []) if s.get('offseason')] != [evidence]:
            return ['市場の材料とsanity添付が不一致']
        expected = [''.join(b for h, b in spec['items'][i:i+2])
                    for i in range(0, len(spec['items']), 2)]
        segments = document.get('segments', [])
        if any('_sanity_original_line' in s for s in segments):
            return [] if all(s.get('text') in {spec['intro'], OUTRO_TEXT, *expected} for s in segments) else ['市場の再点検の行が材料と不一致']
        if ([(s['kind'], s['text']) for s in segments] !=
                [('intro', spec['intro']), *[('list', t) for t in expected], ('outro', OUTRO_TEXT)]):
            return ['市場の本文・冒頭・締めが材料と完全一致しません']
    except (KeyError, TypeError, ValueError, AttributeError):
        return ['市場の材料の型・必要な欄が不正です']
    return []
