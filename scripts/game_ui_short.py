"""game 資産だけの番号付き札。情報層のみ0.3秒で横から入り、以後静止する。"""
import copy
from datetime import datetime
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from PIL import ImageDraw
import asset_v4_cards as old
import review_render_v3 as r3
import short_v4_cards as c
import ps_v3_cover as cover

BOTTOM = 1028
SLIDE = .3
RED = (126, 64, 60)


def plain_item(head, body):
    return bool(old.stat_pairs(body) and head not in ('試合の結果','決勝点','先制で決勝の一打','先発')
                and not body.startswith('「') and '見出しから' not in head and '投稿から' not in head)


def item_pages(spec, head, body):
    return len(old.text_pages(head,plain_body(head,body))[0]) if plain_item(head,body) else old.item_pages(spec,head,body)


def plain_body(head,body):
    if head in ('勝ち投手','セーブ') and '（' in body:
        name,stats=body.split('（',1)
        return name+'\n（'+stats
    return body


def series_status(spec):
    """保存材料の厳密な結果行と回戦・試合番号・得点を相互照合。不明なら無表示。"""
    result = cover._game_result(spec.get('items') or [])
    rnd, game = cover._round_and_number(spec.get('label'))
    need = {'ワイルドカードシリーズ': 2, '地区シリーズ': 3,
            'リーグ優勝決定シリーズ': 4, 'ワールドシリーズ': 4}.get(rnd)
    if not result or not need or not game:
        return None
    state = cover.SERIES_RE.fullmatch(result.get('series') or '') or cover.CLINCH_RE.fullmatch(result.get('series') or '')
    if not state or state['team'] != result['win']:
        return None
    wins, losses = int(state['w']), int(state['l'])
    if wins + losses != game or not (0 <= losses < need and 1 <= wins <= need) or int(result['W']) <= int(result['L']):
        return None
    if 'rnd' in state.groupdict() and state['rnd'] != rnd:
        return None
    if 'rnd' in state.groupdict() and wins != need:
        return None
    board = (spec.get('game_v4') or {}).get('score')
    if board:
        winner = max((board['away'], board['home']), key=lambda v: v['total'])
        loser = min((board['away'], board['home']), key=lambda v: v['total'])
        if (winner['name'], loser['name'], winner['total'], loser['total']) != (
                result['win'], result['lose'], int(result['W']), int(result['L'])):
            return None
    if wins == need:
        return '世界一' if rnd == 'ワールドシリーズ' else rnd + '突破'
    if wins == need - 1:
        return '世界一に王手' if rnd == 'ワールドシリーズ' else '突破に王手'
    # 相手が王手でも勝者を「王手」とは呼ばない。
    return None


def annotate(segments, spec):
    """間引き後の実際の原稿から番号を付ける。同じduo画面は数え直さない。"""
    result = copy.deepcopy(segments)
    number = 1
    screens = {}
    for index, seg in enumerate(result):
        if seg['kind'] == 'outro':
            continue
        meta = seg.setdefault('meta', {})
        screen = meta.get('screen', index)
        if screen in screens:
            meta['game_ui_number'] = screens[screen]
            continue
        screens[screen] = number
        meta['game_ui_number'] = number
        count = 1
        if seg['kind'] == 'list':
            selected = spec['items'][meta['start']:meta['start'] + meta['count']]
            count = sum(item_pages(spec, h, b) for h, b in selected)
        elif seg['kind'] == 'people':
            count = 1 if meta.get('duo') else len((spec.get(meta.get('group', 'japanese')) or [])[:3])
        number += max(1, count)
    targets = [s for s in result if s['kind'] == 'next_line']
    target = (targets or [s for s in result if s['kind'] == 'intro'])[:1]
    if target:
        red_number = target[0]['meta']['game_ui_number']
        for seg in result:
            seg.setdefault('meta', {})['game_ui_red_number'] = red_number
    return result


def panel(im, y, height, fill=(20, 51, 46), width=None):
    x, right = r3.LEFT, min(r3.SAFE_RIGHT,r3.LEFT+width) if width else r3.SAFE_RIGHT
    ImageDraw.Draw(im).polygon([(x,y),(right,y),(right-round(height*.2),y+height),(x,y+height)],
                               fill=fill, outline=(183,204,204), width=2)
    r3.record_box(im, 'card', (x,y,right,y+height))


def text(im, x, y, value, size, color=None, number=False, width=None):
    """縮めて押し込まず、予定した字サイズで収まらなければ描画を止める。"""
    before = len(im.info.get('v3_layout', []))
    c.text(im, x, y, value, size, color, width=width, number=number)
    entries = im.info.get('v3_layout', [])[before:]
    if any(e.get('v4_font', size) != size for e in entries):
        raise ValueError('game UIの字幅超過: ' + str(value))


