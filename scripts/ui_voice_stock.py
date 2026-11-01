"""資産動画のため録り。現在の材料で組んだ原稿と一致する声だけを使う。"""
import argparse
import copy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import ui_voice_queue as q
import ui_voice_parts as parts_crypto
import asset_policy

POLICY = (
    ('資産動画（歴史・殿堂など）', '採用。v3のめたんソロ、次の試合に依存しないもの'),
    ('終了済みシーズンまとめ', '採用。現行のseason_topicsが終了判定したもの'),
    ('選手のいまの流れ', '除外。player_story.validateの公開条件が当日原稿'),
    ('試合直後・PS情勢・予告・現地の声・報道', '除外。試合開始や新しい発言で古くなる'),
)


def eligible(topic, spec):
    return (not asset_policy.paused(topic) and spec.get('style') == 'v3' and not any(spec.get(k) for k in
            ('game', 'story', 'spotlight', 'odds', 'momentum', 'next_line', 'next_game'))
            and not topic.startswith(('soccer_', 'ps_')))


def asset_context(narration):
    topic = narration.get('ui_stock_topic')
    if not topic:
        return None
    import generate_asset_video as assets
    spec = assets.LIST_TOPICS.get(topic, {})
    if not eligible(topic, spec):
        return None
    return dict(topic=topic, material_key=q.digest(spec))


def current_checks(narration):
    import verify_numbers
    import sanity
    bad = verify_numbers.check(narration)
    with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder:
        path = Path(folder)/'narration.json'
        path.write_bytes(q.encoded(narration))
        bad += sanity.check_narration([str(path)])
    return bad


def fresh(order, narration, context, at=None):
    at = at or q.now()
    return (order.get('stock') and context and order.get('context') == context
            and timedelta(0) <= at-q.stamp(order['created']) <= timedelta(days=7)
            and at < q.stamp(order['deadline']) and order['script_key'] == q.script_key(narration)
            and not current_checks(narration))


def take(queue, key):
    def change(state, files):
        order = state.get(key, {})
        if order.get('status') != 'ready' or q.now() >= q.stamp(order['deadline']):
            return None
        prefix = 'payload/'+key+'/'
        bundle = {name[len(prefix):]: blob for name, blob in files.items() if name.startswith(prefix)}
        ref = order.get('parts_ref', '')
        if not re.fullmatch(parts_crypto.REF, ref) or ref not in files:
            raise parts_crypto.PortraitUnavailable('雨衣の共用部品がありません')
        bundle[ref] = files[ref]
        order['status'] = 'used'
        order['used_at'] = q.now().isoformat()
        return copy.deepcopy(order), bundle
    return queue.update(change)


def install(order, bundle, out, narration):
    """返送データの指紋・話者・順番・実音声を検査し、FLACをWAVに戻す。"""
    import wave
    out = Path(out)
    result = json.loads(bundle['result.json'])
    if (result.get('order') != order['id'] or result.get('script_key') != q.script_key(narration)
            or result.get('voice_host') != 'ui' or result.get('voice_engine') != 'voisona'
            or result.get('voice_name') != 'ui_ja_JP'
            or len(result.get('chunks', [])) != len(narration['segments'])):
        raise q.QueueError('返された声と注文が一致しません')
    ref = result.get('parts_ref', '')
    if ref != order.get('parts_ref'):
        raise q.QueueError('雨衣の部品参照が違います')
    portrait_dir = out/'portrait'
    parts_crypto.install(ref, bundle.get(ref, b''), portrait_dir)
    manifest = []
    for i, (chunk, seg) in enumerate(zip(result['chunks'], narration['segments'])):
        name = f'seg_{i:03d}.flac'
        if chunk['file'] != name or hashlib.sha256(bundle[name]).hexdigest() != chunk['sha256']:
            raise q.QueueError('返された音声の指紋・順番が違います')
        flac, wav = out/name, out/f'seg_{i:03d}.wav'
        flac.write_bytes(bundle[name])
        r = subprocess.run([q.ffmpeg(), '-v', 'error', '-y', '-i', str(flac), '-c:a', 'pcm_s16le', str(wav)],
                           capture_output=True, timeout=120)
        if r.returncode:
            raise q.QueueError('返された音声を復元できません')
        with wave.open(str(wav), 'rb') as audio:
            duration = audio.getnframes()/audio.getframerate()
        if not 0 < duration <= 600:
            raise q.QueueError('返された音声の長さが不正です')
        manifest.append(dict(seg, index=i, file=str(wav), duration=duration,
                             voice_host='ui', voice_engine='voisona', voice_name='ui_ja_JP'))
    resolution = dict(host='ui', order=order['id'], portrait_dir=str(portrait_dir.resolve()), parts_ref=ref)
    os.environ['COLLESPO_UI_PORTRAIT_DIR'] = resolution['portrait_dir']
    import host_split
    payload = host_split.carry(narration, dict(segments=manifest, voice_resolution=resolution))
    (out/'manifest.json').write_bytes(q.encoded(payload))
    import voice_manifest
    voice_manifest.save(out, manifest, dict(narration, voice_resolution=resolution), 'voisona')
    return resolution


