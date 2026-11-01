"""既存の欧州予告・順位争い・週末を、同じ材料からv4に描く。"""
import motion
from datetime import datetime, timedelta, timezone
import os
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import notability_engine as ne
import soccer_look
soccer_look.activate()
import review_render_v3 as r3
import soccer_v4_cards as cards
import video_common as vc
import v3_rules as rules

ROOT=Path(__file__).resolve().parents[1]
JST=timezone(timedelta(hours=9))
TAGLINE='欧州の日本人選手とMLBを、毎日数字で'
FILENAMES={'preview':'collespo_short.mp4','race':'collespo_morning_soccer_race.mp4','week':'collespo_morning_soccer_week.mp4'}


def enabled():
    return r3.LOOK=='v4'


def clubs_for(names):
    palette=cards.load_clubs();result={}
    for name in names:
        jp=ne.club_name_jp(name)
        hits={c['team_en']:c for c in palette.values() if ne.normalize_club(ne.club_name_jp(c['team_en']))==ne.normalize_club(jp) or ne.normalize_club(c.get('name_jp',''))==ne.normalize_club(jp)}
        club=dict(next(iter(hits.values()))) if len(hits)==1 else dict(team_en=name,name_jp=jp,abbr=name[:3].upper(),primary=None,secondary=None)
        club['name_jp']=jp
        result[name]=club;result[jp]=club
    return result


def segment(kind,text,spec):
    return dict(kind=kind,text=text,speaker=2,meta=spec)


def kickoff(game,generated):
    raw=game.get('start_time_utc') or game.get('utc')
    if raw:
        value=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if value.tzinfo is None:raise ValueError('キックオフの時差なし')
        return value.astimezone(JST)
    year=datetime.fromisoformat(generated.replace('Z','+00:00')).astimezone(JST).year
    value=datetime.strptime(f"{year}/{game['start_time_jst']}",'%Y/%m/%d %H:%M').replace(tzinfo=JST)
    # 保存材料の年末・年始をまたぐ日付だけを解決する。
    anchor=datetime.fromisoformat(generated.replace('Z','+00:00')).astimezone(JST)
    if value<anchor-timedelta(days=180):value=value.replace(year=year+1)
    return value


def preview_program(data):
    games=[g for g in data.get('games',[]) if g.get('is_notable') and (g.get('home_has_jp') or g.get('away_has_jp'))][:3]
    if not games:return package('preview',data,[],[], '')
    names={g[s+'_team_name'] for g in games for s in ('home','away')};clubs=clubs_for(names)
    lead=games[0];people={}
    for g in games:
        people[str(g['game_id'])]={s:(g.get('jp_by_side') or {}).get(s) or [p['name_jp'] for p in ne.jp_players_for_club(clubs[g[s+'_team_name']]['team_en'])] for s in ('home','away')}
    jp=people[str(lead['game_id'])];who=next((n for s in ('home','away') for n in jp[s]),'日本人選手')
    at=kickoff(lead,data['generated_at']);club=lead['home_team_name'] if jp['home'] else lead['away_team_name']
    head=f"{who}の{ne.club_name_jp(club)}が{ne.club_name_jp(lead['away_team_name'] if jp['home'] else lead['home_team_name'])}と対戦"
    segs=[segment('cover',f'{who}の所属クラブの注目試合です。',dict(kicker='欧州サッカー　予告',name=who,club=club,big=at.strftime('%H:%M'),unit='日本時間',context=f'{at.month}月{at.day}日（{"月火水木金土日"[at.weekday()]}）',chips=[]))]
    for g in games:
        at=kickoff(g,data['generated_at']);jp=people[str(g['game_id'])]
        # 古いAI解説に開催地の逆転があっても、材料のhome/awayから文を作り直す。
        text=f"日本時間{at.hour}時"+(f"{at.minute}分" if at.minute else '')+f"、ホームの{ne.club_name_jp(g['home_team_name'])}と、アウェーの{ne.club_name_jp(g['away_team_name'])}。"
        ranks={s:(g.get(s+'_standing') or {}).get('rank') for s in ('home','away')}
        ranks={s:n for s,n in ranks.items() if type(n) is int and n>0}
        spec=dict(date=f'{at.month}月{at.day}日（{"月火水木金土日"[at.weekday()]}）',time=at.strftime('%H:%M'),league=g['league'],home=g['home_team_name'],away=g['away_team_name'],ranks=ranks,jp=jp)
        segs.append(segment('preview',text,spec))
    return package('preview',data,segs,list(names),head,clubs)