def heading(im, number, label):
    panel(im, 250, 80, (8,28,25))
    im.info['v3_layout'][-1]['role']='game_heading'
    text(im, r3.LEFT+20, 260, f'{number:02}', 64, number=True)
    text(im, r3.LEFT+122, 270, label, 43, width=r3.SAFE_RIGHT-r3.LEFT-150)


def result_card(im, spec):
    result = cover._game_result(spec.get('items') or [])
    if not result:
        raise ValueError('game UIの結果の材料を読めません')
    x = r3.LEFT+8
    text(im,x,386,spec['label'],36,width=c.R-x)
    matchup=result['win']+' 対 '+result['lose']
    import notability_engine as ne
    width=r3.font(44).getlength(matchup)+sum(c.inline_badge_width(tid,44)+12 for tid,name in ne.MLB_TEAM_NAME_JP.items() if name in matchup)
    if width>c.R-x:
        text(im,x,450,result['win'],44,width=c.R-x)
        text(im,x,504,'対 '+result['lose'],44,width=c.R-x)
    else:text(im,x,454,matchup,44,width=c.R-x)
    # 得点を一つの固定幅の文字列で描き、カウントアップしない。
    text(im,x,572 if width>c.R-x else 548,result['W']+'-'+result['L'],260,r3.GOLD,True,width=c.R-x)
    text(im,x,825,result['where']+'勝利',38,width=c.R-x)
    panel(im,890,116)
    v=spec.get('v3') or {}
    if v.get('tag'):text(im,x+16,905,v['tag'],30,r3.GOLD,width=c.R-x-48)
    if result.get('series'):text(im,x+16,960,result['series'],28,width=c.R-x-48)


def starters(im,spec,body):
    result=cover._game_result(spec.get('items') or [])
    parts=old.person_rows(body)
    if not result or len(parts)>2:
        raise ValueError('先発の球団を照合できません')
    parts.sort(key=lambda row: not row.startswith(result['win']+' '))
    if not parts or not parts[0].startswith(result['win']+' '):
        raise ValueError('勝った球団の先発が材料にありません')
    for i,part in enumerate(parts):
        match=re.search(r'\d',part)
        if not match:raise ValueError('先発の成績がありません')
        title,stat=part[:match.start()].strip(),part[match.start():]
        stat=stat.replace('回を無失点','回 0失点').replace('回と3分の','回3分の').replace('を',' ')
        y=405 if i==0 else 780
        panel(im,y,320 if i==0 else 222)
        team,_,name=title.partition(' ')
        text(im,c.L+24,y+28,team,36 if i==0 else 32,width=c.R-c.L-80)
        text(im,c.L+24,y+(92 if i==0 else 80),name,52 if i==0 else 46,width=c.R-c.L-80)
        text(im,c.L+24,y+(197 if i==0 else 158),stat,88 if i==0 else 38,
             r3.GOLD if i==0 else r3.INK,width=c.R-c.L-80)


def next_card(im,spec,line):
    facts=line.get('facts') or {}
    when=facts.get('jst')
    if when and not facts.get('after_first'):
        dt=datetime.fromisoformat(when)
        clock=f'{dt.month}月{dt.day}日({"月火水木金土日"[dt.weekday()]}) {dt.hour}時'+(f'{dt.minute}分' if dt.minute else '')
    else:
        clock=line['screen'].removeprefix('次の試合　').split('　')[0]
    text(im,c.L+8,402,(facts.get('round') or '')+(f' 第{facts["game"]}戦' if facts.get('game') else ''),36,width=c.R-c.L-16)
    panel(im,476,337)
    text(im,c.L+24,510,clock,64,r3.GOLD,width=c.R-c.L-88)
    text(im,c.L+24,600,'日本時間' if when else '日程',30,width=c.R-c.L-88)
    import next_line
    names=next_line.default_names()['teams']
    teams=[names[tid] for tid in line.get('team_ids',[]) if tid in names]
    if teams:text(im,c.L+24,676,' 対 '.join(teams),42,width=c.R-c.L-88)
    result=cover._game_result(spec.get('items') or [])
    if result and result.get('series'):text(im,c.L+24,752,result['series'],28,width=c.R-c.L-88)
    im.info['next_line']=line


def validate(im):
    """描画の実寸で画面外・本文同士・字幕・キャラとの干渉を止める。"""
    import v3_rules
    errors=v3_rules.check_layout(im)
    entries=im.info.get('v3_layout',[])
    content=[e for e in entries if e['role'] in ('text','number','team_badge') and e.get('text') not in ('“','”')]
    def overlaps(a,b):
        return min(a[2],b[2])-max(a[0],b[0])>2 and min(a[3],b[3])-max(a[1],b[1])>2
    protected=[e['box'] for e in entries if e['role'] in ('caption','source','ticker')]
    protected += [r['box'] for r in im.info.get('duo_portraits',[])]
    for i,a in enumerate(content):
        if any(overlaps(a['box'],b) for b in protected):errors.append({'protected_overlap':a})
        for b in content[i+1:]:
            if a['role']=='team_badge' or b['role']=='team_badge':
                outer,inner=(a,b) if a['role']=='team_badge' else (b,a)
                x,y,right,bottom=outer['box'];xx,yy,rr,bb=inner['box']
                if x<=xx<=rr<=right and y<=yy<=bb<=bottom:continue
            if overlaps(a['box'],b['box']):errors.append({'text_overlap':[a,b]})
    if errors:raise ValueError('game UI描画前検査: '+str(errors))


