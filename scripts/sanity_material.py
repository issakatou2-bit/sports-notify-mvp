"""事実の誤りと説明不足を分け、公式材料と照合する。"""
import re
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
FACT = '事実の誤り'
CONTEXT = '説明不足・文脈'


def document_day(document):
    """夕方のvoices/pressは日本時間の日付をsegment.meta.dateに保存する。"""
    return ((document.get('ps_program') or {}).get('date_jst')
            or document.get('sanity_date_jst')
            or document.get('date_jst')
            or document.get('date')
            or (document.get('label') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(document.get('label', ''))) else None)
            or (document.get('soccer_material') or {}).get('date_jst')
            or next(((s.get('meta') or {}).get('date')
                     for s in document.get('segments') or []
                     if (s.get('meta') or {}).get('date')), None))


def blocking(issue):
    return (issue.get('kind') == FACT
            and str(issue.get('severity', '')).lower() == 'high'
            and issue.get('confirmed')
            and not issue.get('supported'))


def _legacy_grounding(documents, snapshot_path='data/postseason.json'):
    """保存済みのPS材料を、出典・取得時刻を保った小さな形で渡す。通信しない。"""
    sources = []
    for document in documents:
        program = document.get('ps_program') or {}
        if program:
            sources.append(dict(source='narration.ps_program',
                                retrieved_at=program.get('retrieved_at'),
                                date_jst=program.get('date_jst'),
                                source_url=program.get('source_url'),
                                series=program.get('series') or []))
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
        source_day = datetime.fromisoformat(snapshot['date']).date()
        # PS予告の原稿日付は翌日の試合日になる場合もある。
        days = {document_day(d) for d in documents}
        if any(day and 0 <= (datetime.fromisoformat(day).date() - source_day).days <= 1
               for day in days):
            sources.append(dict(source=str(snapshot_path), retrieved_at=snapshot.get('updated_at'),
                                date_jst=snapshot['date'],
                                source_url='https://statsapi.mlb.com/api/v1/schedule',
                                series=snapshot.get('series') or []))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = [dict(source, series=[{k: row[k] for k in
            ('key', 'round', 'round_jp', 'teams', 'next', 'played', 'over', 'games', 'results') if k in row}
            for row in source['series']]) for source in sources]
    for source in result:
        for row in source['series']:
            row['teams'] = [{k: t[k] for k in ('id', 'name', 'wins') if k in t}
                            for t in row.get('teams') or []]
    import soccer_sanity_material
    return result + soccer_sanity_material.grounding(documents)


def grounding(documents):
    import sanity_sources
    return sanity_sources.collect(documents)


def claim_context(document, quoted, materials):
    """話者交代で人物名と順位の行が分かれた場合だけ直前の行を引き継ぐ。"""
    import soccer_sanity_material
    names = [r.get('name') for s in materials or [] for c in s.get('competitions') or []
             for r in c.get('jp') or [] if r.get('name')]
    result = []
    segments = document.get('segments') or []
    for index, segment in enumerate(segments):
        text = segment.get('text') or ''
        if not quoted or quoted not in text:
            continue
        previous = segments[index-1] if index else {}
        same_panel = not (previous.get('panel') and segment.get('panel') and
                          previous['panel'] != segment['panel'])
        # 別クラブを明示した順位行へ、直前の日本人選手を主語として渡さない。
        clubs = [r.get('team_en') or r.get('team') for source in materials or []
                 for comp in source.get('competitions') or []
                 for line in comp.get('lines') or []
                 for r in line.get('inside', []) + line.get('outside', [])]
        explicit_club = any(alias in text for club in clubs if club
                            for alias in soccer_sanity_material.aliases(club))
        previous_clubs = [r.get('club_jp') for source in materials or []
                          for comp in source.get('competitions') or [] for r in comp.get('jp') or []
                          if r.get('name') and r['name'] in (previous.get('text') or '')]
        same_club = any(alias in text for club in previous_clubs if club
                        for alias in soccer_sanity_material.aliases(club))
        if index and same_panel and not any(n in text for n in names) and (not explicit_club or same_club):
            text = (previous.get('text') or '') + '。' + text
        result.append(text)
    return '。'.join(result)