def race_program(data):
    import soccer_race as race
    picked=[c for c in data.get('competitions',[]) if c.get('code') in data.get('picked',[]) and c.get('ready')]
    if not picked:return package('race',data,[],[], '')
    got=race.lead(data);comp=picked[0]
    names={r['team_en'] for c in picked for line in c['lines'] for r in line['inside']+line['outside']}
    names.update(p['club_jp'] for c in picked for p in c.get('jp',[]))
    clubs=clubs_for(names);segs=[]
    if got:
        who,near,label=got
        segs.append(segment('cover',f"{who['name']}の{who['club_jp']}は、{near['text']}。",dict(kicker=label+'　順位争い',name=who['name'],club=who['club_jp'],big=str(near['diff']),unit='勝点',big_label=near['text'].rsplit('勝点',1)[0].rstrip('。、')+('　あと' if 'まで' in near['text'] else ''),club_first=True,context=near['text'],chips=[(who['position'],'位'),(who['points'],'勝点')])))
    for comp in picked:
        highlights=[p['club_jp'] for p in comp.get('jp',[])]
        for line in comp.get('lines',[])[:3]:
            rows=sorted({r['position']:dict(position=r['position'],team=r['team_en'],played=r['played'],points=r['points']) for r in line['inside']+line['outside']}.values(),key=lambda r:r['position'])
            if not rows:continue
            focus=next((p for p in comp.get('jp',[]) if p['position'] in [r['position'] for r in rows] and any(n['line']==line['at'] for n in p.get('lines',[]))),None)
            near=next((n for n in focus['lines'] if n['line']==line['at']),None) if focus else None
            if focus:
                focus_key=next(r['team'] for r in rows if r['position']==focus['position'])
                gap='は'+race.phrase(near)
                text=f"{focus['name']}の{focus['club_jp']}は、{race.phrase(near)}。"
            else:
                boundary=[next((r for r in rows if r['position']==pos),None) for pos in (line['at'],line['at']+1)]
                pair='と'.join(f"{r['position']}位の{clubs[r['team']]['name_jp']}" for r in boundary if r)
                focus_key=None;gap='';text=f"{comp['name_jp']}の{line['label']}の境目です。{pair}の勝点差は{line['diff']}。"
            segs.append(segment('standings',text,dict(title=comp['name_jp']+'　'+line['label'],rows=rows,shown=[(r['position'],r['position']) for r in rows],lines=[(line['at'],line['label'])],focus=focus_key,highlights=[r['team'] for r in rows if clubs[r['team']]['name_jp'] in highlights],gap=gap)))
    return package('race',data,segs,list(names),race.title_of(data),clubs)


def week_program(data):
    import soccer_jp_week as week
    rows=data.get('rows') or []
    if not rows:return package('week',data,[],[], '')
    names={r[k] for r in rows for k in ('club','opp')};clubs=clubs_for(names);people=[]
    for row in rows:
        for person in row.get('players') or [row]:
            # 本人の数字を言えるのはプレミアの公式成績がある場合だけ。
            stats=person.get('stats') if row['league']=='PL' else None
            people.append(dict(name=person['name'],club=row['club'],row=row,stats=stats,out=person.get('out',False)))
    active=[p for p in people if p['stats'] is not None and p['stats'].get('minutes',0)>0 or p['stats'] is None and not p['out']]
    if not active:return package('week',data,[],[], '')
    lead=max(active,key=lambda p:((p['stats'] or {}).get('goals',0),(p['stats'] or {}).get('assists',0),p['row']['gf']>p['row']['ga']))
    p=lead;st=p['stats'];row=p['row']
    head=f"{p['name']}が{st['goals']}得点" if st and st.get('goals') else f"{p['name']}が{st['assists']}アシスト" if st and st.get('assists') else f"{p['name']}の{p['club']}は{row['gf']}-{row['ga']}の{row['result']}"
    segs=[]
    for start in range(0,len(people),7):
        chunk=people[start:start+7];display=[]
        for p in chunk:
            st=p['stats'];row=p['row'];values=[];note=''
            if st is not None and not st.get('minutes'):note='出場なし'
            elif st is None and p['out']:note='離脱中・当該試合の出場は未確認'
            elif st is not None:values=[(st[k],unit) for k,unit in (('goals','得点'),('assists','A'),('minutes','分')) if st.get(k) is not None]
            else:note=f"クラブ {row['gf']}-{row['ga']} {row['result']}"
            display.append(dict(name=p['name'],club=p['club'],values=values,note=note))
        segs.append(segment('jp_roster',(head+'。' if start==0 else '')+'日本人選手の週末です。',dict(title='日本人選手の週末　A＝アシスト',rows=display)))
    for p in [lead]+[p for p in active if p is not lead][:1]:
        st=p['stats'];row=p['row'];key=next((k for k in ('goals','assists','minutes') if st and st.get(k)),None)
        units={'goals':'得点','assists':'アシスト','minutes':'分出場'}
        chips=[(st[k],units[k]) for k in units if st.get(k) is not None and k!=key] if st else [(row['gf'],'クラブ得点'),(row['ga'],'失点')]
        spoken=week._one(dict(stats=st,out=p['out'])) if st else f"所属クラブは{row['gf']}対{row['ga']}の{row['result']}。本人の個人成績は未確認です"
        segs.append(segment('jp_player',p['name']+'。'+spoken+'。',dict(kicker=row['league_jp']+'　週末の結果',name=p['name'],club=p['club'],big=str(st[key]) if key else None,unit=units.get(key,''),chips=chips,notes=['所属クラブの結果：'+row['result']] if st else ['本人の出場・個人成績は未確認'])))
    return package('week',data,segs,list(names),head,clubs)


