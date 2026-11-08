"""招集名簿をポジションの帯で示す。先発・フォーメーションは推定しない。"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = 'pitch-v1'
INTRO_SECONDS = 2.0
PLAYER_SECONDS = 3.2
# 長いクラブ名で声が伸びた時は札を声に合わせて伸ばす（11/8 実音声の見本で3.2秒を超えて止まった）。
# 声を切ったり速めたりはしない。これを超える原稿だけ止める。
PLAYER_MAX_SECONDS = 6.0
INTRO_MAX_SECONDS = 3.0
MOVE_SECONDS = .3
CARD = (72, 1160, 940, 1460)
LEAGUES = {'PL':'イングランド1部', 'ELC':'イングランド2部', 'PD':'スペイン1部',
           'SA':'イタリア1部', 'BL1':'ドイツ1部', 'FL1':'フランス1部',
           'DED':'オランダ1部', 'PPL':'ポルトガル1部'}


def league_for(club):
    """登録済みの同一クラブと、リーグ戦の収録表の両方がある時だけ。"""
    import club_display_names as clubs
    import soccer_national as n
    target = clubs.lookup(club)
    if not target:
        return None
    coverage = n.read(ROOT/'data/soccer_club_coverage.json')
    found = []
    for code, names in coverage['competitions'].items():
        if code not in LEAGUES:
            continue
        if any((clubs.lookup(name) or {}).get('id') == target['id'] for name in names):
            found.append(dict(code=code, label=LEAGUES[code], club_id=target['id'],
                              source='data/soccer_club_coverage.json', season=coverage['season']))
    return found[0] if len(found) == 1 else None


def scope_label(data):
    positions = list(dict.fromkeys(p['position'] for p in data['players']))
    count = len(data['players'])
    if len(positions) == 1:
        return f'今日は{positions[0]}の{count}人'
    return '今日は' + '・'.join(f"{pos} {sum(p['position']==pos for p in data['players'])}人" for pos in positions)


def match_label(data):
    """何の試合に向けた招集かを冒頭で言う（Argon 11/8「いつの何の試合か分からない」）。材料の次の試合だけ。"""
    game = data.get('next_game') or {}
    opponent = str(game.get('opponent') or '').strip()
    return f'{opponent}戦の' if opponent else ''


def segments(data):
    """長い所属は札で伝える。声を速めたり、発話途中で切ったりしない。"""
    import soccer_national as n
    from voice_accent_common import mora_count
    readings = n.read(ROOT/'data/soccer_national_club_readings.json')
    rows = [dict(kind='national', text=f"{match_label(data)}招集{data['squad_size']}人。", speaker=2,
                 meta=dict(panel='squad', intro=True))]
    for i, p in enumerate(data['players']):
        name, club = p['name'], p['club']
        if i == 0:
            text = f'{name}、{club}。'
        elif i == len(data['players'])-1:
            text = f'最後は{club}の{name}。'
        else:
            text = f'続いて{name}。{club}です。'
        glue = 0 if i==0 else 5 if i==len(data['players'])-1 else 6
        if mora_count(readings[club]) + mora_count(p['reading']) + glue > 24:
            text = ('最後は' if i == len(data['players'])-1 else '続いて' if i else '') + name + '。'
        if p.get('first_call'):
            text = name + '、初招集です。'
        rows.append(dict(kind='national', text=text, speaker=2, meta=dict(panel='squad', player=i)))
    if data.get('next_game'):
        rows.append(dict(kind='national', text=n.kickoff_sentence(data['next_game'], '次の代表戦'),
                         speaker=2, meta=dict(panel='next')))
    return rows


def validate(data):
    import soccer_national as n
    roster = data['squad_roster']
    official = n.read(ROOT/'data/soccer_national_squad.json')
    if data['source_url'] != official['source_url'] or roster != [n.squad_player(p) for p in official['players']]:
        raise ValueError('全員の点が保存されたJFA発表と一致しません')
    if len(roster) != data['squad_size'] or len({p['name'] for p in roster}) != len(roster):
        raise ValueError('ピッチの全員の名簿が一致しません')
    for p in roster:
        if n.squad_player(dict(p, name_jp=p['name'])) != p:
            raise ValueError('ピッチのポジションと公式名簿が一致しません')
    names = {p['name']:p for p in roster}
    for p in data['players']:
        if any(p[k] != names[p['name']][k] for k in names[p['name']]):
            raise ValueError('今日の選手と全員の名簿が一致しません')
        if p.get('league') != league_for(p['club']):
            raise ValueError('リーグ札が収録済みのクラブ資料と一致しません')


def points(data):
    """発表順で等間隔。MF/FWを独断で二つのポジションへ分けない。"""
    out = []
    for position, ys in [('MF/FW',(620,730)), ('MF',(710,)), ('FW',(590,)), ('DF',(900,)), ('GK',(1040,))]:
        rows = [p for p in data['squad_roster'] if p['position']==position]
        if not rows:
            continue
        columns = math.ceil(len(rows)/len(ys))
        for index,p in enumerate(rows):
            line = index//columns
            count = min(columns,len(rows)-line*columns)
            x = 450 + (index%columns+.5)*(380/count)
            out.append(dict(name=p['name'],position=position,x=x,y=ys[line]))
    return out


def card_state(t, duration, point):
    phase = min(1., max(0., t/MOVE_SECONDS), max(0., (duration-t)/MOVE_SECONDS))
    # smoothstepには行き過ぎがない。説明中はscale=alpha=1で完全停止。
    progress = phase*phase*(3-2*phase)
    x0,y0,x1,y1 = CARD
    scale = .08 + .92*progress
    cx = point['x']*(1-progress)+(x0+x1)/2*progress
    cy = point['y']*(1-progress)+(y0+y1)/2*progress
    width,height = (x1-x0)*scale,(y1-y0)*scale
    return dict(progress=progress,alpha=progress,box=[round(cx-width/2),round(cy-height/2),round(cx+width/2),round(cy+height/2)])


def durations(narration, audio, measured):
    out = list(measured)
    for i,(seg,voice) in enumerate(zip(narration['segments'],audio)):
        meta = seg.get('meta') or {}
        actual = max(float(voice['duration']),float(measured[i]))
        if meta.get('intro'):
            if actual > INTRO_MAX_SECONDS:
                raise ValueError('冒頭の声が3秒を超えます。声の速さを変えず原稿を短くしてください')
            out[i] = max(INTRO_SECONDS,actual)
        elif meta.get('panel') == 'squad' and 'player' in meta:
            if actual+2*MOVE_SECONDS > PLAYER_MAX_SECONDS:
                raise ValueError('選手の声が長すぎます。札に収まる原稿へ短くしてください')
            out[i] = max(PLAYER_SECONDS,actual+2*MOVE_SECONDS)
        elif meta.get("panel")=="next":
            # 日付・相手・日本時間の開始時刻を読み取る時間も確保する。
            out[i] = max(6.4,out[i])
    return out


def frame(t, seg, data, clubs):
    from PIL import Image, ImageDraw
    import soccer_v5_cards as c
    import soccer_readable as readable
    import review_render_v3 as r3
    screen = readable.Screen.__new__(readable.Screen)
    screen.clubs,screen.t = clubs,max(.35,t)
    screen.im = c.canvas(0,clubs,'日本代表')
    im = screen.im
    im.info.update(soccer_readable=True,semantic_items=[],readable_motion='点から拡大＋フェード 0.3秒・説明中停止・点へ縮小 0.3秒')
    d = ImageDraw.Draw(im)
    d.rectangle((0,236,1080,1560),fill=c.PITCH)
    for y in range(236,1560,144):d.rectangle((0,y,1080,min(y+71,1560)),fill=c.GRASS)
    # 上の帯に「日本代表」があるので、相手が分かる日は「ブラジル戦 招集28人」に縮める（幅に入らず止まった）。
    head = f"{match_label(data)[:-1]} 招集{data['squad_size']}人" if match_label(data) else f"日本代表 招集{data['squad_size']}人"
    screen.text(72,258,head,70,868,c.CHALK,role='header')
    screen.text(72,354,scope_label(data),48,868,c.LIME,role='text')
    screen.text(72,434,'発表されたポジション',32,868,c.MUTED,role='supplement')
    screen.text(72,482,'名簿順の並び・先発配置ではありません',30,868,c.MUTED,role='supplement')
    # 既存の薄いコート線と同じ色。縦のピッチとしてゴール・中央線を配置。
    line=(32,62,46)
    for top,bottom in [(590,790),(850,950),(990,1100)]:
        d.rounded_rectangle((72,top,940,bottom),radius=12,fill=(12,39,28))
    d.rectangle((440,540,840,1120),outline=line,width=3)
    d.line((440,830,840,830),fill=line,width=3)
    d.ellipse((585,775,695,885),outline=line,width=3)
    for top,bottom in [(540,590),(1065,1120)]:d.rectangle((565,top,715,bottom),outline=line,width=3)
    for label,y in [('MF/FW',650),('DF',880),('GK',1020)]:
        screen.text(86,y,label,36,170,c.MUTED,role='supplement')
    screen.text(270,550,'MF/FWは一括発表',30,650,c.MUTED,role='supplement')
    selected = {p['name'] for p in data['players']}
    active = data['players'][seg['meta']['player']] if 'player' in seg['meta'] else None
    dots = points(data)
    for point in dots:
        x,y = point['x'],point['y']
        today = point['name'] in selected
        radius = 13 if today else 8
        if active and point['name']==active['name']:
            d.ellipse((x-22,y-22,x+22,y+22),outline=c.LIME,width=3)
        d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=c.LIME if today else (51,82,66))
    state = None
    if active:
        point = next(p for p in dots if p['name']==active['name'])
        ctx = r3._CAPTION
        duration = ctx['duration'] or PLAYER_SECONDS
        state = card_state(t,duration,point)
        layer = Image.new('RGB',im.size,c.PITCH)
        layer.info = dict(v3_layout=[])
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle(CARD,radius=22,fill=(22,54,41),outline=c.LIME,width=3)
        c.text(layer,104,1182,active['position'],30,c.MUTED,role='supplement',width=790)
        c.text(layer,104,1228,active['name'],64,c.CHALK,role='national_fact',width=804)
        club_lines = c.lines(active['club'],44,804)
        if len(club_lines)>2:raise ValueError('所属クラブの札が入りません')
        for j,line_text in enumerate(club_lines):
            c.text(layer,104,1310+j*52,line_text,44,c.CHALK,role='national_fact',width=804)
        league = active.get('league')
        if league:
            c.text(layer,104,1420,league['label'],30,c.LIME,role='supplement',width=804)
        # 拡大中も同じ札の内容で重複判定する。字幕が一瞬だけ出て消えるのを防ぐ。
        im.info['short_visible_texts']=[active['name']+active['club']]
        crop = layer.crop(CARD)
        box = state['box'];width,height = box[2]-box[0],box[3]-box[1]
        crop = crop.resize((max(1,width),max(1,height)),Image.Resampling.LANCZOS)
        mask = Image.new('L',crop.size,round(255*state['alpha']))
        im.paste(crop,(box[0],box[1]),mask)
        if state['progress']==1:im.info['v3_layout'].extend(layer.info['v3_layout'])
    im.info['national_pitch'] = dict(points=dots,selected=sorted(selected),active=active['name'] if active else None,
        card=state,scope=scope_label(data),formation=False)
    im.info['timeline_scene'] = dict(kind='national-pitch',name=active['name'] if active else 'intro')
    # 同じ区間の字幕だけを描く。カードの出現待ちや前区間のフェードを挟まない。
    return screen.finish(dict(source='VOICEVOX:四国めたん / JFA・リーグ表' if any(p.get('league') for p in data['players']) else 'VOICEVOX:四国めたん / JFA公式発表',title='日本代表',caption_alpha=state['alpha'] if state else 1.))
