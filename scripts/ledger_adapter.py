"""旧6台帳を観測へ変換する。原本は保持し、欠測・矛盾を推測で補わない。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from publications import DATE_FIELDS, identity

FILES = ('published_videos', 'published_assets', 'published_tiktok',
         'bluesky_delivery', 'soccer_flash_receipts', 'video_repairs')

# dateキーの由来と意味。UTC実行日は公開予定日と同義ではない。
DATE_RULES = {
    kind: ('unknown', 'upload_youtube.material_date_key: explicit又はUTC実行日。旧backfillはJST公開日。行ごとの由来を復元できない')
    for kind in ('daily', 'morning', 'morning_local', 'morning_press', 'weekly',
                 'morning_player', 'morning_voices', 'verdict', 'longform',
                 'morning_postseason', 'soccer_race')
}
DATE_RULES.update({
    'daily_soccer': ('material_day', 'upload_youtube.material_date_key: generated_atのJST日。試合日ではない'),
    'soccer_results': ('material_day', 'upload_youtube.material_date_key: games.date_jst（夜〜翌朝の材料日）'),
    'soccer_week': ('unknown', 'soccer_jp_week: scheduledは月曜、手動はweek_key。保存行だけで経路を特定できない'),
    'asset': ('topic', 'upload_youtube.record_published/asset分岐: 日付ではなくtopic'),
    'soccer_voices': ('material_day', 'soccer_voices.yml: data.date_jstを--video-dateへ'),
    'player_story': ('unknown', 'player_story.yml: narration.label指定。公開予定日の証明ではない'),
})


def key(kind, value, raw):
    if kind == 'asset':
        return identity('asset', 'topic', {'topic': value})
    domain = 'soccer' if kind.startswith('soccer_') or kind == 'daily_soccer' else 'mlb'
    new_kind = {'daily_soccer': 'daily'}.get(kind, kind.removeprefix('soccer_'))
    field = DATE_RULES.get(kind, ('unknown', 'unknown'))[0]
    # backfillは材料日を知らず公開日で補完する（backfill_records.add_entries）。
    if raw.get('backfilled'):
        field = 'unknown'
    if kind in ('soccer_now', 'soccer_goal_short'):
        game = value.split(':', 1)[-1]
        return identity('soccer', new_kind, {'game_id': game})
    # 長編のepisode/hash、順位の大会/季/節も保存されていない。
    # P0専用legacy鍵を明記して、最終canonical IDと取り違えない。
    return identity(domain, new_kind, {field if field in DATE_FIELDS else 'legacy_key': value})


def observation(kind, value, raw, source, service='youtube', ident=None, forced_state=None):
    result = ident or key(kind, value, raw)
    result = dict(result, **{f: None for f in DATE_FIELDS})
    field, reason = DATE_RULES.get(kind, ('unknown', '日付キーの根拠なし'))
    if field in DATE_FIELDS and not raw.get('backfilled'):
        result[field] = value
    result.update(service=service, legacy_kind=kind, legacy_key=value,
                  source=source, raw=deepcopy(raw), video_id=raw.get('video_id'),
                  state=forced_state or ('scheduled' if raw.get('publish_at') else
                                        'uploaded' if raw.get('video_id') else 'unknown'),
                  unknown_reasons=[reason] if field == 'unknown' or raw.get('backfilled') else [])
    # published_atはYouTubeの実公開ではなく、旧書き手が記録した実行時刻。
    result['run_at'] = (raw.get('published_at') if not raw.get('backfilled') else None) or raw.get('at') or raw.get('checked_at')
    result['scheduled_at'] = raw.get('publish_at')
    if raw.get('publish_at'):
        try:
            at = datetime.fromisoformat(raw['publish_at'].replace('Z', '+00:00'))
            if at.tzinfo is None:
                raise ValueError('timezone missing')
            result['edition_day'] = at.astimezone(timezone(timedelta(hours=9))).date().isoformat()
        except (ValueError, TypeError, AttributeError):
            result['unknown_reasons'].append('publish_atがタイムゾーン付き日時でないため公開予定日不明')
    if raw.get('backfilled'):
        result['unknown_reasons'].append('backfillはJST公開日キー。材料日と実行時刻は復元できない')
    result['player_id'] = raw.get('player_id')
    if kind == 'asset' and value.startswith('season_player_'):
        result['player_id'] = result['player_id'] or value.removeprefix('season_player_')
    if not result['player_id'] and kind == 'player_story':
        result['unknown_reasons'].append('player_publications.recentの題からの選手名推定は行わない')
    return result


def convert(documents):
    out = []
    for kind, rows in documents.get('published_videos', {}).items():
        for value, raw in rows.items():
            out.append(observation(kind, value, raw, f'published_videos/{kind}/{value}'))
    for topic, raw in documents.get('published_assets', {}).get('assets', {}).items():
        out.append(observation('asset', topic, raw, f'published_assets/assets/{topic}'))
    youtube = list(out)
    for kind, rows in documents.get('published_tiktok', {}).items():
        for value, raw in rows.items():
            # 同じ日付でもUTC実行日と材料日が違う。YouTube元IDを推測しない。
            ident = identity('delivery', 'legacy_tiktok', {'kind': kind, 'legacy_key': value})
            st = ('distributed' if raw.get('publicly_available') and raw.get('public_post_ids')
                  else 'uploaded' if raw.get('status') == 'PUBLISH_COMPLETE'
                  else 'error' if raw.get('status') == 'FAILED'
                  else 'upload_pending' if raw.get('status') not in ('SEND_TO_USER_INBOX', None)
                  else 'unknown')
            obs = observation(kind, value, raw, f'published_tiktok/{kind}/{value}', 'tiktok', ident, st)
            obs.update(material_day=None, edition_day=None, event_day=None)
            obs['unknown_reasons'].append('元公開ID不明。time.strftime実行日、受信箱到達は公開確認ではない')
            out.append(obs)
    for value, raw in documents.get('bluesky_delivery', {}).get('editions', {}).items():
        candidates = {o['publication_id']: o for o in youtube
                      if raw.get('video_id') and o['video_id'] == raw['video_id']}
        original = next(iter(candidates.values())) if len(candidates) == 1 else None
        ident = ({k: original[k] for k in ('publication_id', 'domain', 'kind', 'key_parts')}
                 if original else identity('delivery', 'legacy_bluesky', {'edition': value}))
        obs = observation(value.split(':')[0], value, raw, f'bluesky_delivery/editions/{value}',
                          'bluesky', ident, 'distributed' if raw.get('state') == 'linked' else 'uploaded')
        obs.update(material_day=None, edition_day=None, event_day=None)
        if original is None:
            obs['unknown_reasons'].append('video_idの元公開IDが一意に決まらない')
        out.append(obs)
    for game, raw in documents.get('soccer_flash_receipts', {}).items():
        kind = raw.get('kind', 'unknown')
        ident = identity('soccer', kind.removeprefix('soccer_'), {'game_id': game})
        out.append(observation(kind, game, raw, f'soccer_flash_receipts/{game}', ident=ident,
                               forced_state='upload_pending' if raw.get('status') == 'pending' else
                               'uploaded' if raw.get('video_id') else 'unknown'))
    for i, repair in enumerate(documents.get('video_repairs', {}).get('repairs', [])):
        kind, value = repair['kind'], repair['edition']
        for role, raw in [('original', repair['original_record']),
                          ('replacement', {'video_id': repair['replacement_video_id']})]:
            obs = observation(kind, value, raw, f'video_repairs/repairs/{i}/{role}',
                              forced_state='held' if role == 'original' and repair.get('original_visibility') == 'private'
                              else 'public_confirmed' if role == 'replacement' and repair.get('replacement_visibility') == 'public' and repair.get('verified_at') else 'uploaded')
            obs.update(repair=deepcopy(repair), repair_role=role,
                       verified_at=repair.get('verified_at'))
            out.append(obs)
    return out


def documents(root):
    result = {}
    for name in FILES:
        path = Path(root) / 'data' / (name + '.json')
        # 欠落は黙って空にせず停止。空台帳は{}という保存資料で表す。
        result[name] = json.loads(path.read_text(encoding='utf-8'))
    return result


def load(root):
    return convert(documents(root))
