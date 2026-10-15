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

POLICY = (
    ('資産動画（球団・歴史・殿堂など）', '採用。v3のめたんソロ、次の試合に依存しないもの'),
    ('終了済みシーズンまとめ', '採用。現行のseason_topicsが終了判定したもの'),
    ('選手のいまの流れ', '除外。player_story.validateの公開条件が当日原稿'),
    ('試合直後・PS情勢・予告・現地の声・報道', '除外。試合開始や新しい発言で古くなる'),
)


def eligible(topic, spec):
    return (spec.get('style') == 'v3' and not any(spec.get(k) for k in
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
        order['status'] = 'used'
        return copy.deepcopy(order), bundle
    return queue.update(change)


def install(order, bundle, out, narration):
    """返送データの指紋・話者・順番・実音声を検査し、FLACをWAVに戻す。"""
    from PIL import Image
    import wave
    out = Path(out)
    result = json.loads(bundle['result.json'])
    if (result.get('order') != order['id'] or result.get('script_key') != q.script_key(narration)
            or result.get('voice_host') != 'ui' or result.get('voice_engine') != 'voisona'
            or result.get('voice_name') != 'ui_ja_JP'
            or len(result.get('chunks', [])) != len(narration['segments'])):
        raise q.QueueError('返された声と注文が一致しません')
    portrait_dir = out/'portrait'
    portrait_dir.mkdir(parents=True, exist_ok=True)
    for name, blob in bundle.items():
        if re.fullmatch(r'p[0-9]{3}\.png', name):
            path = portrait_dir/name
            path.write_bytes(blob)
            with Image.open(path) as im:
                im.verify()
    parts = json.loads(bundle['parts.json'])
    names = [parts['体']]+[v for k in ('右腕', '左腕', '眉', '目', '口') for v in parts[k].values()]
    if not all(re.fullmatch(r'p[0-9]{3}\.png', n) and (portrait_dir/n).is_file() for n in names):
        raise q.QueueError('雨衣の立ち絵部品が不足しています')
    (portrait_dir/'parts.json').write_bytes(q.encoded(parts))
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
    resolution = dict(host='ui', order=order['id'], portrait_dir=str(portrait_dir.resolve()))
    (out/'manifest.json').write_bytes(q.encoded(dict(segments=manifest, voice_resolution=resolution)))
    return resolution


def fulfill(narration, npath, out, queue=None):
    """在庫対象は待たず在庫だけ、それ以外は既定15分待つ。失敗はその回のめたんへ。"""
    queue = queue or q.GitQueue()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    context = asset_context(narration)
    resolution = None
    try:
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
                print('[info] 雨衣の在庫がないためめたん')
                return None
        else:
            minutes = float(os.getenv('COLLESPO_UI_VOICE_WAIT_MINUTES') or '15')
            if not 0 <= minutes <= 60:
                raise q.QueueError('声の締め切りは0〜60分です')
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
                    break
                time.sleep(min(20, max(0, (q.stamp(order['deadline'])-q.now()).total_seconds())))
            else:
                q.terminal(queue, order['id'], 'expired')
            if not resolution:
                print('[warn] 雨衣の声が間に合わずめたん')
                return None
        narration['voice_resolution'] = resolution
        Path(npath).write_bytes(q.encoded(narration))
        return resolution
    except Exception:
        # 外部キュー・メディアの検査失敗を含め、この回のVOICEVOXに必ず戻す。
        # 固有名詞の検査は呼出元がこの処理より前に実行している。
        print('[warn] 雨衣の声が間に合わずめたん（注文・受取を完了できませんでした）')
        return None


def prioritize(topics):
    """既存の候補・日次上限・種類制限を保ち、その中の在庫を古い順にする。"""
    if os.getenv('COLLESPO_SOLO_HOST') != 'ui':
        return topics
    try:
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
                        '--narration-out', str(path)], cwd=q.ROOT, check=True, capture_output=True)
        return json.loads(path.read_text(encoding='utf8'))


def prepare(count):
    import generate_asset_video as assets
    import next_asset
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
    if os.getenv('COLLESPO_SOLO_HOST') != 'ui':
        print('雨衣が未選択のため注文しません')
        return
    if not 1 <= args.count <= 10:
        p.error('--count は1〜10です')
    (q.ROOT/'build').mkdir(exist_ok=True)
    prepare(args.count)


if __name__ == '__main__':
    main()
