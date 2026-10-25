"""保存された本人の数字・現地報道から日本人選手1人の流れを選ぶ。生成AIは使わない。"""
import argparse
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from notability_engine import JP_PLAYERS_MLB  # noqa: E402

# 基準・締め・表情の決定元。1試合の無安打だけでは不調と決めない。
RULES = {'window_games': 5, 'min_games': 3, 'min_ab': 12,
         'avg_gap': .120, 'hitless_games': 3, 'multi_hit_games': 3,
         'min_pitching_outs': 27, 'era_gap': 2.0,
         'max_material_hours': 48, 'max_story_seconds': 60,
         'down': {'closing': '早く調子を取り戻してほしいですね。', 'face': 'sad', 'effect': None},
         'up': {'closing': 'この調子が続くか注目です。', 'face': 'pose-smile', 'effect': 'sparkle'},
         'neutral': {'closing': '引き続き応援していきたいですね。', 'face': 'base', 'effect': 'none'}}

# 解釈を足さずに訳せる報道だけを扱う。未対応の見出しを無理に原稿へ入れない。
REPORT_RULES = (
    ('rest', r'will discuss sitting .+? in (?:NLCS )?Game (\d+)',
     '第{game}戦で{name}を休ませることを協議する見込みと報じられています。', 'neutral'),
    ('lineup', r'(?:will be in|to remain in|to keep|will remain in).+?(?:Game (\d+).+?lineup|lineup.+?Game (\d+))',
     '第{game}戦でも{name}を先発メンバーに入れる予定と報じられています。', 'neutral'),
)


def stamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        dt = parsedate_to_datetime(str(value))
    if dt.tzinfo is None:
        raise ValueError('報道の時刻にタイムゾーンがありません')
    return dt.astimezone(timezone.utc)


def fresh(value, as_of):
    try:
        delta = as_of - stamp(value)
        return timedelta(0) <= delta <= timedelta(hours=RULES['max_material_hours'])
    except (ValueError, TypeError, OverflowError):
        return False


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def spoken_day(value):
    day = date.fromisoformat(value)
    return f'{day.month}月{day.day}日'


def player_match(row, p):
    # 名前の明示が必要。球団単位のgistや声を本人の話に変えない。
    names = row.get('jp_players') or []
    text = str(row.get('text') or row.get('title') or '')
    return (p['name_en'] in text or row.get('query') == p['name_en']
            or p['name_en'] in names or p['name_jp'] in names)


def reports_for(material, buzz, p, as_of):
    import topic_hub
    if topic_hub.enabled():
        hub = material.get('_topic_hub') or topic_hub.build(material, buzz, {}, as_of=as_of)
        return topic_hub.player_reports(hub, p, as_of)
    rows = list(material.get('posts') or []) + list(material.get('headlines') or [])
    # local_buzz の件数や球団gistは報道の証拠にならない。URL/媒体/時刻付きの見出しのみ。
    rows += list(buzz.get('headlines') or [])
    reports = []
    for row in rows:
        if not player_match(row, p) or not fresh(row.get('at'), as_of):
            continue
        source = row.get('outlet') or row.get('source')
        url = row.get('url') or row.get('uri')
        if url and url.startswith('at://') and row.get('handle'):
            url = f"https://bsky.app/profile/{row['handle']}/post/{url.rsplit('/', 1)[-1]}"
        if not source or not url:
            continue
        original = row.get('text') or row.get('title') or ''
        # 複数選手・否定・疑問・反証を含む文は型訳しない。
        if re.search(r'\b(?:not|never|won.t|might not|denies|denied)\b|\?', original, re.I):
            continue
        other = any(q['name_en'] in original for q in JP_PLAYERS_MLB if q['name_en'] != p['name_en'])
        if other:
            continue
        for kind, pattern, template, direction in REPORT_RULES:
            m = re.search(pattern, original, re.I)
            if not m:
                continue
            game = next(v for v in m.groups() if v)
            # 不調を材料が明示した場合のみ、応援の締めへ。休養検討だけで不調とはしない。
            if re.search(r'\b(?:struggles|struggling|slump)\b', original, re.I):
                direction = 'down'
            reports.append(dict(kind=kind, game=game, direction=direction,
                                claim=template.format(game=game, name=p['name_jp']),
                                source=source, author=row.get('author') or '',
                                url=url, at=stamp(row['at']).isoformat(), original=original))
            break
    # 古い協議→新しい先発報道。続報は最も新しい同じ試合番号のものを残す。
    reports.sort(key=lambda r: r['at'])
    if not reports:
        return []
    latest = reports[-1]
    earlier = next((r for r in reports if r['kind'] == 'rest' and r['game'] == latest['game']
                    and r['at'] < latest['at']), None)
    # 締め用の不調根拠は同じ最新話題の保存報道からのみ。
    if any(r['direction'] == 'down' and r['game'] == latest['game'] for r in reports):
        latest = dict(latest, direction='down')
    return [earlier, latest] if earlier and latest['kind'] == 'lineup' else [latest]


