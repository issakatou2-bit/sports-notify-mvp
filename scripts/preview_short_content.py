"""保存材料の種類別確認版。音声は合成しない。実際の既存札と字幕を動画にする。"""
import argparse
import copy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def episodes(saved):
    os.environ.update(COLLESPO_SHORT_LOOK='v4', COLLESPO_SOCCER_LOOK='v6',
                      COLLESPO_PS_DESIGN='v3', COLLESPO_PLAYERS_DESIGN='bignumber',
                      COLLESPO_COMMENTS_DESIGN='comments', COLLESPO_PRESS_DESIGN='v3',
                      COLLESPO_DUO='off', COLLESPO_HOST_SPLIT='off', COLLESPO_SOLO_HOST='metan')
    import short_saved_render
    short_saved_render.setup()
    import ps_program as ps
    import ps_unified_v3 as unified
    import generate_morning_short as morning
    import bignumber_render as bn
    import daily_v3
    import generated_topics
    import generate_asset_video as asset
    import soccer_slots_v4 as slots
    import soccer_results_render as results
    import soccer_now
    bn._no_network()
    audit = saved/'build/channel-audit-20261014'
    snapshot = read(audit/'data_postseason.json')
    evidence = read(audit/'preview/ps_forecast_source.json')
    for slot, key in (('forecast','daily'), ('situation','morning_postseason')):
        ledger = {} if slot == 'forecast' else dict(morning_postseason={'saved':dict(
            video_id='saved-preview', program_version=ps.VERSION, program_series=snapshot['series'])})
        program = ps.prepare(snapshot, evidence, slot, datetime.fromisoformat(evidence['retrieved_at']), ledger)
        if slot == 'situation':
            # 最終1組だけになった日の保存済みWS資料。日程原応答の代わりに、
            # 既存の最終スコア資料から同じ欄だけを再構成する（公開用ではない）。
            current = read(ROOT/'data/postseason.json')
            ctx = current['editorial']
            active = [r for r in current['series'] if not r.get('over') and len(r.get('teams', [])) == 2]
            if len(active) == 1:
                topic = read(ROOT/'data/ps_game_topics.json')['topics'][0]
                score = topic['game_v4']['score']
                game = dict(gamePk=topic['game_pk'],gameType=active[0]['round'],gameDate=topic['game_date'],
                    seriesGameNumber=active[0]['played'],status=dict(abstractGameState='Final'),
                    teams={side:dict(team=dict(id=score[side]['id']),score=score[side]['total']) for side in ('home','away')})
                program = ps.situation_program(ctx,current['series'],dict(program_series=current['series']))
                program = ps.previous_short_context(program,ctx,[game],current['series'])
                import review_render_v3
                card = dict(ps.common(ctx,'コレスポ'),layout='facts',headline='コレスポ',items=[],outro=True,lineup_kind='postseason')
                ending = ps.segment(card,review_render_v3.OUTRO_TEXT);ending['kind']='outro'
                program['segments'].append(ending)
                program.update(kind='morning_postseason',date_jst=ctx['date_jst'],source_url=ctx['source_url'])
                ps.apply_design(program)
        if not program:
            raise ValueError('保存PS材料がありません: '+slot)
        lead, ticker = unified.lead_card(program), unified.program_ticker(program)
        def draw(t, seg, duration, lead=lead, ticker=ticker, program=program):
            return unified.frame(t, seg['meta']['card'], lead, cover=seg is program['segments'][0], duration=duration, ticker_line=ticker)
        yield key, program, {}, draw, 60, str(audit.relative_to(saved))
    data = read(ROOT/'scripts/fixtures/bignumber/morning_recap.json')
    data['players'] = morning.sort_players(data['players'])
    narr = morning.build_narration(data, 'players')
    scenes = bn.scenes_from_morning(data, narr)
    def draw_player(t, seg, duration):
        index = next(i for i,s in enumerate(narr['segments']) if s is seg)
        return bn.scene(t, dict(scenes[index], dur=duration))
    yield 'morning', narr, data, draw_player, 45, 'scripts/fixtures/bignumber/morning_recap.json'
    for mode, filename in (('press','local_reporters-preview.json'), ('voices','local_voices-preview.json')):
        material = read(ROOT/'scripts/fixtures/comment'/filename)
        if mode == 'voices':
            # 長い返信枝を選ばず、保存した親コメントを3件。発言は書き換えない。
            material = copy.deepcopy(material)
            material['voices'] = material['voices'][:3]
            for row in material['voices']:
                row.update(reply_ja=[], reply_texts=[], replies=0, is_thread=False)
        data = dict(players=[], date_jst=material['updated_at'][:10], **{mode if mode=='voices' else 'reporters':material})
        narr = morning.build_narration(data, mode)
        design = daily_v3.prepare(data, narr, mode)
        yield 'morning_'+mode, narr, data, lambda t,s,d,design=design:daily_v3.frame(t,s,design,d), 61, 'scripts/fixtures/comment/'+filename
    for mode, path in (('preview','scripts/fixtures/soccer-daily/20261026.json'),
                       ('race','data/soccer_race.json'), ('week','data/soccer_jp_week.json')):
        data = read(ROOT/path)
        if mode == 'week':
            # 40秒内で個人の公式成績まで読める2試合。15人の名簿を急いで流さない。
            data['rows'] = [row for row in data['rows'] if row['league']=='PL'][:2]
        plan = slots.program(mode, data)
        yield 'daily_soccer' if mode=='preview' else 'soccer_'+mode, plan['narration'], data, lambda t,s,d,plan=plan:slots.frame(t,s,plan), plan['narration']['duration_budget']['limit'], path
    cases = read(ROOT/'scripts/fixtures/soccer-stats/saved-cases.json')['cases']
    for kind, index in (('soccer_results',1), ('soccer_goal_short',2), ('soccer_now',0)):
        data = copy.deepcopy(cases[index]['data'])
        if kind == 'soccer_now':
            data.update(voices=[], video_url='', sample_fictional=False)
            narr = soccer_now.narration(data)
            draw = lambda t,s,d,data=data:soccer_now.frame(data,t,s)
            limit = 40
        else:
            narr = results.production_narration(data, goal_short=kind=='soccer_goal_short')
            clubs = __import__('soccer_result_story').clubs_for(data)
            draw = lambda t,s,d,data=data,clubs=clubs:results.frame(t,s,data,clubs)
            limit = 60
        yield kind, narr, data, draw, limit, 'scripts/fixtures/soccer-stats/saved-cases.json case '+str(index)
    topics = generated_topics.all_topics()
    for path in (saved/'build/channel-audit-20261016/data_ps_story_topics.json',):
        if path.exists():
            topics.update({s['key']:s for s in read(path)['topics']})
    choices = [('asset_game','season_game_849804'), ('asset_player','season_player_660271'),
               ('asset_team','season_team_119'), ('asset_league','season_league_103_hitting'),
               ('asset_story','season_story_L_119_158'), ('asset_venue','venue_american_family_field'),
               ('asset_rare','rare_808967'), ('asset_legend','legend_158'), ('asset_ws','ws_schedule')]
    for kind, topic in choices:
        spec = copy.deepcopy(topics.get(topic) or {})
        if not spec:
            raise ValueError('保存した資産材料なし: '+topic)
        # この確認は事実の補足。引用を事実の増量として使わない。
        spec['items'] = [row for row in spec.get('items', []) if not any(x in row[0] for x in ('コメント','見出し','番記者'))]
        spec['voice'] = None
        spec['headline'] = None
        if kind == 'asset_team':
            # 1本に収まる主事実＋補足2件。残りはこの確認版の対象外。
            spec['items'] = spec['items'][:3]
            spec['stars'] = []
            spec['japanese'] = []
        if kind == 'asset_ws':
            # 非公開の旧回を使わず、保存済みの訂正版日程で3つの開催区間を確認。
            spec['items'] = spec['items'][:3]
        asset.LIST_TOPICS[topic] = spec
        narr = asset.build_narration(topic)
        # main()と同じ話者と表記。別種類を続けて作る際も前のクレジットを持ち越さない。
        for seg in narr['segments']:
            seg.setdefault('speaker', asset.METAN if spec.get('style') == 'v3' else 3)
        import duo
        credit = duo.credit(narr['segments'])
        def draw_asset(t, seg, duration, spec=spec, topic=topic, credit=credit):
            asset.VOICE_CREDIT = credit
            if spec.get('style') == 'v3':
                return asset.render_v3(t,seg['kind'],seg['meta'],spec,topic,seg=seg,dur=duration)
            p = min(1,t/asset.ANIM_END)
            if spec.get('style') == 'v2':
                return asset.render_v2(p,seg['kind'],seg['meta'],spec,topic)
            if seg['kind'] == 'intro':
                return asset.render_intro(p,spec['label'],asset.hook_for(topic,spec['label']))
            if seg['kind'] == 'outro':
                return asset.render_outro(p)
            if seg['kind'] == 'map':
                return asset.render_map(p,spec)
            if seg['kind'] == 'people':
                return asset.render_people(p,spec.get(seg['meta'].get('group','japanese')) or [],seg['meta'].get('heading',''))
            items = asset.list_items(topic)
            start, count = seg['meta'].get('start',0), seg['meta'].get('count',1)
            return asset.render_list(p,items,start,count,start//2+1,math.ceil(len(items)/2),spec.get('heading',''))
        yield kind, narr, spec, draw_asset, 61, '保存した公式生成材料: '+topic


def times(narr, data=None, key=''):
    """音声未合成の読む速さの仮見積り。28秒へ合わせる定数・無音は足さない。"""
    result = [math.ceil(max(1.5, len(s.get('text',''))/6+.3)*30)/30 for s in narr['segments']]
    if key.startswith('soccer_') or key == 'daily_soccer':
        from soccer_readable import minimum_seconds
        result = [max(t,minimum_seconds(seg,data)) for t,seg in zip(result,narr['segments'])]
    return result


def frame_checks(image, kind):
    """各既存描画の検査を使用。旧形式の未記録を合格と呼ばない。"""
    if not image.info.get('v3_layout'):
        return dict(mode='未実施（旧描画の矩形記録なし）', errors=[], spacing_candidates=[])
    if image.info.get('soccer_readable'):
        import soccer_readable
        import soccer_v4_cards
        return dict(mode='soccer_readable',errors=soccer_readable.check_frame(image,soccer_v4_cards.load_clubs()),spacing_candidates=[])
    import v3_rules
    return dict(mode='v3',errors=v3_rules.check_layout(image),
                spacing_candidates=[] if kind=='outro' else v3_rules.check_spacing(image))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--only')
    parser.add_argument('--resume', action='store_true', help='同じ保存原稿で一覧まで完成した種類を再利用')
    args = parser.parse_args()
    import short_content
    # 描画モジュールのLOOK確定前に episodes を起動する。
    # 実描画時は下の import を再取得（同じモジュール）する。
    inventory = []
    for key, narr, data, draw, limit, source in episodes(args.saved_root):
        import review_render_v3 as r3
        if args.only and key != args.only:
            continue
        durations = times(narr,data,key)
        out = args.out/key; out.mkdir(parents=True, exist_ok=True)
        reusable = (args.resume and (out/'narration.json').exists() and read(out/'narration.json') == narr
                    and (out/'plan.json').exists() and read(out/'plan.json').get('durations') == durations
                    and (out/'capture/video/preview-manifest.json').exists() and (out/'preview.mp4').exists())
        write(out/'narration.json', narr)
        write(out/'material.json', data)
        report = short_content.assess(narr, durations, data, maximum=limit)
        report.update(kind=key, source=source, voice='未合成。6字/秒の字幕確認用。実音声の尺は未確認', durations=durations)
        write(out/'plan.json', report)
        inventory.append(report)
        print(json.dumps(dict(kind=key, seconds=report['planned_seconds'], information=report['information_count'], status=report['status'], reasons=report['reasons']), ensure_ascii=False), flush=True)
        if args.prepare_only:
            continue
        if reusable:
            print(key+' 同じ原稿の完成確認版を保持',flush=True)
            continue
        if report['status'] != 'passed':
            raise ValueError(key+'の確認版を作れません: '+str(report['reasons']))
        import imageio_ffmpeg
        # 既存の札・字サイズ・字幕で頭/本文/終わりを作り、文字の読む長さだけ表示。
        # 公開器に渡せる合格記録は作らない（実音声が未合成のため）。
        timeline = []; clock = 0; paths = []; layouts = []
        for i, (seg,duration) in enumerate(zip(narr['segments'],durations)):
            r3.set_caption(seg.get('text',''), duration, sum(durations), speaker=seg.get('speaker',2), duo=False,
                           hide_caption=seg['kind']=='outro', caption_units=seg.get('caption_units'))
            # 各段の頭・中・終わりの状態。引用/字幕の後半も確認版に必ず含める。
            middle = duration*.5
            if key == 'daily' and (seg.get('meta') or {}).get('card',{}).get('card_index') is not None:
                # 2ページの境界そのものを静止保持せず、札の入り終わった状態を採る。
                middle = min(duration-.25, middle+1.2)
            for j, at in enumerate((min(1.2,duration*.2), middle, max(0,duration-.25))):
                r3.set_program_clock(clock+at)
                image = draw(at,seg,duration)
                check = frame_checks(image,seg['kind'])
                path = out/f'{i:02d}-{j}.png'; image.save(path)
                if check['errors']:
                    raise ValueError(f'{key} 段{i} 時刻{at}: {check["errors"]}')
                layouts.append(dict({k:image.info[k] for k in ('v3_layout','duo_portraits','v3_outro','duo_caption') if k in image.info},**check))
                image.close()
                paths.extend(["file '"+path.resolve().as_posix()+"'", f'duration {duration/3:.8f}'])
            timeline.append(clock); clock += duration
        paths.append("file '"+path.resolve().as_posix()+"'")
        (out/'frames.txt').write_text('\n'.join(paths)+'\n',encoding='utf8')
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        with (out/'ffmpeg.log').open('w',encoding='utf8') as log:
            subprocess.run([ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i',str(out/'frames.txt'),
                '-vf','fps=30','-t',str(clock),'-c:v','libx264','-threads','2','-preset','veryfast','-crf','23',
                '-pix_fmt','yuv420p','-movflags','+faststart',str(out/'preview.mp4')],check=True,stderr=log)
        write(out/'timeline.json',dict(cuts=timeline+[clock],duration=clock))
        write(out/'verification.json',dict(frames=layouts, voice='未合成', publication='not performed'))
        r3.set_program_clock(None)
        # 指定の正式な一覧取り出し器を使う（実行環境にFFmpegを一時的に追加）。
        import soccer_results_render
        soccer_results_render.ensure_ffmpeg(out)
        subprocess.run([sys.executable,str(ROOT/'scripts/visual_capture.py'),'video','--video',str(out/'preview.mp4'),
            '--timeline',str(out/'timeline.json'),'--out',str(out/'capture')],check=True)
    write(args.out/'inventory.json', inventory)


if __name__ == '__main__':
    main()
