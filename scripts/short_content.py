"""ショートの描画前検査。秒数を足さず、実際に使う材料の情報を数える。

情報単位は画面の元になる構造化された事実。表紙・本文の同じ事実は1件。
句点・場面数・文字数は情報数にしない。未対応の材料は確認不能として止める。
"""
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import unicodedata
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MIN_SECONDS = 28.0
TARGET_SECONDS = 30.0
MIN_INFORMATION = 3
VERSION = 'short-content-20261027-v1'


def normalized(value):
    return re.sub(r'[\s、。,.!！「」『』（）()：:／/｜|]+', '',
                  unicodedata.normalize('NFKC', str(value)))


def information(document, material=None):
    """描画する段だけの情報。現在の別ファイルを勝手に根拠にしない。"""
    material = material or {}
    found = {}
    segments = document.get('segments') or []

    def quote_source(value, said, inherited=None):
        if isinstance(value, dict):
            source = value.get('url') or value.get('source_url') or value.get('uri') or inherited
            if source and any(normalized(said) in normalized(value.get(k) or '') for k in ('ja', 'jp', 'said')):
                return source
            return next((found for item in value.values() if (found := quote_source(item, said, source))), None)
        if isinstance(value, list):
            return next((found for item in value if (found := quote_source(item, said, inherited))), None)
        if isinstance(value, str) and inherited and normalized(said) == normalized(value):
            return inherited
        return None

    def add(subject, predicate, value, source, index):
        if value is None or value == '' or value == [] or value == {}:
            return
        if isinstance(value, str) and re.fullmatch(r'(?:確認中|不明|未確認|未定)', value.strip()):
            return
        if not source:
            return
        def canonical(item):
            if isinstance(item, str):
                return normalized(item)
            if isinstance(item, dict):
                return {str(k):canonical(v) for k,v in item.items()}
            if isinstance(item, (list, tuple)):
                return [canonical(v) for v in item]
            return item
        identity = json.dumps([normalized(subject), normalized(predicate), canonical(value)],
                              ensure_ascii=False, sort_keys=True)
        if identity not in found:
            found[identity] = dict(subject=subject, fact=predicate, value=value,
                                   source=source, segments=[])
        if index not in found[identity]['segments']:
            found[identity]['segments'].append(index)

    for index, seg in enumerate(segments):
        kind = seg.get('kind')
        meta = seg.get('meta') or {}
        if kind in ('outro', 'cover', 'ranking', 'score'):
            continue
        card = meta.get('card') or {}
        if card and not card.get('outro') and not card.get('next_line'):
            source = card.get('source_url') or document.get('source_url')
            board = card.get('scoreboard') or {}
            rows = board.get('rows') or []
            if len(rows) == 2:
                subject = '対'.join(sorted(r['name'] for r in rows))
                add(subject, 'シリーズ勝敗', sorted((r['name'], r['wins']) for r in rows), source, index)
            else:
                subject = card.get('headline') or 'PS'
            for item in card.get('items') or []:
                label, value = item.get('label', ''), item.get('value')
                # 同じ勝敗から導く王手・突破・次の第何戦は独立の情報にしない。
                if label in ('シリーズの現在地', 'シリーズの決着', 'シリーズ勝者', '勝者が進む先'):
                    continue
                if label.startswith('日本時間'):
                    add(subject, '開始予定', [card.get('date'), label], source, index)
                elif value is not None and label:
                    add(subject, label, value, source, index)
        for row in meta.get('quote_rows') or []:
            # 引用は発言の一次記録。事実の正しさを示す根拠にはしない。
            said = row.get('said') or row.get('ja')
            source = row.get('url') or row.get('source_url')
            headlines = meta.get('source_headlines') or []
            source = source or next((h.get('url') or ' / '.join(str(h.get(k) or '') for k in ('source','at','title'))
                                    for h in headlines if normalized(h.get('jp')) == normalized(said)), None)
            source = source or ((material.get('voices') or {}).get('video_url') if isinstance(material.get('voices'), dict) else None)
            source = source or quote_source(material.get('voices'), said) or quote_source(material.get('reporters'), said)
            add('引用', '発言', said, source, index)
        if kind == 'voice' and isinstance(meta.get('index'), int):
            rows = material.get('voices') or []
            if isinstance(rows, list) and meta['index'] < len(rows):
                row = rows[meta['index']]
                add('引用', '発言', row.get('ja'), row.get('url') or material.get('video_url'), index)
        # 資産の札と読みは同じ items から作る。1札内の言い換えは1件。
        if material.get('items') and kind in ('list', 'intro'):
            start = meta.get('start', 0)
            count = meta.get('count', 0) if kind == 'list' else 0
            for title, body in material['items'][start:start+count]:
                if any(x in title for x in ('コメント', '見出し', '番記者')):
                    continue
                if str(material.get('key','')).startswith('legend_'):
                    # 同じ札の殿堂入りと通算成績は別の事実。文や数字だけの分割ではない。
                    year = re.search(r'(\d{4})年に殿堂入り', body)
                    if year:
                        add(title, '殿堂入り年', int(year[1]), 'MLB公式 / Hall of Fame recipients', index)
                    for value, unit in re.findall(r'(\d+)(本塁打|安打|奪三振|勝)', body):
                        add(title, '通算'+unit, int(value), 'MLB公式 / 通算成績', index)
                    continue
                add(material.get('key') or material.get('label'), title, body,
                    material.get('source') or document.get('source_url') or '生成材料:items', index)
        if kind == 'people' and meta.get('group') in ('japanese', 'stars'):
            for person in material.get(meta['group']) or []:
                add(person.get('name'), '当該期間の成績', person.get('line') or person.get('why'),
                    material.get('source') or 'MLB公式 / 生成材料:'+meta['group'], index)
        # 朝の日本人選手。成績の束は1件とし、順位と同じ成績の再掲を足さない。
        players = material.get('players') or []
        if isinstance(players, list) and kind in ('intro', 'hero', 'list', 'others') and players and 'headline' in players[0]:
            shown = players[:1] if kind in ('intro', 'hero') else players[meta.get('start', 0):meta.get('start', 0)+meta.get('count', 0)]
            for person in shown:
                add(person.get('name'), '当日成績', person.get('headline'), 'MLB公式 / 生成入力:players', index)
        if kind == 'week' and meta.get('week'):
            add('日本人選手', '直近7日', meta['week'], 'MLB公式 / 保存した7日集計', index)
        if kind in ('p_career', 'p_season', 'p_recent', 'p_awards'):
            field = {'p_career':'career', 'p_season':'this_season', 'p_recent':'recent', 'p_awards':'awards'}[kind]
            add(material.get('name'), field, material.get(field), material.get('source') or 'MLB公式 / 選手資料', index)
        if kind == 'check':
            streaks = material.get('streaks') or []
            if isinstance(meta.get('index'), int) and meta['index'] < len(streaks):
                row = streaks[meta['index']]
                add(row.get('team'), '注目理由の検算', row, '保存した公式結果と予告記録', index)
        if kind == 'totals' and material.get('decided'):
            add('当週', '結果集計', {k:material.get(k) for k in ('decided','home_wins','away_wins','one_run')}, '保存した公式結果', index)
        if kind in ('career', 'base') and meta:
            add('注目試合の累積', kind, {k:v for k,v in meta.items() if k!='who'}, '保存した公式結果の累積', index)
        if kind in ('numbers', 'report') and meta.get('source'):
            # player_story.validateが照合する本人の成績・日付つきの報道。
            if document.get('program') in ('player_story', 'reddit_reaction') or document.get('player'):
                add((document.get('player') or {}).get('name_jp'), kind, seg.get('text'), meta.get('url') or meta['source'], index)
        if kind == 'game' and isinstance(meta.get('game_index'), int):
            games = material.get('games') or []
            if meta['game_index'] < len(games):
                game = games[meta['game_index']]
                subject = str(game.get('game_id') or game.get('gamePk'))
                add(subject, '開始予定', game.get('start_time_jst'), material.get('source') or '生成入力:公式日程', index)
                for side in ('home', 'away'):
                    standing = game.get(side+'_standing') or {}
                    if standing:
                        add(game.get(side+'_team_name'), '順位と勝点', standing, '生成入力:同大会順位表', index)
        # サッカーの各段の元データだけを読む。
        games = material.get('games') or []
        event_id = meta.get('event_id') or meta.get('game_id')
        game = next((g for g in games if str(g.get('id') or g.get('game_id')) == str(event_id)), None)
        if game and game.get('score'):
            source = material.get('source') or 'ESPN / 試合終了・最終名簿照合済み生成入力'
            subject = str(event_id)
            if kind in ('intro', 'followup'):
                add(subject, '試合結果', game['score'], source, index)
            if kind in ('intro', 'roster', 'player-stats', 'followup') and not (kind == 'followup' and meta.get('score_only')):
                people = game.get('players') or []
                if kind == 'intro':
                    people = people[:1]
                if kind == 'player-stats':
                    people = people[meta.get('start', 0):meta.get('start', 0)+meta.get('count', 1)]
                for person in people:
                    if person.get('status') == 'none':
                        continue
                    add(person['name'], '出場と得点関与',
                        {k: person[k] for k in ('status', 'minutes', 'goals', 'assists') if k in person}, source, index)
                    if kind == 'player-stats':
                        import soccer_stats
                        personal = soccer_stats.personal_narration(person)
                        if personal:
                            add(person['name'], '本人の詳細成績', personal, source, index)
            if kind in ('result', 'followup-detail'):
                for goal in meta.get('goals', game.get('goals', [])):
                    add(subject, '得点経過', {k: goal.get(k) for k in ('side', 'minute', 'scorer', 'own_goal')}, source, index)
            if kind == 'team-stats':
                import soccer_stats
                add(subject, 'チームの詳細成績', meta.get('short_context_stats') or soccer_stats.commentary(game), source, index)
        if kind == 'followup-next' and meta.get('row'):
            add('次戦', '公式日程', meta['row'], material.get('source') or '生成入力:preview_followup', index)
        if kind == 'followup-change':
            for row in meta.get('rows', []):
                add(row.get('club'), '順位の変化', [row.get('before'), row.get('after')], row.get('source'), index)
        # v4/v5/v6 予告・順位・週末：表示した値だけ（未表示の入力は数えない）。
        if kind == 'preview' and meta.get('home'):
            subject = meta['home']+'対'+meta['away']
            add(subject, '開始予定', [meta.get('date'), meta.get('time')], '生成入力:公式日程', index)
            for side, rank in (meta.get('ranks') or {}).items():
                import notability_engine
                name = normalized(notability_engine.club_name_jp(meta[side]))
                text = normalized(seg.get('text',''))
                # コンパクト予告は順位を本文に描かない。短縮後も実際に読む値だけ。
                if (normalized(str(rank)+'位')+name in text or name+normalized(f'は{rank}位') in text
                        or name+normalized(f'は現在{rank}位') in text):
                    add(meta[side], '当該大会順位', rank, '生成入力:同大会順位表', index)
            for reason in (meta.get('interest') or {}).get('reasons', []):
                if reason.get('evidence') and reason.get('text') and normalized(reason['text']) in normalized(seg.get('text','')):
                    add(subject, reason.get('kind'), reason['text'], '生成入力:'+str(reason['evidence']), index)
        if kind == 'standings':
            for row in meta.get('rows', []):
                position = row.get('position')
                if not meta.get('shown') or any(a <= position <= b for a, b in meta['shown']):
                    add(row.get('team_en') or row.get('team'), '順位と勝点',
                        [position, row.get('points')], '生成入力:同大会順位表', index)
        if kind == 'jp_roster':
            for row in meta.get('rows', []):
                add(row.get('name'), '当週の成績', row, '生成入力:公式試合と名簿', index)
    return list(found.values())


