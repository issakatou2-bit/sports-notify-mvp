"""番組表に存在する翌日の枠だけを案内する共通締めの日替わり比較。"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

JST = timezone(timedelta(hours=9))
LEGACY = 'チャンネル登録して、また見に来てくださいね。'


def choice(day=None, lineup=None):
    try:
        day = date.fromisoformat(str(day)) if day else datetime.now(JST).date()
    except ValueError:
        return dict(test='outro-next-20261101', enabled=False, variant='generic', reason='invalid_day')
    on = os.getenv('COLLESPO_OUTRO_NEXT', 'off') == 'on'
    result = dict(test='outro-next-20261101', day=str(day), enabled=on,
                  assigned='next' if day.toordinal() % 2 == 0 else 'generic',
                  variant='generic', rule='jst-ordinal-even-v1')
    if not on:
        return result
    if lineup is None:
        import post_common
        lineup = post_common.lineup()
    # 毎日の番組表に確定済みの枠。時刻を別に決め打ちしない。
    row = next((r for r in lineup if r[0] == 'daily_soccer'), None)
    if not row:
        result['reason'] = 'confirmed_next_missing'
        return result
    _, name, _, at = row
    if not re.fullmatch(r'\d{2}:\d{2}', at) or name != '欧州サッカー':
        result['reason'] = 'confirmed_next_unusable'
        return result
    tomorrow = day + timedelta(days=1)
    hour, minute = map(int, at.split(':'))
    spoken_time = f'{hour}時' + (f'{minute}分' if minute else '')
    result.update(eligible=True, source='post_common.lineup:daily_soccer',
                  next_date=str(tomorrow), next_time=at, next_name=name)
    if result['assigned'] == 'next':
        result.update(variant='next',
            speech=f'次は{tomorrow.month}月{tomorrow.day}日{spoken_time}の{name}です。また見に来てくださいね。',
            card=f'次は{tomorrow.month}/{tomorrow.day} {at}の{name}')
    return result


def speech(original, day=None):
    if os.getenv('COLLESPO_OUTRO_NEXT', 'off') != 'on':
        return original
    plan = choice(day)
    return original.replace(LEGACY, plan['speech']) if plan['variant'] == 'next' else original


def card(text, default):
    # 描画時の日付で再割付しない。音声と同じ原稿から表示する。
    found = re.search(r'次は(\d+)月(\d+)日(\d+)時(?:(\d+)分)?の(欧州サッカー)です。', text)
    if not found:
        return default
    month, day, hour, minute, name = found.groups()
    return f'次は{month}/{day} {int(hour):02d}:{int(minute or 0):02d}の{name}'


def publication(video, day=None, narration=None):
    """完成動画に結びついた実読上げの記録から、台帳の条件を作る。"""
    video = Path(video)
    path = video.with_suffix('')/'render_timeline.json'
    if not path.exists():
        common = any(s.get('kind') == 'outro' and s.get('text', '').startswith('コレスポでは毎日、')
                     for s in (narration or {}).get('segments', []))
        if os.getenv('COLLESPO_OUTRO_NEXT') == 'on' and common:
            raise ValueError('共通締めの実動画記録がありません。比較条件を記録できないため停止します')
        return None
    timeline = json.loads(path.read_text(encoding='utf-8'))
    if timeline.get('video_sha256') != hashlib.sha256(video.read_bytes()).hexdigest():
        raise ValueError('締め比較の完成動画と記録が不一致')
    texts = [r.get('text','') for r in timeline.get('lines', []) if r.get('kind') == 'outro']
    variant = 'next' if any(card(t, '') for t in texts) else 'generic' if any(t.startswith('コレスポでは毎日、') and LEGACY in t for t in texts) else 'other'
    plan = choice(day)
    if plan.get('enabled') and plan.get('eligible') and variant != 'other':
        if variant != plan['variant'] or (variant == 'next' and not any(plan['speech'] in t for t in texts)):
            raise ValueError('締め比較の公開日と録音済みの案内が不一致。再制作が必要です')
    plan.update(variant=variant, eligible=bool(plan.get('eligible')) and variant != 'other')
    return {'outro_next': plan}
