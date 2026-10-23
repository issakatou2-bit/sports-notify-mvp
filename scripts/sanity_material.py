"""LLMの違和感は候補。原稿に添付された材料との矛盾だけを確定する。"""
import re
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def grounding(documents, snapshot_path='data/postseason.json'):
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
        days = {(d.get('ps_program') or {}).get('date_jst') or d.get('date_jst')
                for d in documents}
        if any(day and 0 <= (datetime.fromisoformat(day).date() - source_day).days <= 1
               for day in days):
            sources.append(dict(source=str(snapshot_path), retrieved_at=snapshot.get('updated_at'),
                                date_jst=snapshot['date'],
                                source_url='https://statsapi.mlb.com/api/v1/schedule',
                                series=snapshot.get('series') or []))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = [dict(source, series=[{k: row[k] for k in
            ('key', 'round', 'round_jp', 'teams', 'next', 'played', 'over') if k in row}
            for row in source['series']]) for source in sources]
    for source in result:
        for row in source['series']:
            row['teams'] = [{k: t[k] for k in ('id', 'name', 'wins') if k in t}
                            for t in row.get('teams') or []]
    return result


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
    import verify_numbers
    import game_fact_guard
    errors = verify_numbers.check(document) + game_fact_guard.check(document)
    from article_freshness import fresh_articles
    if document.get('date_jst'):
        sources = [h for segment in document.get('segments') or []
                   for h in (segment.get('meta') or {}).get('source_headlines') or []]
        current = fresh_articles(sources, document['date_jst'])
        for row in sources:
            if not fresh_articles([row], document['date_jst'], corroborating=current):
                errors.append('記事の公開日が古いか確認できない: ' + (row.get('title') or row.get('url') or '出典不明'))
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


def assess(issues, documents, materials=None):
    errors = [error for document in documents for error in check(document, materials)]
    # severityは受信値として残す。停止可否を同じ値へ上書きしない。
    reviewed = []
    for issue in issues:
        quoted = issue.get('where') or ''
        scoped = [dict(document, segments=[s for s in document.get('segments') or []
                                          if quoted and quoted in (s.get('text') or '')])
                  for document in documents]
        confirmed = any(check(document, materials) for document in scoped)
        reviewed.append(dict(issue, confirmed=confirmed,
                             verification='材料と矛盾あり' if confirmed else '材料との矛盾は確認されず'))
    return reviewed, list(dict.fromkeys(errors))
