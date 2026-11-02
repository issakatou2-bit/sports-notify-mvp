"""コメントの原文にないプレーを補わない。通信せず、狭い対応表で検査する。"""
import re
import copy


# 「ボール」「プレー」のような広い語では専門語の補完を許可しない。
# K は大文字単独のみ。bank や strike a deal を三振の根拠にしない。
PLAY_TERMS = (
    (r'空振り', r'\b(?:swing\w*|whiff\w*)\b'),
    (r'三振', r'\b(?:strike[ -]?outs?|struck (?:him |them )?out|strikes? (?:him |them )?out|fanned)\b|(?<!\w)(?:\d+\s*)?(?-i:K)s?(?!\w)'),
    (r'見逃し', r'\b(?:looking|called strike|took (?:the |a )?strike)\b'),
    (r'打者|バッター|打撃', r'\b(?:batters?|hitters?|batting|at[ -]bats?|swing\w*)\b'),
    (r'本塁打|ホームラン', r'\b(?:home[ -]?runs?|homers?|HRs?)\b'),
    (r'投手|ピッチャー', r'\b(?:pitchers?|hurlers?|mound|bullpen|relievers?|starters?)\b'),
    (r'投球|球種', r'\b(?:pitch(?:es|ing|ed)?|fastballs?|sliders?|curveballs?|changeups?)\b'),
    (r'捕球|好捕|落球', r'\b(?:catch\w*|caught|grab\w*|drop\w*|field\w*|glov\w*)\b'),
    (r'守備|野手', r'\b(?:defen\w*|field\w*|glov\w*|catch\w*|caught|shortstops?|outfield\w*|infield\w*)\b'),
    (r'送球', r'\b(?:throw\w*|threw|toss\w*)\b'),
    (r'失策|エラー', r'\b(?:errors?|misplay\w*)\b'),
)


def unsupported(original, ja):
    """動画題や親の文は訳語の追加を正当化しない。原文そのものだけを見る。"""
    return [m.group() for jp, en in PLAY_TERMS
            if (m := re.search(jp, ja or '')) and not re.search(en, original or '', re.I)]


def ambiguous_reply(original):
    """短い代名詞・従属句の返信だけ除外。短くても対象の明瞭な称賛は残す。"""
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", original or '')
    if re.search(r'\b(?:swing\w*|whiff\w*|strike[ -]?out\w*|struck out|home runs?|catch\w*|caught|pitch\w*|World Series)\b', original or '', re.I):
        return False
    return len(words) <= 9 and bool(re.search(
        r'^\s*(?:(?:when|if|because)\s+(?:he|she|they|it)|(?:he|she|they|it|that|this)\b)',
        original or '', re.I))


def is_game(video):
    title = video.get('video_title') or video.get('matchup') or ''
    if re.search(r'gold\s*glove|award|best\s+(?:plays|catches)|compilation|top\s+\d+|賞|好プレー集', title, re.I):
        return False
    # 対戦表示がある時だけ試合と判定。不明な題は安全な一般文へ。
    return bool(re.search(r'\bvs\.?\s|\bversus\b|対', video.get('matchup') or title, re.I))


def intro(voices):
    if voices and all(is_game(v) for v in voices):
        return 'MLB公式の試合ハイライトのコメント欄です。'
    return 'MLB公式の動画のコメント欄です。'


def unclear(row, issue):
    ja = (row.get('ja') or '').rstrip('。！!、.')
    where, why = issue.get('where') or '', issue.get('why') or ''
    return (row.get('reply') and ja and issue.get('severity') == 'low' and len(where) >= 4
            and (ja in where or where in ja)
            and re.search(r'(?:どの|何の).*(?:話|場面|プレー).*(?:不明|分から|わから|分かり|わかり|曖昧)|(?:主語|指示対象|指示先|係り先|文脈).*(?:不明|曖昧|不明瞭)', why))


