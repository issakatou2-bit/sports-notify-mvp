"""LLMの違和感は候補。原稿に添付された材料との矛盾だけを確定する。"""
import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


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


def check(document):
    import verify_numbers
    import game_fact_guard
    errors = verify_numbers.check(document) + game_fact_guard.check(document)
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
    return list(dict.fromkeys(errors))


def assess(issues, documents):
    errors = [error for document in documents for error in check(document)]
    # severityは受信値として残す。停止可否を同じ値へ上書きしない。
    reviewed = []
    for issue in issues:
        quoted = issue.get('where') or ''
        scoped = [dict(document, segments=[s for s in document.get('segments') or []
                                          if quoted and quoted in (s.get('text') or '')])
                  for document in documents]
        confirmed = any(check(document) for document in scoped)
        reviewed.append(dict(issue, confirmed=confirmed,
                             verification='材料と矛盾あり' if confirmed else '材料との矛盾は確認されず'))
    return reviewed, list(dict.fromkeys(errors))