def package(mode,data,segs,names,head,clubs=None):
    from sports_dates import material_day
    day=material_day(data)
    source=data.get('source') or ('football-data.org / プレミアリーグ公式' if mode=='week' else 'football-data.org')
    try:
        _d=__import__('datetime').date.fromisoformat(day[:10]);day=f"{_d.month}月{_d.day}日（{'月火水木金土日'[_d.weekday()]}）"
    except ValueError:pass   # 帯は「9月19日（土）」の形（2026-09-18 のような書き方を画面に出さない）
    shared=dict(label={'preview':'欧州サッカー　予告','race':'欧州サッカー　順位争い','week':'欧州サッカー　日本人選手の週末'}[mode],source='音声: VOICEVOX:四国めたん　出典: '+source,ticker=day+'　'+head)
    import solo_host
    if solo_host.for_segments(segs) == 'ui':
        shared['source'] = solo_host.UI_CREDIT+'　出典: '+source
    for seg in segs:seg['meta'].update(shared)
    if segs:segs.append(segment('outro',r3.OUTRO_TEXT,shared))
    narration=dict(label=day,title='【欧州サッカー】'+head+' #Shorts' if head else '',soccer_v4_mode=mode,segments=segs,duration_budget=dict(limit=40,grace=0))
    import soccer_sanity_material
    narration['soccer_material']=soccer_sanity_material.compact(data)
    import sanity_sources
    narration = sanity_sources.attach(narration, data, sport='soccer')
    # 札の配列をJSONの型にそろえ、保存原稿・音声manifestとも同じ値で照合する。
    narration=json.loads(json.dumps(narration,ensure_ascii=False))
    if mode=='race' and soccer_look.v5():
        plan=dict(mode=mode,data=data,narration=narration,shared=shared)
        __import__('short_context').slots(plan, modern=True)
        race_details(plan)
    import host_split
    narration = host_split.adapt(narration, 'daily_soccer' if mode == 'preview' else 'soccer_'+mode)
    return dict(mode=mode,data=data,clubs=clubs or clubs_for(names),narration=narration,shared=shared)


def program(mode,data):
    if not enabled():raise ValueError('v4の場合だけ接続する')
    import soccer_preview
    import soccer_race
    import soccer_jp_week
    if mode=='preview' and soccer_look.v5():
        import soccer_match_interest
        data=soccer_match_interest.attach_season_stats(data)
    if mode=='preview' and data.get('preview_selection'):
        import soccer_selected_preview
        return soccer_selected_preview.program(data)
    plan={'preview':soccer_preview.v4_program,'race':soccer_race.v4_program,'week':soccer_jp_week.v4_program}[mode](data)
    if mode=='preview' and soccer_look.v5():
        import soccer_match_interest
        plan=soccer_match_interest.enrich_plan(plan)
    return plan if mode=='race' else __import__('short_context').slots(plan, modern=soccer_look.v5())