def _clock(text, base):
    match = re.search(r'(?:(\d+)月(\d+)日|(今日|明日|あさって))\s*(\d+)時(?:(\d+)分)?', text)
    if not match:
        return None
    month, day, relative, hour, minute = match.groups()
    try:
        date = (base.replace(month=int(month), day=int(day)) if month else
                base + timedelta(days={'今日': 0, '明日': 1, 'あさって': 2}[relative]))
        return date.replace(hour=int(hour), minute=int(minute or 0), second=0, microsecond=0)
    except ValueError:
        return None


def check(document, materials=None):
    import sanity_sources
    materials = sanity_sources.for_document(document, materials)
    import verify_numbers
    import game_fact_guard
    errors = verify_numbers.check(document) + game_fact_guard.check(document)
    import offseason_news
    errors += offseason_news.check(document)
    import ps_comment_facts
    errors += ps_comment_facts.check(document, materials)
    import soccer_sanity_material
    import sanity_evidence
    for index, segment in enumerate(document.get('segments') or [], 1):
        if sanity_evidence.review(segment.get('text') or '', materials,
                day=(segment.get('meta') or {}).get('date') or document_day(document)) is False:
            errors.append(f'行{index}: 所属・試合番号・スコア・日付が材料と不一致')
        import sanity_claims
        if sanity_claims.review(segment.get('text') or '', materials,
                                context=segment.get('_sanity_context') or claim_context(
                                    document, segment.get('text') or '', materials)) is False:
            errors.append(f'行{index}: 所属・順位・勝点・勝敗が材料と不一致')
        if soccer_sanity_material.review(segment.get('text') or '',
                soccer_sanity_material.for_document(document, materials)) is False:
            errors.append(f'行{index}: サッカーの順位・勝点が材料と不一致')
    from article_freshness import fresh_articles
    if document_day(document):
        sources = [h for segment in document.get('segments') or []
                   for h in (segment.get('meta') or {}).get('source_headlines') or []]
        current = fresh_articles(sources, document_day(document))
        for row in sources:
            if not fresh_articles([row], document_day(document), corroborating=current):
                errors.append('記事の公開日が古いか確認できない: ' + (row.get('title') or row.get('url') or '出典不明'))
    # 原見出しが明示するシリーズ勝敗を、訳文・当日の公式PSと照合する。
    # 試合中の「逆転」からシリーズ連敗を推測しない。
    from team_names import team_names_jp
    for evidence in headline_grounding([document]):
        head = evidence['headline']
        original = re.fullmatch(r'(?:Methodical )?(.+?) chip away at (.+?), rally to seize (\d+)-(\d+) lead',
                                head.get('title') or '')
        if not original:
            continue
        counts = tuple(map(int, original.groups()[2:]))
        spoken = re.search(r'(\d+)勝(\d+)敗', head.get('jp') or '')
        if spoken and tuple(map(int, spoken.groups())) != counts:
            errors.append('見出しの訳のシリーズ勝敗が原文と不一致')
        winner, loser = (team_names_jp(original[n]) for n in (1, 2))
        for source in materials:
            for series in source.get('series') or []:
                teams = {t.get('name'): t.get('wins') for t in series.get('teams') or []}
                if (source.get('date_jst') == document_day(document) and series.get('round') == 'W'
                        and set(teams) == {winner, loser} and (teams[winner], teams[loser]) != counts):
                    errors.append('見出しのシリーズ勝敗が当日の公式PS材料と不一致')
    program = document.get('ps_program') or {}
    for index, segment in enumerate(document.get('segments') or [], 1):
        text = segment.get('text') or ''
        card = (segment.get('meta') or {}).get('card') or {}
        board = card.get('scoreboard') or {}
        rows = board.get('rows') or []
        for row in rows:
            other = next((r for r in rows if r.get('name') != row.get('name')), None)
            if other is None or row.get('wins') is None or other.get('wins') is None:
                continue
            # 「AはBに2勝3敗」の主語はA。「Bに」の数字をBへ帰属しない。
            pattern = re.escape(row['name']) + r'は[^。！？]*?(\d+)勝(\d+)敗'
            match = re.search(pattern, text)
            if match and (int(match[1]), int(match[2])) != (row['wins'], other['wins']):
                errors.append(f'行{index}: {row["name"]}のシリーズ勝敗が材料と不一致')
        line = card.get('next_line') or (segment.get('meta') or {}).get('next_line') or {}
        facts = line.get('facts') or {}
        spoken_game = re.search(r'第(\d+)戦', text)
        if facts.get('game') and spoken_game and int(spoken_game[1]) != int(facts['game']):
            errors.append(f'行{index}: 次の試合番号が材料と不一致')
        when, published = facts.get('jst'), line.get('publication_at')
        if when and published:
            try:
                base = datetime.fromisoformat(published.replace('Z', '+00:00')).astimezone(JST)
                expected = datetime.fromisoformat(when.replace('Z', '+00:00')).astimezone(JST)
            except ValueError:
                continue
            spoken = _clock(text, base)
            if spoken is not None and spoken != expected.replace(second=0, microsecond=0):
                errors.append(f'行{index}: 次の試合の日本時間が材料と不一致')
        # 初戦の絶対日付も、そのカードの対戦シリーズだけと照合する。
        names = {r.get('name') for r in rows}
        for series in program.get('series') or []:
            if names and names == {t.get('name') for t in series.get('teams') or []}:
                label = (series.get('next') or {}).get('verified_label') or ''
                try:
                    base = datetime.fromisoformat(program['date_jst']).replace(tzinfo=JST)
                except (KeyError, ValueError):
                    continue
                actual, expected = _clock(text, base), _clock(label, base)
                if actual and expected and actual != expected:
                    errors.append(f'行{index}: 初戦の日本時間が材料と不一致')
    # 現在の明示された対戦カードだけを見る。過去回の言及や別カードへ
    # 現在のシリーズを当てはめない。学習済みの記憶は照合根拠にしない。
    for index, segment in enumerate(document.get('segments') or [], 1):
        for sentence in (segment.get('text') or '').split('。'):
            if re.search(r'昨年|昨季|前回|振り返|だった|でした', sentence):
                continue
            for source in materials or []:
                for row in source.get('series') or []:
                    names = [t.get('name') for t in row.get('teams') or []]
                    if len(names) != 2 or not all(names):
                        continue
                    rounds = ('ワイルドカードシリーズ', '地区シリーズ',
                              'リーグ優勝決定シリーズ', 'ワールドシリーズ')
                    pair = '|'.join(re.escape(a + join + b)
                                    for a, b in (names, names[::-1])
                                    for join in ('対', 'vs', ' vs '))
                    claim = re.search('(?:' + pair + r')(?:は|の|、)?\s*('
                                      + '|'.join(rounds) + ')', sentence)
                    if claim and re.match(r'ではなく|ではない|でなく', sentence[claim.end():]):
                        continue
                    spoken = claim[1] if claim else None
                    if spoken and row.get('round_jp') and spoken != row['round_jp']:
                        errors.append(f'行{index}: 対戦カードのシリーズ名が材料と不一致')
    return list(dict.fromkeys(errors))


