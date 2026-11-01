"""題と主役を保存材料から決める。通信・AI・所属の推測なし。既定off。"""
import copy
import functools
import json
import math
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def enabled():
    return os.environ.get('COLLESPO_SOCCER_TITLE_V2', 'off') == 'on'


@functools.lru_cache(maxsize=1)
def names():
    return json.loads((ROOT/'data/soccer_title_names.json').read_text(encoding='utf8'))


def player_name(full):
    table = names()
    alias = table['players'].get(full)
    if full in table['keep_full'] or not alias:return full
    import notability_engine
    same_surname = {p['name_jp'] for p in notability_engine.JP_PLAYERS_SOCCER if p['name_jp'].startswith(alias)}
    # 対象の現役名簿に同姓が加わった場合も、推測で短くしない。
    if same_surname - {full}:return full
    return alias


def club_name(full):
    import club_display_names as clubs
    canonical = clubs.display(full)
    return names()['clubs'].get(canonical, canonical)


def title(head, league=''):
    # 語や名前を途中で切らない。後ろの競技札から省く。
    for suffix in (('｜'+league if league else '')+' #Shorts', ' #Shorts', ''):
        if len(head+suffix) <= 100:
            return head+suffix
    raise ValueError('主題が100字を超えます。名前を途中で切らず保留します')


def preview_game(data):
    selected = (data.get('preview_selection') or {}).get('selected_ids')
    if selected:
        import soccer_selection
        ordered = []
        for ident in selected:
            hits = [g for g in data['games'] if str(g['game_id']) == str(ident)]
            if len(hits) != 1:
                raise ValueError('題の主役を選定済み試合に照合できません')
            ordered.extend(hits)
        return next((g for g in ordered if any(soccer_selection.visible_members(g).values())), ordered[0])
    return next((g for g in data.get('games', []) if g.get('is_notable')), None)


def preview_head(data):
    import soccer_selection as selection
    import soccer_match_interest as interest
    game = preview_game(data)
    if not game:
        return None
    people = selection.visible_members(game)
    side = next((s for s in ('home', 'away') if people[s]), 'home')
    other = 'away' if side == 'home' else 'home'
    who = people[side][0] if people[side] else ''
    # 久保ソシエダ。短くしない名前は「町野修斗のボルシアMG」にして名前とクラブをくっつけない。
    short = player_name(who) if who else ''
    subject = (short+('の' if short == who else '') if who else '')+club_name(game[side+'_team_name'])
    opponent = club_name(game[other+'_team_name'])
    insight = interest.decide(game, limit=None)
    evidence = insight['reasons']
    audio_head = thumbnail_head = None
    reason = next((r for r in evidence if r['kind'] in ('derby','title','cl','relegation')), None)
    if reason:
        conclusion = {'derby': reason['text'], 'title':'首位争い', 'cl':'CL圏の境目', 'relegation':'残留争い'}[reason['kind']]
        head = subject+'は'+conclusion+'で'+opponent+'と対戦'
    else:
        gap = interest.point_gap(game.get('home_standing') or {}, game.get('away_standing') or {})
        standing = game.get(side+'_standing') or {}
        rank = standing.get('rank')
        form = next((r for r in evidence if r['kind']=='form' and r['side']==side), None)
        if form:
            conclusion = form['text'].split(' ', 1)[1]
            head = subject+'は'+conclusion+'で'+opponent+'戦'
        elif gap is not None:
            conclusion = ('勝点で並ぶ' if gap == 0 else f'勝点差{gap:g}の')+opponent+'と対戦'
            head = subject+'は'+conclusion
        elif type(rank) is int and rank > 0:
            conclusion = f'{rank}位で'+opponent+'と対戦'
            head = subject+'は'+conclusion
        else:
            personal = insight.get('player')
            if who and personal and personal['name']==who:
                field = 'goals' if (personal.get('goals') or 0)>=3 else 'assists'
                unit = '得点' if field=='goals' else 'アシスト'
                value = personal[field]
                conclusion = interest.stats_label(personal)+f'{value:g}'+unit
                thumbnail_head = player_name(who)+'が'+conclusion
                head = thumbnail_head+'｜'+club_name(game[side+'_team_name'])+'対'+opponent
                import club_display_names
                audio_head = who+'は'+interest.stats_label(personal)+f'で{value:g}'+unit+'。'+club_display_names.display(game[side+'_team_name'])+'対'+club_display_names.display(game[other+'_team_name'])
            else:
                from soccer_selected_preview import preview_details
                previous = [re.fullmatch(r'(.+)は昨季(.+?)(\d+)位', f) for f in preview_details(game)]
                if not who and len(previous)==2 and all(previous) and previous[0][2]==previous[1][2]:
                    low, high = sorted(int(m[3]) for m in previous)
                    conclusion = f'昨季{previous[0][2]}{low}位対{high}位'
                    thumbnail_head = conclusion
                    head = conclusion+'｜'+subject+'対'+opponent
                elif not who and len(previous)==1 and previous[0]:
                    row=previous[0]
                    conclusion=f'昨季{row[2]}{int(row[3])}位'
                    thumbnail_head=club_name(row[1])+'は'+conclusion
                    head=thumbnail_head+'｜'+subject+'対'+opponent
                elif not who:
                    raise ValueError('日本人選手のいないカードの見どころを材料で確認できません')
                else:
                    raise ValueError('選手のカードの見どころを材料で確認できません')
    if not who and thumbnail_head is None:
        # 日本人がいない日は、カード名より見どころの結論を先にする。
        if reason or form:
            head = conclusion+'｜'+subject+'対'+opponent
        elif gap is not None:
            word = '勝点で並ぶ' if gap == 0 else f'勝点差{gap:g}'
            ranks = [(game.get(s+'_standing') or {}).get('rank') for s in (side, other)]
            if all(type(r) is int and r > 0 for r in ranks):
                head = f'{ranks[0]}位{subject}対{ranks[1]}位{opponent}｜{word}'
            else:
                head = word+'｜'+subject+'対'+opponent
        else:
            head = f'{rank}位の'+subject+'が'+opponent+'と対戦'
    return dict(head=head, subject=subject, conclusion=conclusion, name=who,
                audio_head=audio_head, thumbnail_head=thumbnail_head,
                club=game[side+'_team_name'], game_id=str(game['game_id']), league=game['league'])


