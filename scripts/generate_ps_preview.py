"""PS preview entry point; all other morning modes use the existing producer.

Fixture-confirmed preview owns its narration, bracket and JST schedule as one
material. This avoids presenting an already settled qualification race.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw
import video_common as vc

W, H, FPS = 1080, 1920, 24
BG, PANEL, INK, MUTED, ACCENT = '#111827', '#1e293b', '#f8fafc', '#b6c5d6', '#79d5bd'


def cards(context):
    matchups = context.get('matchups', [])
    if context['stage'] == 'bracket_pending':
        return [{'kind': 'ps_preview', 'speaker': 2,
                 'text': 'ポストシーズンの出場12球団が決まりました。組み合わせと開始時刻は、公式日程で確認でき次第お伝えします。',
                 'meta': {'view': 'pending'}}]
    first_day = min(m['first_game']['day_jst'] for m in matchups)
    day = datetime.fromisoformat(first_day)
    segments = [{'kind': 'ps_preview', 'speaker': 3,
                 'text': f'ポストシーズンの組み合わせが確定したのだ。日本時間{day.month}月{day.day}日から、ワイルドカードが始まるのだ。',
                 'meta': {'view': 'opening'}}]
    for lid, name in ((103, 'ア・リーグ'), (104, 'ナ・リーグ')):
        parts = [f'{name}の組み合わせです。']
        for m in matchups:
            if m['league'] != lid:
                continue
            parts.append(f"{m['home']['name']}対{m['away']['name']}。勝った球団は、地区シリーズで{m['bye']['name']}と対戦します。")
        segments.append({'kind': 'ps_preview', 'speaker': 2, 'text': ''.join(parts),
                         'meta': {'view': 'bracket', 'league': lid}})
    segments.append({'kind': 'ps_preview', 'speaker': 3,
                     'text': '初戦の日程はこちらなのだ。時刻はすべて日本時間。変更の可能性があるので、公式の最新日程も確認してほしいのだ。',
                     'meta': {'view': 'schedule'}})
    segments.append({'kind': 'ps_preview', 'speaker': 2,
                     'text': 'ワイルドカードは3試合制で2勝先取。全試合、表の左側の球団の本拠地です。短期決戦なので、まず初戦の先発投手と継投に注目です。第3戦は必要な場合のみ行います。',
                     'meta': {'view': 'guide'}})
    for reaction in context.get('reactions', [])[:1]:
        segments.append({'kind': 'ps_preview', 'speaker': 2,
                         'text': f"現地記者の{reaction['author']}さんは、こう投稿しています。{reaction['text']}",
                         'meta': {'view': 'reaction', 'reaction': reaction}})
    return segments


def narration(context):
    return {'title': 'MLBポストシーズン 組み合わせ・開幕日程',
            'date_jst': context['date_jst'], 'segments': cards(context),
            'source_url': context['source_url'], 'editorial_stage': context['stage']}


def draw_lines(d, text, x, y, size, color=INK, width=920):
    font = vc.font(size)
    for paragraph in text.split('\n'):
        for line in vc.wrap(d, paragraph, font, width):
            d.text((x, y), line, font=font, fill=color)
            y += int(size * 1.5)
    return y


def render(context, segment):
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((70, 135, 135, 145), fill=ACCENT)
    d.text((155, 110), 'コレスポ / MLB', font=vc.font(35), fill=ACCENT)
    d.text((70, 185), 'ポストシーズン', font=vc.font(60), fill=INK)
    d.text((70, 275), context['date_jst'] + ' 更新・時刻は日本時間', font=vc.font(30), fill=MUTED)
    view = segment['meta']['view']
    matchups = context.get('matchups', [])
    if view == 'opening':
        d.text((70, 330), '年間王者を決める短期決戦', font=vc.font(32), fill=MUTED)
        draw_lines(d, '組み合わせ\n決定', 70, 385, 96, width=925)
        day = datetime.fromisoformat(min(m['first_game']['day_jst'] for m in matchups))
        d.text((70, 740), f'{day.month}/{day.day} 開幕', font=vc.font(82), fill=ACCENT)
        draw_lines(d, 'ワイルドカード → 地区シリーズ', 70, 890, 39)
        for i, m in enumerate(matchups):
            y = 1040 + i * 100
            d.text((70, y), f"{m['home']['name']} × {m['away']['name']}", font=vc.font(35), fill=INK)
    elif view == 'bracket':
        lid = segment['meta']['league']
        name = 'ア・リーグ' if lid == 103 else 'ナ・リーグ'
        d.text((70, 390), name + 'の勝ち上がり', font=vc.font(52), fill=ACCENT)
        d.text((90, 505), 'ワイルドカード', font=vc.font(34), fill=MUTED)
        d.text((90, 553), '2勝先取', font=vc.font(29), fill=MUTED)
        d.text((635, 505), '地区シリーズ', font=vc.font(34), fill=MUTED)
        for i, m in enumerate(x for x in matchups if x['league'] == lid):
            y = 610 + i * 465
            d.rounded_rectangle((70, y, 530, y + 305), radius=20, fill=PANEL)
            draw_lines(d, m['home']['name'], 95, y + 35, 39, width=415)
            d.text((95, y + 115), 'vs', font=vc.font(28), fill=MUTED)
            draw_lines(d, m['away']['name'], 95, y + 175, 39, width=415)
            d.line((548, y + 148, 610, y + 148), width=6, fill=ACCENT)
            d.polygon([(610, y + 148), (589, y + 135), (589, y + 161)], fill=ACCENT)
            d.rounded_rectangle((630, y + 72, 1010, y + 248), radius=20, fill=PANEL)
            draw_lines(d, m['bye']['name'], 650, y + 105, 38, width=342)
            d.text((650, y + 179), '1回戦免除・相手待ち', font=vc.font(25), fill=MUTED)
            d.text((90, y + 332), '初戦 ' + m['first_game']['label'], font=vc.font(32), fill=INK)
        draw_lines(d, '左の勝者が、矢印の先の球団と対戦', 70, 1530, 32, MUTED)
        draw_lines(d, '地区S → リーグ優勝決定S → ワールドシリーズ', 70, 1600, 30, ACCENT)
    elif view == 'schedule':
        d.text((70, 390), 'ワイルドカード初戦', font=vc.font(56), fill=ACCENT)
        d.text((70, 469), 'すべて日本時間', font=vc.font(34), fill=MUTED)
        for i, m in enumerate(matchups):
            y = 540 + i * 237
            d.rounded_rectangle((70, y, 1010, y + 207), radius=20, fill=PANEL)
            d.text((95, y + 25), m['first_game']['label'], font=vc.font(54), fill=ACCENT)
            draw_lines(d, f"{m['home']['name']} vs {m['away']['name']}", 95, y + 111, 36, width=885)
        draw_lines(d, '地区シリーズの初戦', 70, 1530, 34)
        ds_labels = sorted({m['ds_first']['label'] for m in matchups})
        draw_lines(d, ' / '.join(ds_labels), 70, 1590, 31, MUTED)
    elif view == 'guide':
        d.text((70, 390), 'ここを見ると面白い', font=vc.font(56), fill=ACCENT)
        for i, (title, detail) in enumerate((('2勝で次のラウンドへ', '3試合制。第3戦は必要な場合のみ'),
                                           ('WCは全試合同じ本拠地', '表の左側の球団がホーム'),
                                           ('初戦の先発と継投に注目', '短期決戦・これはコレスポの見どころ'))):
            y = 575 + i * 330
            d.rounded_rectangle((70, y, 1010, y + 260), radius=20, fill=PANEL)
            draw_lines(d, title, 100, y + 35, 45, width=870)
            draw_lines(d, detail, 100, y + 141, 33, MUTED, width=870)
    elif view == 'reaction':
        r = segment['meta']['reaction']
        d.text((70, 390), '現地記者の投稿', font=vc.font(56), fill=ACCENT)
        y = draw_lines(d, r['text'], 90, 615, 48, width=900)
        draw_lines(d, r['author'] + ' / ' + r['outlet'], 90, y + 70, 33, MUTED)
        draw_lines(d, r['at'][:10] + 'の投稿・翻訳', 90, y + 160, 30, MUTED)
    else:
        draw_lines(d, '出場12球団決定', 70, 440, 70)
        draw_lines(d, '組み合わせ・開始時刻は\n公式日程で確認中', 70, 820, 48, MUTED)
    d.text((70, 1735), '出典：MLB公式日程 / 予定は変更される場合があります', font=vc.font(25), fill=MUTED)
    return im


def movie(context, script, audio_dir, out, require_audio):
    manifest = Path(audio_dir) / 'manifest.json'
    if not manifest.exists():
        raise ValueError('音声manifestがありません')
    audio = json.loads(manifest.read_text(encoding='utf-8'))['segments']
    if len(audio) != len(script['segments']) or any(a.get('meta') != b['meta'] or a.get('text') != b['text'] for a, b in zip(audio, script['segments'])):
        raise ValueError('生成原稿と音声manifestが不一致')
    if require_audio and any(not s.get('file') or not Path(s['file']).exists() or not s.get('duration') for s in audio):
        raise ValueError('音声の欠落があるため公開できません')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    durations = [max(4.0, float(s['duration']) + vc.SEGMENT_TAIL) for s in audio]
    track = vc.build_narration_track(audio, durations, out)
    if require_audio and not track:
        raise ValueError('音声を結合できません')
    video = out / 'collespo_morning_postseason.mp4'
    cmd = ['ffmpeg', '-y', '-nostats', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-framerate', str(FPS), '-i', '-']
    if track:
        cmd += ['-i', str(track)]
    cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
    if track:
        cmd += ['-c:a', 'aac', '-b:a', '160k', '-shortest']
    cmd += [str(video)]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as process:
        for i, (segment, duration) in enumerate(zip(script['segments'], durations)):
            im = render(context, segment)
            im.save(out / f'ps_preview_{i:02}.png')
            frame = im.tobytes()
            for _ in range(round(duration * FPS)):
                process.stdin.write(frame)
        process.stdin.close()
        if process.wait():
            raise ValueError('PS案内動画の書き出しに失敗')
    print(f'[info] PS案内動画: {video}')


def metadata(context):
    day = datetime.fromisoformat(context['date_jst'])
    stamp = f'{day.month}/{day.day}更新'
    if context['stage'] == 'bracket_pending':
        title = f'【{stamp}】MLBポストシーズン 出場12球団決定｜組み合わせ確認中 #Shorts'
        lines = ['出場12球団が決定。組み合わせと開始時刻は公式日程で確認中です。']
    else:
        opening = datetime.fromisoformat(min(m['first_game']['day_jst'] for m in context['matchups']))
        title = f'【{stamp}】MLBポストシーズン 組み合わせ確定｜日本時間{opening.month}/{opening.day}開幕 #Shorts'
        lines = ['対戦表、WC勝者の勝ち上がり先、日本時間の初戦日程をまとめました。', '', '【WC初戦・すべて日本時間】']
        for m in context['matchups']:
            lines.append(f"・{m['first_game']['label']} {m['home']['name']} vs {m['away']['name']} → 勝者は{m['bye']['name']}と地区シリーズ")
        lines += ['', 'WCは3試合制・2勝先取。全試合ホーム球団の本拠地。第3戦は必要な場合のみ。',
                  '先発・継投への注目はコレスポの見どころです。出場や勝敗の予想ではありません。',
                  '時刻未定の試合は確定時刻として扱っていません。日程は変更される場合があります。']
        for r in context.get('reactions', []):
            lines += ['', f"現地記者の投稿（{r['at']}・翻訳）：{r['author']}", r['url']]
    year = day.year
    lines += ['', f"資料時点：{context['retrieved_at']} / 公開日ではなくこの時点の予定です。",
              '出典：MLB公式日程', context['source_url'],
              f'https://www.mlb.com/news/{year}-mlb-playoff-and-world-series-schedule',
              '', 'コレスポ：https://collespo.com/', 'VOICEVOX:ずんだもん / VOICEVOX:四国めたん',
              '#MLB #ポストシーズン #Shorts']
    return {'snippet': {'title': title, 'description': '\n'.join(lines),
                        'tags': ['MLB', 'ポストシーズン', '組み合わせ', '日本時間', 'Shorts'],
                        'categoryId': '17', 'defaultLanguage': 'ja', 'defaultAudioLanguage': 'ja'}}


def upload(context):
    # Keep credentials, scheduling and publication ledger in the canonical
    # uploader. Only replace metadata for the verified preview edition.
    import inspect
    import upload_youtube as uploader
    original = uploader.build_metadata

    def preview_metadata(*args, **kwargs):
        values = inspect.signature(original).bind_partial(*args, **kwargs).arguments
        if values.get('kind') == 'morning' and values.get('morning_mode') == 'postseason' and context.get('stage') in ('bracket_preview', 'bracket_pending'):
            return metadata(context)
        return original(*args, **kwargs)

    uploader.build_metadata = preview_metadata
    sys.argv.remove('--upload')
    uploader.main()
    if context.get('stage') in ('bracket_preview', 'bracket_pending'):
        record = uploader.published_video('morning_postseason', context['date_jst'])
        if record.get('title') != metadata(context)['snippet']['title'] or not record.get('video_id'):
            raise ValueError('今回のPS案内の投稿記録がありません。既存動画と新MP4を混ぜてSNSへ配信しません')


def thumbnail(context, path):
    im = Image.new('RGB', (1280, 720), BG)
    d = ImageDraw.Draw(im)
    d.text((55, 35), 'MLBポストシーズン / コレスポ', font=vc.font(32), fill=ACCENT)
    d.text((55, 103), '組み合わせ決定' if context['stage'] == 'bracket_preview' else '出場12球団決定', font=vc.font(72), fill=INK)
    for i, m in enumerate(context['matchups']):
        d.text((55, 225 + i * 95), f"{m['home']['name']} × {m['away']['name']}", font=vc.font(42), fill=INK)
    d.text((55, 650), '勝ち上がり先・初戦の日本時間も', font=vc.font(30), fill=ACCENT)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--postseason', default='data/postseason.json')
    parser.add_argument('--mode', default='postseason')
    parser.add_argument('--narration-out')
    parser.add_argument('--audio-dir', default='build/mr_audio_postseason')
    parser.add_argument('--out', default='build/morning')
    parser.add_argument('--require-audio', action='store_true')
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--morning-mode', default='players')
    parser.add_argument('--thumbnail-out')
    args, _ = parser.parse_known_args()
    if not args.upload and not args.thumbnail_out and args.mode != 'postseason':
        raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).with_name('generate_morning_short.py')), *sys.argv[1:]]))
    if args.upload and args.morning_mode != 'postseason':
        import upload_youtube as uploader
        sys.argv.remove('--upload')
        uploader.main()
        return
    data = json.loads(Path(args.postseason).read_text(encoding='utf-8')) if Path(args.postseason).exists() else {}
    context = data.get('editorial', {})
    if args.upload:
        upload(context)
        return
    if args.thumbnail_out:
        if context.get('stage') in ('bracket_preview', 'bracket_pending'):
            thumbnail(context, args.thumbnail_out)
        else:
            raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).with_name('generate_thumbnail.py')), '--kind', 'morning', '--mode', 'postseason', '--out', args.thumbnail_out]))
        return
    if args.mode == 'postseason' and context.get('stage') == 'offseason':
        print('[info] PS案内はシーズン外のため作りません')
        return
    if context.get('suppress_unchanged'):
        if args.narration_out:
            Path(args.narration_out).unlink(missing_ok=True)
        print('[info] 公開済みと同じ対戦表・時刻・現地の材料のため、同内容を再制作しません')
        return
    if args.mode != 'postseason' or context.get('stage') not in ('bracket_preview', 'bracket_pending'):
        raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).with_name('generate_morning_short.py')), *sys.argv[1:]]))
    script = narration(context)
    if args.narration_out:
        path = Path(args.narration_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        movie(context, script, args.audio_dir, args.out, args.require_audio)


if __name__ == '__main__':
    main()
