"""雨衣の予定を原稿作成前に確定し、未着の回を公開経路から外す。"""
import copy
from datetime import timedelta, timezone
import importlib
import json
import os
from pathlib import Path

import ui_voice_queue as q

JST = timezone(timedelta(hours=9))
HEALTH_FILE = 'worker-health.json'
MAX_AGE = timedelta(minutes=7)  # 3分タスクの2周期＋1分
LIVE_START = 19 * 60 + 15
OPEN = 8 * 60 + 40
FRESH_ASSETS = frozenset({'asset:season_game', 'asset:season_story', 'asset:season_spotlight',
                          'asset:season_odds', 'asset:season_momentum'})


def failure_action(narration):
    kind = (narration.get('host_assignment') or {}).get('kind', '')
    if kind in FRESH_ASSETS:
        return 'rebuild_metan'
    return ('defer_next_day' if kind.startswith('asset:') or narration.get('ui_stock_topic')
            else 'rebuild_metan')


class VoiceUnavailable(q.QueueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('雨衣の予定を中止しました: '+reason)


def window_reason(at=None, minutes=0):
    at = (at or q.now()).astimezone(JST)
    minute = at.hour * 60 + at.minute
    if minute < OPEN:
        return 'ui_before_0840'
    if minute >= 20 * 60 + 40:
        return 'ui_night_apsc'
    if minute >= LIVE_START:
        return 'ui_live_reserved'
    if at + timedelta(minutes=minutes) >= at.replace(hour=19, minute=15, second=0, microsecond=0):
        return 'ui_deadline_crosses_live'
    return None


def heartbeat(queue, status='ready'):
    """係だけが書く。秘密値・PC名・台本は含めない。"""
    def change(state, files):
        files[HEALTH_FILE] = q.encoded(dict(version=1, checked_at=q.now().isoformat(), status=status))
    queue.update(change)


def health_reason(files, at=None):
    try:
        health = json.loads(files[HEALTH_FILE])
        age = (at or q.now()) - q.stamp(health['checked_at'])
        if health.get('version') != 1 or not timedelta(0) <= age <= MAX_AGE:
            return 'ui_worker_stale'
        if health.get('status') != 'ready':
            return 'ui_worker_unavailable'
    except (KeyError, TypeError, ValueError):
        return 'ui_worker_missing'
    return None


def wait_minutes():
    value = float(os.getenv('COLLESPO_UI_VOICE_WAIT_MINUTES') or '15')
    if not 0 <= value <= 60:
        raise q.QueueError('声の締め切りは0〜60分です')
    return value


def decide(narration, queue=None, at=None):
    at = at or q.now()
    reason = window_reason(at, wait_minutes())
    mode = 'live'
    try:
        # 在庫の検査・描画の依存は、雨衣を予定する経路でだけ読み込む。
        # 集計でhost_split.validを使うだけの週次報告には持ち込まない。
        stock = importlib.import_module('ui_voice_stock')
        # 音声と部品が完成済みなら、時間外もVoiSonaへの要求なしで使用可能。
        context = stock.asset_context(narration) if os.getenv('COLLESPO_UI_VOICE_STOCK') == 'on' else None
        queue = queue or q.GitQueue()
        if not reason or context:
            _, state, files = queue.read()
            candidate = narration
            if context:
                ui_tone = importlib.import_module('ui_tone')
                host_split = importlib.import_module('host_split')
                before = os.environ.get('COLLESPO_SOLO_HOST')
                try:
                    os.environ['COLLESPO_SOLO_HOST'] = 'ui'
                    candidate = ui_tone.narration(narration)
                    host_split.resolve_credits(candidate, 'ui')
                finally:
                    if before is None:
                        os.environ.pop('COLLESPO_SOLO_HOST', None)
                    else:
                        os.environ['COLLESPO_SOLO_HOST'] = before
            if context and any(o.get('status') == 'ready' and stock.fresh(o, candidate, context, at)
                               for o in state.values() if o.get('stock')):
                reason, mode = None, 'stock'
            elif not reason:
                reason = health_reason(files, at)
    except Exception:
        reason = reason or 'ui_queue_unreachable'
    if reason and reason.startswith(('ui_worker_', 'ui_queue_')):
        print('::warning title=雨衣の係を確認::'+reason+'。予定めたん（雨衣不可のため）')
        summary = os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            with Path(summary).open('a', encoding='utf8') as report:
                report.write('\n雨衣の係を確認: '+reason+'。予定めたん（雨衣不可のため）、半々比較から除外。\n')
    return dict(version=1, planned_host='metan' if reason else 'ui',
                reason=reason, checked_at=at.isoformat(), mode=mode,
                label='予定めたん（雨衣不可のため）' if reason else '予定雨衣',
                comparison_eligible=not bool(reason))


def planned(narration):
    return (narration.get('host_delivery') or {}).get('planned_host',
            (narration.get('host_assignment') or {}).get('planned_host'))


def assert_publishable(data):
    delivery = data.get('host_delivery') or {}
    if delivery.get('status') == 'held':
        raise VoiceUnavailable(delivery.get('failure_reason', 'ui_held'))
    resolution = data.get('voice_resolution') or {}
    if planned(data) == 'ui' and resolution and resolution.get('host') != 'ui':
        raise VoiceUnavailable('ui_host_changed_after_plan')


def failure(narration, npath, out, reason):
    """未着の雨衣回を止める。速報だけ原稿から別のめたん回を作る。"""
    action = failure_action(narration)
    delivery = narration.setdefault('host_delivery', dict(version=1, planned_host='ui', comparison_eligible=True))
    delivery.update(status='held', failure_reason=reason, failed_at=q.now().isoformat(), action=action)
    narration['voice_resolution'] = dict(host='ui', audio_available=False, reason=reason)
    Path(npath).write_bytes(q.encoded(narration))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # 古い成功manifestがあっても必ずブロックする。
    held = dict(host_assignment=narration.get('host_assignment'), host_delivery=copy.deepcopy(delivery),
                voice_resolution=narration['voice_resolution'], segments=[])
    (out/'manifest.json').write_bytes(q.encoded(held))
    (out/'voice-hold.json').write_bytes(q.encoded(held))
    import voice_manifest
    voice_manifest.save(out, [], held, status='held')
    print('::warning title=雨衣の回を停止::'+reason+' / '+action)
    if action == 'defer_next_day':
        raise VoiceUnavailable(reason)
    original = narration.get('host_original_segments')
    if not original:
        raise VoiceUnavailable('ui_metan_source_missing')
    result = copy.deepcopy(narration)
    result['segments'] = copy.deepcopy(original)
    result['host_delivery'] = dict(version=1, planned_host='metan', comparison_eligible=False,
                                   reason='ui_rebuilt_after_hold', previous_attempt=copy.deepcopy(delivery),
                                   checked_at=q.now().isoformat())
    result.pop('voice_resolution', None)
    return result
