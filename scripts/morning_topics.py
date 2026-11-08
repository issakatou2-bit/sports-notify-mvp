"""コメント・報道の公開済み題材を7日間照合する。外部APIは使わない。"""
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

KINDS = ('morning_voices', 'morning_press')
LEDGER = 'data/published_videos.json'
SKIPS = 'data/morning_topic_skips.json'
JST = timezone(timedelta(hours=9))


def read(path):
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def normalize(text):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', str(text)).casefold())


def subject(text):
    """旧公開題の番組名・返信数・更新日を出来事の数値に混ぜない。"""
    text = str(text).removeprefix('【MLB】').strip()
    if '現地はこう報じた「' in text:
        text = text.split('現地はこう報じた「', 1)[1].split('」', 1)[0]
    for tail in ('に現地ファンの声', '現地のファンは何と言ったか', '｜現地の報道', ' #Shorts'):
        text = text.split(tail, 1)[0]
    return text.strip('「」。 ｜').removesuffix('のハイライト')


def canonical_url(value):
    parts = urlsplit(value or '')
    host = (parts.hostname or '').lower().removeprefix('www.')
    query = parse_qs(parts.query)
    if host in ('youtube.com', 'm.youtube.com', 'youtu.be'):
        vid = parts.path.strip('/') if host == 'youtu.be' else (query.get('v') or [''])[0]
        if parts.path.startswith(('/shorts/', '/embed/')):
            vid = parts.path.split('/')[2]
        return 'youtube:' + vid if vid else ''
    query = {k: v for k, v in query.items() if not k.lower().startswith('utm_')
             and k.lower() not in ('fbclid', 'gclid', 'ref', 'source')}
    return urlunsplit(('', host, parts.path.rstrip('/'), urlencode(sorted(query.items()), doseq=True), ''))


@lru_cache(maxsize=1)
def aliases():
    names = read('data/player_kana.json').get('names') or {}
    return [(normalize(en), normalize(jp or en)) for en, jp in names.items()] + [
        (normalize(jp), normalize(jp)) for jp in names.values() if jp]


# 出来事の種類と段階を区別する。同じ選手の別の賞・別の出来事は残す。
EVENTS = {
    'extra_base_hits': r'extra[ -]?base hits?|長打',
    'home_runs': r'home runs?|本塁打|ホームラン',
    'saves': r'\bsaves?\b|セーブ',
    'silver_slugger': r'silver slugger|シルバースラッガー',
    'platinum_glove': r'platinum glove|プラチナグラブ|プラチナグローブ',
    'gold_glove': r'gold glove|ゴールドグラブ|ゴールドグローブ',
    'cy_young': r'cy young|サイ[・ ]?ヤング',
    'mvp': r'\bmvp\b|最優秀選手',
    'trade': r'\btrad(?:e|ed|ing)\b|トレード',
    'contract': r'\bsign(?:s|ed|ing)?\b|契約|残留',
    'injury': r'\binjur\w*|負傷|故障|離脱',
    'qualifying_offer': r'qualifying offer|クオリファイング[・ ]?オファー|\bqo\b',
}


def evidence(row):
    """ファンの氏名やコメント本文は保存せず、元動画の題材を保存する。"""
    video = row.get('video_title') or row.get('video_topic')
    fields = ('video_title', 'video_topic', 'topic_jp') if video else ('title', 'jp', 'text', 'topic_jp')
    texts = list(dict.fromkeys(subject(row[k]) for k in fields if row.get(k)))
    players = row.get('players') or row.get('jp_players') or []
    if isinstance(players, str):
        players = [players]
    url = canonical_url(row['url']) if row.get('url') else ''
    return {'texts': texts, 'urls': [url] if url else [],
            'video_ids': [str(row['video_id'])] if row.get('video_id') else [],
            'players': [normalize(p) for p in players],
            'event': str(row.get('event_id') or row.get('event') or ''),
            'game': str(row.get('game_id') or row.get('game_date') or '')}


def signature(topic):
    text = ' '.join(topic.get('texts') or [])
    norm = normalize(text)
    names = set(topic.get('players') or [])
    names.update(jp for name, jp in aliases() if len(name) > 2 and name in norm)
    events = {key for key, pattern in EVENTS.items() if re.search(pattern, text, re.I)}
    stage = ('finalist' if re.search(r'finalist|nominee|ファイナリスト|候補', text, re.I)
             else 'winner' if re.search(r'\bwon\b|\bwins?\b|受賞|獲得', text, re.I) else '')
    # 西暦が片方だけにある翻訳も同じ題材。記録の数値は一致を求める。
    numbers = set(re.findall(r'(?<!\d)\d{1,3}(?!\d)', text))
    return names, events, stage, numbers


