"""Publication edition gate; result dates and collection outcomes stay distinct."""
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def current_day():
    return datetime.now(JST).date()


def rejection(data, edition=None):
    edition = edition or current_day()
    if isinstance(edition, str):
        edition = date.fromisoformat(edition)
    try:
        label = date.fromisoformat(data.get('date_jst', ''))
        source = date.fromisoformat(data.get('date', ''))
    except (TypeError, ValueError):
        return '成績の対象日が読めません'
    if label != edition or source + timedelta(days=1) != label:
        return f'対象日は{label}で、公開する回の{edition}と一致しません'
    if data.get('collection_state') not in (None, 'ready', 'no_games', 'no_appearances'):
        return '成績の取得失敗・一部失敗を正常な空日として使いません'
    return ''


def read_for_edition(data, edition=None):
    reason = rejection(data, edition)
    if reason:
        print('[info] 成績材料を使いません: ' + reason)
        return {}
    return data
