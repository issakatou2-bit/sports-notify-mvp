"""MLBオフの週刊長編「日本人選手の来季 今週の動き」。手入力の市場材料と期限表だけを使う（生成APIなし）。

材料は data/offseason_market.json（確定と報道を分けたまま写す）と data/offseason_deadlines.json（期限の表）。
公開日は JST で、初回だけ 11/18、以後は PUBLISH_WEEKDAY の曜日。材料が2件未満の週は作らず成功で終わる。
"""
import argparse
import copy
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
KIND = 'offseason_weekly_long'
SWITCH = 'COLLESPO_OFFSEASON_WEEKLY_LONG'
FIRST_DAY = date(2026, 11, 18)      # 初回（火）。QOの返事の期限 11/18 6:00 の後
PUBLISH_WEEKDAY = 2                 # 2回目以降の公開曜日（月=0 … 水=2）。ここ1つで変える
PUBLISH_HOUR = 20                   # 公開は JST 20:00
WINDOW_DAYS = 7                     # 公開日の前7日〜当日に確認した材料
MIN_ENTRIES = 2
MAX_PER_PLAYER = 2                  # 1人あたり使う材料の数（新しい順）
MAX_HEADLINES = 3
MAX_PAST_DEADLINES = 2
MAX_UPCOMING_DEADLINES = 5
NEXT_WEEK_DEADLINES = 3
CHUNK_ROWS = 3                      # 1枚の札に載せる行の最大
CHUNK_CHARS = 240                   # 1枚の札に載せる本文の最大字数
TITLE_HEAD = '【MLB】日本人選手の来季 今週の動き'
TITLE_MAX = 50
DESCRIPTION_MAX = 5000
DEADLINE_FIELDS = {'id', 'label', 'at_jst', 'players', 'text', 'source_url', 'checked_on'}
BANNED_TITLE = re.compile(r'[!！?？]|衝撃|驚|必見|絶対|ください|しよう|見て|やばい|ヤバい|ついに|激震')
SENTENCE_END = re.compile(r'(?:です|ます|でした|ました|ません)。$')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


# ---------------------------------------------------------------- 公開日・週の範囲
def is_publish_day(day, published=None):
    """JSTのきょうが公開日で、まだ公開していないか。初回だけ FIRST_DAY、以後は曜日。"""
    if day.isoformat() in (published or {}):
        return False
    return day == FIRST_DAY or (day > FIRST_DAY and day.weekday() == PUBLISH_WEEKDAY)


def window(day):
    return day-timedelta(days=WINDOW_DAYS), day


def publish_moment(day):
    return datetime.combine(day, time(PUBLISH_HOUR), JST)


# ---------------------------------------------------------------- 期限
def at_of(item):
    return datetime.fromisoformat(item['at_jst']).astimezone(JST)


