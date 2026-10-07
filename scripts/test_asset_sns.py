"""出所・公開待ち・動画の版・応答不明・検証だけの副作用を固定材料で検査。"""
from datetime import datetime, timezone
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
        self.assertEqual(sns.select(RUN, {TOPIC: REC}, SPEC, NOW.replace(day=8)), [])
        for time in ['2026-10-07T06:09:00Z', '2026-10-07T06:21:00Z']:
            self.assertEqual(sns.select(RUN, {TOPIC: dict(REC, published_at=time)}, SPEC, NOW), [])
        self.assertEqual(sns.select(RUN, {TOPIC: dict(REC, privacy='private')}, SPEC, NOW), [])

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
        self.assertIn('swapRecord', data)
        self.assertIsNone(data['swapRecord'])
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