def _supported_claim(quoted, document, materials):
    """対応済みの対戦・シリーズ・試合番号・日付をすべて照合する。

    一部一致や未知の主張は裏付けにしない。成績など別の事実が続く引用も
    fullmatchで除外し、判定できる文型を広げるときは固定試験を加える。
    """
    # 引用が過去の言及や否定文の一部分なら、現在の試合の事実で免除しない。
    sentences = [sentence.strip() for segment in document.get('segments') or []
                 for sentence in re.split(r'[。！？\n]', segment.get('text') or '')
                 if quoted.rstrip('。').strip() in sentence]
    if not sentences or any(sentence != quoted.rstrip('。').strip() for sentence in sentences):
        return False
    program = document.get('ps_program') or {}
    try:
        day = datetime.fromisoformat(program.get('target_day') or document.get('date_jst')
                                     or program['date_jst']).date()
    except (KeyError, TypeError, ValueError):
        return False
    matches = []
    for source in materials or []:
        try:
            source_day = datetime.fromisoformat(source['date_jst']).date()
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= (day - source_day).days <= 1:
            continue
        for row in source.get('series') or []:
            names = [t.get('name') for t in row.get('teams') or []]
            if len(names) != 2 or not all(names):
                continue
            pair = '|'.join(re.escape(a + join + b)
                            for a, b in (names, names[::-1])
                            for join in ('対', 'vs', ' vs '))
            claim = re.fullmatch(
                r'(?:(\d+)月(\d+)日(?:の|、)?)?(?:' + pair + r')(?:は|の|、)?'
                r'(ワイルドカードシリーズ|地区シリーズ|リーグ優勝決定シリーズ|ワールドシリーズ)'
                r'第(\d+)戦(?:です|だ)?[。]?', quoted.strip())
            if not claim:
                continue
            month, date, round_jp, game = claim.groups()
            nxt = row.get('next') or {}
            matches.append(bool(
                round_jp == row.get('round_jp') and int(game) == nxt.get('game')
                and nxt.get('day') == f'{day.month}月{day.day}日'
                and (not month or (int(month), int(date)) == (day.month, day.day))))
    return bool(matches) and all(matches)