def preview_plan(plan):
    focus = preview_head(plan['data'])
    if not focus:
        return plan
    plan = copy.deepcopy(plan)
    plan['narration']['title'] = title(focus['head'], focus['league'])
    plan['narration']['soccer_title_v2'] = focus
    for seg in plan['narration']['segments']:
        if seg['kind']=='cover':
            import club_display_names
            spoken = (focus['name']+'の' if focus['name'] else '')+club_display_names.display(focus['club'])
            # 題の区切り｜は字幕と声に持ち込まない。
            seg['text'] = (focus.get('audio_head') or focus['head'].replace(focus['subject'], spoken, 1)).replace('｜', '、')+'。'
            seg['meta']['title_focus'] = focus
        seg['meta']['ticker'] = focus['head']
    return plan


def result_focus(data):
    import soccer_results as results
    played = [p for p in data.get('players', []) if p['status']!='none']
    lead = min(played, key=results.rank_key) if played else None
    ident = lead['event_id'] if lead else next(iter((data.get('preview_followup') or {}).get('games', [])), {}).get('event_id')
    game = next((g for g in data['games'] if str(g['id'])==str(ident)), None)
    if game is None:
        return None
    if lead:
        head = player_name(lead['name'])+results.action(lead)
        subject = player_name(lead['name'])
    else:
        a, b = game['score']['home'], game['score']['away']
        winner = 'home' if a>b else 'away'
        head = (club_name(game['home']['name_en'])+'対'+club_name(game['away']['name_en'])+'は引き分け'
                if a==b else club_name(game[winner]['name_en'])+'が勝利')
        subject = club_name(game['home']['name_en'])+'対'+club_name(game['away']['name_en'])
    score = '対'.join(club_name(game[s]['name_en']) for s in ('home','away'))+f" {game['score']['home']}-{game['score']['away']}"
    return dict(head=head, subject=subject, score=score, game_id=str(game['id']),
                name=lead['name'] if lead else '', lead=lead, game=game)


def results_title(data):
    focus = result_focus(data)
    return title(focus['head']+'｜'+focus['score']) if focus else ''


