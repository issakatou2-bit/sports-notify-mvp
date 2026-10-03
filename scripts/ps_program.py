"""Verified PS programs for the existing daily and morning_postseason slots.

No paid model calls and no new periodic workflow. A failed v2 never publishes
the old race program. Canonical uploader and ledger remain authoritative.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

from ps_render_template import render
from ps_daily_titles import ROUND, forecast_title, situation
import ps_editorial as pe
import ps_series as series
import ps_focus as focus
import video_common as vc
import ps_motion_template as motion
from notability_engine import MLB_TEAM_COLOR
from ps_brand_components import TEAM_SECONDARY_COLORS
from generate_narration import display_name, speech_name

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
VERSION = 'ps-program-20260928-v2'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def layout():
    value = os.getenv('PS_PROGRAM_LAYOUT', 'v2')
    if value not in ('v2', 'legacy', 'hold'):
        raise ValueError('Unknown PS_PROGRAM_LAYOUT; hold instead of fallback')
    return value


def desired(snapshot):
    ctx = snapshot.get('editorial', {})
    rows = snapshot.get('teams', {})
    rows = rows.values() if isinstance(rows, dict) else rows
    qualified = sum(bool(x.get('clinched') or x.get('div_champ') or x.get('wc_clinched')) for x in rows)
    return (snapshot.get('phase') in ('postseason', 'settled') or qualified == 12
            or ctx.get('stage') in ('bracket_preview', 'bracket_pending', 'series'))


def previous(ledger, kind):
    records = ledger.get(kind, {})
    if not isinstance(records, dict):
        return {}
    return next((row for _, row in sorted(records.items(), reverse=True)
                 if row.get('video_id') and row.get('program_version') == VERSION), {})


def validate_source(snapshot, evidence, now):
    stamp = datetime.fromisoformat(evidence['retrieved_at'])
    age = now - stamp
    if not timedelta(0) <= age <= timedelta(hours=2):
        raise ValueError('PS日程が古いか未来の取得時刻です')
    ctx = pe.editorial(snapshot, evidence['schedule'], now, evidence['source_url'])
    games = [g for d in evidence['schedule'].get('dates', []) for g in d.get('games', [])]
    for game in games:
        if game.get('gameType') not in ROUND:
            raise ValueError('PS専用資料に対象外の試合が混入')
        if game.get('status', {}).get('abstractGameState') == 'Final':
            winners = [game['teams'][s].get('isWinner') for s in ('home', 'away')]
            if any(w is not None and type(w) is not bool for w in winners) or sum(w is True for w in winners) != 1:
                raise ValueError('終了試合の勝者が一意に確認できません')
    return ctx, games


def common(ctx, label, day=None):
    return dict(date=day or ctx['date_jst'], source_url=ctx['source_url'],
                source_label='MLB公式日程', sport='MLB', label=label,
                glossary='WCS 2勝 / DS 3勝\nLCS・WS 4勝で決着', production=True)


def segment(card, text, ids=(), speaker=2):
    return dict(kind='ps_program', speaker=speaker, text=text,
                meta=dict(card=card, game_ids=list(ids)))


def spoken_clock(value):
    hour,minute=map(int,value.split(':'))
    return f'{hour}時' + (f'{minute}分' if minute else '')


def spoken_start(value):
    day,clock=value.split()
    month,date=map(int,day.split('/'))
    return f'{month}月{date}日' + spoken_clock(clock)


def club_color(team_id):
    return MLB_TEAM_COLOR.get(str(team_id))


def probable(team):
    """Only a named, identified probable pitcher from this exact official game."""
    row=team.get('probablePitcher') or {}
    if type(row.get('id')) is not int or not row.get('fullName'):
        return None
    return dict(id=row['id'],name=row['fullName'],display=display_name(row['fullName']))


def pitcher_speech(card):
    statements=[]
    for side in ('home','away'):
        pitcher=card.get(side+'_pitcher')
        if pitcher:
            name=speech_name(pitcher['name'])
            # Preserve unknown Latin spellings on screen, rather than guessing a reading.
            if not any(c.isascii() and c.isalpha() for c in name):
                statements.append(card[side]+'の先発予定は'+name+'です。')
    return ''.join(statements)


def render_segment(seg,layers=False):
    side={2:'right',3:'left'}.get(seg['speaker'])
    if side is None:raise ValueError('画面素材のない話者です')
    return render(seg['meta']['card'],presenters=side,layers=layers)


def forecast(ctx, games, rows, now, target_day=None):
    target = target_day or (now.astimezone(JST).date() + timedelta(days=1)).isoformat()
    target_date = datetime.fromisoformat(target).date()
    # An unknown US start can fall on either this Japanese date or the previous
    # one. Do not silently omit it while promising coverage of every game.
    unresolved_days = {target_date.isoformat(), (target_date - timedelta(days=1)).isoformat()}
    by = {row['key']: row for row in rows if row.get('teams')}
    cards = []
    for g in games:
        status = g.get('status', {})
        if (status.get('abstractGameState') == 'Final'
                or status.get('detailedState') in ('Postponed', 'Cancelled', 'Canceled')
                or status.get('codedGameState') in ('D', 'C')):
            continue
        teams = g['teams']
        if not all(series.is_real(teams[s]['team']) for s in ('home', 'away')):
            if status.get('startTimeTBD', True):
                relevant = not g.get('officialDate') or g['officialDate'] in unresolved_days
            else:
                relevant = datetime.fromisoformat(g['gameDate'].replace('Z', '+00:00')).astimezone(JST).date().isoformat() == target
            if relevant:
                raise ValueError(f'試合{g["gamePk"]}の対戦相手が未確定で対象日の全試合を確定できません')
            continue
        ids = [teams[s]['team']['id'] for s in ('home', 'away')]
        row = by.get(series.series_key(g['gameType'], *ids))
        if not row or row['over']:
            continue
        if status.get('startTimeTBD', True):
            if not g.get('officialDate') or g['officialDate'] in unresolved_days:
                raise ValueError(f'試合{g["gamePk"]}の時刻未定で対象日の全試合を確定できません')
            continue  # A dummy timestamp cannot establish tomorrow in JST.
        start = datetime.fromisoformat(g['gameDate'].replace('Z', '+00:00')).astimezone(JST)
        if start.date().isoformat() != target:
            continue
        keyed = {t['id']: t for t in row['teams']}
        card = dict(game_id=g['gamePk'], round=g['gameType'], game_number=g['seriesGameNumber'],
                    home=keyed[ids[0]]['name'], away=keyed[ids[1]]['name'],
                    home_wins=keyed[ids[0]]['wins'], away_wins=keyed[ids[1]]['wins'],
                    when=start.strftime('%H:%M'), conditional=g['seriesGameNumber'] > row['need'],
                    jp_team=any(t.get('players') for t in row['teams']),
                    jp_home=bool(keyed[ids[0]]['players']), jp_away=bool(keyed[ids[1]]['players']),
                    home_players=keyed[ids[0]]['players'],away_players=keyed[ids[1]]['players'],
                    home_color=club_color(ids[0]),away_color=club_color(ids[1]),
                    home_secondary=TEAM_SECONDARY_COLORS.get(str(ids[0])),away_secondary=TEAM_SECONDARY_COLORS.get(str(ids[1])),
                    home_pitcher=probable(teams['home']),away_pitcher=probable(teams['away']))
        match=next((m for m in ctx.get('matchups',[]) if m.get('game_pk')==g['gamePk']),None)
        card['bye']=match['bye']['name'] if match else None
        situation(card)
        cards.append(card)
    cards.sort(key=lambda c: (c['when'], c['game_id']))
    if not cards:
        return None
    lead = next((i for i, c in enumerate(cards) if c['jp_team']), 0)
    chosen = cards[lead]
    lead_side = 'away' if len(chosen['away_players'])>len(chosen['home_players']) else 'home'
    title = forecast_title(cards, target, lead, lead_side)
    if chosen[lead_side+'_players']:
        title=title.replace(chosen[lead_side],chosen[lead_side+'_players'][0]+'が所属する'+chosen[lead_side],1)
    pages = []
    date_label = datetime.fromisoformat(target).strftime('%m/%d').lstrip('0')
    for start in range(0, len(cards), 4):
        group = cards[start:start + 4]
        lead_name = chosen[lead_side]
        round_label = {'F':'WCS','D':'DS','L':'LCS','W':'WS'}[chosen['round']]
        headline = lead_name + '\n明日' + date_label + ' ' + round_label
        cover = dict(common(ctx, 'PS予告', target), layout='schedule',
                     headline=headline if start == 0 else 'PS全試合日程\n続き', subhead=f'第{chosen["game_number"]}戦 / 日本時間 / 全{len(cards)}試合',
                     items=[dict(when=f'{date_label} {c["when"]}', home=c['home'], away=c['away'],home_color=c['home_color'],away_color=c['away_color'],home_secondary=c['home_secondary'],away_secondary=c['away_secondary']) for c in group],
                     headline_colors=[chosen[lead_side+'_color'],None])
        text = title.split('｜')[0] + '。' if start == 0 else '残りの試合の日程です。'
        pages.append(segment(cover, text, [c['game_id'] for c in group], 3))
    # **カードは日本人選手のいる試合から**（表紙の日程表は時刻順のまま）。
    # 10/3 本人「明日の注目試合は特に、日本人選手や、日本人選手の所属する
    # 球団に注目しましょう」。同じ組の中は時刻順。
    ordered = sorted(cards, key=lambda c: (0 if c['jp_team'] else 1, c['when'], c['game_id']))
    for index,c in enumerate(ordered,1):
        state = situation(c)
        rnd = ROUND[c['round']][0]
        note = (('前戦の結果次第で開催される試合' if c['conditional'] else '前戦は結果未確定') if state == 'pending_results' else
                '勝った球団がシリーズを制する試合' if state == 'decider' else
                '世界一がかかる試合' if c['round'] == 'W' and state == 'clinch_chance' else
                '突破と敗退回避がかかる試合' if state == 'clinch_chance' else 'シリーズの初戦' if state == 'opening' else 'シリーズの次戦')
        first_item=dict(label='日本時間の開始予定',value=c['when'],value_size=110)
        if state=='opening':
            if c['home_pitcher'] or c['away_pitcher']:
                items=[first_item]+[dict(label=c[s]+' / 先発予定',value=(c[s+'_pitcher'] or {}).get('display','確認中'),value_size=60,team_color=c[s+'_color'],team_secondary=c[s+'_secondary']) for s in ('home','away')]
            else:
                onward={'F':'地区シリーズ','D':'リーグ優勝決定シリーズ','L':'ワールドシリーズ','W':'世界一'}[c['round']]
                advance=dict(label='勝者の地区シリーズの相手',value=c['bye']) if c['round']=='F' and c['bye'] else dict(label='勝者が進む先' if c['round']!='W' else 'シリーズ勝者',value=onward)
                items=[first_item,advance,dict(label='シリーズの決着',value=f'{ROUND[c["round"]][1]//2+1}勝先取')]
            if c['bye']:note='勝者は'+c['bye']+'とDSへ'
        else:
            items=[dict(label=c[s],value=f'{c[s+"_wins"]}勝',team_color=c[s+'_color']) for s in ('home','away')]+[first_item]
        short_round={'F':'WCS','D':'DS','L':'LCS','W':'WS'}[c['round']]
        card = dict(common(ctx, f'PS予告 / {short_round}第{c["game_number"]}戦', target), layout='facts',
                    headline=f'{c["home"]}\n対{c["away"]}', subhead=note,
                    items=items,card_index=index,card_total=len(cards),headline_colors=[c['home_color'],c['away_color']],
                    headline_secondary_colors=[c['home_secondary'],c['away_secondary']],round_game=f'{short_round} 第{c["game_number"]}戦',
                    affiliations=['・'.join(c[s+'_players'])+' / '+c[s] for s in ('home','away') if c[s+'_players']])
        supplement=None
        if c is chosen and state == 'opening' and not (c['home_pitcher'] or c['away_pitcher']):
            raw=next(g for g in games if g['gamePk']==c['game_id'])
            supplement=focus.venue_focus(raw,games)
            if supplement:
                card['subhead']=supplement['fact_text']
                card['items']=[first_item,dict(label='開催球場',value=supplement['venue']),items[1]]
                card['focus_evidence']=supplement
        record = ('' if state=='opening' else
                  ('確定済みの勝数は' if state=='pending_results' else 'ここまで')
                  + f'{c["home_wins"]}勝対{c["away_wins"]}勝。')
        # 球団名に日本人選手の名前を添えて言う（「大谷翔平・山本由伸の
        # ドジャース」）。題で名前を見て来た人が、本編でも聞ける。
        said = {s: ('・'.join(c[s+'_players'][:3]) + 'の' if c[s+'_players'] else '') + c[s]
                for s in ('home','away')}
        # 日本人選手のいる側を主語に（片側だけのとき）。時刻は午前・午後を付ける
        # （夜中の試合を「2時」とだけ言うと、昼の2時にも聞こえる）。
        jp_side = [s for s in ('home','away') if c[s+'_players']]
        if len(jp_side) == 1:
            me = jp_side[0]; other = 'away' if me == 'home' else 'home'
            opening = f'{said[me]}は、{c[other]}との{rnd}第{c["game_number"]}戦。'
        else:
            opening = f'{said["home"]}対{said["away"]}は{rnd}第{c["game_number"]}戦。'
        hour = int(c["when"].split(':')[0])
        ampm = '午前' if hour < 12 else '午後'
        clock = spoken_clock(f'{hour % 12 if hour >= 12 else hour}:{c["when"].split(":")[1]}')
        speech = (f'{opening}'
                  f'{record}日本時間{ampm}{clock}の予定です。')
        if state=='opening' and c['bye']:speech+='勝者は地区シリーズで'+c['bye']+'と対戦します。'
        elif state!='opening':speech+=note+'です。'
        speech+=pitcher_speech(c)
        if supplement:speech+='第3戦が必要になった場合も、同じ球場で行われる予定です。'
        pages.append(segment(card, speech, [c['game_id']]))
    return dict(title=title, segments=pages, game_ids=[c['game_id'] for c in ordered],
                phase='forecast', target_day=target,
                social_summary=title.split('｜')[0] + f'。{date_label}のPS全{len(cards)}試合を日本時間でまとめました。')


def intro(ctx, now, rows=None, games=None):
    matches = ctx['matchups']
    if len(matches) != 4 or any(not m['first_game']['start_utc'] for m in matches):
        raise ValueError('WCS全4カードの実時刻を確認できません')
    first = min(datetime.fromisoformat(m['first_game']['start_utc']).astimezone(JST).date() for m in matches)
    days = (first - now.astimezone(JST).date()).days
    if days<=1:
        return None  # Card introductions live in tomorrow's all-game forecast; no duplicate NL episode.
    # Reuse the daily construction, rather than a second competing card script.
    program=forecast(ctx,games or [],rows or [],now,target_day=first.isoformat())
    if not program or len(program['game_ids'])!=4:raise ValueError('紹介対象の初戦全4試合が一致しません')
    cover=program['segments'][0]['meta']['card']
    cover.update(headline=f'{first.month}/{first.day}開幕\nWCS全4カード',label='WCS組み合わせ')
    program['phase']='intro_all'
    program['title']=f'{first.month}/{first.day}開幕のWCS全4カード紹介｜'+program['title'].split('｜')[0]
    program['social_summary']=f'日本時間{first.month}月{first.day}日にWCS開幕。全4カードの初戦時刻と勝ち上がり先をまとめました。'
    program['segments'][0]['text']=program['social_summary']
    return program


def situation_program(ctx, rows, before):
    changes = series.changes(rows, before.get('program_series', []))
    changed = {x['key'] for x in changes}
    old = {r['key']: r for r in before.get('program_series', [])}
    for row in rows:
        prior = old.get(row['key'])
        if prior and {t['id']: t['wins'] for t in row['teams']} != {t['id']: t['wins'] for t in prior['teams']}:
            changed.add(row['key'])  # Same game count does not hide a corrected winner.
    selected = [r for r in rows if len(r.get('teams', [])) == 2 and r['key'] in changed]
    if not before:
        selected = [r for r in selected if r['played']]
    if not selected:
        return None
    pages = []
    for row in selected:
        teams = row['teams']
        text = series.text(row)
        next_number = (row.get('next') or {}).get('game')
        live = bool((row.get('next') or {}).get('live'))
        next_label = (row.get('next') or {}).get('verified_label')
        if not row['played']:
            text = row['round_jp'] + teams[0]['name'] + '対' + teams[1]['name'] + '。'
            text += ('初戦は' + next_label + 'の予定です。') if next_label else '初戦の開始時刻は確認中です。'
        if live:
            text += f'。第{next_number}戦は進行中で、この試合の結果はまだ含めていません。'
        after = ('シリーズ終了' if row['over'] else f'第{next_number}戦進行中' if live else
                 f'次は第{next_number}戦' if next_number else '次戦日程確認中')
        card = dict(common(ctx, 'PS情勢'), layout='facts', headline=teams[0]['name'] + '\n対' + teams[1]['name'],
                    subhead=row['round_jp'] + ' / ' + after,
                    card_index=len(pages)+1,card_total=len(selected),headline_colors=[club_color(t['id']) for t in teams],
                    items=[dict(label=t['name'], value=f'{t["wins"]}勝',team_color=club_color(t['id'])) for t in teams] +
                          [dict(label='シリーズの現在地', value='決着' if row['over'] else f'第{next_number}戦進行中' if live else f'第{next_number}戦へ' if next_number else '日程確認中')])
        pages.append(segment(card, text, speaker=2 if len(pages) % 2 else 3))
    top = selected[0]
    rnd = ROUND[top['round']][0]
    a, b = top['teams']
    mine, other = (b,a) if b.get('players') and not a.get('players') else (a,b)
    title = (a['name'] + ('が世界一' if top['round'] == 'W' else 'が' + rnd + '突破') if top['over'] else
             mine['name'] + 'の' + rnd + f'は{mine["wins"]}勝{other["wins"]}敗')
    title += '｜PSシリーズの最新情勢'
    return dict(title=title, segments=pages, game_ids=[], phase='situation',
                social_summary=pages[0]['text'] + '。各カードの勝敗と勝ち上がりをまとめました。')


def verify_next_games(rows, games):
    """Do not turn provisional API timestamps into confirmed Japanese dates."""
    for row in rows:
        nxt = row.get('next')
        if not nxt or row['over'] or len(row['teams']) != 2:
            continue
        matching = [g for g in games if g['gameType'] == row['round']
                    and g['seriesGameNumber'] == nxt['game']
                    and {g['teams'][s]['team']['id'] for s in ('home', 'away')} == {t['id'] for t in row['teams']}
                    and g.get('status', {}).get('abstractGameState') != 'Final']
        if len(matching) != 1:
            raise ValueError('次戦を公式の1試合に対応付けられません')
        game = matching[0]
        nxt['live'] = game.get('status', {}).get('abstractGameState') == 'Live'
        if not game.get('status', {}).get('startTimeTBD', True):
            start = datetime.fromisoformat(game['gameDate'].replace('Z', '+00:00')).astimezone(JST)
            nxt['verified_label'] = f'日本時間{start.month}月{start.day}日' + spoken_clock(start.strftime('%H:%M'))


def prepare(snapshot, evidence, slot, now, ledger=None):
    ctx, games = validate_source(snapshot, evidence, now)
    names = {int(k): v['name'] for k, v in snapshot.get('teams', {}).items()}
    players = {int(k): v.get('players', []) for k, v in snapshot.get('teams', {}).items()}
    # Canonical roster owns team eligibility and names; no invented participants.
    for team in snapshot.get('japanese', []):
        players[int(team['team_id'])] = team.get('players', [])
    rows = series.build(games, names, players)
    verify_next_games(rows, games)
    kind = 'daily' if slot == 'forecast' else 'morning_postseason'
    before = previous(ledger or {}, kind)
    if slot == 'forecast':
        program = forecast(ctx, games, rows, now)
    elif ctx['stage'] == 'bracket_preview':
        program = intro(ctx, now, rows, games)
    elif ctx['stage'] == 'series':
        program = situation_program(ctx, rows, before)
    else:
        program = None
    if program is None:
        return None
    program['segments'][0]['text'] = 'コレスポ。' + program['segments'][0]['text']
    program['segments'][-1]['text'] += 'コレスポ。'
    edition = content_key(program)
    if before.get('program_edition') == edition:
        return None
    program.update(version=VERSION, kind=kind, date_jst=ctx['date_jst'], source_url=ctx['source_url'],
                   retrieved_at=evidence['retrieved_at'], edition_key=edition, series=rows,
                   material_sha256=hashlib.sha256(json.dumps(evidence['schedule'], sort_keys=True).encode()).hexdigest())
    return program


def content_key(program):
    payload = copy.deepcopy({k: program[k] for k in ('phase','segments','game_ids','title','social_summary')})
    for seg in payload['segments']:
        seg['meta']['card'].pop('date', None)
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def check_program(program):
    if content_key(program) != program['edition_key']:
        raise ValueError('検証後の台本・画面・題が変更されています')
    expected_day = program.get('target_day', program['date_jst'])
    if any(s['meta']['card']['date'] != expected_day for s in program['segments']):
        raise ValueError('画面の対象日が台本と不一致')
    found = {i for s in program['segments'] for i in s['meta']['game_ids']}
    if found != set(program['game_ids']) or not program['segments']:
        raise ValueError('素材と全画面の試合IDが一致しません')
    numbered=[s['meta']['card'] for s in program['segments'] if s['meta']['card'].get('card_index') is not None]
    if numbered and (any(c['card_total']!=len(numbered) for c in numbered) or
                     [c['card_index'] for c in numbered]!=list(range(1,len(numbered)+1))):
        raise ValueError('紹介カードの番号・総数・順番が一致しません')
    manifests = []
    for s in program['segments']:
        _, manifest = render_segment(s)
        manifest['speaker']=s['speaker']
        manifests.append(manifest)
    return dict(version=VERSION, edition_key=program['edition_key'], material_sha256=program['material_sha256'],
                expected_game_ids=program['game_ids'], represented_game_ids=sorted(found), rendered=manifests,
                limits=['声の実聴・実媒体UI・将来の天候は別検証'])


def script(program):
    target=program.get('target_day',program['date_jst'])
    return dict(title=program['title'], date_jst=target,
                date_label=datetime.fromisoformat(target).strftime('%m/%d'), segments=program['segments'],
                source_url=program['source_url'], ps_program=program)


def movie(program, audio_dir, out):
    check = check_program(program)
    audio = read(Path(audio_dir) / 'manifest.json')['segments']
    if len(audio) != len(program['segments']):
        raise ValueError('台本と音声の件数が不一致')
    for a, b in zip(audio, program['segments']):
        if (a.get('text') != b['text'] or a.get('meta') != b['meta'] or
                not a.get('file') or not Path(a['file']).exists() or not a.get('duration')):
            raise ValueError('台本と音声の不一致または音声欠落')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    durations = [max(3.0, float(a['duration']) + vc.SEGMENT_TAIL) for a in audio]
    track = vc.build_narration_track(audio, durations, out)
    if not track:
        raise ValueError('音声を結合できません')
    name = 'collespo_short.mp4' if program['kind'] == 'daily' else 'collespo_morning_postseason.mp4'
    path = out / name
    cmd = ['ffmpeg', '-y', '-nostats', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', '1080x1920', '-framerate', '30', '-i', '-', '-i', str(track), '-c:v', 'libx264',
           '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
           '-shortest', '-movflags', '+faststart', str(path)]
    previous_frame=None
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
        for i, (seg, duration) in enumerate(zip(program['segments'], durations)):
            image, _, foreground = render_segment(seg,layers=True)
            image.save(out / f'ps_{i:02d}.png')
            if i == 0:
                image.save(out / ('short.png' if program['kind'] == 'daily' else 'short_postseason.png'))
            prepared=motion.prepare(foreground,seg['meta']['card'])
            for n in range(round(duration * 30)):
                frame=motion.frame(prepared,n/30)
                raw=vc.crossfade(previous_frame,frame,n,round(vc.FADE_SECONDS*30),(1080,1920))
                proc.stdin.write(raw)
            previous_frame=raw
        proc.stdin.close()
        if proc.wait():
            raise ValueError('PS動画の書き出しに失敗')
    check.update(video=str(path), expected_segments=len(audio), durations=durations,
                 motion='sequential-left-entry / subtle-background-drift / shared-crossfade')
    write(out / 'ps_program_gate.json', check)


def metadata(program):
    day = datetime.fromisoformat(program['date_jst'])
    title = f'【{day.month}/{day.day}更新】' + program['title'] + ' #Shorts'
    if len(title) > 100:
        raise ValueError('YouTube題が100文字を超えます')
    body = [program['social_summary'], '', *[s['text'] for s in program['segments']], '',
            '時刻は日本時間。未終了の結果・選手の出場は断定していません。',
            'WCSは2勝、DSは3勝、LCSとWSは4勝で決着。',
            '資料時点：' + program['retrieved_at'], '出典：' + program['source_url'],
            'コレスポ：https://collespo.com/', 'VOICEVOX:ずんだもん / VOICEVOX:四国めたん',
            '#MLB #ポストシーズン #Shorts']
    return dict(snippet=dict(title=title, description='\n'.join(body), tags=['MLB', 'ポストシーズン', 'Shorts'],
                            categoryId='17', defaultLanguage='ja', defaultAudioLanguage='ja'))


def upload(program, argv):
    check_program(program)
    if program.get('rehearsal'):
        raise ValueError('再現用の仮時計で作った動画を公開しません')
    if layout() != 'v2':
        raise ValueError('PS新構成の公開設定がv2ではありません')
    now = datetime.now(JST)
    if program['date_jst'] != now.date().isoformat():
        raise ValueError('当日以外の制作物を公開しません')
    import upload_youtube as uploader
    original = uploader.build_metadata
    expected = metadata(program)
    record = uploader.published_video(program['kind'], program['date_jst'])
    if record.get('video_id') and record.get('program_edition') != program['edition_key']:
        raise ValueError('この枠は投稿済みです。新版の重複再投稿を止めます')
    def program_metadata(*args, **kwargs):
        values = inspect.signature(original).bind_partial(*args, **kwargs).arguments
        kind = uploader.record_kind(values.get('kind', 'daily'), values.get('morning_mode', 'players'), values.get('sport', 'mlb'))
        return expected if kind == program['kind'] else original(*args, **kwargs)
    uploader.build_metadata = program_metadata
    sys.argv = ['upload_youtube.py', *argv]
    uploader.main()
    ledger = read(uploader.VIDEOS_PATH)
    row = ledger.get(program['kind'], {}).get(program['date_jst'], {})
    if not row.get('video_id') or row.get('title') != expected['snippet']['title']:
        raise ValueError('対応する今回の動画の投稿記録がありません')
    row.update(program_version=VERSION, program_edition=program['edition_key'], program_phase=program['phase'],
               program_series=program['series'], social_summary=program['social_summary'])
    write(uploader.VIDEOS_PATH, ledger)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--slot', choices=['forecast', 'situation'])
    p.add_argument('--snapshot', default='data/postseason.json')
    p.add_argument('--evidence', default='build/ps_editorial_source.json')
    p.add_argument('--fresh', action='store_true')
    p.add_argument('--program', default='build/ps_program_situation.json')
    p.add_argument('--narration-out')
    p.add_argument('--audio-dir')
    p.add_argument('--out')
    p.add_argument('--upload', action='store_true')
    p.add_argument('--check', action='store_true')
    args, rest = p.parse_known_args()
    if args.check:
        program = read(args.program)
        write(Path(args.program).with_suffix('.claims.json'), check_program(program)); return
    if args.upload:
        upload(read(args.program), rest); return
    if args.audio_dir:
        movie(read(args.program), args.audio_dir, args.out); return
    now = datetime.now(timezone.utc)
    snapshot = read(args.snapshot)
    if layout() == 'hold':
        print('[info] PS枠はhold設定です'); return
    if args.fresh:
        year = now.astimezone(JST).year
        url = pe.API + f'schedule?sportId=1&season={year}&startDate={year}-09-01&endDate={year}-11-15&gameType=F,D,L,W&hydrate=team,probablePitcher'
        evidence = dict(retrieved_at=now.isoformat(), source_url=url, schedule=pe.fetch(url))
        write(args.evidence, evidence)
    evidence = read(args.evidence)
    ledger = read('data/published_videos.json') if Path('data/published_videos.json').exists() else {}
    program = prepare(snapshot, evidence, args.slot, now, ledger)
    if program is None:
        Path(args.program).unlink(missing_ok=True)
        if args.narration_out:
            Path(args.narration_out).unlink(missing_ok=True)
        print('[info] 試合/新しい情勢がないため正常省略'); return
    check_program(program)
    write(args.program, program)
    write(args.narration_out, script(program))
    print(f'[info] PS新構成 {program["phase"]}: {len(program["segments"])}画面 / {len(program["game_ids"])}試合')


if __name__ == '__main__':
    main()
