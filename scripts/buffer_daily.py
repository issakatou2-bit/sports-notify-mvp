"""Publish the successful daily MLB Short to the three owned Buffer channels.

The source artifact is kept in a GitHub release. A separate Git branch stores a
durable reservation BEFORE each Buffer mutation. An uncertain response must be
reconciled, never blindly retried. No LLM calls or paid storage are required.
"""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from buffer_api import graphql
import content_hashtags as ht

REPO = 'issakatou2-bit/sports-notify-mvp'
API = 'https://api.github.com/repos/' + REPO
STATE_BRANCH = 'codex/buffer-state'
STATE_PATH = 'data/buffer_delivery.json'
JST = timezone(timedelta(hours=9))
CHANNELS = {'twitter': '6aa114c5cd8b9c702c36144a',
            'instagram': '6aa1debacd8b9c702c3cc4db',
            'tiktok': '6aa11393cd8b9c702c360d01'}
ORG = '6aa11108acee3b0c72033754'
MAX_BYTES = 80 * 1024 * 1024

# A post Buffer is still processing is not a post that failed.
#
# TikTok's video ingest routinely outruns the six minutes this runner waits,
# so 'sending' was painting one red run every single day while the Reel and
# the tweet were already live. A watchdog that cries wolf daily stops being
# read. Only a refused post, or one still unsettled long after both scheduled
# reconciles have had their turn, is an actual problem.
FAILED_STATES = ('error', 'rejected', 'failed')
STUCK_AFTER_HOURS = 12


def instant(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    return stamp


def handed_over_at(entry):
    """When Buffer took this post. None when the ledger cannot say."""
    for field in ('reserved_at', 'checked_at'):
        value = entry.get(field)
        if not value:
            continue
        try:
            return instant(value)
        except (ValueError, AttributeError, TypeError):
            continue
    return None


def still_settling(entry, now=None):
    """True while Buffer may yet deliver this post without our help."""
    state = entry.get('state')
    if state == 'sent' or state in FAILED_STATES:
        return False
    started = handed_over_at(entry)
    if started is None:
        return False  # Cannot tell how long it has been waiting; do not excuse it.
    now = now or datetime.now(timezone.utc)
    return now - started < timedelta(hours=STUCK_AFTER_HOURS)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        follow = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlparse(newurl).hostname != urllib.parse.urlparse(req.full_url).hostname:
            follow.remove_header('Authorization')
        return follow


def github(path, method='GET', body=None, raw=False):
    url = API + path
    req = urllib.request.Request(url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                 'User-Agent': 'Collespo/1.0'})
    with urllib.request.build_opener(SafeRedirect).open(req, timeout=60) as response:
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('GitHub response exceeds allowed size')
    return content if raw else json.loads(content) if content else {}


class Ledger:
    def __init__(self):
        try:
            github('/git/ref/heads/' + STATE_BRANCH)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            sha = github('/git/ref/heads/main')['object']['sha']
            github('/git/refs', 'POST', {'ref': 'refs/heads/' + STATE_BRANCH, 'sha': sha})
        try:
            result = github('/contents/' + STATE_PATH + '?ref=' + STATE_BRANCH)
            self.sha = result['sha']
            self.data = json.loads(base64.b64decode(result['content']))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            self.sha, self.data = None, {'version': 1, 'deliveries': {}}

    def save(self):
        body = {'message': 'Record Buffer delivery state', 'branch': STATE_BRANCH,
                'content': base64.b64encode(json.dumps(self.data, ensure_ascii=False, indent=2).encode()).decode()}
        if self.sha:
            body['sha'] = self.sha
        self.sha = github('/contents/' + STATE_PATH, 'PUT', body)['content']['sha']

    def set(self, key, value):
        self.data['deliveries'][key] = value
        self.save()


# 既定の枠。これまでどおり「明日の注目試合」。
DEFAULT_KIND = 'daily'