def numeric_flow(p, stats):
    if stats.get('type', p['type']) != p['type']:
        return None
    games = stats.get('games') or []
    games = sorted(games, key=lambda g: (g['date'], str(g['game_id'])))[-RULES['window_games']:]
    if len({g['game_id'] for g in games}) != len(games):
        raise ValueError('同じ試合の数字が重複しています')
    if p['type'] == 'pitcher':
        if not all(type(g.get(k)) is int and g[k] >= 0 for g in games for k in ('outs', 'er')):
            return None
        outs, er = sum(g['outs'] for g in games), sum(g['er'] for g in games)
        if len(games) < RULES['min_games'] or outs < RULES['min_pitching_outs']:
            return None
        baseline = stats.get('season') or {}
        so, se = baseline.get('outs'), baseline.get('er')
        if type(so) is not int or type(se) is not int or so < 90 or se < 0:
            return None
        era, season_era = er*27/outs, se*27/so
        if abs(era-season_era) < RULES['era_gap']:
            return None
        direction = 'down' if era > season_era else 'up'
        innings = f'{outs//3}' + (f'と{outs%3}/3' if outs%3 else '')
        text = (f"{p['name_jp']}は{spoken_day(games[0]['date'])}から{spoken_day(games[-1]['date'])}の直近{len(games)}登板で、"
                f"{innings}回、自責{er}。防御率は{era:.2f}、今季レギュラーシーズンは{season_era:.2f}です。")
        return dict(direction=direction, reason='era_gap', text=text, games=games,
                    season=baseline, source=stats.get('source'))
    valid = all(type(g.get(k)) is int and g[k] >= 0 for g in games for k in ('ab', 'hits'))
    if not valid or any(g['hits'] > g['ab'] for g in games):
        raise ValueError('打者の数字が不正です')
    if len(games) < RULES['min_games']:
        return None
    ab, hits = sum(g['ab'] for g in games), sum(g['hits'] for g in games)
    if ab < RULES['min_ab']:
        return None
    direction, reason = None, None
    if all(g['hits'] == 0 and g['ab'] > 0 for g in games[-RULES['hitless_games']:]):
        direction, reason = 'down', 'hitless_games'
    elif all(g['hits'] >= 2 for g in games[-RULES['multi_hit_games']:]):
        direction, reason = 'up', 'multi_hit_games'
    baseline = stats.get('season') or {}
    sab, sh = baseline.get('ab'), baseline.get('hits')
    if type(sab) is int and type(sh) is int and sab >= 100 and 0 <= sh <= sab:
        gap = hits / ab - sh / sab
        if direction is None and abs(gap) >= RULES['avg_gap']:
            direction, reason = ('up' if gap > 0 else 'down'), 'avg_gap'
    if not direction:
        return None
    text = f"{p['name_jp']}は{spoken_day(games[0]['date'])}から{spoken_day(games[-1]['date'])}の直近{len(games)}試合で、{ab}打数{hits}安打。"
    if reason == 'hitless_games':
        text += f"直近{RULES['hitless_games']}試合は無安打です。"
    elif reason == 'multi_hit_games':
        text += f"直近{RULES['multi_hit_games']}試合で複数安打が続いています。"
    elif reason == 'avg_gap':
        text += f"打率は{hits / ab:.3f}、今季レギュラーシーズンは{sh / sab:.3f}です。"
    return dict(direction=direction, reason=reason, text=text, games=games,
                season=baseline, source=stats.get('source'))


