"""本人指定の整列一覧＋大きな一組のスコア。v6指定時だけ使用する。"""
import copy
import math

from PIL import ImageDraw
import soccer_v5_cards as c
import review_render_v3 as r3

L, R = 72, 940
BODY_TOP, BODY_BOTTOM = 390, 1440
CAPTION = (64, 1660, 940, 1860)
PORTRAIT = (694, 1484, 920, CAPTION[1]+24)


def intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def page_at(t, count, duration=None):
    duration = duration or r3._CAPTION['duration'] or 12
    return min(count-1, max(0, int(t / max(.1, duration / count))))


def minimum_seconds(seg, data=None):
    meta=seg['meta'];kind=seg['kind'];count=1
    if kind=='player-stats':return 4
    if kind=='team-stats':return 4
    if kind=='jp_roster':count=math.ceil(len(meta['rows'])/4)
    elif kind=='roster':count=math.ceil(meta['count']/4)
    elif kind=='followup' and meta.get('compact_goals'):count=max(1,len(meta.get('goals',[])))
    elif kind in ('result','followup-detail'):
        game=next(g for g in data['games'] if g['id']==meta['event_id']) if data else {}
        count=math.ceil(len(meta.get('goals',game.get('goals',[])))/3)
    elif kind=='standings':
        count=math.ceil(sum(1 for r in meta['rows'] if any(a<=r['position']<=b for a,b in meta['shown']))/4)
    elif kind not in ('intro','followup','preview','cover'):return 0
    return max(1,count)*4


