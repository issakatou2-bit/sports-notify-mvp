"""試合状態で終了を判定する日本人選手の速報。既定は制作のみ。"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import time

import soccer_results as results
import soccer_voices as voices

ROOT = Path(__file__).resolve().parents[1]
MAX_AGE = timedelta(minutes=60)
GOAL_MAX_AGE = timedelta(hours=3)
WATCH_LIMIT = 50*60
SCORE_FORMULA = '攻撃関与★は3×得点＋2×アシスト＋シュート＋枠内シュート。FW/MFの30分以上（交代なし先発を含む）が対象の独自指標。守備を含む公式採点ではありません。'


def completed(event):
    status = event['competitions'][0].get('status', {}).get('type', {})
    return status.get('completed') is True and status.get('state') == 'post'


def relevant(event, code):
    names = [results.ne.normalize_club(c['team']['displayName']) for c in event['competitions'][0]['competitors']]
    return any(p['league'] == code and any(p['match'] in name for name in names) for p in results.ne.JP_PLAYERS_SOCCER)


def watch_delay(events, now):
    """試合の75分後〜210分後だけ5分間隔。それ以外は次の窓まで待つ。"""
    waits = []
    for event in events:
        status = event['competitions'][0].get('status', {}).get('type', {})
        if completed(event) or status.get('name') in ('STATUS_POSTPONED', 'STATUS_CANCELED', 'STATUS_SUSPENDED'): continue
        start = results.utc(event['date'])
        if now > start+timedelta(minutes=210) or start > now+timedelta(hours=4): continue
        delay = max(300, (start+timedelta(minutes=75)-now).total_seconds())
        if delay < WATCH_LIMIT: waits.append(delay)
    return min(waits) if waits else None


def rank_changes(game, standings):
    changes = []
    for side,pair in (standings or {}).items():
        a,b = pair.get('before',{}),pair.get('after',{})
        required = ('competition','season','played','as_of','rank','source')
        if side not in ('home','away') or any(a.get(k) is None or b.get(k) is None for k in required): continue
        if any(type(r[k]) is not int or r[k]<0 for r in (a,b) for k in ('played','rank')): continue
        try:
            valid = (a['competition']==b['competition']==game['league'] and a['season']==b['season']
                     and b['played']==a['played']+1 and results.utc(a['as_of'])<results.utc(game['start_utc'])
                     and results.utc(b['as_of'])>=results.utc(game['finished_utc']))
        except (TypeError,ValueError): continue
        if valid: changes.append(dict(side=side,before=a['rank'],after=b['rank'],source=b['source']))
    return changes


def enrich(game, summary, standings=None):
    game = copy.deepcopy(game)
    game['winner_goal'] = None
    if game['goals_complete'] and game['score']['home'] != game['score']['away']:
        winner = 'home' if game['score']['home'] > game['score']['away'] else 'away'
        loser = 'away' if winner == 'home' else 'home'
        game['winner_goal'] = [g for g in game['goals'] if g['side'] == winner][game['score'][loser]]
    # Exact before/after snapshots only; same competition/season and one extra game.
    game['rank_changes'] = rank_changes(game,standings)
    return game


def build(boards, summaries, now, receipts=None, standings=None, *, max_age=MAX_AGE, goal_short=False):
    """保存/本番が同じ経路。終了の時刻・本人の出場・鮮度を照合。"""
    out = []; rejected = []; receipts = dict(__import__('soccer_publications').load() if receipts is None else receipts)
    for key, board in boards.items():
        for event in board.get('events', []):
            ident = str(event['id'])
            if ident in receipts or not completed(event): continue
            summary = summaries.get(ident)
            if summary is None: continue
            summary = summary.get('summary', summary)
            end = results.completion_time(event['competitions'][0], summary)
            if not end or not timedelta(0) <= now-results.utc(end) <= max_age: continue
            # Results window starts at 07:15 JST, not calendar midnight.
            local = results.utc(end).astimezone(results.JST)
            day = local.date() - timedelta(days=int((local.hour, local.minute) < (7, 15)))
            data = results.build({key: dict(board, events=[event])}, {ident: summary}, str(day))
            rejected.extend(data['rejected'])
            if not data['can_make']: continue
            game = enrich(data['games'][0], summary, (standings or {}).get(ident))
            data.update(games=[game], players=sorted(game['players'], key=results.rank_key),
                        sample_fictional=False, voices=[], video_url='', metric_formula=SCORE_FORMULA)
            if goal_short is not None and not __import__('soccer_publications').eligible(data, receipts, goal_short=goal_short): continue
            receipts[ident] = {}
            out.append(data)
    return out, rejected


def attach_voices(data, video, items, *, sample=False):
    """声は0〜3件。動画のクラブ・投稿時刻を照合し、声がなくても速報を作る。"""
    game = data['games'][0]
    if set(results.club_key(c) for c in video.get('clubs', [])) != set(results.club_key(game[s]['name_en']) for s in ('home', 'away')):
        return data
    if not sample:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video.get('video_id', '')): return data
        stamp = video.get('published_at') or video.get('publishedAt')
        if not stamp or not results.utc(game['start_utc']) <= results.utc(stamp) <= results.utc(game['finished_utc'])+timedelta(hours=12): return data
    players = voices.players_in_match(video, voices.load_names())
    safe = voices.eligible(items, players)[:3]
    data['voices'] = [dict(v, reply_ja=[]) for v in safe]
    data['video_url'] = '' if sample else 'https://www.youtube.com/watch?v='+video['video_id']
    if sample: data['sample_fictional'] = True
    return data


def narration(data):
    import soccer_result_story
    base = soccer_result_story.narration(data)
    segments = [s for s in base['segments'] if s['kind'] not in ('roster', 'outro')]
    for i, v in enumerate(data['voices']):
        segments.append(dict(kind='voice', text='ハイライトのコメントでは、'+voices.spoken_names(v['ja'], voices.load_names())+'。', speaker=2, meta={'index':i}))
    import sanity_sources
    return sanity_sources.attach(dict(label='サッカー試合速報', segments=segments,
        duration_budget={'limit':40,'grace':0}), data, sport='soccer')


def metadata(data):
    import club_display_names as names
    g = data['games'][0]; p = next(p for p in data['players'] if p['status'] != 'none')
    lines = [f"試合終了 {g['finished_utc']}。出典: ESPN", SCORE_FORMULA]
    lines += [f"順位: {r['source']}" for r in g['rank_changes']]
    if data['voices']:
        lines += ['YouTube公式ハイライトのコメントの翻訳。選んだ声であり現地全体の総意ではありません。', data['video_url']]
        for v in data['voices']: lines += ['原文: '+v['title'], '訳: '+v['ja'], v.get('url','')]
    title=('【保存材料の試作】' if data.get('sample_fictional') else '')+p['name']+results.action(p)+'｜'+names.display(g['home']['name_en'])+'対'+names.display(g['away']['name_en'])
    return dict(title=names.youtube_title(title), description=names.display_text('\n'.join(lines), include_short=True)+'\n音声: VOICEVOX:四国めたん', language='ja')


def frame(data, t, seg):
    import soccer_results_render as rr
    c = rr.cards; clubs = rr.resolve_clubs(data); spec = rr.program_spec(data)
    spec.update(label='サッカー試合速報', ticker='保存材料の試作・架空の声' if data.get('sample_fictional') else '試合終了後の結果', source='出典: ESPN / YouTube（翻訳）')
    if seg['kind'] != 'voice': return rr.frame(t, seg, data, clubs)
    if rr.soccer_look.readable():
        from soccer_readable import Screen
        screen = Screen(clubs, t)
        screen.title('現地の声（翻訳）')
        screen.lines(c.L, 430, data['voices'][seg['meta']['index']]['ja'], 48, c.R-c.L)
        return screen.finish(spec)
    im = c.canvas(t, clubs, spec['label']); rr.v4.panel(im, (c.L,258,c.R,1120))
    c.plain(im,c.L+28,282,{'detail':'本人の記録と独自指標','context':'決勝点と順位','voice':'現地の声（翻訳）'}[seg['kind']],46,rr.r3.GOLD,width=c.R-c.L-56)
    text = seg['text']
    if seg['kind'] == 'voice': text = data['voices'][seg['meta']['index']]['ja']
    import soccer_voices_render as quotes
    size = 52
    lines = quotes.wrapped(text,size,c.R-c.L-72,clubs)
    if len(lines)>7: raise ValueError('本文が7行を超えます')
    bottom = quotes.draw_lines(im,c.L+36,410,lines,size,rr.r3.INK)
    if seg['kind']=='voice':
        c.plain(im,c.L+36,bottom+42,'原文（架空の声）' if data.get('sample_fictional') else '原文（YouTube）',28,rr.r3.GOLD,width=c.R-c.L-72)
        original = data['voices'][seg['meta']['index']]['title']
        bottom = quotes.draw_lines(im,c.L+36,bottom+96,quotes.wrapped(original,32,c.R-c.L-72,clubs),32,rr.r3.INK)
    if bottom>1080: raise ValueError('本文/原文が画面を超えます')
    errors = c.check_club_badges(im,clubs)
    if errors: raise ValueError(str(errors))
    return c.finish(im,t,spec)


def save(data, out):
    import short_saved_render as render
    render.setup(); out = Path(out); out.mkdir(parents=True, exist_ok=True)
    (out/'material.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'metadata.json').write_text(json.dumps(metadata(data),ensure_ascii=False,indent=2),encoding='utf8')
    # Drop whole comment pairs to fit measured speech; never cut or accelerate quotes.
    while True:
        try:
            import host_split
            narr = host_split.adapt(narration(data), 'soccer_now')
            return render.render(narr, lambda t,s:frame(data,t,s), out, voiced=True)
        except ValueError as error:
            if '40秒' not in str(error) or not data['voices']: raise
            data['voices'].pop()
            (out/'material.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
            (out/'metadata.json').write_text(json.dumps(metadata(data),ensure_ascii=False,indent=2),encoding='utf8')


def live_boards(now):
    boards = {}; summaries = {}; events = []
    for code, slug in results.LEAGUES.items():
        for day in (now.date(),):
            key = code+'_'+day.strftime('%Y%m%d')
            first,last = day-timedelta(days=1),day+timedelta(days=1)
            board = results.fetch_json(f'{results.ESPN}/{slug}/scoreboard?dates={first:%Y%m%d}-{last:%Y%m%d}&limit=100')
            selected = [e for e in board.get('events',[]) if relevant(e,code) and now-timedelta(hours=5) <= results.utc(e['date']) <= now+timedelta(hours=4)]
            boards[key] = dict(board, events=selected); events += selected
            for e in selected:
                if completed(e): summaries[str(e['id'])] = results.fetch_json(f'{results.ESPN}/{slug}/summary?event={e["id"]}')
    return boards, summaries, events


def live_rank_context(data):
    """前夜の保存順位と現在順位がそろったクラブだけ。同じ大会・シーズンをenrichでも再照合。"""
    if not os.environ.get('FOOTBALL_DATA_API_KEY'): return data
    import soccer_result_followup as followup
    import soccer_result_context as context
    import club_display_names as clubs
    preview = followup.load_preview(data['date_jst'])
    if not preview: return data
    before,after,_ = context.after_context(data,preview)
    g = data['games'][0]; pairs = {}
    for side in ('home','away'):
        ident = (clubs.lookup(g[side]['name_en']) or {}).get('id')
        if ident in before and ident in after: pairs[side] = dict(before=before[ident],after=after[ident])
    g['rank_changes'] = rank_changes(g,pairs)
    return data


def live_voices(data):
    """既存の公式チャンネル収集・翻訳・別呼出しの意味照合を再利用。失敗は速報を遅らせない。"""
    if not os.environ.get('YOUTUBE_API_KEY') or not os.environ.get('ANTHROPIC_API_KEY'): return data
    try:
        subprocess.run([__import__('sys').executable, str(ROOT/'scripts/soccer_buzz.py'), '--out', 'build/soccer-now-buzz.json'],check=True,timeout=120)
        import anthropic
        import local_voices as lv
        buzz = json.loads((ROOT/'build/soccer-now-buzz.json').read_text(encoding='utf8'))
        for video in buzz.get('videos',[]):
            g = data['games'][0]
            if set(map(results.club_key, video.get('clubs',[]))) != {results.club_key(g[s]['name_en']) for s in ('home','away')}: continue
            path = ROOT/'build/soccer-now-one.json'; path.write_text(json.dumps({'videos':[video]},ensure_ascii=False),encoding='utf8')
            ps = voices.players_in_match(video,voices.load_names())
            picked,_ = voices.select(lv.fetch_youtube_comments(str(path)),ps,want=3)
            client = anthropic.Anthropic()
            translated = lv.translate(client,picked,sport='soccer')
            return attach_voices(data,video,voices.review_translations(client,translated,ps))
    except Exception as error: print('[omit] 現地の声:',type(error).__name__)
    return data


def checkpoint_receipt(path, key, entry, extra=()):
    """投稿前の記録を保存し、保存先の main に同じ記録があることまで照合する。"""
    path = Path(path)
    subprocess.run(['bash','scripts/commit_data.sh','soccer publication receipt',str(path.relative_to(ROOT)),*extra],cwd=ROOT,check=True)
    subprocess.run(['git','fetch','origin','main'],cwd=ROOT,check=True,capture_output=True)
    saved = subprocess.run(['git','show','origin/main:'+path.relative_to(ROOT).as_posix()],cwd=ROOT,check=True,capture_output=True,text=True,encoding='utf8')
    if json.loads(saved.stdout).get(key) != entry:
        raise ValueError('本番台帳に記録できないため投稿停止')


def publish(data, out, ledger, *, goal_short=False):
    enabled = (os.environ.get('COLLESPO_SOCCER_GOAL_SHORT') == 'on' if goal_short else
               os.environ.get('COLLESPO_SOCCER_NOW') == 'on' and os.environ.get('SOCCER_NOW_PUBLISH','false') == 'true')
    if not enabled: raise ValueError('公開変数が無効')
    if data.get('sample_fictional'): raise ValueError('試作は公開不可')
    results.validate_data(data)
    if goal_short and (len(data['games']) != 1 or not any(p['status'] != 'none' and (p.get('goals') or p.get('assists')) for p in data['players'])):
        raise ValueError('得点・アシストのある1試合が必要')
    age = GOAL_MAX_AGE if goal_short else MAX_AGE
    if not timedelta(0)<=datetime.now(timezone.utc)-results.utc(data['games'][0]['finished_utc'])<=age: raise ValueError('公開直前の鮮度を超過')
    ident = str(data['games'][0]['id'])
    import soccer_publications as publications
    if ident in ledger or not publications.eligible(data, publications.load(refresh=True), goal_short=goal_short): return
    import host_split
    kind = 'soccer_goal_short' if goal_short else 'soccer_now'
    import sanity
    # 完成原稿を同じCLIで点検し、失敗した回は投稿要求・pending記録より前で止める。
    subprocess.run(sanity.command(kind, Path(out)/'narration.json',
        Path(out)/'sanity.json', Path(out)/'sanity_hold.json'), cwd=ROOT, check=True)
    video = Path(out)/('collespo_soccer_results.mp4' if goal_short else 'preview.mp4')
    tracking = host_split.publication(video)
    path = ROOT/publications.PATH
    fresh = publications.load(refresh=True)
    ledger.clear(); ledger.update(fresh)
    if not publications.eligible(data, ledger, goal_short=goal_short): return
    def checkpoint():
        path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf8')
        publications.mirror_receipt(ident, ledger[ident])
        extra = ['data/published_videos.json'] if tracking else []
        checkpoint_receipt(path, ident, ledger[ident], extra)
    ledger[ident] = {'status':'pending','kind':kind,'at':datetime.now(timezone.utc).isoformat()}; checkpoint()
    # Pending remains on uncertain response. Never retry an upload automatically.
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build as api_build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ['YOUTUBE_REFRESH_TOKEN'],token_uri='https://oauth2.googleapis.com/token',client_id=os.environ['YOUTUBE_CLIENT_ID'],client_secret=os.environ['YOUTUBE_CLIENT_SECRET'])
    meta = metadata(data) if not goal_short else None
    if goal_short:
        lines = results.description_lines(data)
        ended = results.utc(data['games'][0]['finished_utc']).astimezone(results.JST)
        lines[0] = f"日本時間{ended:%Y年%m月%d日 %H:%M}に終了した試合の、日本人選手の得点・アシスト速報です。"
        meta = dict(title=results.title(data), description='\n'.join(lines))
    meta['description'] = host_split.credit(meta['description'])
    body = {'snippet':dict(title=meta['title'],description=meta['description'],categoryId='17',defaultLanguage='ja',defaultAudioLanguage='ja'), 'status':dict(privacyStatus='public',selfDeclaredMadeForKids=False)}
    import localize_videos
    body = localize_videos.prepare_upload(body)
    response = api_build('youtube','v3',credentials=creds,cache_discovery=False).videos().insert(part=localize_videos.upload_parts(body),body=body,media_body=MediaFileUpload(str(video),resumable=True)).execute()
    if not response.get('id'): raise ValueError('投稿結果のIDなし。pendingを手動照合')
    if tracking:
        from upload_youtube import record_video
        record_video(kind, host_split.today()+':'+str(ident), response['id'], meta['title'],
                     host_tracking=tracking)
    ledger[ident].update(status='uploaded',video_id=response['id']); checkpoint()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sample',action='store_true'); ap.add_argument('--watch',action='store_true'); ap.add_argument('--plan',action='store_true')
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer-now')
    args = ap.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    if args.sample:
        boards = json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf8'))
        summaries = json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf8'))
        data,_ = build(boards,summaries,results.utc('2026-09-20T17:15:00Z'), goal_short=None)
        item = data[0]; item['sample_fictional'] = True
        fixture = json.loads((ROOT/'scripts/fixtures/soccer-now/voices.json').read_text(encoding='utf8'))
        for v in fixture['comments']:
            v['semantic_review'] = dict.fromkeys(('noncritical','no_abuse','faithful','actors','names'),True)
            v['semantic_review']['sha256'] = voices.review_hash(v)
        attach_voices(item,fixture['video'],fixture['comments'],sample=True)
        print(save(item,args.out)); return
    if os.environ.get('COLLESPO_SOCCER_NOW') != 'on': print('disabled'); return
    ledger = __import__('soccer_publications').load()
    processed = set(ledger); deadline = time.monotonic()+WATCH_LIMIT
    if args.plan:
        current = datetime.now(timezone.utc); boards,summaries,events = live_boards(current)
        due,_ = build(boards,summaries,current,ledger,goal_short=False)
        print('go=1' if due or watch_delay(events,current) is not None else 'go=0')
        return
    while True:
        now = datetime.now(timezone.utc); boards,summaries,events = live_boards(now)
        data,rejected = build(boards,summaries,now,dict.fromkeys(processed | set(__import__('soccer_publications').load())),goal_short=False)
        if rejected: print('rejected:',json.dumps(rejected,ensure_ascii=False))
        for item in data:
            ident = item['games'][0]['id']; folder = args.out/ident
            save(live_voices(live_rank_context(item)),folder)
            if os.environ.get('SOCCER_NOW_PUBLISH','false') == 'true': publish(item,folder,ledger)
            processed.add(ident)
        delay = watch_delay(events,datetime.now(timezone.utc))
        if not args.watch or delay is None or time.monotonic()+delay >= deadline: break
        time.sleep(delay)


if __name__ == '__main__': main()
