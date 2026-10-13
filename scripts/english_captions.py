"""任意の英語字幕。共有API枠が不明なら送らない。秘密・原稿は台帳に残さない。"""
import json
import math
import os
import pathlib
import re
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

import backstage_guard
import caption_names
import captions
import llm_models
import token_log

COST_LIST = 50
COST_INSERT = 400
SNAPSHOT_TTL = 300


def quota_date(now):
    """YouTube resets at Pacific midnight; US DST rules since 2007, without host tzdata.

    Second Sunday of March at 10:00 UTC through first Sunday of November at 09:00 UTC.
    """
    march = datetime(now.year, 3, 1, 10, tzinfo=timezone.utc)
    start = march + timedelta(days=(6-march.weekday()) % 7 + 7)
    november = datetime(now.year, 11, 1, 9, tzinfo=timezone.utc)
    end = november + timedelta(days=(6-november.weekday()) % 7)
    offset = -7 if start <= now < end else -8
    return now.astimezone(timezone(timedelta(hours=offset))).date().isoformat()


def utcnow():
    return datetime.now(timezone.utc)


def load_state(path):
    p = pathlib.Path(path)
    if not p.exists():
        return {'events': []}
    state = json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(state.get('events'), list):
        raise ValueError('invalid state')
    return state


def save_event(path, state, video, status, *, units=0, now=None):
    now = now or utcnow()
    event = dict(at=now.isoformat(), day=now.astimezone(timezone(timedelta(hours=9))).date().isoformat(),
                 video_id=video, status=status, units=units)
    state['events'].append(event)
    # Keep enough history to reconcile a fresh snapshot and daily attempts.
    state['events'] = state['events'][-2000:]
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    tmp.replace(p)
    message = f'[info] 英語字幕: {status} ({video or "動画未取得"})'
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(message+'\n')


def quota_snapshot(env):
    """Read a fresh shared quota observation at each attempt, not only job startup."""
    url = env.get('YOUTUBE_SHARED_QUOTA_URL') or ''
    if not url:
        return json.loads(env.get('YOUTUBE_SHARED_QUOTA_SNAPSHOT') or '{}')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('invalid quota URL')
    import requests
    token = env.get('YOUTUBE_SHARED_QUOTA_TOKEN') or ''
    headers = {'Authorization': 'Bearer '+token} if token else {}
    response = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
    response.raise_for_status()
    return response.json()


def budget_reason(state, video, env=None, now=None):
    env = os.environ if env is None else env
    now = now or utcnow()
    day = now.astimezone(timezone(timedelta(hours=9))).date().isoformat()
    try:
        cap = int(env.get('COLLESPO_EN_CAPTIONS_DAILY_MAX') or '1')
        reserve = int(env.get('COLLESPO_EN_CAPTIONS_RESERVE') or '1000')
        if cap < 0 or reserve < 0:
            raise ValueError()
    except ValueError:
        return 'invalid_limits'
    attempts = [e for e in state['events'] if e['day'] == day and e['status'] == 'insert_reserved']
    if any(e['video_id'] == video for e in attempts):
        return 'already_attempted'
    if len(attempts) >= cap:
        return 'daily_limit'
    try:
        snap = quota_snapshot(env)
        seen = datetime.fromisoformat(snap['observed_at'].replace('Z', '+00:00'))
        remaining = snap['remaining_units']
        if seen.tzinfo is None or isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
            raise ValueError()
        if not math.isfinite(remaining) or not 0 <= remaining <= 10000:
            raise ValueError()
        age = (now - seen).total_seconds()
        if not 0 <= age <= SNAPSHOT_TTL:
            return 'quota_snapshot_stale'
        if snap['quota_date'] != quota_date(now):
            return 'quota_day_mismatch'
        used = sum(e['units'] for e in state['events'] if datetime.fromisoformat(e['at']) >= seen)
        if remaining - used < COST_LIST + COST_INSERT + reserve:
            return 'quota_insufficient'
    except Exception:
        return 'quota_unknown'
    return ''