def race_details(plan):
    """短い順位回は、選んだ大会の日本人所属クラブの順位・勝点を補う。"""
    narr=plan['narration'];segs=narr['segments']
    if not segs or sum(len(s['text']) for s in segs)>=180:return
    # 冒頭の勝点差の繰り返しではなく、まだ読み上げていない順位と総勝点。
    spoken=''.join(s['text'] for s in segs if s['kind']!='outro')
    added=[];seen=set()
    for comp in plan['data'].get('competitions',[]):
        if comp.get('code') not in plan['data'].get('picked',[]) or not comp.get('ready'):continue
        for person in comp.get('jp',[]):
            club=person.get('club_jp');rank=person.get('position');points=person.get('points')
            if (not club or not person.get('name') or person.get('out') or club in seen
                    or type(rank) is not int or rank<1 or type(points) is not int):continue
            if f'{club}は{rank}位で勝点{points}' in spoken:continue
            seen.add(club)
            meta=dict(plan['shared'],kicker=comp['name_jp']+'　所属クラブの順位',
                      name=person['name'],club=club,big=str(rank),unit='位',
                      chips=[(points,'勝点')],notes=[])
            added.append(segment('jp_player',f"{person['name']}の{club}は{rank}位で勝点{points}。",meta))
            if len(added)==2:break
        if len(added)==2:break
    # 話者・口調の割付より前に追加し、保存原稿と音声の対象をそろえる。
    if added:
        at=next((i for i,s in enumerate(segs) if s['kind']=='outro'),len(segs))
        segs[at:at]=json.loads(json.dumps(added,ensure_ascii=False))


@motion.slot('soccer')
def frame(t,seg,plan):
    if not enabled():raise ValueError('v3の描画は既存の入口を使う')
    if soccer_look.readable():
        import soccer_readable
        im=soccer_readable.slots_frame(t,seg,plan)
        if im is not None:return im
    if soccer_look.v5():
        import soccer_v5_cards as v5
        if seg['kind']=='outro':return v5.outro(t,seg['meta'],exclude='daily_soccer' if plan['mode']=='preview' else 'soccer_'+plan['mode'],credit=seg['meta']['source'],tagline=TAGLINE)
        return getattr(v5,seg['kind'])(t,seg['meta'],plan['clubs'])
    if seg['kind']=='outro':return r3.outro(t,seg['meta'],exclude='daily_soccer' if plan['mode']=='preview' else 'soccer_'+plan['mode'],credit=seg['meta']['source'],tagline=TAGLINE)
    return getattr(cards,seg['kind'])(t,seg['meta'],plan['clubs'])


def material_numbers(plan):
    numbers=set()
    def walk(value):
        if isinstance(value,dict):
            for v in value.values():walk(v)
        elif isinstance(value,(list,tuple)):
            for v in value:walk(v)
        elif value is not None:numbers.update(re.findall(r'\d+(?:\.\d+)?',str(value)))
    walk(plan['data'])
    # 時計は保存された日時をJSTに直す。同じ値を画面へ渡す前に照合する。
    if plan['mode']=='preview':
        for g in plan['data'].get('games',[]):
            at=kickoff(g,plan['data']['generated_at']);numbers.update(str(n) for n in (at.hour,at.minute,at.month,at.day));numbers.update(at.strftime('%H:%M').split(':'))
    return numbers


def check_frame(image,plan):
    if soccer_look.v5():
        import soccer_v5_cards as v5
        errors=v5.check_frame(image,plan['clubs'])
        if not image.info.get('v3_outro'):
            extra=set(cards.drawn_numbers(image))-material_numbers(plan)
            if extra:errors.append(dict(numbers_missing_from_material=sorted(extra)))
        return errors
    errors=rules.check_layout(image)+rules.check_spacing(image)+cards.check_club_badges(image,plan['clubs'])
    if not image.info.get('v3_outro'):
        extra=set(cards.drawn_numbers(image))-material_numbers(plan)
        if extra:errors.append(dict(numbers_missing_from_material=sorted(extra)))
    return errors