class Screen:
    def __init__(self, clubs, t=3):
        self.clubs, self.t = clubs, t
        self.im = c.canvas(t, clubs, '欧州サッカー')
        self.im.info.update(soccer_readable=True, semantic_items=[], readable_motion='フェードイン 0.35秒・以後停止')

    def text(self, x, y, value, size=44, width=800, color=None, number=False, role='text'):
        if c.screen_text(value, number) != str(value):
            raise ValueError('欠字を省略しません: '+str(value))
        return c.text(self.im, x, y, value, size, color or c.CHALK,
                      width=width, number=number, role=role, minimum=size)

    def panel(self, y, bottom, x=L, right=R):
        ImageDraw.Draw(self.im).rounded_rectangle((x, y, right, bottom), radius=12, fill=c.BOARD)
        c.rec(self.im, 'card', (x, y, right, bottom))

    def lines(self, x, y, value, size=44, width=800, color=None, role='text'):
        rows = c.lines(value, size, width)
        for i, row in enumerate(rows):
            self.text(x, y+i*(size+12), row, size, width, color, role=role)
        return y+len(rows)*(size+12)

    def name(self, x, y, key, width=800, size=44, short=False):
        club = copy.deepcopy(self.clubs[key])
        name = c.club_display_names.display(club, short=short)
        if not club.get('primary') and c.screen_text(club['abbr'], True) != club['abbr']:
            club['abbr'] = '?'
            self.im.info['unknown_club_badge'] = True
        height = c.measure(name, size)[2][3]-c.measure(name, size)[2][1]
        rows = c.lines(name, size, width-c.tag_width(club, height)-16)
        if len(rows) > 2:
            raise ValueError('クラブ名は次画面が必要: '+name)
        # 継続行にも同じ札を付け、名前の字体と行高を維持する。
        for i, row in enumerate(rows):
            c.club_name(self.im, x, y+i*(size+10), club, size, width=width, display_name=row)
        self.im.info['semantic_items'].append(name)
        return y+len(rows)*(size+10)

    def title(self, main, sub=''):
        self.text(L, 260, main, 52, R-L)
        if sub:
            self.lines(L, 330, sub, 30, R-L, c.MUTED, 'supplement')

    def finish(self, spec):
        import characters
        import solo_host
        # 下部も情報・字幕・胸上で使う。旧v5の1150px下端やtickerは持ち込まない。
        ctx = r3._CAPTION
        elapsed = self.t if r3._PROGRAM_CLOCK[0] is None else r3._PROGRAM_CLOCK[0]-ctx['start']
        line = r3.current_sentence(elapsed, ctx['text'], ctx['duration']) if ctx['text'] else ''
        speaker, _ = solo_host.presentation('metan', ('metan',))
        face = r3.face_for(line, elapsed, ctx['duration'] or 1)
        art = characters.bust(speaker, face, 360, False)
        if art is None:
            raise ValueError('胸上の既存素材がありません')
        x = PORTRAIT[2]-art.width
        y = PORTRAIT[3]-art.height
        self.im.paste(art, (x, y), art)
        self.im.info['duo_layer'] = [dict(who=speaker, face=face, height=360, dim=False,
                                         at=[x,y], cut=max(1,CAPTION[1]-y))]
        if line and not ctx.get('hide_caption'):
            import bubble_styles
            # 既存の幅・48px起点・数字強調・文節改行を引き継ぐ。
            # 胸上の下端に字幕を後から重ね、切れ目を箱の下へ隠す。
            bubble_styles.draw(self.im, speaker, line, style='slant', box=CAPTION, seconds=elapsed)
        # 出典の長文は2行。日次の詳細出典は従来の説明欄と材料に保持。
        source = spec.get('source', '')
        # 雨衣の回はクレジットが長い（10/26 朝の結果が書き出しで停止）。前置きを詰め、入らなければ字を2段まで小さくする。
        if source.startswith('音声: '):
            source = source[len('音声: '):]
        source = source.replace('　出典: ', ' / ')
        for size in (30, 28, 26):
            rows = c.lines(source, size, R-L)
            if len(rows) > 1:
                rows = c.lines(source, size, 1000)
            if len(rows) <= 1:
                break
        if len(rows) > 1:
            raise ValueError('出典は説明欄と分けて短く指定してください')
        if rows:
            self.text(40 if c.measure(rows[0],size)[1]>R-L else L, 1880, rows[0], size, 1000, c.MUTED, role='source')
        self.im.info['readable_zones'] = dict(body=[L,BODY_TOP,R,BODY_BOTTOM], caption=CAPTION, portrait=PORTRAIT)
        # 出現演出は1つ。説明中に動かさず、キャラ・字幕も同時にフェード。
        if self.t < .35:
            from PIL import Image
            info = self.im.info
            info['timeline_subtitle_visible'] = self.t > 0
            self.im = Image.blend(c._background(), self.im, max(0,self.t/.35))
            self.im.info = info
        return self.im

    def roster(self, spec):
        rows = spec['rows']
        pages = [rows[i:i+4] for i in range(0, len(rows), 4)] or [[]]
        index = page_at(self.t, len(pages));shown = pages[index]
        self.title(spec['title'].split('　')[0], 'A＝アシスト')
        self.im.info.update(readable_page=index, readable_page_count=len(pages), readable_rows=shown)
        height = (BODY_BOTTOM-BODY_TOP)//max(1,len(shown))
        for i,row in enumerate(shown):
            y = BODY_TOP+i*height;self.panel(y,y+height-14)
            self.text(100,y+round(height*.08),row['name'],76 if len(shown)==1 else 52,780)
            self.name(100,y+round(height*.32),row['club'],800,52 if len(shown)==1 else 40)
            stat_y=y+round(height*(.82 if len(shown)==1 else .64))
            if row.get('note'):
                self.lines(100,stat_y,row['note'],52 if len(shown)==1 else 40,790,c.MUTED)
            else:
                for j,(value,unit) in enumerate(row.get('values',[])):
                    x=100+j*268
                    box=self.text(x,stat_y,value,120 if len(shown)==1 else 76,160,c.LIME,True)
                    self.text(box[2]+10,stat_y+36,unit,30,110,role='supplement')
        return self.finish(spec)

    def preview(self, specs, spec):
        pages=[specs[i:i+4] for i in range(0,len(specs),4)]
        index=page_at(self.t,len(pages));shown=pages[index]
        self.title('注目試合の予告')
        subtitle=' / '.join(dict.fromkeys(s['date'] for s in shown))+'　'+' / '.join(dict.fromkeys(s['league'] for s in shown))
        subtitle_y=max(330,self.im.info['focus_title_bottom']+12) if self.im.info.get('focus_title_bottom') else 330
        subtitle_bottom=self.lines(L,subtitle_y,subtitle,30,R-L,c.MUTED,'supplement')
        # 件数が少なくても1件分の中身を縦に引き伸ばさない。
        # 札内は4件の日と同じ文字・行間を保ち、まとまりを中央へ置く。
        body_top=max(BODY_TOP,subtitle_bottom+16)
        height=min(300,(BODY_BOTTOM-body_top)//len(shown))
        top=body_top+(BODY_BOTTOM-body_top-height*len(shown))//2
        self.im.info['preview_body']=[L,top,R,top+height*len(shown)-14]
        for i,s in enumerate(shown):
            y=top+i*height;self.panel(y,y+height-14)
            # 時刻列を固定し、長いクラブ名は2行のまま40pxを保つ。
            self.name(100,y+28,s['home'],566,40)
            self.name(100,y+148,s['away'],566,40)
            self.text(706,y+50,s['time'],68,210,c.LIME,True)
            self.text(720,y+132,'日本時間',30,180,role='supplement')
            self.im.info['semantic_items'].append(s['time'])
        if self.im.info.get('unknown_club_badge'):
            self.text(L,1438,'灰色の ? はクラブ色・略称が未確認',30,850,c.MUTED,role='supplement')
        return self.finish(spec)

    def standings(self, spec):
        title=spec['title'].split('　');self.title(title[0],'　'.join(title[1:]))
        rows={r['position']:r for r in spec['rows']}
        shown=[rows[p] for p in sorted({p for a,b in spec['shown'] for p in range(a,b+1) if p in rows})]
        pages=[shown[i:i+4] for i in range(0,len(shown),4)] or [[]]
        index=page_at(self.t,len(pages));shown=pages[index]
        self.im.info.update(readable_page=index,readable_page_count=len(pages),readable_rows=shown)
        labels=dict(spec.get('lines',[]))
        top=442;bottom=1302 if spec.get('gap') else BODY_BOTTOM
        height=(bottom-top)//max(1,len(shown))
        for x,label,width in [(96,'順位',100),(220,'クラブ',420),(710,'試合',90),(830,'勝点',100)]:
            self.text(x,390,label,30,width,c.MUTED,role='supplement')
        for i,row in enumerate(shown):
            y=top+i*height;self.panel(y,y+height-14)
            self.text(100,y+44,row['position'],60,90,number=True)
            self.name(220,y+38,row['team'],450,40)
            self.text(714,y+44,row['played'],60,80,number=True)
            self.text(832,y+30,row['points'],80,84,c.LIME,True)
            if row['position'] in labels:
                label=labels[row['position']]
                color=c.LINE_COLORS.get(c.original._line_kind(label),c.MUTED)
                self.text(100,y+height-66,label,30,800,color,role='supplement')
                ImageDraw.Draw(self.im).line((L,y+height-16,R,y+height-16),fill=color,width=3)
        if spec.get('gap'):
            self.panel(1318,BODY_BOTTOM)
            self.name(100,1336,spec['focus'],400,40)
            self.text(520,1352,spec['gap'],30,390,c.LIME,role='supplement')
        return self.finish(spec)

    def score(self, game, spec, title='試合結果', person=None, score_only=False, compact_goals=None):
        import soccer_result_facts as facts
        self.title(title, facts.competition(game))
        if compact_goals is not None or score_only:
            shown=[]
            if compact_goals:
                page=page_at(self.t,len(compact_goals));shown=compact_goals[page:page+1]
                self.im.info.update(readable_page=page,readable_page_count=len(compact_goals))
            # Keep the score and one short explanation close together.
            self.panel(BODY_TOP,1000)
            self.name(100,430,game['home']['name_jp'],800,52)
            self.text(120,570,f"{game['score']['home']}-{game['score']['away']}",246,760,c.LIME,True)
            self.name(100,880,game['away']['name_jp'],800,52)
            people=[p['name'] for p in game['players'] if p['status']!='none'] or [p['name'] for p in game['players']]
            if people:self.text(100,1030,' / '.join(people),40,800)
            if shown:
                line=facts.compact_goal_line(shown[0],game)
                from soccer_v5_program import quote_lines, _quote_rows
                rows=quote_lines(line,40,800,self.clubs)
                height=len(rows)*60+48
                self.panel(1110,1110+height)
                _quote_rows(self.im,100,1134,rows,40,c.CHALK)
            self.im.info.update(soccer_goals=shown,compact_score=True)
            return self.finish(spec)
        self.panel(BODY_TOP,980)
        self.name(100,440,game['home']['name_jp'],800,52)
        self.text(120,616,f"{game['score']['home']}-{game['score']['away']}",246,760,c.LIME,True)
        self.name(100,870,game['away']['name_jp'],800,52)
        if game.get('match_stats'):
            self.match_statistics(game)
            return self.finish(spec)
        people=[person] if person else [p for p in game['players'] if p['status']!='none']
        self.panel(1002,BODY_BOTTOM)
        if not people:
            self.text(100,1300,'日本人選手の出場なし',52,800)
        y=1070
        for i,p in enumerate(people):
            if len(people)==1:
                self.text(100,1060,p['name'],76,800)
                detail=facts.player_line(p).rstrip('。').removeprefix(p['name']+'は')
                y=self.lines(100,1240,detail,60,800)
            else:
                y=1040+i*(370//len(people))
                self.text(100,y,p['name'],52,800)
                detail=facts.player_line(p).rstrip('。').removeprefix(p['name']+'は')
                y=self.lines(100,y+62,detail,40,800)+20
        if y>BODY_BOTTOM:
            raise ValueError('選手の結果は次画面が必要です')
        return self.finish(spec)

    def match_statistics(self, game):
        stats=game['match_stats']
        self.panel(1002,BODY_BOTTOM)
        self.text(100,1022,self.clubs[game['home']['name_jp']]['abbr'],30,200,c.MUTED,role='supplement')
        self.text(744,1022,self.clubs[game['away']['name_jp']]['abbr'],30,160,c.MUTED,role='supplement')
        for i,(key,label) in enumerate((('possession','保持率'),('shots','シュート'),('on_target','枠内'))):
            y=1090+i*102
            left=f"{stats['home'][key]:g}"+('%' if key=='possession' else '')
            right=f"{stats['away'][key]:g}"+('%' if key=='possession' else '')
            self.text(110,y,left,60,260,c.LIME,True)
            self.text(426,y+10,label,40,240)
            self.text(724,y,right,60,190,c.LIME,True)
        self.text(100,1390,'ESPN / '+game['date_jst']+'の夜',30,800,c.MUTED,role='supplement')

    def player_statistics(self, game, people, spec):
        import soccer_stats
        import soccer_results
        self.title('日本人選手の結果',game['date_jst']+'の夜 / ESPN')
        single=len(people)==1
        # 10/26本人指定：1人札は内容に合わせて上下を詰める。
        self.im.info['compact_player_statistics']=single
        height=(BODY_BOTTOM-BODY_TOP)//max(1,len(people))
        for i,p in enumerate(people):
            y=BODY_TOP+i*height
            label=soccer_stats.attack_label(p)
            bottom=y+height-14
            if single:
                bottom=y+(920 if label else 720 if p.get('position')=='GK' else 820)
            self.panel(y,bottom)
            self.text(100,y+40 if single else y+20,p['name'],76 if single else 52,800)
            self.name(100,y+160 if single else y+90,p['club'],800,52 if single else 40)
            state=soccer_results.STATUS[p['status']]
            minute_label=soccer_stats.minutes_label(p)
            if minute_label:state+=' / '+minute_label
            self.text(100,y+250 if single else y+156,state,52 if single else 40,800)
            ga=' / '.join(f"{p[k]}{unit}" for k,unit in (('goals','得点'),('assists','アシスト')) if p.get(k) is not None)
            if ga and p.get('position')!='GK':self.text(100,y+340 if single else y+216,ga,60 if single else 44,800)
            label=soccer_stats.attack_label(p)
            detail=soccer_stats.personal_line(p)
            if single and detail:
                measures=(('saves','セーブ'),('conceded','失点')) if p.get('position')=='GK' else (('shots','シュート'),('on_target','枠内'))
                for j,(key,unit) in enumerate(measures):
                    if p.get(key) is None:continue
                    x=110+j*410
                    offset=340 if p.get('position')=='GK' else 470
                    self.text(x,y+offset,p[key],120 if label else 180,350,c.LIME,True)
                    self.text(x,y+offset+(150 if label else 210),unit,44,350)
            elif detail:self.lines(100,y+286,detail,40,800)
            if label:
                self.text(100,y+710 if single else y+362,label,52 if single else 40,800,c.LIME)
                self.text(100,y+810 if single else y+442,soccer_stats.NOTICE,30,800,c.MUTED,role='supplement')
        return self.finish(spec)

    def goals(self, game, goals, spec):
        import soccer_result_facts as facts
        goals=sorted(goals,key=lambda g:tuple(int(v) for v in (g['minute'].split('+')+['0'])[:2]))
        pages=[goals[i:i+3] for i in range(0,len(goals),3)] or [[]]
        index=page_at(self.t,len(pages));shown=pages[index]
        self.title('得点・アシスト',facts.competition(game))
        self.im.info.update(soccer_goals=shown,readable_page=index,readable_page_count=len(pages))
        if not shown:
            self.panel(BODY_TOP,BODY_BOTTOM)
            self.name(100,440,game['home']['name_jp'],800,52)
            self.text(120,616,f"{game['score']['home']}-{game['score']['away']}",246,760,c.LIME,True)
            self.name(100,870,game['away']['name_jp'],800,52)
            self.text(100,1300,'得点なし' if game['goals_complete'] else '得点経過は未取得',52,800)
        height=(BODY_BOTTOM-BODY_TOP)//max(1,len(shown))
        rows=[]
        size=64 if len(shown)==1 else 44
        for g in shown:
            # 名前がない行を埋め草で増やさず、同じ画面の開始位置をそろえる。
            name=(facts.scorer_name(g) or g.get('scorer') or '').strip()
            if name in ('得点者不明','不明','情報なし'):name=''
            assists=facts.assist_names(g)
            label='オウンゴール' if g['own_goal'] else '得点'
            details=([label+'：'+name] if name else ['オウンゴール'] if g['own_goal'] else [])
            if assists:details.append('アシスト：'+'・'.join(assists))
            row_height=size+12
            detail_rows=[line for value in details for line in c.lines(value,size,800)]
            content_height=92+50+len(detail_rows)*row_height
            rows.append((g,details,content_height))
        offset=max(18,height-40-max((row[2] for row in rows),default=0))
        for i,(g,details,_) in enumerate(rows):
            y=BODY_TOP+i*height;self.panel(y,y+height-14)
            start=y+offset
            self.text(100,start,facts.minute_text(g['minute']),68,800,c.LIME)
            end=self.name(100,start+92,game[g['side']]['name_jp'],800,40)
            for value in details:
                end=self.lines(100,end+8,value,size,800,c.MUTED if value.startswith('アシスト') else None)
        return self.finish(spec)


def slots_frame(t, seg, plan):
    s=Screen(plan['clubs'],t);kind=seg['kind'];spec=seg['meta']
    if kind=='jp_roster':return s.roster(spec)
    if kind=='standings':return s.standings(spec)
    if plan['mode']=='preview' and kind in ('cover','preview'):
        specs=[x['meta'] for x in plan['narration']['segments'] if x['kind']=='preview']
        from datetime import datetime
        starts={g['game_id']:datetime.fromisoformat(g['start_time_utc']) for g in plan['data']['games']}
        specs=sorted(specs,key=lambda x:starts[x['game_id']])
        return s.preview(specs,spec)
    return None


def results_frame(t,seg,data,clubs,spec):
    s=Screen(clubs,t)
    game=next((g for g in data['games'] if g['id']==seg['meta'].get('event_id')),None)
    if seg['kind'] in ('flash-results','other-results'):
        s.title(seg['meta'].get('heading','速報済みの試合結果'))
        ids = seg['meta']['event_ids']
        top = (BODY_TOP+BODY_BOTTOM-(len(ids)*190+(len(ids)-1)*24))//2
        for i, ident in enumerate(ids):
            match = next(g for g in data['games'] if g['id']==ident)
            y = top+i*214
            s.panel(y, y+190)
            for side, x in (('home', L+8), ('away', L+492)):
                s.name(x, y+46, match[side]['name_jp'], width=368, size=40, short=True)
            s.text(L+382, y+60, f"{match['score']['home']}-{match['score']['away']}", 48, 100, number=True)
        s.im.info['compact_results'] = True
        return s.finish(spec)
    if seg['kind']=='player-stats':
        people=[p for p in game['players'] if p['status']!='none']
        start=seg['meta'].get('start',0)
        return s.player_statistics(game,people[start:start+seg['meta'].get('count',2)],spec)
    if seg['kind']=='followup':return s.score(game,spec,score_only=seg['meta'].get('score_only',False),
        compact_goals=seg['meta'].get('goals',[]) if seg['meta'].get('compact_goals') else None)
    if seg['kind']=='team-stats':
        return s.score(game,spec,title='チームのスタッツ')
    if seg['kind'] in ('result','followup-detail'):
        return s.goals(game,seg['meta'].get('goals',game['goals']),spec)
    if seg['kind']=='intro':
        person=next(p for p in data['players'] if p['name']==seg['meta']['player_detail']) if seg['meta'].get('player_detail') else next(p for p in data['players'] if p['status']!='none')
        return s.score(game,spec,person['name']+'の試合結果',person)
    if seg['kind']=='roster':
        rows=[p for p in data['players'] if p['status']!='none' and str(p['event_id']) not in seg['meta'].get('exclude_events',[] )]
        if not seg['meta'].get('player_names'):rows=rows[:seg['meta']['count']]
        if seg['meta'].get('player_names'):
            by_name={p['name']:p for p in rows}
            rows=[by_name[name] for name in seg['meta']['player_names']]
        import soccer_results
        display=[dict(name=p['name'],club=p['club'],values=[(p[k],u) for k,u in (('goals','得点'),('assists','A')) if p.get(k)],note='' if p.get('goals') or p.get('assists') else soccer_results.STATUS[p['status']]) for p in rows]
        return s.roster(dict(spec,title='日本人選手の結果',rows=display))
    return None


def check_frame(im,clubs):
    """最終描画のカード自体・字幕下の帯・40/30pxを検査する。"""
    import characters
    errors=c.original.check_club_badges(im,clubs)
    entries=im.info['v3_layout']
    body=[e for e in entries if e['role'] not in ('header','source','caption','ticker','team_badge','badge','decoration','card')]
    for e in entries:
        x,y,right,bottom=e['box']
        if not (0<=x<=right<=1080 and 0<=y<=bottom<=1920):errors.append(dict(outside_screen=e))
        size=e.get('v5_font')
        minimum=30 if e['role'] in ('source','supplement') else 40
        if e in body and size is not None and size<minimum:errors.append(dict(small_text=e,minimum=minimum))
        if e in body and (not e['text'].strip() or (e['role']=='text' and e['text'].strip()=='得点') or '情報なし' in e['text']):
            errors.append(dict(empty_item=e))
    for i,a in enumerate(body):
        for b in body[i+1:]:
            if intersects(a['box'],b['box']):errors.append(dict(text_overlap=[a,b]))
    cards=[e for e in entries if e['role']=='card']
    for card in cards:
        x,y,right,bottom=card['box']
        children=[e for e in body if x<=e['box'][0]<=e['box'][2]<=right and y<=e['box'][1]<=e['box'][3]<=bottom]
        if not children or bottom-max(e['box'][3] for e in children)>200:
            errors.append(dict(empty_card_bottom=card['box']))
    for item in im.info.get('duo_layer',[]):
        art=characters.bust(item['who'],item['face'],item['height'],item['dim'])
        x,y=item['at'];box=[x,y,x+art.width,y+min(art.height,item['cut'])]
        for e in cards+body:
            if intersects(e['box'],box):errors.append(dict(presenter_overlap=e))
    caption=im.info.get('duo_caption',{}).get('box')
    if caption:
        import bubble_styles
        legacy=bubble_styles.geometry()
        if caption[2]-caption[0]<legacy[2]-legacy[0]:errors.append(dict(narrow_caption=caption))
        text=next(e['text'] for e in entries if e['role']=='caption')
        _,minimum,_=bubble_styles._runs(ImageDraw.Draw(im.copy()),text,legacy,'slant',
                                      band=im.info.get('bubble_style',{}).get('variant')=='band')
        if im.info['duo_caption']['font_size']<minimum:errors.append(dict(small_caption=caption,minimum=minimum))
        for e in cards+body:
            if intersects(e['box'],caption):errors.append(dict(caption_overlap=e))
        if 1920-caption[3]>100:errors.append(dict(empty_below_caption=1920-caption[3]))
    # 予告は内容量に合わせた中央配置。札の中の余白は上の200px検査で
    # 従来どおり検査し、外側は描画が宣言した情報領域の下端へ照合する。
    body_bottom=im.info.get('preview_body',[L,BODY_TOP,R,BODY_BOTTOM])[3]
    if cards and not any(im.info.get(k) for k in ('compact_player_statistics','compact_results','compact_score')) and body_bottom-max(e['box'][3] for e in cards)>80:
        errors.append(dict(empty_body_bottom=body_bottom-max(e['box'][3] for e in cards)))
    return errors