def translate(cues, ai):
    source = [text for _, _, text in cues]
    if any(backstage_guard.violations(text) for text in source):
        raise ValueError('backstage_source')
    prompt = ('Translate each Japanese caption to English. Return ONLY a JSON array of strings, '
              'one per input cue in exactly the same order. Do not merge or split cues. '
              'Keep facts, numbers, speakers, and quotation attribution; add no claims or explanations. '
              'Use the full official spellings in this canonical name table wherever those names occur. '
              'Other player names must use MLB official English spellings. No markdown.\n'
              + json.dumps({ja: name for text in source for ja, name in caption_names.required(text).items()}, ensure_ascii=False) + '\nINPUT:\n'
              + json.dumps(source, ensure_ascii=False))
    if not token_log.allowed('translate'):
        raise ValueError('translation_budget')
    response = backstage_guard.create(ai, label='english_captions.py', category='translate', mode='whole',
                                     **llm_models.params('translate', max(1600, len(source)*180)),
                                     messages=[{'role': 'user', 'content': prompt}])
    token_log.record('translate', llm_models.model('translate'), response)
    if response.stop_reason == 'max_tokens':
        raise ValueError('translation_truncated')
    result = json.loads(backstage_guard.response_text(response))
    if not isinstance(result, list) or len(result) != len(cues):
        raise ValueError('translation_count')
    for original, english in zip(source, result):
        if (not isinstance(english, str) or not english.strip() or len(english) > 1000
                or re.search(r'[\u3040-\u30ff\u3400-\u9fff]', english)
                or backstage_guard.violations(english)):
            raise ValueError('translation_invalid')
        if any(name not in english for name in caption_names.required(original).values()):
            raise ValueError('translation_names')
        # Arabic numerals must survive; Japanese written numbers are handled by translation.
        if re.findall(r'\d+(?:[.,]\d+)?', original) != re.findall(r'\d+(?:[.,]\d+)?', english):
            raise ValueError('translation_numbers')
    return [(start, end, text.strip()) for (start, end, _), text in zip(cues, result)]


def find_video(args):
    if args.kind == 'daily':
        # upload_youtube records this key in UTC, even though the daily slot is JST.
        return captions.video_id_for('daily', args.date or utcnow().date().isoformat(), args.record)
    if args.kind == 'asset' and args.asset_topic.startswith('season_game_'):
        record = json.loads(pathlib.Path(args.record).read_text(encoding='utf-8'))
        row = (record.get('assets') or {}).get(args.asset_topic) or {}
        return row.get('video_id') or ''
    return ''


def main(args):
    if os.environ.get('COLLESPO_EN_CAPTIONS') != 'on':
        print('[info] 英語字幕はoffです')
        return 0
    state = None
    video = ''
    try:
        state = load_state(args.state)
        if args.kind != 'daily' and not (args.kind == 'asset' and args.asset_topic.startswith('season_game_')):
            save_event(args.state, state, video, 'unsupported_kind')
            return 0
        video = find_video(args)
        if not video and not args.out:
            save_event(args.state, state, video, 'video_missing')
            return 0
        if any(e['video_id'] == video and e['status'] in ('inserted', 'already_present') for e in state['events']) and not args.out:
            save_event(args.state, state, video, 'already_recorded')
            return 0
        reason = budget_reason(state, video)
        if reason and not args.out:
            save_event(args.state, state, video, reason)
            return 0
        narration = json.loads(pathlib.Path(args.narration).read_text(encoding='utf-8'))
        manifest = json.loads((pathlib.Path(args.audio_dir)/'manifest.json').read_text(encoding='utf-8'))['segments']
        cues = captions.build_cues(narration, manifest)
        if not cues:
            save_event(args.state, state, video, 'empty_script')
            return 0
        yt = None
        if not args.out:
            yt = captions.client()
            if yt is None:
                save_event(args.state, state, video, 'oauth_missing')
                return 0
            # Reserve even failed requests; do not spend units on retries.
            save_event(args.state, state, video, 'list_reserved', units=COST_LIST)
            have = yt.captions().list(part='snippet', videoId=video).execute()
            if any(i.get('snippet', {}).get('language') == 'en' and i['snippet'].get('name') == 'Collespo' for i in have.get('items', [])):
                save_event(args.state, state, video, 'already_present')
                return 0
        import anthropic
        srt = captions.render_srt(translate(cues, anthropic.Anthropic()), english=True)
        if args.out:
            p = pathlib.Path(args.out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(srt, encoding='utf-8')
            print(f'[info] 英語SRTを書き出しました: {p}')
            return 0
        # Recheck freshness/budget after translation; list units have already been reserved.
        reason = budget_reason(state, video)
        if reason:
            save_event(args.state, state, video, reason)
            return 0
        from googleapiclient.http import MediaFileUpload
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td)/'en.srt'
            p.write_text(srt, encoding='utf-8')
            save_event(args.state, state, video, 'insert_reserved', units=COST_INSERT)
            media = MediaFileUpload(str(p), mimetype='application/octet-stream')
            try:
                yt.captions().insert(part='snippet', body={'snippet': {'videoId': video, 'language': 'en',
                    'name': 'Collespo', 'isDraft': False}}, media_body=media).execute()
            finally:
                media.stream().close()
        save_event(args.state, state, video, 'inserted')
    except Exception as exc:
        # Never dump OAuth/HTTP objects or model responses into public records.
        known = {'backstage_source', 'translation_budget', 'translation_truncated', 'translation_count',
                 'translation_invalid', 'translation_names', 'translation_numbers'}
        status = str(exc) if isinstance(exc, ValueError) and str(exc) in known else 'failed_' + type(exc).__name__
        if getattr(getattr(exc, 'resp', None), 'status', None) == 403:
            status = 'forbidden_check_scope_or_quota'
        if state is not None:
            save_event(args.state, state, video, status)
        else:
            print('[warn] 英語字幕: state_unreadable（送信なし）')
    return 0
