"""朝の引用ショートの編集。保存された訳文から1つの題材だけを使う。"""
import re


def sentences(text):
    return [part.strip() for part in re.findall(r"[^。！？!?]+[。！？!?]+|[^。！？!?]+$", text or "") if part.strip()]


def press_parts(row, collection):
    if row.get('_translation_failed') or row.get('_translation_dropped'):
        return []
    if collection == 'posts':
        body = row.get('jp') or ''
    else:
        body = next((row.get(key) for key in ('body_jp', 'summary_jp', 'jp_summary') if row.get(key)), '')
    if not isinstance(body, str) or not re.search(r'[一-龯ぁ-んァ-ヶ]', body):
        return []
    parts = sentences(body)
    # 見出しだけ、1文だけの予告、本文の取得失敗は穴埋めしない。
    return parts if len(parts) >= 2 else []


def press_story(reporters):
    for collection in ('headlines', 'posts'):
        for index, row in enumerate(reporters.get(collection) or []):
            parts = press_parts(row, collection)
            if parts and (row.get('url') or row.get('uri')):
                return dict(collection=collection, index=index, parts=parts[:4])
    return None


def selected_press(seg, reporters):
    story = (seg.get('meta') or {}).get('press_story')
    if not story:
        return None
    rows = reporters.get(story['collection']) or []
    index, part = story['index'], story['part']
    if type(index) is not int or not 0 <= index < len(rows):
        raise ValueError('報道の本文番号が材料と合いません')
    row = rows[index]
    parts = press_parts(row, story['collection'])
    if type(part) is not int or not 0 <= part < len(parts) or parts[part].rstrip('。！？!?') not in seg['text'].rstrip('。！？!?'):
        raise ValueError('報道の本文が保存材料と合いません')
    return [(row, parts[part])]


def press_segments(data, meta):
    reporters = data.get('reporters') or {}
    story = press_story(reporters)
    if story is None:
        return []
    row = reporters[story['collection']][story['index']]
    who = ' / '.join(str(row.get(k) or '') for k in ('outlet', 'source', 'author') if row.get(k))
    result = []
    for part, text in enumerate(story['parts']):
        kind = 'intro' if part == 0 else 'reporters'
        result.append(dict(kind=kind, text=text, speaker=2,
            meta=dict(meta, press_story=dict(collection=story['collection'], index=story['index'], part=part),
                quote_rows=[dict(said=text, who=who, read=True, clip=True)],
                source_press=[row],
                **(dict(source_headlines=[row], used_headline=story['index']) if story['collection']=='headlines' else dict(source_posts=[row])))))
    return result


def voice_selection(data):
    import fan_privacy
    rows = (data.get('voices') or {}).get('voices') or []
    valid = [(i, row) for i, row in enumerate(rows) if row.get('ja') and fan_privacy.safe(row)]
    if not valid:
        return []
    first = valid[0][1]
    # 別の選手のハイライトへの声を、同じ選手への反応として並べない。
    def identity(row):
        return row.get('url') or row.get('video_title') or row.get('matchup')
    key = identity(first)
    return [(i, row) for i, row in valid if identity(row) == key] if key else []


def voice_topic(data, voice):
    import generate_morning_short as g
    for buzz in data.get('buzz') or []:
        ident = buzz.get('video_id') or ''
        same = (ident and ident in (voice.get('url') or '')) or (buzz.get('title') and buzz['title'] == voice.get('video_title'))
        if same:
            topic = g.buzz_label(buzz).strip().rstrip('。')
            if re.search(r'[一-龯ァ-ヶ]', topic):
                return g.yomi_stats(topic) + '。'
    names = voice.get('jp_players') or []
    if names:
        return '・'.join(names) + 'の動画への声です。'
    # 対戦カードは既存の球団名辞書で日本語にできる場合だけ。
    from comment_render import jp_matchup
    matchup = jp_matchup(voice.get('matchup') or '')
    if matchup and re.search(r'[一-龯ァ-ヶ]', matchup) and not re.search(r'[A-Za-z]{3,}', matchup):
        return matchup + 'への声です。'
    return ''


def reaction(row, index):
    text = row.get('ja') or ''
    if re.search(r'来[たてる]|移籍|ハマる|来れば', text):
        return 'これはファンの移籍への期待なのだ。'
    if re.search(r'だけじゃ|だけでなく', text):
        return '結果だけでなく、見せ方への声なのだ。'
    if re.search(r'守備|捕球|送球', text):
        return '守備に注目しているのだ。'
    if re.search(r'三振|球速|マイル|キロ', text):
        return '投球への反応なのだ。'
    if re.search(r'\d', text):
        return '数字に注目した一言なのだ。'
    return ('熱のこもった一言なのだ。', '短い言葉でも気持ちが伝わるのだ。', '思わず声が出た感じなのだ。')[index % 3]


def voices_segments(data, meta):
    chosen = voice_selection(data)
    if not chosen:
        return []
    topic = voice_topic(data, chosen[0][1])
    if not topic:
        return []
    result = [dict(kind='intro', text=topic, speaker=2,
        meta=dict(meta, used_voice=None, duo=True, screen='voice-topic', who='四国めたん',
            quote_rows=[dict(said=topic, who='お題', fact=True, read=True, clip=True)]))]
    import fan_privacy
    quoted=0;characters=0
    for order, (index, voice) in enumerate(chosen):
        if len(voice['ja'])>120:continue
        quotes = [(voice, False)] + [(r, True) for r in (voice.get('reply_ja') or [])[:1] if r.get('ja') and fan_privacy.safe(r)]
        for row, reply in quotes:
            if quoted>=3 or characters+len(row['ja'])>210:continue
            text = row['ja'].strip()
            quoted+=1;characters+=len(row['ja'])
            if text[-1:] not in '。！？!?':
                text += '。'
            screen = f'voice:{index}:{int(reply)}'
            quote = dict(said=row['ja'], who='返信' if reply else 'コメント', reply=reply, read=True, clip=True)
            common = dict(meta, duo=True, screen=screen, index=index, picked=[index], parent_read=reply,
                quote_rows=[quote], who='四国めたん')
            result.append(dict(kind='thread' if reply else 'voices', text=text, speaker=2, meta=common))
            answer = reaction(row, order)
            result.append(dict(kind='voices', text=answer, speaker=3,
                meta=dict(meta, duo=True, screen=screen, who='ずんだもん', reaction=True,
                    quote_rows=[dict(quote, read=False), dict(said=answer, who='ずんだもん', fact=True, read=True, clip=True)])))
    return result if quoted else []


def edit(data, mode, segments, meta):
    body = press_segments(data, meta) if mode == 'press' else voices_segments(data, meta)
    if not body:
        return []
    return body + [s for s in segments if s['kind'] == 'outro']
