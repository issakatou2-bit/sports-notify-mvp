"""出所・公開待ち・動画の版・応答不明・検証だけの副作用を固定材料で検査。"""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import asset_sns as sns

NOW = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
TOPIC = 'season_momentum_D_114_145_145'
RUN = dict(id=10, head_branch='main', conclusion='success', event='workflow_run',
           path='.github/workflows/season_review.yml', repository=dict(full_name=sns.bd.REPO),
           created_at='2026-10-07T06:10:00Z', updated_at='2026-10-07T06:20:00Z',
           html_url='https://github.com/example/run/10', head_sha='123')
REC = dict(video_id='xbfpDJqtQUk', privacy='public', published_at='2026-10-07T06:16:46Z')
SPEC = {TOPIC: dict(style='v3')}


class Ledger:
    def __init__(self):
        self.data = dict(deliveries={})
    def set(self, key, value):
        self.data['deliveries'][key] = value


def response(status, body):
    r = Mock(status_code=status)
    r.json.return_value = body
    if status >= 400:
        r.raise_for_status.side_effect = sns.requests.HTTPError('mock')
    return r


class AssetSNS(unittest.TestCase):
    def archive(self, receipt=True, override=None):
        video = b'media' * 300
        digest = hashlib.sha256(video).hexdigest()
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('collespo_asset_' + TOPIC + '.mp4', video)
            if receipt:
                z.writestr('collespo_asset_' + TOPIC + '.sns.json', json.dumps(
                    override or dict(topic=TOPIC, style='v3', sha256=digest)))
        return out.getvalue(), digest

    def test_same_run_v3_only(self):
        self.assertEqual(len(sns.select(RUN, {TOPIC: REC}, SPEC, NOW)), 1)
        for changes in [dict(style='v2'), dict(style='v1'), {}]:
            self.assertEqual(sns.select(RUN, {TOPIC: REC}, {TOPIC: changes}, NOW), [])

    def test_untrusted_run_rejected(self):
        for field, value in [('head_branch', 'draft'), ('conclusion', 'failure'),
                             ('event', 'pull_request'), ('path', '.github/workflows/design_preview.yml'),
                             ('repository', dict(full_name='other/repo'))]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                sns.select(dict(RUN, **{field: value}), {TOPIC: REC}, SPEC, NOW)

    def test_stale_future_or_other_run_records_are_not_posted(self):
        self.assertEqual(sns.select(RUN, {TOPIC: REC}, SPEC, NOW.replace(day=9)), [])
        for time in ['2026-10-07T06:09:00Z', '2026-10-07T06:21:00Z']:
            self.assertEqual(sns.select(RUN, {TOPIC: dict(REC, published_at=time)}, SPEC, NOW), [])
        self.assertEqual(sns.select(RUN, {TOPIC: dict(REC, privacy='private')}, SPEC, NOW), [])

    def test_previous_jst_day_keeps_original_delivery_key_and_guards(self):
        # UTCは同じ日でもJSTでは翌日。遅延実行の実行日キーを維持する。
        late = NOW.replace(hour=16)
        rows = sns.select(RUN, {TOPIC: REC}, SPEC, late)
        self.assertEqual(rows, [('2026-10-07', TOPIC, REC, 'season-review')])
        self.assertEqual(sns.select(RUN, {TOPIC: REC}, SPEC, late + timedelta(days=1)), [])
        self.assertEqual(sns.select(RUN, {TOPIC: REC}, SPEC, NOW - timedelta(days=1)), [])
        for change in [dict(privacy='private'), dict(published_at='2026-10-07T06:09:00Z'),
                       dict(published_at='2026-10-07T06:21:00Z')]:
            self.assertEqual(sns.select(RUN, {TOPIC: dict(REC, **change)}, SPEC, late), [])
        self.assertEqual(sns.select(RUN, {TOPIC: REC}, {TOPIC: dict(style='v2')}, late), [])

    def test_late_retry_does_not_redistribute_sent_video(self):
        ledger = Ledger()
        key = '2026-10-07:asset_' + TOPIC + ':'
        for service in ('twitter', 'bluesky'):
            ledger.set(key + service, dict(state='sent', youtube_id=REC['video_id']))
        with patch.dict(os.environ, {'V3_SNS_ENABLED': 'true', 'BUFFER_CHANNELS': 'twitter'}), \
             patch.object(sns.bd, 'Ledger', return_value=ledger), \
             patch.object(sns.bd, 'verify_youtube') as verify, \
             patch.object(sns, 'artifacts_of') as download, \
             patch.object(sns.bd, 'submit_once') as submit, patch.object(sns, 'bsky_once') as bsky:
            sns.distribute(RUN, sns.select(RUN, {TOPIC: REC}, SPEC, NOW.replace(hour=16)), True)
            for mock in (verify, download, submit, bsky):
                mock.assert_not_called()

    def test_compare_v3_receipt_round_trip_and_old_artifact_is_rejected(self):
        topic = 'season_compare_2026_579328_608372'
        import season_stock
        spec = season_stock.base(topic, '比較', '比較', [])
        self.assertEqual(spec['style'], 'v3')
        rows = sns.select(RUN, {topic: REC}, {topic: spec}, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(sns.select(RUN, {topic: REC}, {topic: dict(style='v2')}, NOW), [])
        scratch = Path(__file__).resolve().parents[1] / 'build'
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            video = Path(tmp) / ('collespo_asset_' + topic + '.mp4')
            video.write_bytes(b'compare-media')
            digest = hashlib.sha256(video.read_bytes()).hexdigest()
            with patch.object(sns.gt, 'all_topics', return_value={topic: spec}):
                sns.write_receipts(tmp)
            receipt = video.with_suffix('.sns.json')
            self.assertEqual(json.loads(receipt.read_text()), dict(topic=topic, style='v3', sha256=digest))
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as z:
                z.write(receipt, receipt.name)
            self.assertTrue(sns.verify_receipt(archive.getvalue(), video.name, topic, digest))
            self.assertFalse(sns.verify_receipt(self.archive(receipt=False)[0], video.name, topic, digest))

    def test_social_workflows_prepare_generated_comparison_topics(self):
        root = Path(__file__).resolve().parents[1]
        for workflow in ('asset_social.yml', 'buffer_daily.yml'):
            with self.subTest(workflow=workflow):
                text = (root / '.github/workflows' / workflow).read_text(encoding='utf-8')
                prepare = 'python scripts/jp_assets.py --out build/jp_asset_topics.json'
                self.assertIn(prepare, text)
                self.assertLess(text.index(prepare), text.index('python scripts/asset_sns.py'))

    def test_invalid_id_is_an_error(self):
        with self.assertRaises(ValueError):
            sns.select(RUN, {TOPIC: dict(REC, video_id='bad')}, SPEC, NOW)

    def test_current_json_does_not_promote_old_render(self):
        archive, digest = self.archive(receipt=False)
        self.assertFalse(sns.verify_receipt(archive, 'collespo_asset_' + TOPIC + '.mp4', TOPIC, digest))

    def test_render_receipt_requires_exact_topic_version_and_hash(self):
        archive, digest = self.archive()
        self.assertTrue(sns.verify_receipt(archive, 'collespo_asset_' + TOPIC + '.mp4', TOPIC, digest))
        for override in [dict(topic='different', style='v3', sha256=digest),
                         dict(topic=TOPIC, style='v2', sha256=digest),
                         dict(topic=TOPIC, style='v3', sha256='wrong')]:
            with self.assertRaises(ValueError):
                sns.verify_receipt(self.archive(override=override)[0],
                                   'collespo_asset_' + TOPIC + '.mp4', TOPIC, digest)

    def test_disabled_flag_prevents_any_mutation(self):
        with patch.dict(os.environ, {'V3_SNS_ENABLED': ''}), patch.object(sns.bd, 'Ledger') as ledger:
            with self.assertRaises(RuntimeError):
                sns.distribute(RUN, sns.select(RUN, {TOPIC: REC}, SPEC, NOW), publish=True)
            ledger.assert_not_called()

    def test_validation_does_not_create_ledger_release_or_post(self):
        archive, _ = self.archive()
        scratch = Path(__file__).resolve().parents[1] / 'build'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as tmp, patch.object(sns, 'artifacts_of', return_value=archive), \
             patch.object(sns.bd, 'verify_youtube', return_value=dict(title='【MLB】ホワイトソックスが4連勝 #Shorts')), \
             patch.object(sns.bd, 'verify_media', return_value=46), \
             patch.object(sns.bd, 'Ledger') as ledger, patch.object(sns.bd, 'host_video') as host, \
             patch.object(sns.bd, 'graphql') as mutate, patch.object(sns, 'bsky_once') as bsky:
            prev = Path.cwd()
            try:
                os.chdir(tmp)
                sns.distribute(RUN, sns.select(RUN, {TOPIC: REC}, SPEC, NOW))
            finally:
                os.chdir(prev)
            for mock in [ledger, host, mutate, bsky]:
                mock.assert_not_called()

    def test_private_publication_waits_without_distributing(self):
        with patch.object(sns.bd, 'verify_youtube', side_effect=ValueError('YouTube video is not public')), \
             patch.object(sns, 'artifacts_of') as download:
            sns.distribute(RUN, sns.select(RUN, {TOPIC: REC}, SPEC, NOW))
            download.assert_not_called()

    def test_captions_use_published_facts_not_forecast(self):
        kind, _ = sns.register(TOPIC, 'season-review', RUN)
        rec = dict(REC, title='【MLB】ホワイトソックスが4連勝 #Shorts')
        for service in sns.bd.CHANNELS:
            caption = sns.bd.caption(service, '2026-10-07', rec, kind)
            self.assertIn('4連勝', caption)
            self.assertNotIn('明日の', caption)
            self.assertNotIn('進出争い', caption)
        self.assertLessEqual(sns.bd.x_weight(sns.bd.caption('twitter', '2026-10-07', rec, kind)), 280)

    def test_review_and_ps_captions_and_bluesky_descriptions(self):
        archive, _ = self.archive()
        for artifact, workflow, word, lead in [
                ('season-review', 'season_review.yml', 'シーズンまとめ', 'シーズンの試合を公式の数字で振り返ります'),
                ('ps-game-now', 'ps_game_now.yml', 'PSの話題', '試合とシリーズの状況を公式の数字で紹介します')]:
            run = dict(RUN, path='.github/workflows/' + workflow)
            with self.subTest(artifact=artifact), \
                 patch.object(sns, 'artifacts_of', return_value=archive), \
                 patch.object(sns.bd, 'verify_youtube', return_value=dict(title='【MLB】4連勝 #Shorts')), \
                 patch.object(sns.bd, 'verify_media', return_value=46), \
                 patch.object(sns.bd, 'extract_video', return_value=self.archive()[1]), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                sns.distribute(run, sns.select(run, {TOPIC: REC}, SPEC, NOW))
                words = sns.bd.KIND_WORDS['asset_' + TOPIC]
                self.assertEqual((words['short'], words['long'], words['lead']), (word, word, lead))
                result = json.loads(output.getvalue())
                self.assertEqual(result['bluesky']['embed']['external']['description'], 'コレスポの' + word + 'です。')
                for caption in result['captions'].values():
                    if artifact == 'season-review':
                        self.assertNotIn('PSの話題', caption)

    def test_bluesky_link_byte_ranges_and_embed(self):
        text = '村上宗隆の4連勝\nhttps://www.youtube.com/watch?v=xbfpDJqtQUk'
        record = sns.bsky_record(text, 'title', REC['video_id'], NOW)
        index = record['facets'][0]['index']
        self.assertEqual(text.encode()[index['byteStart']:index['byteEnd']].decode(), record['embed']['external']['uri'])

    def http(self, ledger=None):
        http = Mock()
        http.post.side_effect = [response(200, dict(handle='collespo.bsky.social', did='did:plc:mock', accessJwt='fake')),
                                 response(200, dict(uri='at://did:plc:mock/app.bsky.feed.post/key'))]
        http.get.return_value = response(400, dict(error='RecordNotFound'))
        return http

    def test_bluesky_reservation_precedes_new_only_write(self):
        ledger, http = Ledger(), self.http()
        post = sns.bsky_record('title', 'title', REC['video_id'], NOW)
        with patch.dict(os.environ, {'BLUESKY_HANDLE': 'collespo.bsky.social', 'BLUESKY_APP_PASSWORD': 'mock'}):
            sns.bsky_once(ledger, 'day:topic:bluesky', post, {}, http)
        data = http.post.call_args.kwargs['json']
        # 新規だけを作る createRecord（同じ rkey があれば失敗＝二重に作らない）
        self.assertTrue(http.post.call_args.args[0].endswith('com.atproto.repo.createRecord'))
        self.assertNotIn('swapRecord', data)
        self.assertTrue(data['validate'])
        self.assertEqual(ledger.data['deliveries']['day:topic:bluesky']['state'], 'sent')

    def test_uncertain_bluesky_receipt_is_reconciled_without_second_write(self):
        ledger, http = Ledger(), self.http()
        ledger.set('key', dict(state='reserved'))
        post = sns.bsky_record('title', 'title', REC['video_id'], NOW)
        http.get.return_value = response(200, dict(uri='at://receipt', value=post))
        with patch.dict(os.environ, {'BLUESKY_HANDLE': 'collespo.bsky.social', 'BLUESKY_APP_PASSWORD': 'mock'}):
            sns.bsky_once(ledger, 'key', post, {}, http)
        self.assertEqual(http.post.call_count, 1)  # Login only.

    def test_absent_post_after_uncertain_response_is_not_blindly_retried(self):
        ledger, http = Ledger(), self.http()
        ledger.set('key', dict(state='reserved'))
        with patch.dict(os.environ, {'BLUESKY_HANDLE': 'collespo.bsky.social', 'BLUESKY_APP_PASSWORD': 'mock'}):
            with self.assertRaises(RuntimeError):
                sns.bsky_once(ledger, 'key', sns.bsky_record('x', 'x', REC['video_id'], NOW), {}, http)
        self.assertEqual(http.post.call_count, 1)

    def test_sent_receipt_skips_even_login(self):
        ledger, http = Ledger(), self.http()
        ledger.set('key', dict(state='sent'))
        sns.bsky_once(ledger, 'key', {}, {}, http)
        http.post.assert_not_called()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
