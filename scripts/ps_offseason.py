"""WSの決着を日次枠へ渡す。月日だけで休止せず、公式の勝敗を使う。"""
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def world_series_over(rows):
    for row in rows or []:
        if row.get('round') != 'W' or row.get('over') is not True:
            continue
        teams = row.get('teams') or []
        winner = row.get('winner')
        if (row.get('best_of') == 7 and row.get('need') == 4
                and len(teams) == 2 and winner is not None
                and type(row.get('played')) is int and 4 <= row['played'] <= 7
                and all(type(t.get('wins')) is int and 0 <= t['wins'] <= 4 for t in teams)
                and sum(t['wins'] == 4 for t in teams) == 1
                and any(t.get('id') == winner and t.get('wins') == 4 for t in teams)
                and sum(t.get('wins', 0) for t in teams) == row.get('played')):
            return True
    return False


def finished_on(games, rows):
    """不要になった第6・7戦は決着日に含めない。日付は日本時間。"""
    if not world_series_over(rows):
        return ''
    days = []
    for game in games:
        if (game.get('gameType') == 'W'
                and game.get('status', {}).get('abstractGameState') == 'Final'):
            try:
                stamp = datetime.fromisoformat(game['gameDate'].replace('Z', '+00:00'))
                if stamp.tzinfo is not None:
                    days.append(stamp.astimezone(JST).date().isoformat())
            except (KeyError, TypeError, ValueError):
                pass
    return max(days, default='')


def completed_before(snapshot, today):
    """当日の優勝結果は残し、翌日以降の日次PS枠を見送る。"""
    if isinstance(today, datetime):
        today = today.astimezone(JST).date()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    if not world_series_over(snapshot.get('series')):
        return False
    try:
        # 旧データのdateは、決着が確認済みだった日の上限として使える。
        end = date.fromisoformat(snapshot.get('ws_finished_on') or snapshot.get('date', ''))
        return int(snapshot.get('season')) == today.year == end.year and end < today
    except (TypeError, ValueError):
        return False