def result_narration(data):
    import soccer_result_facts as facts
    import soccer_stats as stats
    import review_render_v3 as r3
    import sanity_sources
    focus = result_focus(data)
    if not focus:
        return dict(label=data['date_jst'], segments=[], duration_budget=dict(limit=60, grace=0))
    g, p = focus['game'], focus['lead']
    segs = []
    def add(kind, text, **meta):
        if text:
            segs.append(dict(kind=kind, text=text, speaker=2, meta=dict(event_id=g['id'], title_focus_v2=True, **meta)))
    first = (p['name']+__import__('soccer_results').action(p)+'。' if p else '')+g['home']['name_jp']+'対'+g['away']['name_jp']+f"は{g['score']['home']}対{g['score']['away']}。"
    add('intro' if p else 'followup', first, **(dict(player_detail=p['name']) if p else dict(score_only=True)))
    goals = sorted(g['goals'], key=lambda x: tuple(int(v) for v in (x['minute'].split('+')+['0'])[:2]))
    pages = math.ceil(len(goals)/3)
    sizes = [len(goals)//pages+(i<len(goals)%pages) for i in range(pages)] if pages else []
    start = 0
    for count in sizes:
        shown = goals[start:start+count]
        start += count
        row = next((r for r in (data.get('preview_followup') or {}).get('games', []) if str(r['event_id'])==str(g['id'])), {})
        add('followup-detail', ''.join(facts.goal_line(goal, g) for goal in shown),
            goals=shown, details=facts.display_details(g, row), required=True)
    if p:
        index = [x for x in g['players'] if x['status']!='none'].index(p)
        add('player-stats', stats.result_narration(p), start=index, count=1)
    add('team-stats', stats.commentary(g))
    row = next((r for r in (data.get('preview_followup') or {}).get('games', []) if str(r['event_id'])==str(g['id'])), {})
    if row.get('rank_changes'):
        changes = row['rank_changes']
        add('followup-change', ''.join(f"{c['club']}の順位は{c['before']}位から{c['after']}位。" for c in changes), rows=changes)
    segs.append(dict(kind='outro', text=r3.OUTRO_TEXT, speaker=2, meta={}))
    narr = sanity_sources.attach(dict(label=data['date_jst'], title=results_title(data), segments=segs,
        duration_budget=dict(limit=60, grace=0), soccer_title_v2={k:focus[k] for k in ('head','subject','score','game_id','name')}), data, sport='soccer')
    # 元の3情報・尺ゲートは描画時も通す。材料不足を他試合の羅列で埋めない。
    import short_content
    if len(short_content.information(narr, data)) < short_content.MIN_INFORMATION:
        raise ValueError('主役1試合の確認済み情報が3件未満です')
    return narr


def metadata_names(data, results=False):
    if results:
        focus = result_focus(data)
        return [focus['name']] if focus and focus['name'] else []
    focus = preview_head(data)
    return [focus['name']] if focus and focus['name'] else []


def headline_frame(t, focus, clubs, spec, preview_specs=None):
    """既存の予告一覧／大きいスコアを保ち、見出しだけ結論にそろえる。"""
    from soccer_readable import Screen, L, R
    from soccer_v5_program import quote_lines, _quote_rows
    import soccer_v5_cards as c
    aliases = dict(clubs)
    for key, club in clubs.items():
        aliases.setdefault(club_name(key), club)
    class FocusScreen(Screen):
        def title(self, main, sub=''):
            rows = quote_lines(focus.get('thumbnail_head') or focus['head'], 52, R-L, aliases)
            if len(rows)>2:raise ValueError('主題の見出しが2行を超えます')
            bottom = _quote_rows(self.im, L, 260, rows, 52, c.CHALK)
            self.im.info['focus_title_bottom'] = bottom
            if sub and len(rows)==1:
                self.lines(L, 330, sub, 30, R-L, c.MUTED, 'supplement')
    s = FocusScreen(clubs, t)
    if preview_specs:
        im = s.preview(preview_specs, spec)
    else:
        im = s.score(focus['game'], spec, person=focus.get('lead'), score_only=not focus.get('lead'))
    im.info['soccer_title_v2'] = focus['head']
    return im
