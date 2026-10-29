"""日付だけの資料と、時差を持つ時刻を分けて扱う。通信しない。"""
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def jst_day(value):
    """ISO時刻は日本日付へ。日付だけなら維持、時差不明の時刻は採用しない。"""
    try:
        raw = str(value or '')
        if len(raw) == 10:
            return date.fromisoformat(raw).isoformat()
        at = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return at.astimezone(JST).date().isoformat() if at.tzinfo else ''
    except (ValueError, TypeError):
        return ''


def material_day(data):
    """明示された対象日を優先し、無いときだけ取得時刻を日本日付へ直す。"""
    return (data.get('date_jst') or data.get('date') or
            jst_day(data.get('generated_at') or data.get('updated_at')))


def archive_day(data):
    """日次保存先は検索対象日。旧形式だけは従来の取得日を引き継ぐ。"""
    try:
        if 'schedule_date' in data:
            return date.fromisoformat(data['schedule_date']).isoformat()
        return datetime.fromisoformat(data['generated_at'].replace('Z', '+00:00')).date().isoformat()
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def mlb_jp_label(game):
    """現地の公式日付の翌日。公式日付が無ければ、確定した開始時刻だけ使う。"""
    official = game.get('officialDate')
    if official:
        try:
            day = date.fromisoformat(official) + timedelta(days=1)
        except ValueError:
            return ''
    else:
        if (game.get('status') or {}).get('startTimeTBD'):
            return ''
        actual = jst_day(game.get('gameDate'))
        if not actual:
            return ''
        day = date.fromisoformat(actual)
    return f'{day.month}月{day.day}日'
