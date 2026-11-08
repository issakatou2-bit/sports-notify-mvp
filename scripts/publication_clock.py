"""遅れた見張りと復旧で、対象日と公開期限を共有する。"""
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
DAY_ROLLOVER_HOUR = 12


def target_day(now=None):
    local = (now or datetime.now(JST)).astimezone(JST)
    if local.hour < DAY_ROLLOVER_HOUR:
        local -= timedelta(days=1)
    return local.date().isoformat()


def publication_due(day, at, now, grace_minutes=45):
    planned = datetime.fromisoformat(f'{day}T{at}').replace(tzinfo=JST)
    return planned + timedelta(minutes=grace_minutes) <= now


def edition_day(value=None, now=None):
    """手動指定を優先し、遅れた夕方枠は正午まで前日分として扱う。"""
    return date.fromisoformat(value).isoformat() if value else target_day(now)


def game_day(edition):
    return (date.fromisoformat(edition) - timedelta(days=1)).isoformat()


def edition_publish_at(day, clock):
    return datetime.fromisoformat(f'{day}T{clock}').replace(tzinfo=JST).isoformat()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=None, help='公開する回の日本日付。空なら正午前は前日')
    parser.add_argument('--game-day', action='store_true', help='対応する米国試合日を出力')
    args = parser.parse_args()
    day = edition_day(args.date)
    print(game_day(day) if args.game_day else day)