def frame(t,kind,meta,spec,label):
    """生成器と同じkind/metaで呼ぶ。他競技・他topicへは接続しない。"""
    spec=dict(spec,_game_ui_static=True)
    number=meta.get('game_ui_number',1)
    elapsed=t
    head='結果'
    if kind=='list':
        selected=spec['items'][meta.get('start',0):meta.get('start',0)+meta.get('count',1)]
        weights=[len((spec.get('speech') or {}).get(h) or f'{h.replace("｜","、")}。{b}。') for h,b in selected]
        i,fraction=old.timing(t,weights)
        head,body=selected[i]
        pages=item_pages(spec,head,body);page=min(pages-1,int(fraction*pages))
        number += sum(item_pages(spec,h,b) for h,b in selected[:i])+page
        elapsed=(fraction*pages-page)*(r3._CAPTION.get('duration') or 20)*weights[i]/sum(weights)/pages
        if meta.get('count')==1 and pages==1:elapsed=t
    elif kind=='people':
        rows=(spec.get(meta.get('group','japanese')) or [])[:3]
        if meta.get('duo') and 'row' in meta:
            rows=rows[meta['row']:meta['row']+1]
        weights=[len(row.get('name','')+'が'+row.get('line',row.get('why',''))+'、') for row in rows]
        i,fraction=old.timing(t,weights)
        number+=i
        if not meta.get('duo'):
            elapsed=fraction*(r3._CAPTION.get('duration') or 20)*weights[i]/sum(weights)
        rows=rows[i:i+1]
        head=meta.get('heading','日本人選手')
    im=c.canvas(0,label)
    custom=kind in ('intro','next_line') or (kind=='list' and head=='先発')
    if kind=='intro':result_card(im,spec)
    elif kind=='next_line':
        head='次の試合';next_card(im,spec,meta['next_line'])
    elif head=='先発':starters(im,spec,body)
    else:
        # 元の表をそのまま描く。字サイズ/座標/横幅/直角の枠を変えない。
        if kind=='list':
            if plain_item(head,body):
                im=old.text_screen(0,spec,label,head,plain_body(head,body),page)
            else:im=old.item(0,spec,label,head,body,page)
        else:
            row=rows[0]
            im=old.text_screen(0,spec,label,head,row['name']+'　'+row.get('line',row.get('why','')))
        backdrop=c.canvas(0,label)
        im.paste(backdrop.crop((c.L,236,c.R+1,338)),(c.L,236))
        im.info['v3_layout']=[e for e in im.info.get('v3_layout',[]) if not (236<=e['box'][1]<338)]
    heading(im,number,'経過' if head=='試合の結果' else head)
    status=series_status(spec) if number==meta.get('game_ui_red_number') else None
    if status:
        band_y=340 if kind=='intro' else 884
        panel(im,band_y,40 if kind=='intro' else 54,RED,width=640)
        text(im,c.L+24,band_y+8,status,26 if kind=='intro' else 32,width=c.R-c.L-72)
    if custom:
        v=spec.get('v3') or {}
        r3.ticker(im,t,v.get('ticker',''),once=v.get('ticker_once',False))
        r3.source(ImageDraw.Draw(im),'出典：MLB公式日程' if kind=='next_line' else '出典: MLB公式（Stats API）',r3.colors(None)[1])
        r3.presenter(im,t)
    im.info['game_ui']={'number':number,'heading':head,'status':status,'slide_seconds':SLIDE}
    im.info['skip_short_effects']=True
    state=dict(im.info.get('asset_v4') or {})
    state.setdefault('kind',{'intro':'intro','next_line':'next_line'}.get(kind,'stats'))
    state.update(head=head,animation_time=elapsed)
    if kind=='list':state.update(item=meta.get('start',0)+i,page=page,pages=pages)
    if kind=='people':state.update(row=meta.get('row',i))
    im.info['asset_v4']=state
    validate(im)
    # 予約領域・下部レイヤーは一切動かさない。検査は移動前の完成レイアウトで行う。
    if elapsed<SLIDE:
        box=(c.L,236,c.R+1,BOTTOM+1)
        layer=im.crop(box)
        background=c.canvas(0,label)
        im.paste(background.crop(box),box[:2])
        dx=round(120*(1-max(0,elapsed)/SLIDE))
        im.paste(layer.crop((dx,0,layer.width,layer.height)),box[:2])
    return im