def headline_grounding(documents):
    """読み上げた見出しだけを、原文・翻訳・記事URL・公開日時と対応づける。"""
    return [dict(source='segment.meta.source_headlines',
                 date_jst=document_day(document), text=segment.get('text'),
                 headline={k: head[k] for k in ('title', 'jp', 'url', 'source', 'at', 'published_date')
                           if k in head})
            for document in documents for segment in document.get('segments') or []
            for head in (segment.get('meta') or {}).get('source_headlines') or []]


def _supported_headline_comeback(quoted, document, materials):
    """試合の逆転と、その勝利後のシリーズ勝敗を混同した指摘を照合する。

    原文と訳文を丸ごと解釈できる文型だけ扱う。見出しの一部一致や未知の
    言い換えでは解除せず、別の数字・所属などの指摘にも適用しない。
    """
    from urllib.parse import urlparse
    from team_names import team_names_jp
    from article_freshness import fresh_articles
    for evidence in headline_grounding([document]):
        head = evidence['headline']
        if quoted.rstrip('。').strip() != (head.get('jp') or '').rstrip('。').strip():
            continue
        claim = quoted.rstrip('。').strip()
        sentences = [s.strip() for s in re.split(r'[。！？\n]', evidence['text'] or '') if claim in s]
        if not sentences or any(s != claim for s in sentences):
            continue
        day = evidence['date_jst']
        if not day or not fresh_articles([head], day):
            continue
        url = urlparse(head.get('url') or '')
        game = re.fullmatch(r'/news/[a-z0-9-]+-win-world-series-game-(\d+)-(\d+)', url.path)
        if url.scheme != 'https' or url.hostname != 'www.mlb.com' or head.get('source') != 'MLB.com' or not game:
            continue
        original = re.fullmatch(r'(Methodical )?(.+?) chip away at (.+?), rally to seize (\d+)-(\d+) lead',
                                head.get('title') or '')
        if not original or not day.startswith(game[2] + '-'):
            continue
        style, winner_en, loser_en, wins, losses = original.groups()
        winner, loser = team_names_jp(winner_en), team_names_jp(loser_en)
        # 不明な英名や、日本語へ変換できない主語は裏付けにしない。
        if winner == winner_en or loser == loser_en:
            continue
        expected = f'{"手堅い" if style else ""}{winner}、{loser}にじわじわ迫り逆転 {wins}勝{losses}敗とリード'
        if quoted.rstrip('。').strip() != expected:
            continue
        for source in materials or []:
            if source.get('date_jst') != day:
                continue
            for series in source.get('series') or []:
                teams = {t.get('name'): t.get('wins') for t in series.get('teams') or []}
                if (series.get('round') == 'W' and set(teams) == {winner, loser}
                        and teams[winner] == int(wins) and teams[loser] == int(losses)
                        and int(wins) > int(losses)
                        and series.get('played') == int(game[1]) == int(wins) + int(losses)):
                    return True
    return False