def fulfill(narration, npath, out, queue=None):
    """完成在庫を先に使い、それ以外は受付直後に注文。未着は理由を返して停止。"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    resolution = None
    try:
        try:
            parts_crypto.key()
        except q.QueueError:
            raise parts_crypto.PortraitUnavailable('雨衣の部品鍵がありません') from None
        queue = queue or q.GitQueue()
        context = asset_context(narration)
        if context:
            _, state, _ = queue.read()
            for order in sorted(state.values(), key=lambda r: r['created']):
                if not order.get('stock') or order.get('context', {}).get('topic') != context['topic']:
                    continue
                if order['status'] not in ('ready', 'pending', 'working'):
                    continue
                if not fresh(order, narration, context):
                    q.terminal(queue, order['id'], 'discarded')
                    print('[info] 数字・所属・原稿または期限が変わった雨衣の在庫を破棄しました')
                    continue
                if order['status'] == 'ready':
                    payload = take(queue, order['id'])
                    if payload:
                        resolution = install(*payload, out, narration)
                        break
            else:
                resolution = None
            if not resolution:
                # 在庫切れを理由に声を変更しない。利用可能時間なら通常注文へ。
                pass
        if not resolution:
            import ui_voice_policy as policy
            minutes = policy.wait_minutes()
            reason = policy.window_reason(minutes=minutes)
            if reason:
                raise policy.VoiceUnavailable(reason)
            order = q.enqueue(queue, q.make_order(narration, Path(npath).stem, minutes))
            while q.now() < q.stamp(order['deadline']):
                _, state, _ = queue.read()
                saved = state.get(order['id'], {})
                if saved.get('status') == 'ready':
                    payload = take(queue, order['id'])
                    if payload:
                        resolution = install(*payload, out, narration)
                        break
                if saved.get('status') in ('used', 'discarded', 'expired'):
                    raise policy.VoiceUnavailable('ui_order_'+saved['status'])
                time.sleep(min(20, max(0, (q.stamp(order['deadline'])-q.now()).total_seconds())))
            else:
                q.terminal(queue, order['id'], 'expired')
            if not resolution:
                raise policy.VoiceUnavailable('ui_delivery_timeout')
        narration['voice_resolution'] = resolution
        Path(npath).write_bytes(q.encoded(narration))
        manifest = out/'manifest.json'
        saved = json.loads(manifest.read_text(encoding='utf8'))
        saved['narration_path'] = str(Path(npath).resolve())
        manifest.write_bytes(q.encoded(saved))
        return resolution
    except parts_crypto.PortraitUnavailable:
        from ui_voice_policy import VoiceUnavailable
        raise VoiceUnavailable('ui_portrait_unavailable') from None
    except Exception as exc:
        from ui_voice_policy import VoiceUnavailable
        if isinstance(exc, VoiceUnavailable):
            raise
        raise VoiceUnavailable('ui_queue_or_payload_failed') from None


def prioritize(topics):
    """既存の候補・日次上限・種類制限を保ち、その中の在庫を古い順にする。"""
    # 比較中は在庫の有無で題材や公開順を変えない。
    if os.getenv('COLLESPO_HOST_SPLIT') == 'half' or os.getenv('COLLESPO_SOLO_HOST') != 'ui':
        return topics
    try:
        parts_crypto.key()
        queue = q.GitQueue()
        _, state, _ = queue.read()
        ready = {}
        for order in sorted(state.values(), key=lambda r: r['created']):
            topic = order.get('context', {}).get('topic')
            if order.get('stock') and order['status'] == 'ready' and topic in topics:
                narration = rebuild(topic)
                if not fresh(order, narration, asset_context(narration)):
                    q.terminal(queue, order['id'], 'discarded')
                    print(f'[info] 古い雨衣在庫を候補から破棄: {topic}', file=sys.stderr)
                    continue
                ready.setdefault(topic, order['created'])
        return sorted(topics, key=lambda t: (t not in ready, ready.get(t, '')))
    except Exception:
        print('[warn] 雨衣在庫を確認できないため通常の候補順です', file=sys.stderr)
        return topics


def rebuild(topic):
    with tempfile.TemporaryDirectory(dir=q.ROOT/'build') as folder:
        path = Path(folder)/'narration.json'
        subprocess.run([sys.executable, str(q.ROOT/'scripts/generate_asset_video.py'), '--topic', topic,
                        '--narration-out', str(path)], cwd=q.ROOT, check=True, capture_output=True,
                       env=dict(os.environ, COLLESPO_HOST_SPLIT='', COLLESPO_SOLO_HOST='ui'))
        return json.loads(path.read_text(encoding='utf8'))


def prepare(count):
    import generate_asset_video as assets
    import next_asset
    try:
        parts_crypto.key()
    except q.QueueError:
        print('[warn] 雨衣の部品鍵がないため在庫注文を作りません')
        return
    import ui_voice_policy as policy
    reason = policy.window_reason(minutes=15)
    if reason:
        print('::warning::雨衣の在庫注文を見送り: '+reason)
        return
    queue = q.GitQueue()
    _, state, _ = queue.read()
    done = next_asset.published(str(q.ROOT/'data/published_assets.json'))
    existing = {o.get('context', {}).get('topic') for o in state.values()
                if o.get('stock') and o['status'] in ('pending', 'working', 'ready')
                and q.now() < q.stamp(o['deadline'])}
    avg = next_asset.measured(str(q.ROOT/'data/published_assets.json'), str(q.ROOT/'data/analytics.json'))
    topics = [t for t, spec in sorted(assets.LIST_TOPICS.items()) if eligible(t, spec) and t not in done | existing
              and (t.startswith('season_') or avg.get(next_asset.kind_of(t), next_asset.FLOOR) >= next_asset.FLOOR)]
    queued = 0
    for topic in topics:
        if queued >= count:
            break
        narration = rebuild(topic)
        import solo_host
        if solo_host.for_segments(narration['segments']) != 'ui' or current_checks(narration):
            continue
        order = q.make_order(narration, 'asset:'+topic, minutes=7*24*60, stock=True)
        order['context'] = asset_context(narration)
        q.enqueue(queue, order)
        queued += 1
    print(f'雨衣ため録りの注文: {queued}件')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list', action='store_true')
    p.add_argument('--count', type=int, default=3)
    args = p.parse_args()
    if args.list:
        for kind, reason in POLICY:
            print(f'{kind}: {reason}')
        import generate_asset_video as assets
        for topic, spec in sorted(assets.LIST_TOPICS.items()):
            if eligible(topic, spec):
                print(f'候補 {topic}: {spec.get("label", topic)}')
        return
    if os.getenv('COLLESPO_SOLO_HOST') != 'ui' and os.getenv('COLLESPO_HOST_SPLIT') != 'half':
        print('雨衣が未選択のため注文しません')
        return
    os.environ['COLLESPO_SOLO_HOST'] = 'ui'
    if not 1 <= args.count <= 10:
        p.error('--count は1〜10です')
    (q.ROOT/'build').mkdir(exist_ok=True)
    prepare(args.count)


if __name__ == '__main__':
    main()
