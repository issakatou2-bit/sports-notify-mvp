"""既存の保存材料を出来事単位にまとめる。ドメインが公式というだけで公式発表にしない。"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import player_story as story
from notability_engine import JP_PLAYERS_SOCCER

ROOT = Path(__file__).resolve().parents[1]
LEVELS = {'official': '公式で確認', 'multiple': '複数の報道', 'single': '1つの報道のみ', 'fan': 'ファンの声'}
CLAIMS = {'rest': '第{game}戦で{name}を休ませることを協議する予定です。',
          'lineup': '第{game}戦で{name}が先発メンバーに入る予定です。',
          'starting_lineup': '{name}が試合の先発メンバーに入っています。',
          'probable_pitcher': '{name}が試合の先発予定投手です。',
          'transaction': '{name}の公示は「{detail}」です。'}
MEDIA = {'MLB.com': 'mlb', 'ESPN': 'espn', 'CBS Sports': 'cbs', 'The Athletic': 'athletic',
         'Associated Press': 'ap', 'Reuters': 'reuters', 'スポニチ': 'sponichi',
         'スポーツ報知': 'hochi', 'サンスポ': 'sanspo', 'デイリースポーツ': 'daily'}
MAX_AGE = timedelta(hours=48)
FAN_NOTE = '短く選んだコメントを訳したものです。全員の意見ではありません。'
PLAYERS = [dict(p, sport='MLB') for p in story.JP_PLAYERS_MLB] + [dict(p, sport='PL') for p in JP_PLAYERS_SOCCER]


def enabled():
    return os.environ.get('COLLESPO_TOPIC_HUB') == 'on'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def load(path):
    if not Path(path).is_file(): return {}
    try:
        data=story.read(path)
        return data if isinstance(data,dict) else dict(_input_state='failed',_input_reason='一覧はJSON objectが必要')
    except (ValueError,OSError) as exc:
        return dict(_input_state='failed',_input_reason=type(exc).__name__)


def utc(value):
    try: return story.stamp(value).isoformat() if value else None
    except (ValueError, TypeError, OverflowError): return None


def evidence_time(row):
    return row.get('observed_at') or row.get('published_at') or ''


def fresh_evidence(row, now):
    at=evidence_time(row)
    if not at or not timedelta(0)<=now-story.stamp(at)<=MAX_AGE: return False
    if row['kind']=='transaction' and row.get('event_date'):
        try: days=(now.date()-datetime.fromisoformat(row['event_date']).date()).days
        except ValueError: return False
        if not 0<=days<=2: return False  # 今取った古い公示を今日の出来事にしない。
    return True


def origin(row):
    # 引用元・配信元が明記されていたら媒体名より優先。Yahoo等の転載元不明は票に数えない。
    declared = row.get('origin_source') or row.get('wire_source')
    source = declared or row.get('outlet') or row.get('source') or ''
    original = row.get('text') or row.get('title') or ''
    for name, group in MEDIA.items():
        if re.search(r'(?:according to|via|reports? by)\s+'+re.escape(name), original, re.I):
            return group
    return MEDIA.get(source, 'unknown:'+source)


def base(row, material, channel, player, kind, game='', series='', polarity='positive'):
    published = utc(row.get('at') or row.get('published_at'))
    collected = utc(row.get('fetched_at') or material.get('updated_at'))
    if not collected:
        # 取得時刻を出来事時刻で埋めない。旧材料で不明なら不明のまま。
        collected = None
    url = row.get('url') or row.get('uri') or ''
    if url.startswith('at://') and row.get('handle'):
        url = f"https://bsky.app/profile/{row['handle']}/post/{url.rsplit('/',1)[-1]}"
    original = row.get('text') or row.get('title') or row.get('original') or ''
    item = dict(channel=channel, player_en=player['name_en'], player_jp=player['name_jp'], sport=player.get('sport', 'MLB'),
                kind=kind, game=str(game), series=series, season=(published or '')[:4],
                event_at=utc(row.get('event_at')), published_at=published, observed_at=None, collected_at=collected,
                game_date=row.get('game_date'), url=url, original=original,
                source=row.get('outlet') or row.get('source') or '', origin=origin(row), polarity=polarity)
    if channel != 'fan': item['author'] = row.get('author') or ''
    item['id'] = digest([channel, url, original, published, kind, player['name_en'], polarity])
    return item


def parse_reports(material, channel='report'):
    observations = []; rejected = []
    rows = list(material.get('posts') or []) + list(material.get('headlines') or [])
    for row in rows:
        if not isinstance(row,dict): continue
        text = row.get('text') or row.get('title') or ''
        if not isinstance(text,str) or not (row.get('outlet') or row.get('source')):
            rejected.append(dict(reason='報道の本文または出どころが不明',url=row.get('url'))); continue
        players = [p for p in PLAYERS if story.player_match(row, p) or p['name_jp'] in text]
        if len(players) != 1: continue
        p = players[0]
        if not row.get('url') and not row.get('uri'): continue
        if '?' in text or not utc(row.get('at')):
            rejected.append(dict(reason='疑問または公開時刻不明', url=row.get('url') or row.get('uri'))); continue
        series = next((name for name in ('ALCS','NLCS','ALDS','NLDS','ALWC','NLWC','World Series') if name.lower() in text.lower()), '')
        # 否定は正の型に無理に当てない。明示された否定を別の観測として保持。
        denial = re.search(r'(?:will not|won.t|not going to) (?:discuss )?(?:sit|sitting|bench|rest).+?Game (\d+)', text, re.I)
        if denial:
            observations.append(base(row, material, channel, p, 'rest', denial[1], series, 'negative')); continue
        lineup_denial=re.search(r'(?:will not|won.t) (?:be|remain) in.+?(?:Game (\d+).+?lineup|lineup.+?Game (\d+))',text,re.I)
        if lineup_denial:
            game=next(v for v in lineup_denial.groups() if v)
            observations.append(base(row,material,channel,p,'lineup',game,series,'negative')); continue
        if re.search(r'\b(?:not|never|denies|denied)\b', text, re.I):
            rejected.append(dict(reason='未対応の否定文', url=row.get('url') or row.get('uri'))); continue
        for kind, pattern, _, _ in story.REPORT_RULES:
            m = re.search(pattern, text, re.I)
            if m:
                game = next(v for v in m.groups() if v)
                observations.append(base(row, material, channel, p, kind, game, series)); break
        else:
            rejected.append(dict(reason='出来事の型が未対応。勝手に要約しない', url=row.get('url') or row.get('uri')))
    return observations, rejected


def official_documents(material):
    """チームのpress-releaseのみ。MLB.com/newsや記者の投稿は公式発表に昇格させない。"""
    accepted = []; rejected = []
    for row in material.get('documents') or []:
        u = urlsplit(row.get('url') or '')
        valid = u.scheme == 'https' and u.hostname in ('www.mlb.com','mlb.com') and bool(re.fullmatch(r'/(?:[a-z]+/)?press-release/[^/]+', u.path))
        if not valid:
            rejected.append(dict(reason='確認済みの公式発表URLではありません', url=row.get('url'))); continue
        rows, errors = parse_reports(dict(updated_at=material.get('updated_at'), posts=[row]), 'official_announcement')
        for item in rows: item.update(source='MLB球団公式発表', origin='official:'+u.path.split('/')[1])
        accepted += rows; rejected += errors
    # 公式サイトからのリンクを人が確認した名簿のみ。自己申告のofficialフラグでは昇格しない。
    accounts=load(ROOT/'data/topic_hub_policy.json').get('official_accounts',[])
    for row in material.get('posts') or []:
        account=next((a for a in accounts if a.get('handle')==row.get('handle') and a.get('reviewed_at')
                      and urlsplit(a.get('official_source_page','')).hostname in ('www.mlb.com','mlb.com')),None)
        if not account: rejected.append(dict(reason='公式アカウントの対応名簿未確認',url=row.get('url'))); continue
        u=urlsplit(row.get('url') or '')
        if u.hostname!='bsky.app' or not u.path.startswith('/profile/'+account['handle']+'/post/'): continue
        rows, errors=parse_reports(dict(updated_at=material.get('updated_at'),posts=[row]),'official_announcement')
        for item in rows: item.update(origin='official:'+account['handle'],source=account['name'])
        accepted+=rows; rejected+=errors
    return accepted, rejected


def official_stats(material):
    """保存した公式のboxscore/schedule/transactions。APIの生フィールドからだけ確認する。"""
    out = []
    players = {p['name_en']: p for p in story.JP_PLAYERS_MLB}
    for snapshot in material.get('snapshots') or []:
        u = urlsplit(snapshot.get('url') or '')
        if u.scheme != 'https' or u.hostname != 'statsapi.mlb.com': continue
        raw = snapshot.get('data') or {}; rows = []
        match = re.fullmatch(r'/api/v1/game/(\d+)/boxscore', u.path)
        if match:
            for side in (raw.get('teams') or {}).values():
                for row in (side.get('players') or {}).values():
                    name = (row.get('person') or {}).get('fullName')
                    order = str(row.get('battingOrder') or '')
                    # x00が先発、x01以降は代打等。ロースターにいるだけでは先発と言わない。
                    if name in players and re.fullmatch(r'[1-9]00', order):
                        rows.append((players[name], 'starting_lineup', '', dict(game_id=match[1], batting_order=order)))
        elif u.path == '/api/v1/transactions':
            for row in raw.get('transactions') or []:
                name = (row.get('person') or {}).get('fullName')
                if name in players and row.get('description'):
                    rows.append((players[name], 'transaction', '', dict(detail=row['description'], event_date=row.get('effectiveDate'), event_at=utc(row.get('effectiveDate')))))
        elif u.path == '/api/v1/schedule':
            for day in raw.get('dates') or []:
                for game_row in day.get('games') or []:
                    for side in (game_row.get('teams') or {}).values():
                        name=(side.get('probablePitcher') or {}).get('fullName')
                        if name in players and game_row.get('gamePk'):
                            rows.append((players[name],'probable_pitcher','',dict(game_id=str(game_row['gamePk']))))
        for p, kind, game, detail in rows:
            row = dict(source='MLB Stats API', url=snapshot['url'], at=snapshot.get('observed_at'),
                       fetched_at=snapshot.get('fetched_at'), game_date=snapshot.get('game_date'),
                       event_at=detail.get('event_at'), text=json.dumps(detail, ensure_ascii=False))
            item = base(row, {}, 'official_data', p, kind, game, snapshot.get('series') or '')
            item.update(detail=detail, game_id=detail.get('game_id'), origin='mlb_stats',
                        published_at=None, observed_at=utc(snapshot.get('observed_at')),
                        event_date=detail.get('event_date'))
            # Game番号/回戦は保存した公式日程との明示的な照合があるときだけ関連付ける。
            schedule = snapshot.get('schedule') or (raw if u.path=='/api/v1/schedule' else {})
            for day in schedule.get('dates') or []:
                for g in day.get('games') or []:
                    if str(g.get('gamePk')) == item.get('game_id') and g.get('seriesGameNumber'):
                        item['game'] = str(g['seriesGameNumber']); item['season'] = str(g.get('season') or '')
                        item['game_date'] = g.get('officialDate'); item['scheduled_game_at'] = utc(g.get('gameDate'))
                        desc = g.get('seriesDescription') or ''
                        item['series'] = {'National League Championship Series':'NLCS','American League Championship Series':'ALCS'}.get(desc, item['series'])
                        if kind=='starting_lineup': item['kind']='lineup'; item['confirmed_lineup']=True
            out.append(item)
    return out


def fan_rows(material, reddit=False):
    if reddit and os.environ.get('COLLESPO_REDDIT') != 'on': return []
    out = []
    for row in material.get('voices') or []:
        text = row.get('ja') or row.get('original') or row.get('title') or ''
        if not __import__('fan_privacy').safe(row): continue
        if not text or len(text) > (140 if reddit else 100) or not row.get('url') or '@' in text: continue
        targets=[p for p in PLAYERS if story.player_match(row,p)]
        if reddit and not targets:
            u=urlsplit(row.get('url') or '')
            if u.scheme=='https' and u.hostname in ('reddit.com','www.reddit.com') and '/comments/' in u.path:
                targets=[dict(name_en='reddit:'+row['url'],name_jp='Redditの試合スレッド',sport=row.get('sport','MLB'))]
        for p in targets:
            item = base(row, material, 'fan', p, 'fan')
            original = row.get('original') or row.get('title') or text
            item.update(original=original, translated=row.get('ja'), display_text=text,
                        subject_type='thread' if p['name_en'].startswith('reddit:') else 'player',
                        language='ja' if re.search(r'[ぁ-んァ-ン一-龯]', original) else 'other',
                        source=__import__('fan_privacy').LABEL if reddit else row.get('source') or '公式ハイライトのコメント',
                        platform='reddit' if reddit else 'youtube', translation_note=FAN_NOTE)
            item['id'] = digest(['fan', row['url'], original, p['name_en']]); out.append(item)
    return out[:6]


def build(reporters, buzz, voices, official=None, reddit=None, history=None, as_of=None):
    as_of = as_of or datetime.now(timezone.utc)
    observations, rejected = parse_reports(reporters)
    extra, errors = parse_reports(buzz); observations += extra; rejected += errors
    documents, errors = official_documents(official or {}); observations += documents; rejected += errors
    observations += official_stats(official or {})
    observations += fan_rows(voices) + fan_rows(reddit or {}, reddit=True)
    # 以前の公式否定を消して、古い記事で復活させない。
    old = [o for event in (history or {}).get('events', []) for o in event['observations']]
    removed=set((voices.get('removed_urls') or []) + ((reddit or {}).get('removed_urls') or []))
    old=[o for o in old if o['url'] not in removed and (o['channel']!='fan' or
         (evidence_time(o) and as_of-story.stamp(evidence_time(o))<=timedelta(days=30)))]
    merged = {o['id']: o for o in old+observations}
    observations = list(merged.values())
    # Game番号のみの報道は同時期に唯一の回戦が明示されているときだけ結び付ける。
    for o in observations:
        if o['series'] or not o['game']: continue
        scopes = {q['series'] for q in observations if q['player_en'] == o['player_en'] and q['game'] == o['game'] and q['season']==o['season'] and q['series']}
        if len(scopes) == 1: o['series'] = scopes.pop(); o['scope_resolution'] = '同じ選手/年/戦番号に唯一の明示回戦'
    grouped = defaultdict(list)
    for o in observations:
        key = [o['sport'], o['player_en'], o['season'], o['series'], o['game'], o['kind'], o.get('game_id') if not o['game'] else None]
        if o['kind']=='transaction': key += [o['original']]
        if o['channel']=='fan': key += [o['id']]
        grouped[digest(key)].append(o)
    events = []
    for key, rows in grouped.items():
        sample = rows[0]
        known = [o for o in rows if o['channel']!='fan' and evidence_time(o)]
        current = [o for o in known if fresh_evidence(o,as_of)]
        official_rows = [o for o in current if o['channel'].startswith('official_')]
        reports = [o for o in current if o['channel']=='report' and o['polarity']=='positive']
        identities = {o['origin'] for o in reports if not o['origin'].startswith('unknown:')}
        certainty = 'official' if official_rows else 'multiple' if len(identities)>=2 else 'single' if reports else 'fan'
        if not current and sample['channel']!='fan':
            historical = known or rows
            origins = {o['origin'] for o in historical if o['channel']=='report' and not o['origin'].startswith('unknown:')}
            certainty = 'official' if any(o['channel'].startswith('official_') for o in historical) else 'multiple' if len(origins)>=2 else 'single'
        last_official = max((o for o in known if o['channel'].startswith('official_')), key=evidence_time, default=None)
        refuted = bool(last_official and last_official['polarity']=='negative')
        if refuted: certainty='official'
        latest_evidence=max(current,key=evidence_time,default=None)
        disputed=bool(latest_evidence and latest_evidence['polarity']=='negative' and not official_rows)
        status = 'refuted' if refuted else 'disputed' if disputed else 'active' if current or sample['channel']=='fan' else 'stale'
        if not known and sample['channel']!='fan': status='unverified'
        if sample['channel']=='fan':
            fresh_fan = sample['published_at'] and timedelta(0)<=as_of-story.stamp(sample['published_at'])<=MAX_AGE
            status = 'active' if fresh_fan else 'stale'
        event = dict(id=key, player_en=sample['player_en'], player_jp=sample['player_jp'], sport=sample['sport'], kind=sample['kind'],
                     game=sample['game'], series=sample['series'], season=sample['season'], status=status,
                     certainty=certainty, certainty_label=LEVELS[certainty], usable=status=='active' and certainty!='fan',
                     observations=sorted(rows,key=evidence_time), independent_origins=sorted(identities),
                     updated_by=None, game_date=sample.get('game_date'), event_at=sample.get('event_at'))
        events.append(event)
    # 協議→先発という結論は同じ対象試合の更新。検討自体が虚偽だったとは言わない。
    for event in events:
        if event['kind']!='rest' or not event['usable']: continue
        followups = [e for e in events if e['kind'] in ('lineup','starting_lineup')
                     and ((e['usable'] and e['certainty'] in ('official','multiple')) or (e['status']=='refuted' and e['certainty']=='official'))
                     and all(e[k]==event[k] for k in ('sport','player_en','season','series','game'))
                     and e['game'] and e['series']
                     and max(evidence_time(o) for o in e['observations']) > max(evidence_time(o) for o in event['observations'])]
        if followups:
            later=max(followups,key=lambda e:max(evidence_time(o) for o in e['observations']))
            event.update(status='superseded',usable=False,updated_by=later['id'])
    state = dict(reporters=reporters.get('_input_state') or ('ready' if reporters else 'missing'),
                 local_buzz=buzz.get('_input_state') or ('counts_only' if buzz.get('teams') and not buzz.get('headlines') else 'ready' if buzz else 'missing'),
                 voices=voices.get('_input_state') or ('ready' if voices else 'missing'),
                 official=(official or {}).get('_input_state') or ('ready' if official else 'missing'),
                 reddit='off' if os.environ.get('COLLESPO_REDDIT')=='off' else (reddit or {}).get('_input_state') or (reddit or {}).get('state','saved_only'))
    return dict(schema_version=1, generated_at=as_of.isoformat(), events=sorted(events,key=lambda e:e['id']), channel_states=state, rejected=rejected)


def active(hub, player_en=None, fans=False, now=None):
    now = now or datetime.now(timezone.utc)
    out = []
    for e in hub.get('events') or []:
        if e['status']!='active' or (player_en and e['player_en']!=player_en): continue
        if not fans and not e['usable']: continue
        current=[o for o in e['observations'] if fresh_evidence(o,now)]
        if not current: continue
        if e['certainty']=='fan': out.append(dict(e,observations=current)); continue
        official=[o for o in current if o['channel'].startswith('official_') and o['polarity']=='positive']
        origins={o['origin'] for o in current if o['channel']=='report' and o['polarity']=='positive' and not o['origin'].startswith('unknown:')}
        certainty='official' if official else 'multiple' if len(origins)>=2 else 'single'
        out.append(dict(e,observations=current,certainty=certainty,certainty_label=LEVELS[certainty],independent_origins=sorted(origins)))
    return out


def phrase(event):
    if not event['usable'] or event['status']!='active' or event['certainty']=='fan': raise ValueError('使用不可の話を事実にしません')
    rows = [o for o in event['observations'] if o['polarity']=='positive' and o['channel']!='fan']
    if not rows: raise ValueError('事実の根拠がありません')
    official = [o for o in rows if o['channel'].startswith('official_')]
    count = len({o['origin'] for o in rows if o['channel']=='report' and not o['origin'].startswith('unknown:')})
    if event['certainty']=='official' and not official: raise ValueError('報道を公式に昇格させません')
    if event['certainty']=='multiple' and count<2: raise ValueError('転載や同じ媒体を複数の報道に数えません')
    row=max(rows,key=evidence_time)
    claim=CLAIMS[event['kind']].format(game=event['game'], name=event['player_jp'], detail=(row.get('detail') or {}).get('detail',''))
    if event['certainty']=='official':
        if any(o.get('confirmed_lineup') for o in rows): return f"第{event['game']}戦で{event['player_jp']}が先発メンバーに入っています。"
        return claim
    sources=sorted({o['source'] for o in rows if o['source']})
    prefix='複数の報道によると、' if event['certainty']=='multiple' else (sources[0]+'によると、')
    return prefix+claim.removesuffix('です。')+'とのことです。'


def reporter_material(hub, player_en=None, now=None):
    heads=[]
    for event in active(hub,player_en,now=now):
        row=max(event['observations'],key=evidence_time)
        if event['kind'] not in CLAIMS: continue
        heads.append(dict(query=event['player_en'], title=phrase(event), jp=phrase(event), source=row['source'], url=row['url'],
                          at=evidence_time(row), hub_event=event))
    return dict(updated_at=hub.get('generated_at'), posts=[], headlines=heads)


def reaction_material(hub, player_en, now=None):
    rows=[]
    for event in active(hub,player_en,fans=True,now=now):
        if event['certainty']=='fan':
            row=event['observations'][-1]
            if row.get('language')!='ja': continue
            rows.append(dict(kind='youtube' if row['platform']=='youtube' else 'reddit', original=row['original']+'（'+FAN_NOTE+'）',
                             source=__import__('fan_privacy').source(row), url=row['url'], at=row['published_at'], player_en=player_en, hub_event=event))
        else:
            row=event['observations'][-1]
            if row['origin'] not in ('sponichi','hochi','sanspo','daily') or not re.search(r'[ぁ-んァ-ン一-龯]',row['original']): continue
            rows.append(dict(kind='headline',original=phrase(event),source=row['source'],url=row['url'],at=evidence_time(row),player_en=player_en,hub_event=event))
    return rows[:3]


def player_reports(hub,p,now):
    reports=[]
    for event in active(hub,p['name_en'],now=now):
        if event['kind'] not in ('rest','lineup'): continue
        row=event['observations'][-1]
        down=any(re.search(r'\b(?:struggles|struggling|slump)\b',o['original'],re.I) for o in event['observations'])
        reports.append(dict(kind=event['kind'],game=event['game'],direction='down' if down else 'neutral',claim=phrase(event),
                            source=row['source'],author=row.get('author',''),url=row['url'],at=evidence_time(row),original=row['original'],hub_event=event))
    return sorted(reports,key=lambda r:r['at'])[-2:]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('reporters','buzz','voices'):
        ap.add_argument('--'+name,default='data/local_'+('reporters' if name=='reporters' else 'buzz' if name=='buzz' else 'voices')+'.json')
    ap.add_argument('--official'); ap.add_argument('--reddit',default='data/reddit_voices.json'); ap.add_argument('--history')
    ap.add_argument('--as-of'); ap.add_argument('--out',default='data/topic_hub.json')
    args=ap.parse_args()
    if not enabled(): print('話題の集め所は既定オフです'); return
    now=story.stamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
    result=build(load(args.reporters),load(args.buzz),load(args.voices),load(args.official) if args.official else {},
                 load(args.reddit) if args.reddit else {},load(args.history or args.out),now)
    target=Path(args.out); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(events=len(result['events']),states=result['channel_states']),ensure_ascii=False))


if __name__=='__main__': main()