# 枠ごとの、どこから取るか。
#
# (記録の鍵, 成果物の名前, その中のファイル名, 元のワークフロー)
#
# 夕方の4本は既に `collespo-social-shorts` へまとめて保存されていて
# （morning_recap.yml が build/social_shorts/${mode}.mp4 にコピーする）、
# published_videos.json も同梱されている。**繋ぐだけで投げられる。**
SOURCES = {
    'daily': ('daily', 'collespo-video', 'collespo_short.mp4',
              'daily_notify.yml'),
    'morning': ('morning', 'collespo-social-shorts', 'players.mp4',
                'morning_recap.yml'),
    'morning_voices': ('morning_voices', 'collespo-social-shorts',
                       'voices.mp4', 'morning_recap.yml'),
    'morning_press': ('morning_press', 'collespo-social-shorts',
                      'press.mp4', 'morning_recap.yml'),
    'morning_postseason': ('morning_postseason', 'collespo-social-shorts',
                           'postseason.mp4', 'morning_recap.yml'),
}


def source_of(kind: str):
    if kind not in SOURCES:
        raise ValueError('Unknown kind: ' + str(kind))
    return SOURCES[kind]


def select_record(run, records, now, kind=DEFAULT_KIND):
    key, _, _, wf = source_of(kind)
    if run.get('head_branch') != 'main' or run.get('path') != '.github/workflows/' + wf:
        raise ValueError('Source must be ' + wf)
    if run.get('conclusion') != 'success' or run.get('event') not in ('workflow_dispatch', 'schedule', 'workflow_run'):
        raise ValueError('Source workflow did not finish successfully')
    if run.get('repository', {}).get('full_name') != REPO:
        raise ValueError('Unexpected source repository')
    created = instant(run['created_at'])
    day = created.astimezone(JST).date().isoformat()
    if day != now.astimezone(JST).date().isoformat():
        raise ValueError('Stale source: only the current JST edition may be posted')
    record = records.get(key, {}).get(day)
    if not record or not re.fullmatch(r'[A-Za-z0-9_-]{11}', record.get('video_id', '')):
        raise ValueError('No matching YouTube record for ' + key)
    if not created <= instant(record['published_at']) <= instant(run['updated_at']):
        raise ValueError('Video record was not produced during this workflow run')
    if instant(record.get('publish_at') or record['published_at']) > now:
        raise ValueError('YouTube publication is still in the future')
    return day, record


def latest_run(workflow: str, day: str):
    """その日に成功した、その枠の実行。無ければ None。"""
    try:
        runs = github('/actions/workflows/' + workflow
                      + '/runs?branch=main&status=success&per_page=10'
                      )['workflow_runs']
    except Exception:                                    # noqa: BLE001
        return None
    for run in runs:
        try:
            when = instant(run['created_at']).astimezone(JST).date()
        except Exception:                                # noqa: BLE001
            continue
        if when.isoformat() == day:
            return run
    return None