def build(recap, reporters, buzz, voices, stats, as_of):
    candidates = []
    for p in JP_PLAYERS_MLB:
        numeric = stats.get(p['name_en']) or {}
        flow = None
        if fresh(numeric.get('updated_at'), as_of) and numeric.get('source'):
            # 更新時刻だけ新しい過去の試合で発火させない。
            games = numeric.get('games') or []
            if games and 0 <= (as_of.date() - date.fromisoformat(max(g['date'] for g in games))).days <= 2:
                flow = numeric_flow(p, numeric)
        reports = reports_for(reporters, buzz, p, as_of)
        if not flow and not reports:
            continue
        candidates.append((int(bool(flow)) + int(bool(reports)), p, flow, reports))
    if not candidates:
        return dict(can_make=False, reason='成績の流れと本人の現地報道がありません', segments=[])
    _, p, flow, reports = max(candidates, key=lambda item: (item[0], item[3][-1]['at'] if item[3] else ''))
    direction = flow['direction'] if flow else reports[-1]['direction']
    segments = []
    def add(kind, text, source, **meta):
        segments.append(dict(kind=kind, speaker=2, text=text,
                             meta=dict(source=source, **meta)))
    if flow:
        add('numbers', flow['text'], flow['source'])
    else:
        # 単日の数字は流れの根拠ではないが、報道がある回の冒頭に使える。
        row = next((r for r in recap.get('players', []) if r.get('name_en') == p['name_en']
                    and r.get('type') == 'batter'), None)
        if row and fresh(recap.get('updated_at'), as_of) and recap.get('date'):
            ab, hits = row.get('ab'), row.get('hits')
            if type(ab) is int and type(hits) is int and 0 <= hits <= ab:
                add('numbers', f"現地{spoken_day(recap['date'])}の試合で{p['name_jp']}は{ab}打数{hits}安打でした。", 'MLB公式',
                    at=recap['date'])
        if not segments:
            add('intro', p['name_jp']+'の現地報道です。', '保存した現地報道')
    for i, report in enumerate(reports):
        when = stamp(report['at']).astimezone(timezone(timedelta(hours=9)))
        label = '' if report.get('hub_event') else 'その後の報道によると、' if i else '報道によると、'
        add('report', label+report['claim'], report['source'], report=report,
            display_time=f'{when.month}/{when.day} {when:%H:%M} JST')
    # 一般の投稿者名を一切出さない。病気・心理・予測や根拠のない理由も取り込まない。
    safe_fan = re.compile(r'けが|怪我|負傷|病|疲|心理|精神|プレッシャー|原因|せい|だから|なので|理由|必ず|絶対|だろう|はず|引退|クビ|@')
    count = 0
    for voice in voices.get('voices') or []:
        text = voice.get('ja') or ''
        if (count >= 2 or not player_match(voice, p) or not fresh(voice.get('at'), as_of)
                or not voice.get('url') or not text or len(text) > 90 or safe_fan.search(text)):
            continue
        # 短い感想と応援。番号だけの誤訳・本人名も評価語も無い声を採らない。
        if re.fullmatch(r'[\d０-９]+番[。.!！]?', text) or not re.search(r'頑張|がんば|応援|復調|調子|怖|驚|すご|凄|想像|活躍|打席', text):
            continue
        add('fan', 'ファンの感想には「'+text+'」という声もあります。',
            voice.get('source') or 'ファンの声', url=voice['url'], at=voice['at'])
        count += 1
    add('closing', RULES[direction]['closing'], 'コレスポの応援の言葉')
    sources = [f"{r['source']} {r['author']} / {r['at']}\n{r['url']}\n原文: {r['original']}" for r in reports]
    sources += [f"匿名のファンの感想（事実の判定やチャンネルの見解ではありません）\n{seg['meta']['url']}" for seg in segments if seg['kind'] == 'fan']
    sources += [flow['source']] if flow else []
    if direction == 'down' and not flow:
        # 最新報道とは別の見出しが不調を明記している場合も、締めの根拠を出典付きで残す。
        mood_rows = list(reporters.get('posts') or []) + list(reporters.get('headlines') or [])
        sources += [f"不調への言及: {r.get('outlet') or r.get('source')} / {r['at']}\n{r.get('url') or r.get('uri')}\n原文: {r.get('text') or r.get('title')}"
                    for r in mood_rows if player_match(r, p) and fresh(r.get('at'), as_of)
                    and re.search(r'\b(?:struggles|struggling|slump)\b', r.get('text') or r.get('title') or '', re.I)]
    result = dict(can_make=True, label=as_of.date().isoformat(), player=p,
                direction=direction, flow=flow, reports=reports, segments=segments,
                title=p['name_jp']+'のいまの流れ #Shorts',
                description='数字と現地報道を出典・時点付きで紹介します。\n'+'\n'.join(sources),
                duration_budget=dict(limit=RULES['max_story_seconds'], grace=0))
    import host_split
    return host_split.adapt(result, 'player_story')


