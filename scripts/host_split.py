"""話し手の交互割付。公開順や乱数を使わず、種類とJST日付で再現する。"""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path

RULE = 'half-jst-week-v1'
JST = timezone(timedelta(hours=9))
ANCHOR = date(2026, 1, 5)  # 月曜。ISO年の53週目でも連続する週番号。
HOSTS = ('metan', 'ui')
KINDS = ('morning', 'morning_voices', 'morning_press', 'daily', 'morning_postseason',
         'daily_soccer', 'soccer_race', 'soccer_week', 'soccer_results', 'soccer_voices',
         'soccer_now', 'japan_reacts', 'player_story', 'reddit_reaction')


def enabled():
    return os.getenv('COLLESPO_HOST_SPLIT') == 'half'


def today():
    return datetime.now(JST).date().isoformat()


def solo(segments, default=3):
    return bool(segments) and all(str(s.get('speaker', default)) == '2'
                                 and not (s.get('meta') or {}).get('duo') for s in segments)


def asset_kind(topic):
    pieces = topic.split('_')
    family = '_'.join(pieces[:2]) if topic.startswith('season_') else pieces[0]
    return 'asset:'+family


def plan(kind, day):
    if kind not in KINDS and not kind.startswith('asset:'):
        raise ValueError('半々比較の対象外の種類です')
    day = date.fromisoformat(str(day)[:10])
    week = (day-ANCHOR).days // 7
    phase = hashlib.sha256(kind.encode('utf8')).digest()[0] % 2
    host = HOSTS[(week+day.weekday()+phase) % 2]
    return dict(rule=RULE, kind=kind, day=day.isoformat(), week=week,
                weekday=day.weekday(), phase=phase, planned_host=host)


def valid(value):
    try:
        return value == plan(value['kind'], value['day'])
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def prepare(narration, kind=None, day=None, default=3):
    if not enabled() or not solo(narration.get('segments', []), default):
        return narration
    saved = narration.get('host_assignment')
    if saved is not None:
        if not valid(saved):
            raise ValueError('保存した話し手の割付が不正です')
        assignment = saved
    elif kind:
        assignment = plan(kind, day or narration.get('date_jst') or today())
    else:
        # 種類を推測して掛け合いや長編を実験へ混ぜない。
        return narration
    result = copy.deepcopy(narration)
    result['host_assignment'] = assignment
    os.environ['COLLESPO_SOLO_HOST'] = (narration.get('voice_resolution') or {}).get('host', assignment['planned_host'])
    return result


def adapt(narration, kind, day=None):
    result = prepare(narration, kind, day)
    if enabled() and result.get('host_assignment') and not result.get('voice_resolution'):
        result = importlib.import_module('ui_tone').narration(result)
        resolve_credits(result, os.getenv('COLLESPO_SOLO_HOST'))
    return result


def resolve_credits(narration, host):
    if not enabled() or not narration.get('host_assignment'):
        return
    from ui_voice_queue import UI_CREDIT
    for seg in narration.get('segments', []):
        meta = seg.get('meta') or {}
        for name in ('source', 'credit'):
            value = meta.get(name)
            if isinstance(value, str):
                meta[name] = (value.replace('VOICEVOX:四国めたん', UI_CREDIT) if host == 'ui'
                              else value.replace(UI_CREDIT, 'VOICEVOX:四国めたん'))


def carry(source, target):
    if source.get('host_assignment'):
        target['host_assignment'] = copy.deepcopy(source['host_assignment'])
    return target


def read(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def render_audio(audio_dir, out, narration=None):
    """独立した描画入口も、予定より保存音声の実話者を優先する。"""
    if not enabled():
        return
    import argparse
    import ui_voice_queue
    ui_voice_queue.configure(argparse.Namespace(audio_dir=audio_dir, out=out, narration=narration))


def use_audio(narration, audio_dir):
    if not enabled() or not audio_dir:
        return narration
    manifest = read(Path(audio_dir)/'manifest.json')
    if valid(manifest.get('host_assignment')):
        saved = read(manifest.get('narration_path', ''))
        if saved.get('host_assignment') != manifest['host_assignment']:
            raise ValueError('保存原稿と音声の割付が一致しません')
        return saved
    return narration


def video_receipt(video):
    video = Path(video)
    return video.with_name(video.name+'.voice.json')


def bind_video(video, audio_dir=None):
    video = Path(video)
    data = read(Path(audio_dir)/'manifest.json') if audio_dir else read(video.parent/'voice-resolution.json')
    if not valid(data.get('host_assignment')):
        return
    receipt = carry(data, dict(voice_resolution=data.get('voice_resolution'),
                              video_sha256=hashlib.sha256(video.read_bytes()).hexdigest()))
    video_receipt(video).write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True), encoding='utf8')


def publication(video, narration=None):
    """動画と同じ出力先の受領記録が根拠。予定から実際の声を推測しない。"""
    data = read(video_receipt(video))
    if data and (not Path(video).is_file() or data.get('video_sha256') != hashlib.sha256(Path(video).read_bytes()).hexdigest()):
        return None
    if enabled() and not data:
        return None
    if not data.get('host_assignment') and narration:
        data = read(narration)
    assignment = data.get('host_assignment')
    if not valid(assignment):
        return None
    resolution = data.get('voice_resolution') or {}
    actual = resolution.get('host', 'unknown')
    if actual not in HOSTS or resolution.get('audio_available') is False:
        actual = 'unknown'
    return dict(host_assignment=assignment, planned_host=assignment['planned_host'], actual_host=actual,
                host_fallback_reason=resolution.get('reason') if actual != assignment['planned_host'] else None)


def credit(text):
    if enabled() and os.getenv('COLLESPO_SOLO_HOST') == 'ui':
        from ui_voice_queue import UI_CREDIT
        return text.replace('VOICEVOX:四国めたん', UI_CREDIT).replace('VOICEVOX 四国めたん', UI_CREDIT)
    return text