def durations(segments,audio,check_limit=True):
    import synthesize_narration as sn
    if len(segments)!=len(audio):raise ValueError('音声の区間数が原稿と違う')
    times=[]
    for seg,voice in zip(segments,audio):
        if (seg['text'],seg['speaker'],seg['kind'],seg['meta'])!=(voice.get('text'),voice.get('speaker'),voice.get('kind'),voice.get('meta')):raise ValueError('音声の文/話者/画面が原稿と違う')
        path=Path(voice.get('file') or '')
        if not path.is_file():raise ValueError('実音声がありません')
        actual=sn.audio_duration(path)
        if actual<=0 or abs(actual-float(voice.get('duration') or 0))>.05:raise ValueError('音声の尺が実測と違う')
        times.append(max(actual,10.0 if seg['kind']=='preview' and seg['meta'].get('preview_duration_limit') else 3.0 if seg['kind']=='jp_roster' else 2.6 if seg['kind']=='outro' else 2.0))
    limit=55 if any(s['meta'].get('preview_duration_limit') for s in segments) else 40
    if check_limit and sum(times)>limit:raise ValueError(f'{limit}秒を超えます: {sum(times):.3f}。声の設定は変えず原稿を短くしてください')
    return times


def video_times(segments,audio):
    """音声後の間と30fpsの切り上げまで含めて予算を判定する。"""
    times=durations(segments,audio,check_limit=False)
    if soccer_look.readable():
        from soccer_readable import minimum_seconds
        times=[max(length,minimum_seconds(seg)) for length,seg in zip(times,segments)]
    if motion.enabled():
        times=[max(t,float(row['duration'])+vc.SEGMENT_TAIL) for t,row in zip(times,audio)]
    return [math.ceil(t*30)/30 for t in times]


class PreviewVoiceUnavailable(ValueError):
    """runnerから雨衣の短縮再合成を要求せず、既存の代役規則へ戻す。"""


def rebuild_preview_metan(plan, audio_dir, narration_path=None):
    import copy
    import host_split
    import synthesize_narration as synth
    import ui_voice_policy as policy
    original = copy.deepcopy(plan['narration'])
    folder = Path(audio_dir)
    held_path = folder/'shortening-held-narration.json'
    rebuilt = policy.failure(original, held_path, folder, 'ui_shortening_unavailable')
    target = folder/'metan-rebuild'
    target.mkdir(parents=True, exist_ok=True)
    source = target/'narration.json'
    host_split.resolve_credits(rebuilt, 'metan')
    rebuilt['voice_resolution'] = dict(host='metan', reason='ui_rebuilt_after_hold')
    source.write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2), encoding='utf-8')
    before = os.environ.get('COLLESPO_SOLO_HOST')
    try:
        os.environ['COLLESPO_SOLO_HOST'] = 'metan'
        synth.main(['--narration', str(source), '--out-dir', str(target), '--speaker', '2'])
    finally:
        if before is None:
            os.environ.pop('COLLESPO_SOLO_HOST', None)
        else:
            os.environ['COLLESPO_SOLO_HOST'] = before
    manifest = json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    rows = manifest['segments']
    if (len(rows) != len(rebuilt['segments']) or not rows or
            any(not r.get('file') or r.get('duration', 0) <= 0 or r.get('voice_host') == 'ui' for r in rows)):
        raise policy.VoiceUnavailable('ui_metan_rebuild_incomplete')
    plan['narration'] = json.loads(source.read_text(encoding='utf-8'))
    return rows, target, manifest