def due(services) -> list:
    """いま投げられる枠。**公開済みで、まだ投げていないものだけ。**

    なぜ要るのか:
      夕方の4本は15時台に作られ、公開は17:00〜20:00の予約になる。
      作った時点では「公開は未来」なので投げられない。
      19:47のcron（いまは照合だけをしている枠）で追いつく。

    返すのは [(枠, 実行ID)]。実行IDは成果物を取るために要る。
    """
    try:
        records = json.loads(Path('data/published_videos.json')
                             .read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    ledger = Ledger()
    now = datetime.now(timezone.utc)
    day = now.astimezone(JST).date().isoformat()
    out = []
    for kind, (key, _artifact, _name, wf) in sorted(SOURCES.items()):
        rec = (records.get(key) or {}).get(day)
        if not rec or not rec.get('video_id'):
            continue
        try:
            when = instant(rec.get('publish_at') or rec['published_at'])
        except Exception:                                # noqa: BLE001
            continue
        if when > now:
            continue                 # まだ公開されていない
        if all(ledger.data['deliveries'].get(day + ':' + kind + ':' + s)
               for s in services):
            continue                 # もう全部投げた
        run = latest_run(wf, day)
        if run:
            out.append((kind, run['id']))
    return out


def verify_youtube(record):
    query = urllib.parse.urlencode({'part': 'status,snippet', 'id': record['video_id'],
                                   'key': os.environ['YOUTUBE_API_KEY']})
    try:
        with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/videos?' + query, timeout=20) as response:
            items = json.load(response).get('items', [])
    except Exception:
        raise RuntimeError('Unable to verify YouTube publication') from None
    if not items or items[0]['status'].get('privacyStatus') != 'public':
        raise ValueError('YouTube video is not public')
    if items[0]['snippet']['channelId'] != 'UCpZ_j8X8uOex5VvKwwTJj3Q':
        raise ValueError('YouTube video belongs to a different channel')
    return items[0]['snippet']


def extract_video(archive, destination, wanted='collespo_short.mp4'):
    """成果物から1本だけ取り出す。**動画だけを見て、名前で選ぶ。**

    夕方の4本は `collespo-social-shorts` に4本まとめて入っていて
    （players.mp4 / voices.mp4 / press.mp4 / postseason.mp4）、
    サムネイル（short.png）や記録（published_videos.json）も同梱される。

    **「知らない名前があれば止める」にしていたら、short.png で
    9/19と9/20の2日続けて落ちた。**成果物の中身は枠を足すたびに
    変わるので、許す名前を並べる形は脆い。取り出すのは .mp4 だけで、
    それ以外は見ない。ここは自分のワークフローが作った成果物なので、
    外から知らないファイルが入ってくる経路は無い。

    `wanted` に合う .mp4 がちょうど1つでなければ止める（同名が2つ
    あればどちらか分からず、0なら枠を間違えている）。
    """
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        hits = [e for e in source.infolist()
                if e.filename.lower().endswith('.mp4')
                and e.filename.split('/')[-1] == wanted]
        if len(hits) != 1:
            raise ValueError('Expected exactly one %s in the artifact'
                             % wanted)
        entry = hits[0]
        if entry.file_size > MAX_BYTES or entry.file_size < 1000:
            raise ValueError('Invalid video size')
        # No archive path is used for extraction.
        with source.open(entry) as video:
            data = video.read(MAX_BYTES + 1)
        if len(data) != entry.file_size:
            raise ValueError('Incomplete video')
        destination.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def verify_media(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    media = json.loads(result.stdout)
    duration = float(media['format']['duration'])
    videos = [s for s in media['streams'] if s['codec_type'] == 'video']
    audios = [s for s in media['streams'] if s['codec_type'] == 'audio']
    if not 5 <= duration <= 140 or not videos or not audios:
        raise ValueError('Require a 5–140 second video with audio for all three platforms')
    video = videos[0]
    if video['codec_name'] != 'h264' or audios[0]['codec_name'] != 'aac':
        raise ValueError('Require H.264 and AAC')
    if abs(video['width'] / video['height'] - 9 / 16) > 0.02:
        raise ValueError('Require a vertical 9:16 video')
    return round(duration, 2)


def host_video(run, day, path, digest, kind=DEFAULT_KIND):
    source_of(kind)
    tag = 'social-' + kind + '-' + day
    try:
        release = github('/releases/tags/' + tag)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        release = github('/releases', 'POST', {
            # This release hosts media, not source code. Older source commits
            # can require workflows:write to tag when workflows changed since.
            # Use the maintained branch, keeping media provenance below and in
            # the delivery ledger; never broaden the publishing token's scope.
            'tag_name': tag, 'target_commitish': 'main',
            'name': day + ' ' + words(kind)['long'] + '・配信用動画',
            'body': 'コレスポの自動生成動画。YouTubeでの公開を確認後、SNS配信に利用します。\n元の実行: ' + run['html_url'] + '\n動画生成元SHA: ' + run['head_sha'] + '\n動画SHA256: ' + digest,
            'make_latest': 'false'})
    name = 'collespo-' + kind + '-' + day + '.mp4'
    asset = next((a for a in release['assets'] if a['name'] == name), None)
    if asset:
        if asset.get('digest') != 'sha256:' + digest:
            raise ValueError('Existing release video differs; refusing to replace it')
        return asset['browser_download_url']
    req = urllib.request.Request('https://uploads.github.com/repos/' + REPO + '/releases/' +
        str(release['id']) + '/assets?name=' + name, data=path.read_bytes(),
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Content-Type': 'video/mp4', 'User-Agent': 'Collespo/1.0'})
    with urllib.request.urlopen(req, timeout=120) as response:
        asset = json.load(response)
    if asset.get('digest') != 'sha256:' + digest:
        raise ValueError('Uploaded media digest mismatch')
    return asset['browser_download_url']


# 枠ごとの言い方。**1行目でその回が何なのかを言い切る。**
#
# 明日の注目試合の文面だけが埋め込まれていて、他の枠を投げられなかった。
# 同じ文で全部を出すと「明日の注目試合」が7本並ぶことになり、
# どれが何の回か分からなくなる。
#
# short … Xの1行目（文字数が厳しいので短く）
# long  … Instagram / TikTokの1行目
# lead  … 何を見られるかの一言
# cut   … 題からここより後ろを落とす（枠の名前が二重に出るため）
# sport … ハッシュタグを選ぶときの競技
#
# 一言は**ふつうの文**で終える。「キックオフ前に、見どころを。」のような
# 体言止めを並べると、読点のあとに句点が来る形が続いて読みにくい。
KIND_WORDS = {
    'daily': {'short': '明日のMLB', 'long': '明日の注目試合',
              'lead': '先発と見どころを、試合の前に確かめられます',
              'cut': '｜明日の注目試合', 'sport': 'mlb'},
    'morning': {'short': 'きょうの日本人選手', 'long': '日本人選手の成績',
                'lead': '誰がどれだけ動いたかが、成績の順に並びます',
                'cut': '｜', 'sport': 'mlb'},
    'morning_press': {'short': '現地の報道', 'long': '現地の報道',
                      'lead': '現地の記者と見出しが伝えていることを訳しました',
                      'cut': '｜', 'sport': 'mlb'},
    'morning_voices': {'short': '現地の反応', 'long': 'ファンのコメント欄',
                       'lead': '現地のファンの声をそのまま訳しました',
                       'cut': '｜', 'sport': 'mlb'},
    'morning_postseason': {'short': '進出争い', 'long': 'ポストシーズン進出争い',
                           'lead': 'マジックと、いまの並びを追いました',
                           'cut': '｜', 'sport': 'mlb'},
    'daily_soccer': {'short': '今夜の欧州サッカー', 'long': '今夜の注目カード',
                     'lead': 'キックオフ前に見どころを確かめられます',
                     'cut': '｜', 'sport': 'soccer'},
    'soccer_race': {'short': '欧州サッカー 順位争い',
                    'long': '欧州サッカー 順位争い',
                    'lead': '圏内と圏外の境目がどうなっているかを見ます',
                    'cut': '｜', 'sport': 'soccer'},
}


def words(kind: str, record=None) -> dict:
    result = dict(KIND_WORDS.get(kind) or KIND_WORDS[DEFAULT_KIND])
    if kind == 'morning_postseason':
        from race_words import ps_label
        # Use the verified video's edition, not today's possibly newer JSON.
        # The generator includes ps_label in the published title.
        title = (record or {}).get('title', '')
        if ps_label({}) in title:
            return result
        result.update(short=ps_label({'phase': 'postseason'}),
                      long=ps_label({'phase': 'postseason'}),
                      lead='各シリーズの勝敗と、勝ち上がりの状況を確認します')
        if 'ポストシーズン' not in title:
            result['lead'] = '公開動画で最新の状況を確認できます'
    return result


def first_game_reason(description):
    """Reuse one published reason from game 1, never a promotional footer.

    This is selection, not new reporting. A title alone cannot establish that
    a team is in a must-win game or a player will return from an injury.
    """
    in_game = False
    for line in (description or '').splitlines():
        line = line.strip()
        if re.match(r'^1\.\s+\d{2}/\d{2}\s+\d{2}:\d{2}\s+', line):
            in_game = True
            continue
        if in_game:
            if not line or not line.startswith('・'):
                break
            fact = line[1:].strip()
            if fact and len(fact) <= 72 and not re.search(r'https?://|#|[<>]', fact):
                return fact if fact.endswith(('。', '！', '？', '!', '?')) else fact + '。'
    return ''


def headline_game_reason(title, description):
    """Only reuse a reason from a game that explicitly matches the headline.

    The highlighted game is not necessarily game 1. Match registered subjects
    in the published text, without inferring rosters or inventing context.
    """
    subjects = [aliases for _, aliases in ht.entities()
                if any(ht.present(alias, title) for alias in aliases)]
    if not subjects:
        return ''
    blocks = re.split(r'(?m)^(?=\d+\.\s+\d{2}/\d{2}\s+\d{2}:\d{2}\s+)', description or '')
    matches = []
    for block in blocks:
        lines = block.splitlines()
        if not lines or not re.match(r'^\d+\.\s+\d{2}/\d{2}\s+\d{2}:\d{2}\s+', lines[0]):
            continue
        game = [lines[0]]
        for line in lines[1:]:
            if not line.strip().startswith('・'):
                break
            game.append(line.strip())
        text = '\n'.join(game)
        score = sum(any(ht.present(alias, text) for alias in aliases) for aliases in subjects)
        if score:
            reason = first_game_reason(re.sub(r'^\d+\.', '1.', text))
            if reason:
                matches.append((score, reason))
    if not matches:
        return ''
    best = max(score for score, _ in matches)
    reasons = {reason for score, reason in matches if score == best}
    return next(iter(reasons)) if len(reasons) == 1 else ''


def friendly_lead(title):
    # Only add grammar around facts already stated, preserving uncertainty.
    match = re.fullmatch(r'(.+?)\s+先発予定', title)
    if match:
        return match[1] + 'が先発予定です。'
    match = re.fullmatch(r'(.+?)\s+(\d+連勝中)', title)
    if match:
        return match[1] + 'は' + match[2] + 'です。'
    return title if title.endswith(('。', '！', '？', '!', '?')) else title + '。'


def caption(service, day, record, kind=DEFAULT_KIND):
    w = words(kind, record)
    title = ht.strip_tags(record['title'].split(w['cut'])[0].replace('【MLB】', '').strip())
    if kind == DEFAULT_KIND:
        title = re.split(r'｜\d{1,2}/\d{1,2}の注目試合', title)[0].strip()
    lead = friendly_lead(title) if kind == DEFAULT_KIND else title
    reason = headline_game_reason(title, record.get('description', '')) if kind == DEFAULT_KIND else ''
    details = [lead] + ([reason] if reason and reason != lead else [])
    youtube = 'https://www.youtube.com/watch?v=' + record['video_id']
    stamp = day[5:].replace('-', '/')
    if service == 'twitter':
        # Retain the topic and links. Drop optional whole sentences, never half a fact.
        for summary in dict.fromkeys(('\n'.join(details), lead)):
            for note in (w['lead'] + '。\n', ''):
                tags = ht.select(summary, service, sport=w['sport'])
                body = f'{stamp}更新｜{w["short"]}\n{summary}\n\n{note}{youtube}\nhttps://collespo.com/'
                text = body + '\n' + ht.display(tags)
                while x_weight(text) > 280 and tags:
                    tags.pop()
                    text = body + ('\n' + ht.display(tags) if tags else '')
                if x_weight(text) <= 280:
                    return text
        raise ValueError('X caption exceeds 280 weighted characters')
    summary = '\n'.join(details)
    tags = ht.select(summary, service, sport=w['sport'])
    return (f'{stamp}更新｜{w["long"]}\n{summary}\n\n' + w['lead'] + '。\n'
            '動画・記事はこちら：collespo.com\nYouTube：' + youtube +
            '\n\n音声：VOICEVOX:ずんだもん\n' + ht.display(tags))


def x_weight(text):
    return sum(1 if ord(c) <= 0x10ff or 0x2000 <= ord(c) <= 0x200d or
               0x2010 <= ord(c) <= 0x201f or 0x2032 <= ord(c) <= 0x2037 else 2
               for c in re.sub(r'https?://[^\s]+', 'x' * 23, text))


def selected_services(value):
    services = tuple(dict.fromkeys(s.strip() for s in (value or ','.join(CHANNELS)).split(',')))
    if not services or any(s not in CHANNELS for s in services):
        raise ValueError('BUFFER_CHANNELS must name only twitter, instagram or tiktok')
    return services


def recent_posts(channel):
    posts, cursor = [], None
    for _ in range(5):
        after = ', after: ' + json.dumps(cursor) if cursor else ''
        result = graphql('{ posts(first: 100' + after + ', input: { organizationId: ' +
            json.dumps(ORG) + ', filter: {channelIds:[' + json.dumps(channel) +
            ']}, sort:[{field:createdAt,direction:desc}]}) { edges {node {id text status externalLink}} pageInfo {hasNextPage endCursor} } }')['posts']
        posts.extend(e['node'] for e in result['edges'])
        if not result['pageInfo']['hasNextPage']:
            return posts
        cursor = result['pageInfo']['endCursor']
    raise RuntimeError('Too many posts to reconcile safely')


def create_payload(service, text, media_url):
    payload = {'channelId': CHANNELS[service], 'text': text, 'schedulingType': 'automatic',
               'mode': 'shareNow', 'assets': [{'video': {'url': media_url,
                           'metadata': {'thumbnailOffset': 2000}}}],
               'needsApproval': False, 'aiAssisted': True}
    if service == 'instagram':
        payload['metadata'] = {'instagram': {'type': 'reel', 'shouldShareToFeed': True, 'isAiGenerated': True}}
    elif service == 'tiktok':
        payload['metadata'] = {'tiktok': {'isAiGenerated': True}}
    return payload


def reconcile():
    """Refresh saved deliveries without creating media or posts, even after midnight."""
    ledger = Ledger()
    pending_services = {key.rsplit(':', 1)[-1] for key, entry in ledger.data['deliveries'].items()
                        if entry.get('state') != 'sent'}
    posts_by_channel = {service: recent_posts(channel) for service, channel in CHANNELS.items()
                       if service in pending_services}
    if not posts_by_channel:
        print('No pending deliveries; no Buffer request needed')
        return
    unresolved, settling = [], []
    for key, entry in list(ledger.data['deliveries'].items()):
        service = key.rsplit(':', 1)[-1]
        if entry.get('state') == 'sent' or service not in posts_by_channel:
            continue
        post = next((p for p in posts_by_channel[service]
                     if p['id'] == entry.get('post_id') or p['text'] == entry.get('text')), None)
        if post:
            ledger.set(key, {**entry, 'state': post['status'], 'post_id': post['id'],
                            'external_link': post.get('externalLink'),
                            'checked_at': datetime.now(timezone.utc).isoformat()})
        row = ledger.data['deliveries'][key]
        print(key, row.get('state'), row.get('external_link'))
        if row.get('state') == 'sent':
            continue
        (settling if still_settling(row) else unresolved).append(key)
    if settling:
        print('Buffer is still processing, which is not a failure: ' + ', '.join(settling))
    if unresolved:
        raise SystemExit('Still unconfirmed: ' + ', '.join(unresolved))


def submit_once(ledger, key, payload, metadata, retry_rejected=False):
    old = ledger.data['deliveries'].get(key)
    posts = recent_posts(payload['channelId'])
    matches = [p for p in posts if (old and p['id'] == old.get('post_id')) or p['text'] == payload['text']]
    if matches:
        post = matches[0]
        ledger.set(key, {**metadata, 'state': post['status'], 'post_id': post['id'],
                         'external_link': post.get('externalLink')})
        return post
    if old and not (old['state'] == 'rejected' and retry_rejected):
        raise RuntimeError('Existing reservation requires inspection; will not resend: ' + key)
    entry = {**metadata, 'state': 'reserved', 'text': payload['text'],
             'reserved_at': datetime.now(timezone.utc).isoformat()}
    ledger.set(key, entry)  # Must be durable before any external post mutation.
    result = graphql('mutation($input: CreatePostInput!) { createPost(input:$input) { '
        '__typename ... on PostActionSuccess { post { id status text externalLink } } '
        '... on MutationError { message } } }', {'input': payload})['createPost']
    if result.get('__typename') != 'PostActionSuccess':
        ledger.set(key, {**entry, 'state': 'rejected', 'message': result.get('message', 'Rejected')})
        raise RuntimeError('Buffer rejected post: ' + result.get('message', 'unknown'))
    post = result['post']
    ledger.set(key, {**entry, 'state': post['status'], 'post_id': post['id'],
                     'external_link': post.get('externalLink')})
    return post


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-run', type=int)
    # どの枠を投げるか。既定はこれまでどおり「明日の注目試合」。
    parser.add_argument('--kind', default=DEFAULT_KIND,
                        choices=sorted(SOURCES),
                        help='投げる枠（既定 daily）')
    parser.add_argument('--reconcile', action='store_true')
    parser.add_argument('--list-due', action='store_true',
                        help='いま投げられる枠と実行IDを1行ずつ出す')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--retry-rejected', action='store_true')
    args = parser.parse_args()
    if args.list_due:
        # 投げられる枠を1行ずつ。ワークフローがこれを読んで回す。
        rows = due(selected_services(os.environ.get('BUFFER_CHANNELS')))
        for kind, run_id in rows:
            print('%s\t%s' % (kind, run_id))
        if not rows:
            print('[info] いま投げられる枠はありません', file=sys.stderr)
        return
    if args.reconcile:
        reconcile()
        return
    if not args.source_run:
        parser.error('--source-run is required for validation or publication')
    services = selected_services(os.environ.get('BUFFER_CHANNELS'))
    run = github('/actions/runs/' + str(args.source_run))
    records = json.loads(Path('data/published_videos.json').read_text(encoding='utf-8'))
    day, record = select_record(run, records, datetime.now(timezone.utc),
                                args.kind)
    _key, _artifact, _file, _wf = source_of(args.kind)
    snippet = verify_youtube(record)
    record = {**record, 'title': snippet['title'], 'description': snippet.get('description', '')}
    available = graphql('{channels(input:{organizationId:' + json.dumps(ORG) + '}){id name service}}')['channels']
    for service in services:
        channel = CHANNELS[service]
        if not any(c['id'] == channel and c['service'] == service and c['name'] == ('collespo' if service == 'tiktok' else 'collespo_jp') for c in available):
            raise ValueError('Owned channel is missing: ' + service)
    artifacts = github('/actions/runs/' + str(args.source_run) + '/artifacts')['artifacts']
    selected = [a for a in artifacts
                if a['name'] == _artifact and not a['expired']]
    if len(selected) != 1 or selected[0]['size_in_bytes'] > MAX_BYTES:
        raise ValueError('Expected one unexpired source video artifact')
    artifact = github('/actions/artifacts/' + str(selected[0]['id']) + '/zip', raw=True)
    output = Path('build/buffer'); output.mkdir(parents=True, exist_ok=True)
    video = output / 'collespo_short.mp4'
    digest = extract_video(artifact, video, _file)
    duration = verify_media(video)
    texts = {service: caption(service, day, record, args.kind)
             for service in services}
    print(json.dumps({'edition': day, 'source_run': args.source_run, 'video_id': record['video_id'],
                      'duration': duration, 'sha256': digest, 'captions': texts}, ensure_ascii=False))
    if not args.publish:
        print('Validation only: no releases, reservations or posts created')
        return
    ledger = Ledger()
    url = host_video(run, day, video, digest, args.kind)
    failed = False
    for service in services:
        key = day + ':' + args.kind + ':' + service
        try:
            post = submit_once(ledger, key, create_payload(service, texts[service], url),
                {'source_run': args.source_run, 'youtube_id': record['video_id'], 'sha256': digest,
                 'media_url': url, 'checked_at': datetime.now(timezone.utc).isoformat()}, args.retry_rejected)
            print(service, json.dumps(post, ensure_ascii=False))
        except Exception as exc:
            print(service, 'Delivery did not complete:', type(exc).__name__, str(exc)[:300])
            failed = True
    # Give platforms time to process the uploaded video. This is a runner, not an interactive wait.
    for _ in range(12):
        pending = False
        for service in services:
            channel = CHANNELS[service]
            key = day + ':' + args.kind + ':' + service
            entry = ledger.data['deliveries'].get(key, {})
            if not entry.get('post_id'):
                continue
            post = next((p for p in recent_posts(channel) if p['id'] == entry['post_id']), None)
            if post:
                if entry.get('state') != post['status'] or entry.get('external_link') != post.get('externalLink'):
                    ledger.set(key, {**entry, 'state': post['status'], 'external_link': post.get('externalLink'),
                                     'checked_at': datetime.now(timezone.utc).isoformat()})
                print(service, post['status'], post.get('externalLink'))
                pending |= post['status'] not in ('sent', 'error')
        if not pending:
            break
        time.sleep(30)
    rows = {s: ledger.data['deliveries'].get(
        day + ':' + args.kind + ':' + s, {}) for s in services}
    statuses = {s: row.get('state') for s, row in rows.items()}
    pending = [s for s, row in rows.items() if row.get('state') != 'sent']
    waiting = [s for s in pending if still_settling(rows[s])]
    stuck = [s for s in pending if s not in waiting]
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as report:
            report.write('## Bufferへの動画配信\n\n' + day + ' / YouTube: https://youtu.be/' + record['video_id'] + '\n\n')
            for service in services:
                row = rows.get(service, {})
                report.write(f'- {service}: {row.get("state", "未投入")} {row.get("external_link") or ""}\n')
            if waiting:
                report.write('\n' + '・'.join(waiting) + ' はBufferがまだ処理中です。'
                             '**失敗ではありません。**19:47と23:47の照合で確定します。\n')
            report.write('\n`sent`はBufferの配信結果です。公開範囲と画面・音声は各SNSでも確認してください。未確定の再実行では二重投稿しません。\n')
    if failed or stuck:
        raise SystemExit('Some deliveries did not go through: ' + json.dumps(statuses))
    if waiting:
        print('Handed over; Buffer is still processing: ' + json.dumps(statuses))


if __name__ == '__main__':
    main()