def fetch_stats(recap, as_of):
    """出場者だけの公式記録。レギュラーシーズンの水準と直近試合を分ける。"""
    import requests
    from mlb_splits import season_stat
    out = {}
    for p in recap.get('players') or []:
        if p.get('type') not in ('batter', 'pitcher') or not p.get('player_id'):
            continue
        registered = next((q for q in JP_PLAYERS_MLB if q['name_en'] == p.get('name_en')), None)
        if not registered or registered['type'] != p['type']:
            continue  # 二刀流の投手行で打者の水準を上書きしない。
        url = f"https://statsapi.mlb.com/api/v1/people/{p['player_id']}/stats"
        try:
            def query(kind, game_type):
                response = requests.get(url, params=dict(stats=kind, group='pitching' if p['type']=='pitcher' else 'hitting', season=as_of.year,
                                                        gameType=game_type), timeout=30)
                response.raise_for_status()
                return response.json().get('stats') or []
            baseline = query('season', 'R')
            season = season_stat(baseline[0].get('splits', [])) if baseline else {}
            games = {}
            for game_type in ('R', 'F', 'D', 'L', 'W'):
                for block in query('gameLog', game_type):
                    for s in block.get('splits') or []:
                        st = s.get('stat') or {}; gid = (s.get('game') or {}).get('gamePk')
                        if p['type'] == 'pitcher' and gid and s.get('date') and 'inningsPitched' in st and 'earnedRuns' in st:
                            games[str(gid)] = dict(game_id=str(gid), date=s['date'], outs=ip_outs(st['inningsPitched']), er=int(st['earnedRuns']))
                        elif p['type'] == 'batter' and gid and s.get('date') and 'atBats' in st and 'hits' in st:
                            games[str(gid)] = dict(game_id=str(gid), date=s['date'], ab=int(st['atBats']), hits=int(st['hits']))
            baseline_values = (dict(outs=ip_outs(season.get('inningsPitched', '0.0')), er=int(season.get('earnedRuns', 0)))
                               if p['type']=='pitcher' else dict(ab=int(season.get('atBats', 0)), hits=int(season.get('hits', 0))))
            out[p['name_en']] = dict(updated_at=as_of.isoformat(), source=url, type=p['type'],
                season=baseline_values,
                games=sorted(games.values(), key=lambda g: (g['date'], g['game_id']))[-RULES['window_games']:])
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f"[warn] {p.get('name_en')}の流れの数字は取得失敗: {type(exc).__name__}", file=sys.stderr)
    return out