def fit_preview(plan,audio):
    """補足→4試合目→3試合目の順に短縮し、実測してから描画へ渡す。"""
    import synthesize_narration as sn
    import solo_host
    segments=plan['narration']['segments']
    if not any(s['meta'].get('preview_duration_limit') for s in segments):return
    limit=plan['narration']['duration_budget']['limit']
    original_ids=[s['meta'].get('game_id') for s in segments if s['kind']=='preview']
    def fits():return sum(video_times(segments,audio))<=limit
    if fits():return

    def rewrite(index,text):
        seg=segments[index];row=audio[index]
        # 元音声は保持。音声を切ったり速度を上げたりせず、同じ話者で再合成する。
        path=Path(row['file']).with_name(Path(row['file']).stem+'_short.wav')
        host=solo_host.for_segments([seg],seg['speaker'])
        if host == 'ui':
            raise PreviewVoiceUnavailable('雨衣の短縮はrunnerで再合成せず別のめたん回へ作り直します')
        ok=sn.synth_one(text,seg['speaker'],path)
        if not ok:raise ValueError('短縮原稿の音声合成に失敗しました')
        actual=sn.audio_duration(path)
        if actual<=0:raise ValueError('短縮音声の実測尺がありません')
        seg['text']=text
        row.update(text=text,file=str(path),duration=actual)
        print(f"[shorten] 試合{seg['meta'].get('game_id','')}: 補足を削除、音声{actual:.3f}秒")

    # 対戦・時刻の最初の文を必ず残し、補足を文単位で後ろから落とす。
    for index in reversed(range(len(segments))):
        if segments[index]['kind']!='preview':continue
        sentences=re.findall(r'[^。！？]+[。！？]?',segments[index]['text'])
        # 履歴に期待選手を残すなら、その氏名と成績の文も読み上げに残す。
        required=1
        if (segments[index]['meta'].get('interest') or {}).get('player'):
            for i,sentence in enumerate(sentences):
                if sentence.startswith('期待選手は'):required=min(len(sentences),i+2)
        while len(sentences)>required:
            sentences.pop();rewrite(index,''.join(sentences))
            if fits():return
            # 1試合10秒の表示下限まで縮んだら、それ以上削っても全尺は減らない。
            if video_times([segments[index]],[audio[index]])[0]<=10:break
    for count in (4,3):
        indices=[i for i,s in enumerate(segments) if s['kind']=='preview']
        if len(indices)>=count:
            index=indices[-1];ident=segments[index]['meta'].get('game_id','')
            del segments[index];del audio[index]
            plan['narration']['preview_length_adjustment']=dict(
                original_ids=original_ids,kept_ids=[s['meta'].get('game_id') for s in segments if s['kind']=='preview'])
            print(f'[shorten] {count}試合目を除外: {ident}')
            if fits():return
    # 異常に長い声でも長さだけを理由に全体を落とさない。最後の1試合は残す。
    indices=[i for i,s in enumerate(segments) if s['kind']=='preview']
    if len(indices)>1:
        index=indices[-1];del segments[index];del audio[index]
        plan['narration']['preview_length_adjustment']=dict(
            original_ids=original_ids,kept_ids=[s['meta'].get('game_id') for s in segments if s['kind']=='preview'])
        print('[shorten] 緊急短縮: 先頭の1試合を残す')
        if fits():return
    for kind in ('outro','cover'):
        for index in reversed(range(len(segments))):
            if segments[index]['kind']==kind:
                del segments[index];del audio[index]
                print(f'[shorten] 緊急短縮: {kind}を除外')
        if fits():return
    # 対戦名が極端に長い場合は画面に残し、音声は短い導入にする。
    index=next(i for i,s in enumerate(segments) if s['kind']=='preview')
    rewrite(index,'注目の一戦です。')
    meta=segments[index]['meta']
    if meta.get('interest'):
        meta['interest']['player']=None
        meta.pop('expectation_name',None)
        audio[index]['meta']=json.loads(json.dumps(meta))