def check_deadlines(data, names=None, sample=False):
    """期限表の書式検査。names（英語名→日本語名）があれば、対象選手が連載の対象かも見る。"""
    import offseason_market as market
    if not isinstance(data, dict) or set(data) != {'version', 'items'} or data['version'] != 1 or not isinstance(data['items'], list):
        raise ValueError('期限表の書式が不正です')
    ids = set()
    for item in data['items']:
        if not isinstance(item, dict) or set(item) != DEADLINE_FIELDS:
            raise ValueError('期限の欄が書式と不一致です')
        if not isinstance(item['id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', item['id']) or item['id'] in ids:
            raise ValueError('期限のIDが不正または重複しています')
        ids.add(item['id'])
        for field in ('label', 'text', 'at_jst', 'source_url', 'checked_on'):
            if not isinstance(item[field], str) or not item[field] or item[field].strip() != item[field]:
                raise ValueError('期限の欄が空か不正です: '+field)
        if len(item['label']) > 24 or '\n' in item['label']:
            raise ValueError('期限の見出しは24字以内にしてください')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00', item['at_jst']):
            raise ValueError('期限の日時は +09:00 つきのISO形式にしてください')
        datetime.fromisoformat(item['at_jst'])
        date.fromisoformat(item['checked_on'])
        text = item['text']
        if len(text) > 150 or '\n' in text or not SENTENCE_END.search(text) or '。' in text[:-1]:
            raise ValueError('期限の本文は敬語1文・句点つき・150字以内にしてください')
        if __import__('ui_tone').text(text) != text:
            raise ValueError('期限の本文は口調の自動整形で変わらない敬語にしてください')
        market.source(item['source_url'], sample)
        if not isinstance(item['players'], list) or any(not isinstance(p, str) or not p for p in item['players']):
            raise ValueError('期限の対象選手は英語名の配列にしてください')
        if names is not None and any(p not in names for p in item['players']):
            raise ValueError('期限の対象選手が連載の対象にありません')
    return len(data['items'])


def deadline_state(item, day):
    """('済', None) / ('本日', 0) / ('あと', N)。基準は公開日のJST 0時、公開時刻を過ぎた物は済。"""
    when = at_of(item)
    if when <= publish_moment(day):
        return '済', None
    days = (when.date()-day).days
    return ('本日', 0) if days == 0 else ('あと', days)


def tag(item, day):
    kind, days = deadline_state(item, day)
    return kind if days is None or kind == '本日' else f'あと{days}日'


def shown_deadlines(items, day):
    """表に出す物。この週に済んだ物は新しい順に2つまで、これからの物は近い順に5つまで。日付順。"""
    start = datetime.combine(window(day)[0], time(0), JST)
    ordered = sorted(items, key=lambda i: (at_of(i), i['id']))
    past = [i for i in ordered if deadline_state(i, day)[0] == '済' and at_of(i) >= start][-MAX_PAST_DEADLINES:]
    upcoming = [i for i in ordered if deadline_state(i, day)[0] != '済'][:MAX_UPCOMING_DEADLINES]
    return past+upcoming


def when_text(item):
    at = at_of(item)
    return f'{at.month}月{at.day}日{at.hour}時'+(f'{at.minute}分' if at.minute else '')


# ---------------------------------------------------------------- 材料
def select_entries(entries, day):
    """公開日の前7日〜当日に確認した物。同じ選手は新しい順に2件まで。"""
    start, end = window(day)
    picked = [e for e in entries if start <= date.fromisoformat(e['checked_on']) <= end]
    picked.sort(key=lambda e: (e['checked_on'], e['id']), reverse=True)
    count, kept = {}, []
    for e in picked:
        count[e['name_en']] = count.get(e['name_en'], 0)+1
        if count[e['name_en']] <= MAX_PER_PLAYER:
            kept.append(e)
    return sorted(kept, key=lambda e: (e['checked_on'], e['id']))


def material(day, market_data, deadline_data, fixture=False, sample=False):
    import jp_future_catalog as series
    import offseason_market as market
    if not isinstance(market_data, dict) or set(market_data) != {'version', 'entries'} or market_data['version'] != 1:
        raise ValueError('市場材料の書式が不正です')
    jp, _ = series.targets()
    ids = set()
    for entry in market_data['entries']:
        if entry['id'] in ids:
            raise ValueError('市場項目IDが重複しています')
        ids.add(entry['id'])
        market.validate(entry, sample=sample)
    check_deadlines(deadline_data, jp, sample)
    entries = select_entries(market_data['entries'], day)
    names = {e['name_en']: jp[e['name_en']] for e in entries}
    for item in deadline_data['items']:
        for p in item['players']:
            names[p] = jp[p]
    start, end = window(day)
    can_make = len(entries) >= MIN_ENTRIES
    return dict(version=1, key=day.isoformat(), start=start.isoformat(), end=end.isoformat(), fixture=bool(fixture),
                can_make=can_make,
                reason='' if can_make else f'この週の材料が{len(entries)}件で、{MIN_ENTRIES}件に満たないため作りません',
                entries=copy.deepcopy(entries), deadlines=copy.deepcopy(sorted(deadline_data['items'], key=lambda i: (i['at_jst'], i['id']))),
                names=names)


def check_material(data):
    """保存した材料が、書式・窓・選び方・名前と一致するか。"""
    import jp_future_catalog as series
    import offseason_market as market
    day = date.fromisoformat(data['key'])
    jp, _ = series.targets()
    for entry in data['entries']:
        market.validate(entry)
    check_deadlines(dict(version=1, items=data['deadlines']), jp)
    if select_entries(data['entries'], day) != data['entries']:
        raise ValueError('材料の選び方（週の範囲・1人2件まで・日付順）と一致しません')
    expected_names = {e['name_en']: jp[e['name_en']] for e in data['entries']}
    for item in data['deadlines']:
        for p in item['players']:
            expected_names[p] = jp[p]
    if data['names'] != expected_names:
        raise ValueError('選手の日本語名が連載の名簿と一致しません')
    start, end = window(day)
    if (data['start'], data['end']) != (start.isoformat(), end.isoformat()):
        raise ValueError('週の範囲が一致しません')
    if data['can_make'] != (len(data['entries']) >= MIN_ENTRIES):
        raise ValueError('作る・作らないの判定が材料と一致しません')


def players_in_order(data):
    """その週に材料のある選手。最初の確認日が早い順。"""
    order = {}
    for e in data['entries']:
        order.setdefault(e['name_en'], e['checked_on'])
    return sorted(order, key=lambda en: (order[en], en))


def headlines(data):
    """要点の題。選手ごとに新しい1件を選び、新しい順に最大3つ。"""
    seen, result = set(), []
    for e in sorted(data['entries'], key=lambda e: (e['checked_on'], e['id']), reverse=True):
        if e['name_en'] not in seen:
            seen.add(e['name_en'])
            result.append(e)
    return result[:MAX_HEADLINES]


# ---------------------------------------------------------------- 題・概要欄
def title(data):
    names = []
    for e in headlines(data):
        jp = data['names'][e['name_en']]
        if jp not in names:
            names.append(jp)
    while names:
        text = TITLE_HEAD+'｜'+'・'.join(names)
        if len(text) <= TITLE_MAX:
            break
        names.pop()
    else:
        text = TITLE_HEAD
    check_title(text)
    return text


def check_title(text):
    if len(text) > TITLE_MAX or not text.startswith('【MLB】') or text.count('【') != 1 or text.count('】') != 1:
        raise ValueError('題は50字以内で、【】は先頭の【MLB】だけにしてください')
    if BANNED_TITLE.search(text):
        raise ValueError('題に語りかけ・煽りの語は使えません')


def description(data, youtube_chapters=None):
    day = date.fromisoformat(data['key'])
    start, end = window(day)
    lines = [title(data), f'対象：日本時間 {start.month}月{start.day}日〜{end.month}月{end.day}日に確認した動きです。',
             '確定した動きと、媒体による報道は分けて紹介しています。報道は確定ではありません。', '']
    if youtube_chapters:
        lines += youtube_chapters+['']
    lines.append('■ 今週の動き')
    for e in data['entries']:
        lines.append(f"・{e['title']}（確認日 {e['checked_on']}）")
        for row in e['facts']:
            lines.append(f"  確定｜{row['text']} {row['source_url']}")
        for row in e['reports']:
            lines.append(f"  報道｜{row['text']} {row['source_url']}")
    shown = shown_deadlines(data['deadlines'], day)
    if shown:
        lines += ['', '■ 期限']
        for item in shown:
            lines.append(f"・{item['label']}（{tag(item, day)}）：{item['text']} {item['source_url']}（確認日 {item['checked_on']}）")
    lines += ['', '音声：VOICEVOX ずんだもん / 四国めたん', '#MLB #日本人選手 #日本人選手の来季']
    text = '\n'.join(lines)
    if len(text) > DESCRIPTION_MAX:
        raise ValueError('概要欄が長すぎます')
    return text


# ---------------------------------------------------------------- 台本
def chunks(rows):
    """札に入る行の束。行数と字数で決め、入るかどうかは描画の事前検査が見る。"""
    result, current, size = [], [], 0
    for row in rows:
        if current and (len(current) >= CHUNK_ROWS or size+len(row['text']) > CHUNK_CHARS):
            result.append(current)
            current, size = [], 0
        current.append(row)
        size += len(row['text'])
    if current:
        result.append(current)
    return result


def dialogue(data):
    from review_render_v3 import OFFSEASON_OUTRO_TEXT
    day = date.fromisoformat(data['key'])
    start, end = window(day)
    fixture = data.get('fixture', False)
    mark = '【検証用】 ' if fixture else ''
    panels, segments, used = {}, [], []
    shown = shown_deadlines(data['deadlines'], day)
    upcoming = [i for i in sorted(data['deadlines'], key=lambda i: (at_of(i), i['id'])) if deadline_state(i, day)[0] != '済']

    def chapter(key):
        if key not in used:
            used.append(key)
        return key

    def card(key, heading, rows, section, v2rows, atomic=(), note=None):
        panels[key] = dict(type='soccer_weekly', heading=mark+heading, rows=rows, atomic=list(dict.fromkeys(atomic)),
                           v2=dict(layout='table', title=heading, rows=v2rows, note=note, fixture=fixture,
                                   atomic=list(dict.fromkeys(atomic))))
        return key, chapter(section)

    def say(who, text, ref):
        segments.append(dict(kind='talk', speaker=who, text=text, panel=ref[0], chapter=ref[1],
                             meta=dict(who='ずんだもん' if who == 3 else 'めたん')))

    def call(kind):
        return [dict(kind=kind, text='コレスポ', speaker=who, panel=None, meta=dict(who=name))
                for who, name in ((3, 'ずんだもん'), (2, 'めたん'))]

    def date_row(item, tone=None):
        at = at_of(item)
        state = deadline_state(item, day)[0]
        return dict(date=f'{at.month}.{at.day}', time=f'{at.hour}:{at.minute:02d}', label=item['label'], tag=tag(item, day),
                    tag_tone='done' if state == '済' else 'today' if state == '本日' else 'soon', tone='plain')

    def date_line(item):
        return f"{at_of(item).month}/{at_of(item).day} {at_of(item).hour}:{at_of(item).minute:02d} {item['label']} / {tag(item, day)}"

    heads = headlines(data)
    nxt = upcoming[0] if upcoming else None
    rows = [dict(badge=str(i+1), text=e['title'], tone='plain') for i, e in enumerate(heads)]
    plain = [e['title'] for e in heads]
    if nxt:
        rows.append(date_row(nxt))
        plain.append('次の期限　'+date_line(nxt))
    ref = card('opening', '日本人選手の来季　今週の動き', plain, 'opening', rows,
               atomic=[data['names'][e['name_en']] for e in heads],
               note=f'対象：日本時間 {start.month}月{start.day}日〜{end.month}月{end.day}日に確認した動き')
    say(3, '今週のMLBオフ、日本人選手の来季の動きを見ていくのだ。', ref)
    count = {1: '一つ', 2: '二つ', 3: '三つ'}[len(heads)]
    say(2, f"今週の要点は{count}です。"+'、'.join(e['title'] for e in heads)+'。', ref)
    if nxt:
        state, days = deadline_state(nxt, day)
        say(2, f"次の期限は、{nxt['label']}。日本時間の{when_text(nxt)}で、"+('本日です。' if days == 0 else f'あと{days}日です。'), ref)
        say(3, 'この期限は、あとで表でも確認するのだ。', ref)
    else:
        say(2, 'いま登録されている、これからの期限はありません。', ref)

    if shown:
        ref = card('deadlines', '期限の表', [date_line(i) for i in shown], 'deadlines', [date_row(i) for i in shown],
                   atomic=[i['label'] for i in shown],
                   note='あとの日数は、公開日の日本時間の始まりから数えています')
        say(3, '期限を日付の順に表で確認するのだ。', ref)
        say(2, '済と書いてあるものは、すでに過ぎた期限です。', ref)
        for item in shown:
            say(3, item['label']+'なのだ。', ref)
            state, days = deadline_state(item, day)
            say(2, item['text']+('この期限は済みです。' if state == '済' else '期限は本日です。' if days == 0 else f'期限まであと{days}日です。'), ref)

    for index, en in enumerate(players_in_order(data)):
        jp = data['names'][en]
        mine = [e for e in data['entries'] if e['name_en'] == en]
        facts = [dict(badge='確定', text=r['text'], tone='fact') for e in mine for r in e['facts']]
        reports = [dict(badge='報道', text=r['text'], tone='report') for e in mine for r in e['reports']]
        first = True
        fact_groups, report_groups = chunks(facts), chunks(reports)
        for part, group in enumerate(fact_groups):
            heading = f'{jp}　確定した動き'+('（続き）' if part else '')
            ref = card(f'p{index}_f{part}', heading, ['確定｜'+r['text'] for r in group], 'players', group, atomic=[jp])
            say(3, f'{jp}の動きなのだ。' if first else f'{jp}、続きなのだ。', ref)
            first = False
            for row in group:
                say(2, row['text'], ref)
        for part, group in enumerate(report_groups):
            heading = f'{jp}　報道（確定ではありません）'+('（続き）' if part else '')
            outlets = [o for e in mine for o in (r['outlet'] for r in e['reports'])]
            ref = card(f'p{index}_r{part}', heading, ['報道｜'+r['text'] for r in group], 'players', group, atomic=[jp]+outlets)
            if first:
                say(3, f'{jp}の動きなのだ。', ref)
                first = False
            say(3, 'ここからは報道なのだ。確定とは分けて聞いてほしいのだ。' if part == 0 else f'{jp}の報道、続きなのだ。', ref)
            for row in group:
                say(2, row['text'], ref)

    coming = upcoming[:NEXT_WEEK_DEADLINES]
    if coming:
        ref = card('next', '来週の注目', [date_line(i) for i in coming], 'next', [date_row(i) for i in coming],
                   atomic=[i['label'] for i in coming])
        say(3, '来週の注目は、これからの期限なのだ。', ref)
        say(2, '近い順に見ていきます。', ref)
        for item in coming:
            state, days = deadline_state(item, day)
            say(2, f"{item['label']}は、日本時間の{when_text(item)}です。"+('期限は本日です。' if days == 0 else f'あと{days}日です。'), ref)
    else:
        ref = card('next', '来週の注目', ['登録されているこれからの期限はありません'], 'next',
                   [dict(text='登録されているこれからの期限はありません', tone='plain')])
        say(3, '来週の注目なのだ。', ref)
        say(2, 'いま登録されている、これからの期限はありません。', ref)

    ref = card('closing', 'コレスポ', ['日本人選手の来季　今週の動き', f'{start.month}/{start.day}〜{end.month}/{end.day}'], 'closing',
               [dict(text='日本人選手の来季　今週の動き', tone='plain'),
                dict(text=f'{start.month}月{start.day}日〜{end.month}月{end.day}日の確認分', tone='plain')])
    say(2, OFFSEASON_OUTRO_TEXT, ref)
    titles = dict(opening='冒頭', deadlines='期限の表', players='選手ごと', next='来週の注目', closing='締め')
    return dict(kind=KIND, label=data['key'], top='日本人選手の来季 今週の動き', title=title(data),
                chapters=[dict(id=k, title=titles[k]) for k in used], panels=panels,
                segments=call('intro')+segments+call('outro'), offseason_weekly_material=copy.deepcopy(data))


def allowed_numbers(data):
    text = []
    for e in data['entries']:
        text.append(e['title'])
        for kind in ('facts', 'reports'):
            text += [r['label']+r['text'] for r in e[kind]]
    day = date.fromisoformat(data['key'])
    derived = set()
    for item in data['deadlines']:
        text += [item['label'], item['text']]
        at = at_of(item)
        derived |= {str(at.month), str(at.day), str(at.hour)}
        if at.minute:
            derived.add(str(at.minute))
        kind, days = deadline_state(item, day)
        if days:
            derived.add(str(days))
    return set(re.findall(r'\d+', ' '.join(text)))|derived


def validate_document(doc):
    """材料から全文と全札を再構成し、書換え・材料外の数字・確定と報道の混在を止める。"""
    data = doc['offseason_weekly_material']
    if not data['can_make']:
        raise ValueError(data['reason'])
    check_material(data)
    expected = dialogue(data)
    for key in ('kind', 'label', 'top', 'title', 'chapters', 'panels', 'segments', 'offseason_weekly_material'):
        if doc.get(key) != expected[key]:
            raise ValueError('週刊長編の確定台本と不一致: '+key)
    allowed = allowed_numbers(data)
    for seg in doc['segments']:
        extra = set(re.findall(r'\d+', seg['text']))-allowed
        if extra:
            raise ValueError('材料にない数字が台詞にあります: '+','.join(sorted(extra)))
    report_rows = {r['text']: r['outlet'] for e in data['entries'] for r in e['reports']}
    fact_rows = {r['text'] for e in data['entries'] for r in e['facts']}
    for seg in doc['segments']:
        if seg['text'] in report_rows and (report_rows[seg['text']] not in seg['text'] or '報じています' not in seg['text']):
            raise ValueError('報道の行に媒体名と「報じています」がありません')
        if seg['text'] in fact_rows and '報じ' in seg['text']:
            raise ValueError('確定の行に報道の言い方が混ざっています')
    import name_reading_guard
    name_reading_guard.validate_dialogue(doc)


def metadata(doc, timeline_path=None):
    validate_document(doc)
    import soccer_weekly_long as weekly
    data = doc['offseason_weekly_material']
    return dict(snippet=dict(title=title(data), description=description(data, weekly.rendered_chapters(doc, timeline_path)),
                             categoryId='17', tags=['MLB', '日本人選手', 'オフシーズン', '日本人選手の来季'],
                             defaultLanguage='ja', defaultAudioLanguage='ja'))


def validate_upload(args, now=None):
    now = (now or datetime.now(JST)).astimezone(JST)
    if os.environ.get(SWITCH) != 'on':
        raise ValueError('オフ週刊長編の公開変数が無効です')
    doc = load(args.narration)
    validate_document(doc)
    data = load(args.games)
    if data != doc['offseason_weekly_material'] or not data['can_make'] or data.get('fixture'):
        raise ValueError('投稿用の材料と台本が一致しないか、検証用です')
    if args.force:
        raise ValueError('オフ週刊長編は週キーでの二重投稿を許可しません')
    published = {}
    records = ROOT/'data/published_videos.json'
    if records.exists():
        published = load(records).get(KIND, {})
    if args.video_date != data['key'] or data['key'] != now.date().isoformat() or not is_publish_day(now.date(), published):
        raise ValueError('投稿は公開日（未公開の日）に限ります')
    if args.publish_at != f'{PUBLISH_HOUR}:00' or now >= publish_moment(now.date())-timedelta(minutes=1):
        raise ValueError(f'{PUBLISH_HOUR}:00の予約に間に合わないため投稿しません')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--day', help='公開日 YYYY-MM-DD（既定はJSTのきょう）')
    ap.add_argument('--sample', action='store_true', help='公開日でなくても作る（見本の実行用。公開しない）')
    ap.add_argument('--check', action='store_true', help='材料の検査だけ。--dialogue があればその台本も検査する')
    ap.add_argument('--dialogue', type=Path)
    ap.add_argument('--market', type=Path, default=ROOT/'data/offseason_market.json')
    ap.add_argument('--deadlines', type=Path, default=ROOT/'data/offseason_deadlines.json')
    ap.add_argument('--published', type=Path, default=ROOT/'data/published_videos.json')
    ap.add_argument('--out-dir', type=Path, default=ROOT/'build/offseason_weekly')
    args = ap.parse_args()
    day = date.fromisoformat(args.day) if args.day else datetime.now(JST).date()
    market_data, deadline_data = load(args.market), load(args.deadlines)

    def finish(can_make, reason=''):
        print(reason or title(load(args.out_dir/'material.json')))
        output = os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output, 'a', encoding='utf8') as stream:
                stream.write(f"can_make={'true' if can_make else 'false'}\nkey={day.isoformat()}\n")
        return 0

    if args.check:
        data = material(day, market_data, deadline_data)
        if args.dialogue:
            validate_document(load(args.dialogue))
        print(f'検査OK: 期限{len(deadline_data["items"])}件 / この週の材料{len(data["entries"])}件')
        return 0
    published = load(args.published).get(KIND, {}) if args.published.exists() else {}
    if not args.sample and not is_publish_day(day, published):
        return finish(False, f'{day}は公開日ではないか、公開済みのため作りません')
    data = material(day, market_data, deadline_data)
    save(args.out_dir/'material.json', data)
    if not data['can_make']:
        return finish(False, data['reason'])
    doc = dialogue(data)
    validate_document(doc)
    save(args.out_dir/'dialogue.json', doc)
    save(args.out_dir/'metadata.json', metadata(doc))
    return finish(True)


if __name__ == '__main__':
    raise SystemExit(main())