def same(left, right):
    if set(left.get('urls') or []) & set(right.get('urls') or []):
        return True
    if set(left.get('video_ids') or []) & set(right.get('video_ids') or []):
        return True
    if left.get('game') and right.get('game') and left['game'] != right['game']:
        return False
    if left.get('event') and right.get('event') and left.get('players') and right.get('players'):
        return left['event'] == right['event'] and bool(set(left['players']) & set(right['players']))
    ln, le, ls, ld = signature(left)
    rn, revents, rs, rd = signature(right)
    if ln and rn and not ln & rn:
        return False
    if le and revents and le != revents:
        return False
    if ls and rs and ls != rs:
        return False
    if ld and rd and not (ld <= rd or rd <= ld):
        return False
    if ln & rn and le and le == revents and (not ls or not rs or ls == rs):
        return True
    for a in left.get('texts') or []:
        for b in right.get('texts') or []:
            a, b = normalize(a), normalize(b)
            if min(len(a), len(b)) >= 12 and (a == b or SequenceMatcher(None, a, b).ratio() >= .84):
                return True
    return False


def repeated_for_upload(topics, kind, day, ledger=None):
    data = read(LEDGER) if ledger is None else ledger
    previous = dict(data)
    previous[kind] = {key: row for key, row in (data.get(kind) or {}).items() if key != day}
    history = recent(day, previous)
    return any(same(topic, old) for topic in topics for old in history)


def recent(day, ledger=None):
    edition = date.fromisoformat(day)
    data = read(LEDGER) if ledger is None else ledger
    seed = read('data/morning_topic_seed.json')
    out = []
    for kind in KINDS:
        for key, record in (data.get(kind) or {}).items():
            if not record.get('video_id') or record.get('privacy') == 'private':
                continue
            stamp = record.get('publish_at') or record.get('published_at') or key
            published = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            public_day = published.astimezone(JST).date() if published.tzinfo else published.date()
            if not edition - timedelta(days=7) <= public_day <= edition:
                continue
            topics = record.get('source_topics')
            seeded = (seed.get(kind) or {}).get(key) or {}
            if topics is None and seeded.get('video_id') == record.get('video_id'):
                topics = seeded.get('source_topics')
            if topics is None:
                # 移行前の記録は公開した題と保存済みの発話から照合する。
                topics = [evidence({'title': record.get('title', '')})]
                topics += [evidence({'title': r.get('text', '')})
                           for r in record.get('dialogue_starts') or []]
            out.extend(topics)
    return out


def filter_rows(rows, day=None, ledger=None):
    from publication_clock import target_day
    previous = recent(day or target_day(), ledger)
    return [r for r in rows if not any(same(evidence(r), old) for old in previous)]


def filter_material(data, mode, day):
    """保存済み材料での再実行にも同じ照合を適用する。"""
    if mode == 'voices':
        voice = dict(data.get('voices') or {})
        voice['voices'] = filter_rows(voice.get('voices') or [], day)
        data['voices'] = voice
        allowed = {canonical_url(r.get('url', '')) for r in voice['voices']}
        data['buzz'] = [r for r in data.get('buzz') or []
                        if 'youtube:' + str(r.get('video_id')) in allowed]
    elif mode == 'press':
        reporters = dict(data.get('reporters') or {})
        for field in ('headlines', 'posts', 'headline_pool'):
            reporters[field] = filter_rows(reporters.get(field) or [], day)
        data['reporters'] = reporters
    return data


def attach(document, data, mode):
    if mode not in ('voices', 'press'):
        return document
    rows = []
    for seg in document.get('segments') or []:
        meta = seg.get('meta') or {}
        if mode == 'voices':
            voices = (data.get('voices') or {}).get('voices') or []
            indices = list(meta.get('picked') or []) if seg['kind'] == 'voices' else []
            indices += [meta[k] for k in ('used_voice', 'index') if isinstance(meta.get(k), int)]
            rows += [voices[i] for i in indices if 0 <= i < len(voices)]
        else:
            rows += meta.get('source_headlines') or []
            rows += meta.get('source_posts') or []
    topics = []
    for row in rows:
        topic = evidence(row)
        if topic not in topics:
            topics.append(topic)
    result = dict(document, source_topics=topics, edition_date=data.get('date_jst'))
    if mode == 'voices':
        result['topic_video_id'] = next((url.removeprefix('youtube:')
            for topic in topics for url in topic['urls'] if url.startswith('youtube:')), '')
    else:
        result['topic_headline'] = next((str(row.get('jp') or row.get('title') or '').rstrip('。')
            for seg in document.get('segments') or [] if seg['kind'] == 'intro'
            for row in (seg.get('meta') or {}).get('source_headlines') or []), '')
    return result


def record_skip(kind, day, reason, path=SKIPS):
    data = read(path)
    data.setdefault(kind, {})[day] = {'reason': reason, 'checked_at': datetime.now(JST).isoformat()}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('[info] 題材の見送りを記録しました: ' + kind + '/' + day + ' ' + reason)


def skip_reason(kind, day, path=SKIPS):
    return ((read(path).get(kind) or {}).get(day) or {}).get('reason', '') if kind in KINDS else ''
