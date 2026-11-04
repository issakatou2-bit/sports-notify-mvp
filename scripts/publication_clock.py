"""遅れた見張りと復旧で、対象日と公開期限を共有する。"""
from datetime import datetime, timedelta, timezone

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


if __name__ == '__main__':
    print(target_day())