def assess(document, durations, material=None, *, maximum=60):
    reasons = []
    try:
        units = information(document, material)
    except (KeyError, TypeError, ValueError, AttributeError):
        units = []
        reasons.append('元材料の型・必要な欄が一致しないため情報数を確認できません')
    valid = len(durations) == len(document.get('segments') or []) and bool(durations)
    valid = valid and all(type(x) in (int, float) and math.isfinite(x) and x > 0 for x in durations)
    total = sum(durations) if valid else None
    if not valid:
        reasons.append('区間数または長さが不明・不正です')
    elif total < MIN_SECONDS - 1e-6:
        reasons.append(f'長さ{total:.3f}秒が下限{MIN_SECONDS:g}秒未満です')
    elif total > maximum + 1e-6:
        reasons.append(f'長さ{total:.3f}秒が既存上限{maximum:g}秒を超えます')
    if len(units) < MIN_INFORMATION:
        reasons.append(f'確認できる独立情報{len(units)}件。主の事実1件＋2次情報2件以上が必要です')
    return dict(version=VERSION, status='held' if reasons else 'passed',
                minimum_seconds=MIN_SECONDS, target_seconds=TARGET_SECONDS,
                maximum_seconds=maximum, planned_seconds=total,
                information_count=len(units), supplementary_count=max(0, len(units)-1),
                information=units, reasons=reasons,
                action='材料を増やして再作成・他の回とまとめる・見送り。言い換えや無音で延ばさない' if reasons else '')


