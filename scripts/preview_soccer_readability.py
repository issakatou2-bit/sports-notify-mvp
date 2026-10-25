"""保存した直近材料による静止画監査と配置案。制作・公開の入口には接続しない。

python scripts/preview_soccer_readability.py --out build/soccer-look-20261025
音声・通信・動画エンコードなし。プロセス内の表示設定だけを固定する。
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(relative, revision=None):
    raw = (subprocess.check_output(['git', 'show', f'{revision}:{relative}'], cwd=ROOT)
           if revision else (ROOT / relative).read_bytes())
    return json.loads(raw.decode('utf-8-sig'))


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sources():
    """公開台帳と保存履歴から選ぶ。架空データや当日への日付置換は使わない。"""
    import soccer_slots_v4 as slots
    import soccer_results_render as result
    import soccer_result_story as story
    cases = []
    for key, mode, relative, revision, day in [
        ('preview', 'preview', 'data/soccer_games.json', 'a8186c0f', '2026-10-21'),
        ('race', 'race', 'data/soccer_race.json', None, '2026-10-25'),
        ('week', 'week', 'data/soccer_jp_week.json', None, '2026-10-15'),
    ]:
        data = read(relative, revision or '8a78a84b')
        # 追加の現在成績を混ぜず、保存当時の成績・注目理由を使う。
        if mode == 'preview':
            import soccer_match_interest as interest
            from unittest.mock import patch
            availability = read('data/soccer_availability.json', revision)
            attach = interest.attach_season_stats
            with patch.object(interest, 'attach_season_stats', side_effect=lambda d: attach(d, availability)):
                plan = slots.program(mode, data)
        else:
            plan = slots.program(mode, data)
        cases.append(dict(key=key, day=day, data=data, plan=plan, clubs=plan['clubs'],
                          narration=plan['narration'], source=relative, revision=revision or '8a78a84b',
                          draw=lambda t, seg, p=plan: slots.frame(t, seg, p)))
    data = read('data/soccer_results.json', '8a78a84b')
    cases.insert(0, dict(key='results', day=data['date_jst'], data=data,
                        clubs=story.clubs_for(data), narration=result.production_narration(data),
                        source='data/soccer_results.json', revision='8a78a84b',
                        draw=lambda t, seg, d=data: result.frame(t, seg, d, story.clubs_for(d))))
    revision = '41eefcba367428d7ccd417eac1a4dd9763e07ae3'
    data = read('data/soccer_results.json', revision)
    lead = next(p for p in data['players'] if p.get('goals') or p.get('assists'))
    data = copy.deepcopy(data)
    data['games'] = [g for g in data['games'] if g['id'] == lead['event_id']]
    data['players'] = [p for p in data['players'] if p['event_id'] == lead['event_id']]
    data.pop('preview_followup', None)
    clubs = result.resolve_clubs(data)
    cases.append(dict(key='goal', day=data['date_jst'], data=data, clubs=clubs,
                      narration=result.production_narration(data, goal_short=True),
                      source='data/soccer_results.json', revision=revision,
                      note='速報の公開記録なし。最新の保存済み日本人得点試合を速報入口で再描画。',
                      draw=lambda t, seg, d=data, c=clubs: result.frame(t, seg, d, c)))
    return cases


def intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def metrics(im):
    import soccer_v5_cards as c
    entries = im.info.get('v3_layout', [])
    original_entries=entries
    if im.info.get('motion'):
        motion=im.info['motion']
        # motionは中央を別の画像で置換する。元v3_layoutは最終画素の測定に使えない。
        entries=[e for e in entries if e['role'] in ('header','source','caption','ticker')]
        entries += [dict(role='text',box=list(e['box']),text=e['text'],v5_font=e['size'],
                         v5_color=(242,243,228)) for e in motion['texts']]
        entries.append(dict(role='text',box=[96,260,916,296],text=im.info.get('readability_motion_heading','一覧見出し'),
                            v5_font=36,v5_color=(242,243,228)))
    text = [e for e in entries if e.get('text') and e['role'] not in ('card', 'team_badge', 'decoration')]
    body = [e for e in text if e['role'] not in ('header', 'source', 'ticker', 'caption', 'badge')]
    fonts = [e.get('v5_font', e.get('v4_font')) for e in body]
    fonts = [v for v in fonts if v is not None]
    overlapping = []
    for i, first in enumerate(body):
        for second in body[i+1:]:
            if intersects(first['box'], second['box']):
                overlapping.append([first['text'], second['text']])
    yrows = sorted({round(e['box'][1]) for e in body})
    gaps = [(b-a, a, b) for a, b in zip(yrows, yrows[1:])]
    badges = im.info.get('v5_contrasts', [])
    contrasts = []
    for e in body:
        rgb = e.get('v5_color', e.get('v4_color'))
        if rgb:
            x,y,right,bottom=map(round,e['box'])
            crop=im.crop((max(0,x-3),max(0,y-3),min(im.width,right+3),min(im.height,bottom+3)))
            pixels=Counter(crop.get_flattened_data() if hasattr(crop,'get_flattened_data') else crop.getdata())
            # 字色に近いアンチエイリアス画素を除いた最多色を背景として記録。
            # クラブ色で塗ったスコア札を、暗い地の色と誤比較しない。
            bg=next((p for p,n in pixels.most_common() if sum(abs(a-b) for a,b in zip(p,rgb))>30),c.BOARD)
            contrasts.append(dict(text=e['text'], ratio=round(c.contrast(rgb,bg),2),foreground=rgb,background=bg))
    return dict(body_text_count=len(body), body_font_min=min(fonts, default=None),
                body_font_max=max(fonts, default=None), body_text=body,
                max_text_top_gap=max(gaps, default=(0, 0, 0)),
                overlap_pairs=overlapping, body_contrasts=contrasts,
                badge_min_contrast=None if im.info.get('motion') else round(min((x['text_ratio'] for x in badges), default=0), 2),
                visible_badges=0 if im.info.get('motion') else len(im.info.get('v4_badges',[])),
                overwritten_by_motion=bool(im.info.get('motion')),original_entry_count=len(original_entries),
                caption=im.info.get('duo_caption'), portraits=im.info.get('duo_layer', []),
                entries=entries)


class Proposal:
    """既存の字・札・キャラを使用。中央の内容部分だけを描き直す見本。"""
    def __init__(self, case, variant):
        import soccer_v5_cards as c
        self.c, self.case, self.variant = c, case, variant
        self.clubs = case['clubs']
        self.im = c.canvas(3, self.clubs, '欧州サッカー')
        self.im.info['readability_proposal'] = variant
        self.im.info['semantic_items'] = []

    def txt(self, x, y, value, size=36, width=800, color=None, number=False, role='text'):
        if self.c.screen_text(value,number)!=str(value):
            raise ValueError('表示字体にない文字を省略しません: '+str(value))
        return self.c.text(self.im, x, y, value, size, color or self.c.CHALK,
                           width=width, number=number, role=role, minimum=size)

    def panel(self, y, bottom, fill=None, x=72, right=940):
        # 垂直の揃えを優先。札だけは既存のマフラー形をそのまま使う。
        from PIL import ImageDraw
        ImageDraw.Draw(self.im).rounded_rectangle((x, y, right, bottom), radius=12, fill=fill or self.c.BOARD)
        self.c.rec(self.im, 'card', (x, y, right, bottom))

    def name(self, x, y, club, width=630, size=38, compact=False):
        c = self.c
        club = copy.deepcopy(self.clubs[club])
        name = c.club_display_names.display(club,short=compact)
        if not club.get('primary') and c.screen_text(club['abbr'],True)!=club['abbr']:
            # 未登録の色・略称を推測しない。日本語を数字字体に渡して空札にしない。
            club['abbr']='?'
            self.im.info['unknown_club_badge']=True
        self.im.info['semantic_items'].append(name)
        h=c.measure(name,size)[2][3]-c.measure(name,size)[2][1]
        badge_w = c.tag_width(club,h)
        # 名前の文字サイズを縮めず、最大2行。クラブ名の札は先頭に一度。
        rows = c.lines(name, size, width-badge_w-16)
        if len(rows) > 2:
            raise ValueError('クラブ名に次ページが必要: '+name)
        for i, row in enumerate(rows):
            c.club_name(self.im,x,y+i*(size+6),club,size,width=width,display_name=row)
        return max(size+6, len(rows)*(size+6))

    def title(self, main, sub=''):
        rows = self.c.lines(main, 44, 868)
        if len(rows) > 2: raise ValueError('見出しが長すぎます')
        for i, row in enumerate(rows): self.txt(72, 262+i*54, row, 44, 868)
        if sub: self.txt(72, 262+len(rows)*54+14, sub, 28, 868, self.c.MUTED)
        return 262+len(rows)*54+66

    def end(self, spec):
        # 本文は完全に停止。演出案は0.35秒のフェードインのみ（動画未制作）。
        self.im.info['proposal_motion'] = dict(name='フェードイン', seconds=.35, hold=True)
        return self.c.finish(self.im, 3, spec)

    def standings(self, spec):
        c = self.c
        # 大会名と境界の意味を別行にして、タイトルの横長縮小を止める。
        title = spec['title'].split('　')
        y = self.title(title[0], '　'.join(title[1:]))
        rows = {r['position']:r for r in spec['rows']}
        shown = [p for a,b in spec['shown'] for p in range(a,b+1) if p in rows]
        labels = dict(spec.get('lines', []))
        height = 132 if self.variant == 'A' else 144
        self.txt(94, y, '順位', 26, 90, c.MUTED)
        self.txt(210, y, 'クラブ', 26, 440, c.MUTED)
        self.txt(744, y, '試合', 26, 70, c.MUTED)
        self.txt(844, y, '勝点', 26, 80, c.MUTED)
        y += 42
        for p in shown:
            row=rows[p]; self.panel(y,y+height-10)
            self.txt(94,y+22,p,48 if self.variant=='A' else 58,84,number=True)
            self.name(188,y+24,row['team'],528,38)
            self.txt(752,y+22,row['played'],42,62,c.MUTED,True)
            self.txt(844,y+14,row['points'],60 if self.variant=='A' else 76,74,c.LIME,True)
            y += height
            if p in labels:
                from PIL import ImageDraw
                color=c.LINE_COLORS.get(c.original._line_kind(labels[p]),c.MUTED)
                ImageDraw.Draw(self.im).line((72,y-4,940,y-4),fill=color,width=3)
                self.txt(94,y+6,labels[p],28,800,color);y+=44
        if spec.get('gap'):
            self.panel(y+8,y+88)
            self.name(94,y+22,spec['focus'],380,30)
            self.txt(500,y+24,spec['gap'],30,410,c.LIME)
        return self.end(spec)

    def preview_overview(self):
        """現行motionが表示する全カードを残す。詳細1カードへの取り違えを避ける。"""
        c=self.c
        specs=[s['meta'] for s in self.case['narration']['segments'] if s['kind']=='preview']
        if len(specs)>4:raise ValueError('予告は次ページが必要です')
        days=list(dict.fromkeys(s['date'] for s in specs))
        leagues=list(dict.fromkeys(s['league'] for s in specs if s['league']))
        self.title('注目試合の予告',' / '.join(days)+'　'+' / '.join(leagues))
        for i,s in enumerate(specs):
            if self.variant=='A':
                y=398+i*170;self.panel(y,y+158)
                self.name(102,y+22,s['home'],610,38)
                self.name(102,y+88,s['away'],610,38)
                self.txt(754,y+28,s['time'],62,160,number=True)
                self.txt(754,y+88,'日本時間',26,150,c.MUTED)
            else:
                x=72+(i%2)*446;y=398+(i//2)*354;right=x+422
                self.panel(y,y+338,x=x,right=right)
                self.txt(x+24,y+20,s['time'],76,374,number=True)
                self.txt(x+24,y+96,'日本時間',26,374,c.MUTED)
                self.name(x+24,y+146,s['home'],374,34,compact=True)
                self.name(x+24,y+238,s['away'],374,34,compact=True)
        self.im.info['semantic_items'].extend(s['time'] for s in specs)
        if self.im.info.get('unknown_club_badge'):
            self.txt(72,1100,'灰色の ? はクラブ色・略称が未確認',26,620,c.MUTED)
        return self.end(specs[0])

    def roster(self, spec):
        c = self.c
        self.title(spec['title'])
        rows=spec['rows'];top=352
        if len(rows)>7:raise ValueError('一覧は次ページに分ける必要があります')
        # Aは列を固定、Bは数字の組を独立させ、どちらも全件を保持。
        for i,row in enumerate(rows):
            y=top+i*102;self.panel(y,y+96)
            self.txt(94,y+12,row['name'],34,300)
            self.name(94,y+54,row['club'],348,28)
            if row.get('note'):
                # 不明・離脱を消さない。二行の固定字サイズ。
                note=self.c.lines(row['note'],28,438)
                for j,line in enumerate(note):self.txt(474,y+18+j*36,line,28,438,c.MUTED)
            else:
                for j,(value,unit) in enumerate(row.get('values',[])):
                    x=478+j*145
                    self.txt(x,y+14,value,50 if self.variant=='A' else 60,100,c.LIME,True)
                    self.txt(x+58 if self.variant=='A' else x+76,y+34,unit,28,64,c.CHALK)
        return self.end(spec)

    def match(self, seg):
        c=self.c;data=self.case['data'];game=next(g for g in data['games'] if g['id']==seg['meta']['event_id'])
        import soccer_result_facts as facts
        self.title('試合結果',facts.competition(game)+'　試合終了')
        if self.variant=='A':
            for side,y in [('home',420),('away',600)]:
                self.panel(y,y+154)
                self.txt(102,y+18,'ホーム' if side=='home' else 'アウェー',26,200,c.MUTED)
                self.name(102,y+68,game[side]['name_jp'],630,42)
                self.txt(818,y+28,game['score'][side],102,96,c.LIME,True)
        else:
            self.panel(420,774)
            self.name(102,456,game['home']['name_jp'],790,44)
            self.txt(102,536,str(game['score']['home'])+' - '+str(game['score']['away']),150,690,c.LIME,True)
            self.name(102,680,game['away']['name_jp'],790,44)
        people=[p for p in game['players'] if p['status']!='none']
        height=52+sum(len(c.lines(facts.player_line(p).rstrip('。'),38,808))*50 for p in people)
        top=914 if height<=152 else 818
        self.panel(top,top+height)
        y=top+26
        for p in people:
            value=facts.player_line(p).rstrip('。')
            rows=c.lines(value,38,808)
            for line in rows:self.txt(102,y,line,38,808);y+=50
            self.im.info['semantic_items'].append(value)
        if y>1110:raise ValueError('選手の情報は次ページが必要です')
        return self.end(__import__('soccer_results_render').program_spec(data))

    def goal(self, seg):
        data=self.case['data'];c=self.c
        person=next(p for p in data['players'] if p.get('goals') or p.get('assists'))
        game=data['games'][0]
        self.title(person['name']+'の試合結果',game['league_jp'])
        value=person['goals'] if person.get('goals') else person['assists']
        unit='得点' if person.get('goals') else 'アシスト'
        if self.variant=='A':
            self.panel(406,734)
            self.name(102,432,person['club'],790,42)
            self.txt(102,522,value,246,300,c.LIME,True)
            self.txt(340,614,unit,48,500)
            for side,y in [('home',766),('away',926)]:
                self.panel(y,y+150)
                self.name(102,y+32,game[side]['name_jp'],634,42)
                self.txt(818,y+18,game['score'][side],106,96,c.LIME,True)
        else:
            self.panel(406,1016)
            self.name(102,432,person['club'],790,42)
            self.txt(102,500,str(value)+unit,60,790,c.LIME)
            self.name(102,610,game['home']['name_jp'],790,42)
            self.txt(102,704,str(game['score']['home'])+' - '+str(game['score']['away']),246,790,c.LIME,True)
            self.name(102,914,game['away']['name_jp'],790,42)
        return self.end(__import__('soccer_results_render').program_spec(data))


def caption(seg, duration=12):
    import review_render_v3 as r3
    r3.set_program_clock(0)
    r3.set_caption(seg['text'],duration,60,speaker=seg.get('speaker',2),
                   hide_caption=seg['kind']=='outro',caption_units=seg.get('caption_units'))
    r3.set_program_clock(3)


def render_current(case,seg):
    im=case['draw'](3,seg)
    if im.info.get('motion') and case.get('plan'):
        import motion
        kind=seg['kind'] if seg['kind'] in ('standings','jp_roster') else 'soccer'
        args=(seg['meta'],case['clubs']) if kind!='soccer' else (seg,case['plan'])
        im.info['readability_motion_heading']=motion.adapt(kind,3,args,{})[1]
    return im


def sheet(rows, path, titles, cell=270):
    from PIL import Image, ImageDraw
    import soccer_v5_cards as c
    label_w=210;head=100;row_h=cell*1920//1080+90
    im=Image.new('RGB',(label_w+len(titles)*(cell+16)+16,head+len(rows)*row_h),(13,24,21))
    d=ImageDraw.Draw(im)
    for i,title in enumerate(titles):d.text((label_w+16+i*(cell+16),26),title,font=c.jp(24),fill=c.CHALK)
    for y,(label,items) in enumerate(rows):
        top=head+y*row_h
        for j,line in enumerate(c.lines(label,22,label_w-22)):
            d.text((14,top+j*30),line,font=c.jp(22),fill=c.CHALK)
        for x,(image_,description) in enumerate(items):
            left=label_w+16+x*(cell+16)
            im.paste(image_.resize((cell,cell*1920//1080),Image.Resampling.LANCZOS),(left,top))
            for j,line in enumerate(c.lines(description,18,cell)):
                d.text((left,top+cell*1920//1080+8+j*24),line,font=c.jp(18),fill=c.MUTED)
    im.save(path)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer-look-20261025')
    args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    # 直近race Actionsログで確認した見た目。設定はこの子プロセスだけ。
    os.environ.update(COLLESPO_SOCCER_LOOK='v5',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_BADGE='B',
                      COLLESPO_BUBBLE='slant',COLLESPO_MOTION='on',COLLESPO_DUO='off',COLLESPO_SOLO_HOST='metan')
    import soccer_v5_cards as c
    import review_render_v3 as r3
    cases=sources();current=[];comparisons=[];reports=[]
    labels={'results':'欧州の結果','race':'順位争い','preview':'注目試合の予告','week':'日本人の週末','goal':'ゴール速報'}
    for case in cases:
        folder=out/case['key'];folder.mkdir(exist_ok=True)
        save(folder/'material.json',case['data']);save(folder/'narration.json',case['narration'])
        segs=case['narration']['segments']
        indices=[0,(len(segs)-1)//2,len(segs)-1]
        frames=[];stats=[]
        for label,index in zip(('頭','中','終'),indices):
            seg=segs[index];caption(seg)
            im=render_current(case,seg);im.save(folder/(label+'.png'))
            frames.append((im,f'{label}：場面{index+1}/{len(segs)}　{seg["kind"]}　+3秒'))
            m=metrics(im);m.update(position=label,segment=index,kind=seg['kind'],errors=c.check_frame(im,case['clubs']));stats.append(m)
        current.append((labels[case['key']]+'\n'+case['day'],frames))
        if case['key']=='preview': index=next(i for i,s in enumerate(segs) if s['kind']=='preview')
        else:index=0
        seg=segs[index];caption(seg);before=render_current(case,seg)
        before.save(folder/'current.png')
        baseline=metrics(before)
        baseline['errors']=c.check_frame(before,case['clubs'])
        numbers=lambda m:set(re.findall(r'\d+(?:\.\d+)?',' '.join(e['text'] for e in m['body_text'])))
        samples=[(before,'現行と同じ材料・同じ字幕')];proposals=[]
        for variant in ('A','B'):
            caption(seg);p=Proposal(case,variant)
            if case['key']=='race':im=p.standings(seg['meta'])
            elif case['key']=='preview':im=p.preview_overview()
            elif case['key']=='week':im=p.roster(seg['meta'])
            elif case['key']=='goal':im=p.goal(seg)
            else:im=p.match(seg)
            im.save(folder/f'proposal-{variant}.png')
            check=c.check_frame(im,case['clubs'])
            m=metrics(im)
            if m['overlap_pairs']:check.append(dict(text_overlaps=m['overlap_pairs']))
            missing=numbers(baseline)-numbers(m);added=numbers(m)-numbers(baseline)
            if missing or added:check.append(dict(changed_numbers=dict(missing=sorted(missing),added=sorted(added))))
            m.update(variant=variant,errors=check,semantic_items=im.info['semantic_items'],motion_plan=im.info['proposal_motion'])
            proposals.append(m);samples.append((im,'配置A：列と左端を揃える' if variant=='A' else '配置B：主役を大きく見せる'))
        comparisons.append((labels[case['key']]+'\n'+case['day'],samples))
        reports.append(dict(key=case['key'],day=case['day'],source=case['source'],revision=case['revision'],
                            note=case.get('note'),material_sha256=hashlib.sha256((folder/'material.json').read_bytes()).hexdigest(),
                            segment_count=len(segs),current=stats,comparison_current=baseline,proposals=proposals))
    # MLBのv4実装＋pinstripe札。サッカーと同じ頭・中・終の場面区分。
    os.environ['COLLESPO_MLB_BADGE']='pinstripe'
    import test_v3_rules as fixtures
    mlb_refs={}
    for case in fixtures.daily_cases():
        if case['name'] not in ('players','forecast'):continue
        for motion_mode in ('on','off'):
            os.environ['COLLESPO_MOTION']=motion_mode
            folder=out/('mlb-'+case['name']+'-motion-'+motion_mode);folder.mkdir(exist_ok=True)
            frames=[];stats=[];indices=[0,(len(case['frames'])-1)//2,len(case['frames'])-1]
            for label,index in zip(('頭','中','終'),indices):
                seg=case['segments'][index];caption(seg);im=case['frames'][index](3)
                im.save(folder/(label+'.png'));frames.append((im,f'{label}：場面{index+1}　+3秒'))
                stats.append(metrics(im))
            current.append(('MLB v4 縦じま札\n'+case['name']+'\nmotion '+motion_mode,frames))
            if motion_mode=='off':mlb_refs[case['name']]=frames
            save(folder/'measurements.json',stats)
    os.environ['COLLESPO_MOTION']='on'
    sheet(current,out/'01-current-by-type-and-time.png',['頭（各場面内+3秒）','中（各場面内+3秒）','終（各場面内+3秒）'])
    paired=[]
    for case,(label,items) in zip(cases,current[:len(cases)]):
        refs=mlb_refs['forecast' if case['key']=='preview' else 'players']
        paired.append((label, [item for pair in zip(items,refs) for item in pair]))
    sheet(paired,out/'01-current-and-MLB-paired.png',['サッカー 頭','MLB v4 頭','サッカー 中','MLB v4 中','サッカー 終','MLB v4 終'],cell=240)
    sheet(comparisons,out/'02-current-A-B.png',['今','案A　整列を優先','案B　主役を強調'],cell=360)
    for label,items in comparisons:
        key=next(k for k,v in labels.items() if label.startswith(v))
        sheet([(label,items)],out/key/'comparison.png',['今','案A　整列を優先','案B　主役を強調'],cell=360)
    save(out/'measurements.json',dict(base_commit='8a78a84b2f906fc9e178f0c3d17d340b418661b1',
        settings_evidence='Actions 40183829178 job 121140295000: v5 / slant / motion on / host half',
        timings='映像の実尺ではなく、保存原稿の頭・中央・最終場面を各3秒で再描画。声の再合成なし。',
        assumptions='直近raceと同じ表示設定。他の過去回の変数・字幕分割・声の実尺は未取得。',
        publication=False,production_connected=False,cases=reports))
    r3.set_program_clock(None)
    errors=[(r['key'],p['variant'],p['errors']) for r in reports for p in r['proposals'] if p['errors']]
    save(out/'validation.json',dict(proposal_errors=errors,checked_proposals=10,production_files_modified=False))
    print(json.dumps(dict(out=str(out),proposal_errors=errors),ensure_ascii=False))
    return bool(errors)


if __name__=='__main__':raise SystemExit(main())