def ip_outs(value):
    whole, _, fraction = str(value).partition('.')
    if not whole.isdigit() or fraction not in ('', '0', '1', '2'):
        raise ValueError('投球回の端数が不正です')
    return int(whole)*3+int(fraction or 0)


def validate(narr, publish=False):
    """型訳・応援・出典の取り違えを公開直前にも止める。"""
    if not narr.get('can_make') or not narr.get('segments'):
        raise ValueError('この日は選手の話題の材料がありません')
    direction = narr['direction']
    if narr['segments'][-1]['text'] != RULES[direction]['closing']:
        raise ValueError('締めが流れと違います')
    if not narr.get('flow') and not narr.get('reports'):
        raise ValueError('ファンの声だけでは作れません')
    if narr.get('flow'):
        expected = numeric_flow(narr['player'], narr['flow'])
        if not expected or expected != narr['flow'] or expected['direction'] != direction:
            raise ValueError('数字と流れが一致しません')
    if publish and narr['label'] != datetime.now(timezone.utc).date().isoformat():
        raise ValueError('当日の原稿ではありません')
    for seg in narr['segments']:
        if seg['kind'] != 'report':
            continue
        report = seg['meta']['report']
        if report.get('hub_event'):
            import topic_hub
            if report['claim'] != topic_hub.phrase(report['hub_event']) or seg['text'] != report['claim']:
                raise ValueError('集め所の確かさと言い方が一致しません')
            continue
        rule = next(r for r in REPORT_RULES if r[0] == report['kind'])
        template = rule[2]
        original_match = re.search(rule[1], report['original'], re.I)
        if not original_match or report['game'] not in original_match.groups():
            raise ValueError('報道の原文と試合番号が違います')
        claim = template.format(game=report['game'], name=narr['player']['name_jp'])
        if report['claim'] != claim or seg['text'] not in ('報道によると、'+claim, 'その後の報道によると、'+claim):
            raise ValueError('報道を断定や根拠のない理由に変えています')
        if not report['source'] or not report['url'] or not report['at']:
            raise ValueError('報道の出典がありません')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--recap', default='data/morning_recap.json')
    ap.add_argument('--reporters', default='data/local_reporters.json')
    ap.add_argument('--buzz', default='data/local_buzz.json')
    ap.add_argument('--voices', default='data/local_voices.json')
    ap.add_argument('--stats', help='保存した直近試合と今季水準')
    ap.add_argument('--topic-hub', default='data/topic_hub.json')
    ap.add_argument('--fetch-stats', action='store_true')
    ap.add_argument('--as-of', help='保存材料の評価時点（タイムゾーン付きISO）')
    ap.add_argument('--out', default='build/player_story/narration.json')
    args = ap.parse_args()
    target = Path(args.out); target.unlink(missing_ok=True)
    if os.environ.get('COLLESPO_PLAYER_STORY') != 'on':
        print('選手の話題の回は既定オフです'); return
    as_of = stamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
    recap = read(args.recap)
    stats = read(args.stats) if args.stats else fetch_stats(recap, as_of) if args.fetch_stats else {}
    reporters = read(args.reporters)
    import topic_hub
    if topic_hub.enabled():
        hub = topic_hub.load(args.topic_hub)
        if not hub: hub = topic_hub.build(reporters, read(args.buzz), read(args.voices), as_of=as_of)
        reporters = dict(reporters, _topic_hub=hub)
    narr = build(recap, reporters, read(args.buzz), read(args.voices), stats, as_of)
    import sanity_sources
    narr = sanity_sources.attach(narr, dict(date_jst=as_of.date().isoformat(),
        source='generation.player_story', players=[narr['player']] if narr.get('player') else []))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(narr, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(can_make=narr['can_make'], direction=narr.get('direction')), ensure_ascii=False))


if __name__ == '__main__':
    main()