def assess(issues, documents, materials=None):
    import sanity_sources
    import sanity_claims
    errors = [error for document in documents for error in check(document, materials)]
    # severityは受信値として残す。停止可否を同じ値へ上書きしない。
    reviewed = []
    for issue in issues:
        quoted = issue.get('where') or ''
        referenced = [document for document in documents
                      if quoted and any(quoted in (s.get('text') or '')
                                        for s in document.get('segments') or [])]
        scoped = [dict(document, _sanity_document_key=sanity_sources.key(document), segments=[dict(s, text=quoted, _sanity_context=claim_context(document, quoted, sanity_sources.for_document(document, materials)))
                                          for s in document.get('segments') or []
                                          if quoted and quoted in (s.get('text') or '')])
                  for document in referenced]
        confirmed = any(check(document, materials) for document in scoped)
        supported = bool(scoped) and not confirmed and all(
            (_supported_claim(quoted, document, sanity_sources.for_document(document, materials))
             or _supported_headline_comeback(quoted, document, sanity_sources.for_document(document, materials))) for document in referenced)
        import soccer_sanity_material
        if referenced and not confirmed:
            import sanity_evidence
            supported = supported or all(all(sentence.strip() == quoted.rstrip('。').strip()
                for s in document.get('segments') or [] for sentence in re.split(r'[。！？\n]', s.get('text') or '')
                if quoted.rstrip('。').strip() in sentence) and sanity_evidence.review(
                quoted, sanity_sources.for_document(document, materials), issue.get('why') or '',
                day=document_day(document)) is True
                for document in referenced)
            supported = supported or all(sanity_claims.review(
                quoted, sanity_sources.for_document(document, materials), issue.get('why') or '',
                context=claim_context(document, quoted, sanity_sources.for_document(document, materials))) is True
                for document in referenced)
            supported = supported or all(soccer_sanity_material.review(
                quoted, soccer_sanity_material.for_document(document, materials),
                issue.get('why') or '', context='。'.join(s.get('text') or ''
                    for s in document.get('segments') or [] if quoted in (s.get('text') or ''))
                ) is True for document in referenced)
        # 旧保存応答は事実指摘として扱い、稼働中のhighを黙って解除しない。
        # 新しいAI応答のkind必須検査はsanity.generalで行う。
        kind = issue.get('kind') or FACT
        if not confirmed and re.search(r'(?:成立(?:する|している)|事実(?:として)?(?:は|が)?正しい)'
                                       r'(?:[。．、,]|[」』]?(?:が|けれど|ものの|ただし)|$)',
                                       issue.get('why') or ''):
            kind = CONTEXT
        missing = kind == FACT and not confirmed and not supported and any(
            sanity_sources.missing_for(issue, d, materials) for d in (referenced or documents))
        reviewed.append(dict(issue, kind=kind, confirmed=confirmed, supported=supported,
                             material_missing=missing,
                             verification='材料と矛盾あり' if confirmed else
                             '材料で裏付け済み（誤検出）' if supported else
                             '材料不足（材料が空・公開を止めない）' if missing else
                             '説明不足・文脈（公開を止めない）' if kind == CONTEXT else '材料で確認できず'))
    return reviewed, list(dict.fromkeys(errors))