def omit_low_replies(document, issues):
    """音声生成前専用。引用の境界が確定する返信だけ外し、吹出し履歴も更新。

    旧構成や引用の位置・役割が確定しない原稿は通常の停止検査に委ねる。
    """
    candidates = {r['ja'] for s in document.get('segments') or []
                  for r in (s.get('meta') or {}).get('source_voices') or []
                  if any(unclear(r, i) for i in issues)}
    if not candidates:
        return document, []
    normalize = lambda text: (text or '').strip().rstrip('。！!、.')
    removable, spans = set(), {}
    for ja in candidates:
        matches = [n for n, s in enumerate(document.get('segments') or [])
                   if normalize(ja) in (s.get('text') or '')]
        if len(matches) != 1:
            continue
        n = matches[0]
        seg = document['segments'][n]
        text = seg.get('text') or ''
        active = [r for r in (seg.get('meta') or {}).get('quote_rows') or []
                  if r.get('read') and not r.get('fact')]
        parent_overlap = any(not r.get('reply') and normalize(r.get('ja')) == normalize(ja)
                             for r in (seg.get('meta') or {}).get('source_voices') or [])
        targets = [r for r in active if normalize(r.get('said')) == normalize(ja)]
        if parent_overlap or len(targets) != 1 or text.count(normalize(ja)) != 1:
            continue
        # すべての引用が読まれる順に一意に一致するときだけ、返信の区間を切る。
        cursor, target_span = 0, None
        for row in active:
            body = normalize(row.get('said'))
            at = text.find(body, cursor) if body else -1
            if at < 0 or text.count(body) != 1:
                break
            end = at+len(body)
            while end < len(text) and text[end] in '。！!、.':
                end += 1
            if row is targets[0]:
                target_span = (at, end)
            cursor = end
        else:
            if target_span:
                removable.add(ja)
                spans.setdefault(n, []).append(target_span)
    if not removable:
        return document, []
    result = copy.deepcopy(document)
    omitted = {normalize(j) for j in removable}
    for n, seg in enumerate(result['segments']):
        for start, end in sorted(spans.get(n, []), reverse=True):
            seg['text'] = seg['text'][:start]+seg['text'][end:]
        meta = seg.get('meta') or {}
        if 'quote_rows' in meta:
            meta['quote_rows'] = [r for r in meta['quote_rows'] if normalize(r.get('said')) not in omitted]
        if 'source_voices' in meta:
            meta['source_voices'] = [r for r in meta['source_voices'] if normalize(r.get('ja')) not in omitted]
        if n in spans and not any(r.get('reply') for r in meta.get('source_voices') or []):
            # 返答の予告を消す。ただし残った引用自体に含まれる表現は変えない。
            quoted = [r.get('said') or '' for r in meta.get('quote_rows') or [] if not r.get('fact')]
            seg['text'] = re.sub(r'(?:これに、?)?こう返っています。?',
                                 lambda m: m[0] if any(m[0] in q for q in quoted) else '', seg['text'])
    result['segments'] = [s for s in result['segments'] if (s.get('text') or '').strip()]
    # 最後の返信を落としたとき、返答の予告だけを残さない。
    for n in range(len(result['segments'])-1, -1, -1):
        seg = result['segments'][n]
        if re.fullmatch(r'(?:これに、?)?こう返っています。?', seg.get('text') or ''):
            following = result['segments'][n+1:]
            if not following or following[0].get('kind') != seg.get('kind') or not any(
                    r.get('reply') for r in (following[0].get('meta') or {}).get('source_voices') or []):
                result['segments'].pop(n)
    omissions = [dict(ja=ja, reason='low: 返信の指示対象が不明', action='omit_reply_quote',
                      findings=[i for i in issues if unclear(dict(ja=ja, reply=True), i)])
                 for ja in sorted(removable)]
    result.setdefault('voices_context_omissions', []).extend(omissions)
    return result, omissions


def checks(documents, issues=()):
    """生成時に保存した引用だけを照合。未使用のコメントで別の回を止めない。"""
    errors = []
    for doc in documents:
        for seg in doc.get('segments') or []:
            text = seg.get('text') or ''
            for row in (seg.get('meta') or {}).get('source_voices') or []:
                ja, original = row.get('ja') or '', row.get('original') or ''
                if not ja or ja.rstrip('。！!、.') not in text:
                    continue
                terms = unsupported(original, ja)
                if terms:
                    errors.append('文脈の取り違え: 原文に対応語のない訳語「' + '・'.join(terms) + '」')
                if not row.get('reply'):
                    continue
                if ambiguous_reply(original):
                    errors.append('主語・場面が定まらない短い返信: ' + ja)
                for issue in issues:
                    if unclear(row, issue):
                        errors.append('返信の文脈指摘: 返信を外し音声・画面ごと再生成が必要: ' + ja)
    return list(dict.fromkeys(errors))


def attach(document, data):
    """検査で原文を辿れるよう、実際に読んだ引用のみ保存する。"""
    rows = []
    for voice in (data.get('voices') or {}).get('voices') or []:
        rows.append(dict(original=voice.get('title', ''), ja=voice.get('ja', ''),
                         video_title=voice.get('video_title', ''), reply=False))
        rows.extend(dict(r, reply=True, video_title=voice.get('video_title', ''))
                    for r in voice.get('reply_ja') or [])
    for seg in document.get('segments') or []:
        used = [r for r in rows if r.get('ja') and
                r['ja'].rstrip('。！!、.') in (seg.get('text') or '')]
        if used:
            seg.setdefault('meta', {})['source_voices'] = used
    return document