def require(document, durations, out, material=None, *, maximum=60, video_name=None):
    """音声結合・フレーム描画より先。失敗理由を保存して必ず停止する。"""
    report = assess(document, durations, material, maximum=maximum)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    report['segments_sha256'] = hashlib.sha256(json.dumps(document.get('segments'), ensure_ascii=False,
        sort_keys=True).encode()).hexdigest()
    report['video_name'] = video_name
    (out/'short_content_gate.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if video_name:
        (out/(video_name+'.short_content.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if report['reasons']:
        import os
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
                stream.write('\n### ショート制作見送り\n\n'+'\n'.join('- '+reason for reason in report['reasons'])+'\n')
        raise ValueError('ショート制作見送り: '+' / '.join(report['reasons']))
    return report


def validate_upload(video):
    """描画に失敗して残った旧MP4や別動画の合格を公開に流用しない。通信前に呼ぶ。"""
    import subprocess
    import shutil
    video = Path(video)
    receipt = video.with_name(video.name+'.short_content.json')
    if not receipt.is_file():
        raise ValueError('ショートの長さ・情報数の合格記録がありません。再制作してください')
    report = json.loads(receipt.read_text(encoding='utf-8'))
    if (report.get('version') != VERSION or report.get('status') != 'passed'
            or report.get('video_name') != video.name or report.get('information_count', 0) < MIN_INFORMATION
            or len(report.get('information', [])) != report.get('information_count')
            or video.stat().st_mtime_ns < receipt.stat().st_mtime_ns):
        raise ValueError('ショートの検査が不合格・古い記録・別動画です。公開を停止します')
    executable = shutil.which('ffmpeg')
    if not executable:
        # システムのFFmpegがない場合だけ、任意の同梱版を読み込む。
        imageio_ffmpeg = importlib.import_module('imageio_ffmpeg')
        executable = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run([executable, '-hide_banner', '-i', str(video)], capture_output=True,
                           text=True, encoding='utf-8', errors='replace')
    match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', probe.stderr)
    seconds = int(match[1])*3600+int(match[2])*60+float(match[3]) if match else None
    if (seconds is None or seconds < MIN_SECONDS-.01 or seconds > report.get('maximum_seconds', 60)+.05
            or abs(seconds-report.get('planned_seconds', 0)) > .15):
        raise ValueError('完成ショートの尺が下限・既存上限・検査時の計画を満たしません')
    report['actual_seconds'] = seconds
    return report


def publication_fields(report):
    """次回の洗い出しで尺を不明に戻さない。既存の台帳書込み器へ渡す。"""
    return dict(duration_seconds=report['actual_seconds'], short_information_count=report['information_count'],
                short_content_policy=report['version'])