def render_video(plan,audio,out,audio_dir=None):
    __import__('slant_by_episode').set_episode('soccer_'+plan['mode'])
    narr=plan['narration'];times=video_times(narr['segments'],audio)
    import render_timeline
    timeline=render_timeline.Recorder(30,audio,narr)
    limit=narr['duration_budget']['limit']
    if motion.enabled():
        motion.measured(audio)
    if sum(times)>limit:raise ValueError(f'丸め後{limit}秒を超える')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    import short_content
    short_content.require(narr, times, out, plan.get('data'), maximum=limit, video_name=FILENAMES[plan['mode']])
    if not shutil.which('ffmpeg'):raise ValueError('FFmpegがありません。install_video_tools.shまたは保存材料のpreviewを使ってください')
    track=vc.build_narration_track(audio,times,out)
    if not track:raise ValueError('声がありません')
    video=out/FILENAMES[plan['mode']];images=[];previous=None;clock=0
    cmd=['ffmpeg','-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','30','-i','-','-i',str(track),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-t',str(sum(times)),'-movflags','+faststart',str(video)]
    with (out/'ffmpeg.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        try:
            for i,(seg,duration) in enumerate(zip(narr['segments'],times)):
                timeline.select(audio[i],i)
                r3.set_caption(seg['text'],duration,sum(times),speaker=2,duo=False,hide_caption=seg['kind']=='outro')
                snap=min(3,duration*.6) if seg['kind']=='outro' else min(1.4,duration*.6)
                r3.set_program_clock(clock+snap);im=frame(snap,seg,plan)
                errors=check_frame(im,plan)
                if errors:
                    import hashlib
                    (out/'layout_hold.json').write_text(json.dumps(dict(status='held', scene=i,
                        segments_sha256=hashlib.sha256(json.dumps(narr['segments'], ensure_ascii=False,
                            sort_keys=True).encode()).hexdigest(),
                        errors=errors), ensure_ascii=False, indent=2)+'\n', encoding='utf8')
                    raise ValueError(f'画面{i}: {errors}')
                im.save(out/f'{i+1:02d}.png');images.append(im)
                for k in range(round(duration*30)):
                    r3.set_program_clock(clock+k/30);im=frame(k/30,seg,plan)
                    timeline.write(proc.stdin,soccer_look.transition(previous,im,k,30),im)
                previous=im.tobytes();clock+=duration
        finally:proc.stdin.close();code=proc.wait();r3.set_program_clock(None)
    if code:raise ValueError('動画生成失敗。ffmpeg.logを確認')
    timeline.save(video,audio_dir or next((Path(s['file']).parent for s in audio if s.get('file')),out))
    from preview_unified_v3 import sheet
    sheet(images,[s['kind'] for s in narr['segments']],out/'all-screens.png',columns=4)
    probe=subprocess.run(['ffmpeg','-hide_banner','-i',str(video)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    m=re.search(r'Duration: (\d+):(\d+):([\d.]+)',probe.stderr)
    if not m:raise ValueError('動画の実測尺なし')
    seconds=int(m[1])*3600+int(m[2])*60+float(m[3])
    if seconds>limit:raise ValueError(f'実動画{limit}秒超過')
    report=dict(mode=plan['mode'],seconds=seconds,title=narr['title'],screens=len(images),layout_badges_numbers='PASS',publication='not performed')
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return report


def run_compat(mode,path,narration_out=None,audio_dir=None,out=None,narration_path=None):
    data=json.loads(Path(path).read_text(encoding='utf-8'));plan=program(mode,data);narr=plan['narration']
    if not narr['segments']:print('この日は対象の材料がないため作りません');return
    if narration_out:
        target=Path(narration_out);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return
    import host_split
    if host_split.enabled():
        narr = host_split.use_audio(narr, audio_dir)
        plan['narration'] = narr
        host_split.render_audio(audio_dir, out, narration_path)
    if narration_path:
        supplied=json.loads(Path(narration_path).read_text(encoding='utf-8'))
        if supplied!=narr:raise ValueError('原稿が現在の材料と違う')
    manifest_path=Path(audio_dir)/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));audio=manifest['segments']
    original=json.loads(json.dumps(narr))
    rebuilt_after_hold = False
    try:
        fit_preview(plan,audio)
    except PreviewVoiceUnavailable:
        # 短縮途中の原稿を引き継がず、話者切替前の全文から全音声を作る。
        plan['narration'] = original
        audio, audio_dir, manifest = rebuild_preview_metan(plan, audio_dir, narration_path)
        narr = plan['narration']
        manifest_path = Path(audio_dir)/'manifest.json'
        os.environ['COLLESPO_SOLO_HOST'] = 'metan'
        host_split.render_audio(audio_dir, out, str(Path(audio_dir)/'narration.json'))
        before = os.environ.get('COLLESPO_SOLO_HOST')
        try:
            os.environ['COLLESPO_SOLO_HOST'] = 'metan'
            fit_preview(plan, audio)
        finally:
            if before is None: os.environ.pop('COLLESPO_SOLO_HOST', None)
            else: os.environ['COLLESPO_SOLO_HOST'] = before
        rebuilt_after_hold = True
    if narr!=original:
        if rebuilt_after_hold:
            Path(manifest.get('narration_path', Path(audio_dir)/'narration.json')).write_text(
                json.dumps(narr, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        __import__('voice_manifest').save(audio_dir, audio, narr)
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        # 日次の後続処理（表紙・説明欄）も実際に読んだ原稿を使う。
        saved=Path(narration_path) if narration_path else Path(audio_dir).parent/'soccer_narration.json'
        if rebuilt_after_hold or (saved.is_file() and json.loads(saved.read_text(encoding='utf-8'))==original):
            saved.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        target=Path(out)/'narration.json';target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    render_video(plan,audio,out)
    host_split.bind_video(Path(out)/FILENAMES[mode], audio_dir)
    return 0
