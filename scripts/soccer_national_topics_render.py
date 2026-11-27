"""代表戦の話題ショートを、新しい見た目（v2）・v6 focus・実音声で制作する。

ずんだもん（問い）は左下、めたん（答え）は右下に小さな胸上。真ん中の情報は問いの区間で右から入り、
答えの区間の終わりに左へ抜ける（同じ画面の間は動かさない）。画面の数字は原稿と同じ材料の数字だけ。
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import wave

import short_common
import soccer_national as national
import soccer_national_topics as topics
from duo import ZUNDA, METAN

ROOT = Path(__file__).resolve().parents[1]
FPS = 30
VIDEO = topics.VIDEO
CREDIT = '音声: VOICEVOX:ずんだもん・四国めたん　出典: ESPN'
CTA = '高評価・チャンネル登録で応援を'


def credit(doc, panel=None):
    """画面の出典。試合後の声は記事の媒体を先に出す（ESPN は試合結果だけ）。"""
    if doc.get('analysis_material'):
        voice = '音声: VOICEVOX:ずんだもん・四国めたん'
        return voice if panel is None else voice + '　出典: ' + doc['analysis_material']['items'][panel]['source_names']
    if doc.get('news_material'):
        voice = '音声: VOICEVOX:ずんだもん・四国めたん'
        return voice if panel is None else voice + '　出典: ' + doc['news_material']['items'][panel]['source_names']
    if doc.get('program') == topics.MLB_PROGRAM:
        voice = '音声: VOICEVOX:ずんだもん・四国めたん'
        if panel is None:
            return voice
        return voice + '　出典: ' + doc['followup_material']['items'][panel]['source_names']
    if doc.get('program') in ('mlb_season_insight', 'long_highlight'):
        return '音声: VOICEVOX:ずんだもん・四国めたん' + ('　出典: ' + doc['credit'] if panel is not None else '')
    if doc.get('credit'):
        return doc['credit']  # 欧州の注目試合（soccer_stake）は台本が出典を持つ。
    names = []
    if topics.is_reactions(doc.get('topic')):
        names += [q['source'].replace('／', '・') for q in doc['reaction_material']['quotes']]
        names += [f['source_names'] for f in doc['reaction_material'].get('facts', []) if f.get('source_names')]
    if doc.get('topic_reaction'):
        names += [q['source'].replace('／', '・') for q in doc['topic_reaction']['quotes']]
    if topics.is_followup(doc.get('topic')):
        # その後の話題は試合の数字を使わないので ESPN を出さない。
        names = [f['source_names'] for f in doc['followup_material']['items']]
        return '音声: VOICEVOX:ずんだもん・四国めたん　出典: ' + '・'.join(dict.fromkeys(n for part in names for n in part.split('・')))
    if not names:
        return CREDIT
    media = '・'.join(dict.fromkeys(n for part in names for n in part.split('・')))
    return f'音声: VOICEVOX:ずんだもん・四国めたん　出典: {media}・ESPN'


def clubs_for(doc):
    if doc.get('analysis_material'):
        return doc.get('clubs') or {}
    if doc.get('program') in (topics.MLB_PROGRAM, 'mlb_season_insight', 'long_highlight'):
        return {}
    if doc.get('clubs'):
        return doc['clubs']
    c = doc['topic_summary']['header']['competitions'][0]
    names = {}
    for t in c['competitors']:
        name = '日本' if str(t['id']) == national.JAPAN else national.team_name(t['team']['displayName'])
        names[name] = t['team'].get('abbreviation') or '?'
    return {n: dict(team_en=n, name_jp=n, abbr=a, primary=None, secondary=None, league='親善試合') for n, a in names.items()}


def opening_frames(segments, first_frames):
    if not segments[0]['meta'].get('hook'):
        return 0
    return max(first_frames, math.ceil(topics.OPENING_SECONDS * FPS))


def topic_transition_cues(segments, frame_counts, hook_end):
    """話者の区間から、実際に表示する札の区間を作る。"""
    core = topics.core_panel(segments)
    screens = [dict(meta=dict(screen='hook'))] if hook_end else []
    lengths = [hook_end / FPS] if hook_end else []
    start = 0
    for seg, count in zip(segments, frame_counts):
        end = start + count
        visible = end - max(start, hook_end)
        start = end
        if visible <= 0:
            continue
        panel = seg['meta'].get('panel')
        screen = seg['kind'] if panel is None else panel
        screens.append(dict(meta=dict(screen=screen, core=core is not None and panel == core)))
        lengths.append(visible / FPS)
    return short_common.transition_cues(screens, lengths, core_only=True)


def club_cast(im, speaker, line, elapsed, clock, duration):
    """既存の内向き素材の胸上を、字幕と出典の下で左右に置く。"""
    import characters
    import review_render_v3 as r3
    height = 420
    layers, portraits = [], []
    for who, (side, _, _, face_ratio) in characters.CORNERS.items():
        active = who == speaker
        face = characters.expression(who, speaker, line, elapsed, clock, volume=True)
        dy = characters.speaking_offset(elapsed, active and bool(line) and 0 <= elapsed < duration)
        art = characters.bust(who, face, height, side=side)
        x = r3.LEFT if side == 'left' else r3.SAFE_RIGHT - art.width
        y = 1475 - art.height + dy
        im.paste(art, (x, y), art)
        a, b, c, d = art.getbbox()
        ink = [x+a, y+b, x+c, y+d]
        left, top, right, bottom = face_ratio
        face_box = [x+round(art.width*left), y+round(height*top),
                    x+round(art.width*right), y+round(height*bottom)]
        r3.record_box(im, 'face', face_box)
        portraits.append(dict(who=who, box=ink, face=face_box, ink=ink, active=active))
        layers.append(dict(who=who, face=face, height=height, dim=False, side=side, at=[x,y],
                           cut=art.height, active=active, dy=dy, facing=characters.inward_facing(who, side)))
    im.info.update(duo_portraits=portraits, duo_layer=layers)


def club_outro(t, doc):
    import review_render_v3 as r3
    import short_cast
    footer = {}
    token = short_cast.DEFERRED.set(footer)
    try:
        im = r3.outro(t, credit=credit(doc), cta=CTA)
    finally:
        short_cast.DEFERRED.reset(token)
    speaker, elapsed, line, clock = footer['presenter']
    club_cast(im, speaker, line, elapsed, clock, r3._CAPTION['duration'])
    text, color = footer['source']
    text = text.removeprefix('音声: ').replace('　出典: ', ' / ')
    short_cast.source(im, text+'　立ち絵: 坂本アヒル', color)
    return im


def frame(t, seg, doc, clubs, index=0, count=1, *, opening_hook=None):
    """index 番目の区間の時刻 t の絵。問い（ずんだもん）と答え（めたん）の組は同じ画面。"""
    club_topic = doc.get('program') == 'soccer_club_topic'
    if seg['kind'] == 'outro':
        if club_topic:
            return club_outro(t, doc)
        import review_render_v3 as r3
        return r3.outro(t, credit=credit(doc), cta=CTA)
    import soccer_readable as readable
    import soccer_v5_cards as cards

    class TopicScreen(readable.Screen):
        def __init__(self, clubs, t, shift=0.0):
            self.clubs, self.t, self.shift = clubs, t + shift, shift

        def _slide_v2(self, body_only, duration, enter=True, leave=True):
            # 答えの区間は行を出し切った状態にするため時刻を進めている。抜ける時刻は区間の本当の終わりで測る
            # （進めた分だけ早く消えていた。Argon 11/15「話し終わる約1秒前に枠が消える」）。
            return super()._slide_v2(body_only, duration + self.shift if duration else duration, enter, leave)

        def lines(self, x, y, value, size=44, width=800, color=None, role='text'):
            # 数字は日本語より1.12倍の字で背が高い。数字を含む複数行は行の間を広げる
            # （11/15 引用「見事な2点で」の行が次の行に2px重なり描画が止まった）。
            rows = cards.lines(value, size, width)
            step = size + (20 if len(rows) > 1 and any(ch.isdigit() for ch in str(value)) else 12)
            for i, row in enumerate(rows):
                self.text(x, y + i * step, row, size, width, color, role=role)
            return y + len(rows) * step

        def text(self, x, y, value, size=44, width=800, color=None, number=False, role='text'):
            # 国名「日本」をクラブの言及と取り違えない（代表番組と同じ）。
            if role == 'text' and (value == '日本時間' or any(name in value for name in clubs)):
                role = 'national_fact'
            return super().text(x, y, value, size, width, color, number, role)

    meta = seg['meta']
    asking = seg['speaker'] == ZUNDA
    # 答えの区間は同じ画面の続き。入場の動きを繰り返さない。
    s = TopicScreen(clubs, t, 0.0 if asking else 1.0)
    hook = opening_hook or meta.get('hook')
    label = doc.get('screen_title') or '日本代表'
    s.im = cards.canvas(0 if hook else s.t, clubs, label)
    if doc.get('program') == topics.MLB_PROGRAM and doc.get('team_id'):
        import short_v4_cards
        short_v4_cards.pinstripe_badge(s.im, cards.L + 400, 163, doc['team_id'], 108, 54)
    s.im.info.update(soccer_readable=True, semantic_items=[], readable_motion='v2 右から0.28秒・説明中停止・左へ0.14秒')
    spec = dict(source=credit(doc, meta.get('panel')), title=label, presenter='zundamon' if asking else 'metan',
                cast=('zundamon', 'metan'), slide_in=asking, slide_out=not asking)
    if club_topic:
        spec['paint_cast'] = club_cast
    if hook:
        spec.update(slide_in=False, slide_out=False)
        return hook_screen(s, hook, spec)
    if doc.get('program') == topics.MLB_PROGRAM:
        # 分析の回（相場・移籍1年目の比べ）は材料で札を変える（11/27 平良の防御率の回に「移籍報道」と出た）。
        sub = (doc.get('followup_material') or {}).get('sub') or '移籍報道'
    elif meta.get('sub'):
        sub = meta['sub']
    elif doc.get('program') in ('mlb_season_insight', 'long_highlight'):
        sub = doc['date_jst'][:4] + '年'
    else:
        other = next(n for n in clubs if n != '日本')
        sub = f'日本対{other}' + ('' if meta.get('topic') == 'rematch' else '　親善試合')
    rows = [tuple(r) for r in meta['rows']]
    if doc.get('program') == topics.MLB_PROGRAM:
        rows = [row for row in rows if row[0] != '出典']
    # その後の話題も値を釣り合いよく折る（Argon 11/15「ヴォルフスブル／ク」の1字だけの改行）。
    if topics.is_reactions(meta.get('topic')) or meta.get('quote') or topics.is_followup(meta.get('topic')):
        if topics.is_reactions(meta.get('topic')):
            sub = f'日本対{other}　試合後'
    if topics.is_followup(meta.get('topic')):
        if doc.get('program') != topics.MLB_PROGRAM:
            sub = '日本代表　その後'
        size = 72 if len(rows) == 1 else 64
        rows = [(label, chr(10).join(balanced_lines(value, size, readable.R - readable.L - 56))) for label, value in rows]

    mlb = doc.get('program') == topics.MLB_PROGRAM
    limit = fact_body_limit(spec) if mlb else readable.BODY_BOTTOM
    if (topics.is_followup(meta.get('topic')) or doc.get('news_material')) and meta.get('big'):
        facts = [tuple(r) for r in meta['rows']]
        # MLB は出典の行を外すだけ。折り返しは big_fact_screen で1回（2回折ると改行を測って Linux の raqm が落ちる）。
        if mlb:
            facts = [row for row in facts if row[0] != '出典']
        if mlb and topics.is_followup(meta.get('topic')):
            hero = (doc.get('followup_material') or {}).get('hook', {}).get('score')
            if rank_candidates(facts):
                return rank_screen(s, meta['head'], facts, meta['big'], spec, sub, hero, limit)
            if bar_candidates(facts):
                return bar_screen(s, meta['head'], facts, meta['big'], spec, sub, limit)
        return big_fact_screen(s, meta['head'], meta['big'], facts, spec, sub, limit)
    if mlb and topics.is_followup(meta.get('topic')) and 'cast' in spec:
        facts = [tuple(r) for r in meta['rows'] if r[0] != '出典']
        if rank_candidates(facts):
            hero = (doc.get('followup_material') or {}).get('hook', {}).get('score')
            return rank_screen(s, meta['head'], facts, None, spec, sub, hero, limit)
        if bar_candidates(facts):
            return bar_screen(s, meta['head'], facts, None, spec, sub, limit)
    if meta.get('compare'):
        cmp = meta['compare']
        return s.national_compare(meta['head'], cmp['rows'], cmp['teams'], spec, sub)
    return s.national_facts(meta['head'], rows, spec, sub, body_bottom=limit if mlb else None)


LOSS = (255, 112, 112)


def hook_screen(s, hook, spec):
    """題の中心の数字と結果を、最初のコマから静止した札で見せる。"""
    import soccer_readable as readable
    import soccer_v5_cards as cards
    from PIL import ImageDraw
    win = hook['result'] == '勝利'
    accent = cards.LIME if win else LOSS if hook['result'] == '敗戦' else cards.CHALK
    s.text(readable.L, 260, hook['score'], 52, 560, role='national_fact')
    # 結果の札（勝ち＝黄、負け＝赤、引き分け＝白）
    chip = cards.measure(hook['result'], 40)[1] + 48
    d = ImageDraw.Draw(s.im)
    d.rounded_rectangle((readable.R - chip, 254, readable.R, 322), radius=10, fill=accent)
    cards.rec(s.im, 'card', (readable.R - chip, 254, readable.R, 322))
    s.text(readable.R - chip + 24, 266, hook['result'], 40, chip, cards.DARK if win or hook['result'] != '敗戦' else (40, 8, 8), role='supplement')
    big, unit = str(hook['big']), hook['unit']
    numeral = big.isascii()
    limit = fact_body_limit(spec)
    subject_h = len(cards.lines(hook['subject'], 68, 800)) * 80
    note_h = len(cards.lines(hook['note'], 48, 800)) * 60 + 48 if hook.get('note') else 0
    for size in (300, 260, 220, 180, 150, 120):
        bw = cards.measure(big, size, numeral)[1]
        uw = cards.measure(unit, 72)[1] + 24 if unit else 0
        b = cards.measure(big, size, numeral)[2]
        height = 56 + subject_h + 40 + b[3] - b[1] + note_h + 56
        if bw + uw <= 800 and height <= limit - readable.BODY_TOP:
            break
    else:
        raise ValueError('冒頭の札が本文に入りません')
    # 中身の高さに合わせた箱を、本文の領域の真ん中に置く（下が空いた箱にしない）。
    top = readable.BODY_TOP + (limit - readable.BODY_TOP - height) // 2
    s.panel(top, top + height)
    y = s.lines(100, top + 56, hook['subject'], 68, 800, role='national_fact')
    box = s.text(100, y + 40, big, size, 800, accent, numeral, role='national_fact')
    # 防御率のように単位の無い数字もある（11/27 平良の回で空の文字が画面検査に落ちた）。
    if unit:
        s.text(box[2] + 24, box[3] - 84, unit, 72, 800 - (box[2] - 100) - 24, accent, role='national_fact')
    if hook.get('note'):
        s.lines(100, box[3] + 48, hook['note'], 48, 800, cards.MUTED, 'supplement')
    s.im.info['preview_body'] = [readable.L, top, readable.R, top + height]
    s.im.info['opening_hook'] = hook
    s.im.info['timeline_scene'] = '冒頭の札'
    return s.finish(spec)


BIG_SIZES = (240, 210, 180, 150, 120)
LABEL_SIZES = (42, 40, 38, 36)
VALUE_SIZE = 56
BAR_SIZES = (96, 92, 88)


def fact_body_limit(spec):
    import soccer_readable as readable
    if 'cast' in spec:
        import short_cast
        return short_cast.BODY_BOTTOM - 4
    return readable.BODY_BOTTOM - 8


def text_height(value, size, number=False):
    import soccer_v5_cards as cards
    box = cards.measure(value, size, number)[2]
    return box[3] - box[1]


def split_quantity(value):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([^\d.]*)', str(value).strip())
    if not match:
        return None
    number, unit = match.group(1), match.group(2)
    if float(number) <= 0:
        return None
    return number, unit


def bar_candidates(rows):
    parsed = [split_quantity(value) for _, value in rows]
    if len(rows) < 2 or any(item is None for item in parsed):
        return None
    if len({item[1] for item in parsed}) != 1:
        return None
    return [(label, item[0], item[1], float(item[0])) for (label, _), item in zip(rows, parsed)]


def rank_candidates(rows):
    parsed = []
    for label, value in rows:
        match = re.match(r'^(\d+)位\s*(.*)$', str(label))
        quantity = split_quantity(value)
        if not match or not quantity:
            return None
        parsed.append((match.group(1), match.group(2).strip(), quantity[0], quantity[1]))
    return parsed if len(parsed) >= 2 else None


def require_big_on_rows(big, numbers):
    if big is not None and str(big['value']) not in numbers:
        raise ValueError('要の数字が行に出ていません: ' + str(big['value']))


def label_extent(lines, size):
    return (len(lines) - 1) * (size + 12) + max(text_height(line, size) for line in lines)


def choose_big_card(big, limit, minimum_left=0):
    """要の数字の札を、今と同じ字級の段から選ぶ。入らなければ黙らず止める。"""
    import soccer_readable as readable
    import soccer_v5_cards as cards
    value, unit = str(big['value']), big['unit']
    numeral = value.isascii()
    for size in BIG_SIZES:
        _, advance, box = cards.measure(value, size, numeral)
        if advance + 24 + (cards.measure(unit, 48)[1] if unit else 0) > 800:
            continue
        for label_size in LABEL_SIZES:
            lines = cards.lines(str(big['label']), label_size, 800)
            extent = label_extent(lines, label_size)
            height = 12 + extent + box[3] - box[1]
            if limit - readable.BODY_TOP - height - 6 >= minimum_left:
                return dict(size=size, label_size=label_size, label_lines=lines,
                            label_extent=extent, height=height)
    return None


def draw_big_card(s, big, config, top):
    import soccer_v5_cards as cards
    value, unit = str(big['value']), big['unit']
    numeral = value.isascii()
    s.panel(top, top + config['height'])
    for index, line in enumerate(config['label_lines']):
        s.text(100, top + 4 + index * (config['label_size'] + 12), line, config['label_size'],
               800, cards.MUTED, role='supplement')
    box = s.text(100, top + 8 + config['label_extent'], value, config['size'], 800,
                 cards.LIME, numeral, role='national_fact')
    if unit:
        bounds = cards.measure(unit, 48)[2]
        s.text(box[2] + 24, box[3] - (bounds[3] - bounds[1]), unit, 48,
               800 - (box[2] - 100) - 24, cards.LIME, role='national_fact')


def value_extent(lines, size):
    step = size + (20 if len(lines) > 1 and any(ch.isdigit() for ch in ''.join(lines)) else 12)
    return (len(lines) - 1) * step + max(text_height(line, size) for line in lines)


def bar_screen(s, head, rows, big, spec, sub, limit):
    """同じ単位の数字を、長さで比べられる横棒にする。"""
    import soccer_readable as readable
    import soccer_v5_cards as cards
    from PIL import ImageDraw
    s.title(head, sub)
    parsed = bar_candidates(rows)
    unit = parsed[0][2]
    unit_adv = cards.measure(unit, 48)[1] + 12 if unit else 0
    x0, bar_cap, gap = 112, 640, 12
    maximum = max(item[3] for item in parsed)
    matching = [i for i, item in enumerate(parsed)
                if big is not None and item[1] == str(big['value'])]
    big_card = None
    if big is not None and not matching:
        big_card = choose_big_card(big, limit, len(parsed) * 120 + (len(parsed) - 1) * gap)
        if big_card is None:
            raise ValueError('棒の画面に要の数字が入りません')
    available = limit - readable.BODY_TOP
    if big_card:
        available -= big_card['height'] + gap
    row_height = min(160, (available - (len(parsed) - 1) * gap) // len(parsed))
    if row_height < 120:
        raise ValueError('棒の画面に行が入りません')
    label_size = 36 if big_card else 42
    label_height = max(text_height(str(label), label_size) for label, _, _, _ in parsed)
    bar_top = 8 + label_height
    bar_height = min(72 if big_card else 80, row_height - bar_top - 6)
    for size in BAR_SIZES:
        advances = [cards.measure(number, size, True)[1] for _, number, _, _ in parsed]
        if max(advances) + unit_adv <= readable.R - x0 - 20 and text_height('0', size, True) <= bar_height + 4:
            break
    else:
        raise ValueError('棒の値が入りません')
    number_width = int(max(advances)) + 4
    room = min((readable.R - 20 - advance - unit_adv - x0) / item[3]
               for item, advance in zip(parsed, advances))
    scale = min(bar_cap / maximum, room)
    if scale <= 0:
        raise ValueError('棒の値が入りません')
    total = len(parsed) * row_height + (len(parsed) - 1) * gap
    center = max(0, (available - total) // 2)
    top = readable.BODY_TOP + center
    if big_card:
        draw_big_card(s, big, big_card, readable.BODY_TOP)
    y = readable.BODY_TOP + (big_card['height'] + gap if big_card else 0) + center
    highlight = max(matching) if matching else len(parsed) - 1
    for index, (label, number, _, value) in enumerate(parsed):
        active = index == highlight
        cards.rec(s.im, 'card', (readable.L, y, readable.R, y + row_height))
        s.text(100, y + 4, label, label_size, 800, cards.MUTED, role='supplement')
        width = max(2, round(value * scale))
        bar = (x0, y + bar_top, x0 + width, y + bar_top + bar_height)
        ImageDraw.Draw(s.im).rounded_rectangle(bar, radius=10, fill=cards.LIME if active else (70, 92, 140))
        cards.rec(s.im, 'decoration', bar)
        color = cards.LIME if active else cards.CHALK
        value_y = y + bar_top + (bar_height - text_height(number, size, True)) // 2
        box = s.text(x0 + width + 20, value_y, number, size, number_width, color, number=True, role='national_fact')
        if unit:
            bounds = cards.measure(unit, 48)[2]
            s.text(box[2] + 12, box[3] - (bounds[3] - bounds[1]), unit, 48, 400, color, role='national_fact')
        y += row_height + gap
    s.im.info.update(fact_bars=True, fact_bars_highlight=parsed[highlight][0])
    s.im.info['preview_body'] = [readable.L, top, readable.R, y - gap]
    return s.finish(spec)


def rank_screen(s, head, rows, big, spec, sub, hero, limit):
    """順位の並びを1行1枚の札にする。主役の行だけ枠と値を黄にする。"""
    import soccer_readable as readable
    import soccer_v5_cards as cards
    from PIL import ImageDraw
    s.title(head, sub)
    parsed = rank_candidates(rows)
    require_big_on_rows(big, [item[2] for item in parsed])
    card_height, gap = 158, 16
    total = len(parsed) * card_height + (len(parsed) - 1) * gap
    top = readable.BODY_TOP + max(0, (limit - readable.BODY_TOP - total) // 2)
    if top + total > limit:
        raise ValueError('順位札の画面に行が入りません')
    y = top
    highlight = ''
    for rank, name, number, unit in parsed:
        active = bool(hero and hero in name)
        if active:
            highlight = name
        advance = cards.measure(number, 88, True)[1]
        unit_adv = cards.measure(unit, 46)[1] + 10 if unit else 0
        vx = readable.R - 24 - advance - unit_adv
        rank_adv = cards.measure(rank + '位', 42)[1]
        name_x = 110 + rank_adv + 16
        for name_size in (44, 42, 40, 38, 36):
            if int(cards.measure(name, name_size)[1]) <= vx - 18 - name_x:
                break
        else:
            raise ValueError('順位札の名前が値とぶつかります: ' + name)
        fill = cards.mix(cards.BOARD, cards.LIME, .14) if active else cards.BOARD
        outline = cards.LIME if active else cards.mix(cards.BOARD, cards.CHALK, .18)
        box = (90, y, readable.R, y + card_height)
        ImageDraw.Draw(s.im).rounded_rectangle(box, radius=14, fill=fill, outline=outline, width=3 if active else 1)
        cards.rec(s.im, 'card', box)
        s.text(110, y + 46, rank + '位', 42, max(120, int(rank_adv) + 8),
               cards.LIME if active else cards.MUTED, role='supplement')
        s.text(name_x, y + 42, name, name_size, vx - 18 - name_x, cards.CHALK, role='national_fact')
        bounds = s.text(vx, y + 42, number, 88, int(advance) + 8,
                        cards.LIME if active else cards.CHALK, number=True, role='national_fact')
        if unit:
            ub = cards.measure(unit, 46)[2]
            s.text(bounds[2] + 10, bounds[3] - (ub[3] - ub[1]), unit, 46, 200,
                   cards.LIME if active else cards.CHALK, role='national_fact')
        y += card_height + gap
    s.im.info.update(fact_ranking=True, fact_ranking_highlight=highlight)
    s.im.info['preview_body'] = [readable.L, top, readable.R, y - gap]
    return s.finish(spec)


def big_fact_screen(s, head, big, rows, spec, sub, limit):
    """その後の話題の答え。要の数字1つを大きく、残りの行は小さく（Argon 11/15「字が均一で主役の数字が分からない」）。"""
    import soccer_readable as readable
    import soccer_v5_cards as cards
    s.title(head, sub)
    value, unit = str(big['value']), big['unit']
    numeral = value.isascii()
    # 要の数字と同じ行（例 本塁打 39 と要の数字の本塁打 39本）は二重になるので行からは外す。
    same = [r for r in rows if str(r[0]) == str(big['label']) and str(r[1]).startswith(value)]
    if same and len(rows) > len(same):
        rows = [r for r in rows if r not in same]
    wrapped = [(cards.lines(str(label), LABEL_SIZES[0], 800), cards.lines(str(v), VALUE_SIZE, 800))
               for label, v in rows]
    chosen = None
    # 行の札の余白（上・ラベルと値の間・下）。入らない時だけ詰める（11/27 佐藤の成績で字と札がくっついた）。
    for pad_top, pad_mid, pad_bottom, gap in ((10, 8, 12, 10), (8, 6, 8, 8), (2, 4, 0, 6)):
        for big_size in BIG_SIZES:
            _, advance, box = cards.measure(value, big_size, numeral)
            if advance + 24 + (cards.measure(unit, 48)[1] if unit else 0) > 800:
                continue
            for label_size in LABEL_SIZES:
                big_lines = cards.lines(str(big['label']), label_size, 800)
                big_extent = label_extent(big_lines, label_size)
                labels = [cards.lines(''.join(item[0]), label_size, 800) for item in wrapped]
                extents = [label_extent(lines, label_size) for lines in labels]
                heights = [pad_top + extent + pad_mid + value_extent(item[1], VALUE_SIZE) + pad_bottom
                           for extent, item in zip(extents, wrapped)]
                big_height = 12 + big_extent + box[3] - box[1]
                total = big_height + gap + sum(heights) + gap * (len(heights) - 1)
                if total <= limit - readable.BODY_TOP:
                    chosen = (big_size, label_size, big_height, big_lines, big_extent,
                              labels, extents, heights, total, pad_top, pad_mid, gap)
                    break
            if chosen:
                break
        if chosen:
            break
    if chosen is None:
        raise ValueError('要の数字の画面に行が入りません')
    (big_size, label_size, big_height, big_lines, big_extent, labels, extents, heights, total,
     pad_top, pad_mid, gap) = chosen
    top = readable.BODY_TOP + (limit - readable.BODY_TOP - total) // 2
    draw_big_card(s, big, dict(size=big_size, label_size=label_size, label_lines=big_lines,
                               label_extent=big_extent, height=big_height), top)
    y = top + big_height + gap
    for label_lines, item, label_ext, height in zip(labels, wrapped, extents, heights):
        values = item[1]
        s.panel(y, y + height)
        for index, line in enumerate(label_lines):
            s.text(100, y + pad_top + index * (label_size + 12), line, label_size, 800,
                   cards.MUTED, role='supplement')
        step = VALUE_SIZE + (20 if len(values) > 1 and any(ch.isdigit() for ch in ''.join(values)) else 12)
        for index, line in enumerate(values):
            s.text(100, y + pad_top + label_ext + pad_mid + index * step, line, VALUE_SIZE, 800,
                   role='national_fact')
        y += height + gap
    s.im.info['preview_body'] = [readable.L, top, readable.R, y - gap]
    return s.finish(spec)


NO_START = '、。，．」』）】!?！？ーぁぃぅぇぉっゃゅょ'


def kinsoku_lines(value, size, width):
    """行頭に句読点・閉じ括弧・小書きを置かない折り返し（前の行の最後の字を送る）。"""
    import soccer_v5_cards as cards
    out, current = [], ''
    for ch in str(value):
        if current and cards.measure(current + ch, size)[1] > width:
            if ch in NO_START and len(current) > 1:
                out.append(current[:-1]); current = current[-1]
            else:
                out.append(current); current = ''
        current += ch
    if current:
        out.append(current)
    return out


def balanced_lines(value, size, width):
    """同じ行数のまま、いちばん狭い幅で折り返して行の長さを揃える（最後の行に1〜2字だけ残さない）。"""
    count = len(kinsoku_lines(value, size, width))
    for w in range(width // 2, width + 1, 8):
        out = kinsoku_lines(value, size, w)
        if len(out) == count:
            return out
    return kinsoku_lines(value, size, width)


def allowed_numbers(doc):
    pool = json.dumps([doc['title'], [s['text'] for s in doc['segments']], [s['meta'] for s in doc['segments']]], ensure_ascii=False)
    return {float(v) for v in re.findall(r'\d+(?:\.\d+)?', pool)}


def caption_source_problems(im):
    """字幕の箱と出典が、YouTube ショートの UI に隠れない安全範囲（shorts_safe_area）の内側にあるか。"""
    import shorts_safe_area
    return [dict(caption_or_source_outside_safe_area=e) for e in im.info.get('v3_layout', [])
            if e['role'] in ('caption', 'source') and shorts_safe_area.outside(e['box'])]


def validate_frame(im, clubs, doc):
    import soccer_readable
    import soccer_v4_cards
    errors = soccer_readable.check_frame(im, clubs)
    errors += caption_source_problems(im)
    allowed = allowed_numbers(doc)
    drawn = {v for v in soccer_v4_cards.drawn_numbers(im)}
    drawn |= {v for e in im.info.get('v3_layout', []) if e['role'] == 'national_fact'
              for v in re.findall(r'\d+(?:\.\d+)?', str(e['text']))}
    extra = {v for v in drawn if float(v) not in allowed}
    if extra:
        errors.append(dict(numbers_missing_from_material=sorted(extra)))
    return errors


def silent_audio(narr, out, rate=24000):
    """声が無い環境の見本用。原稿の文字数から長さを決めた小さな音を、実音声の記録と同じ形で作る（公開には使えない）。"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, seg in enumerate(narr['segments']):
        seconds = 1.4 if seg['kind'] == 'outro' else len(seg['text']) / 7.5 + .4
        path = out / f'{i:03d}.wav'
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            # 完全な無音は音声結合が止めるので、小さな低い音を入れる（見本専用）。
            w.writeframes(b''.join(struct.pack('<h', round(2500 * math.sin(2 * math.pi * 220 * j / rate)))
                                   for j in range(round(seconds * rate))))
        rows.append(dict(text=seg['text'], speaker=seg['speaker'], kind=seg['kind'], meta=seg['meta'],
                         file=str(path), duration=round(seconds, 3)))
    national.save(out / 'manifest.json', dict(segments=rows, silent_sample=True))
    return rows


def render(narr, audio, out, *, sample=False, video_name=VIDEO):
    import soccer_results_render as common
    import soccer_look
    import short_content
    import review_render_v3 as r3
    import video_common as vc
    import render_timeline
    import voice_manifest
    if narr.get('program') == 'soccer_club_topic':
        from soccer_club_topics import check as check_topics
    elif narr.get('program') in ('mlb_season_insight', 'long_highlight'):
        from phase2_shorts import check as check_topics
    else:
        check_topics = topics.check
    if check_topics(narr):
        raise ValueError('原稿と材料が一致しません')
    if not soccer_look.readable() or not soccer_look.focus():
        raise ValueError('話題ショートはv6 focusだけを使います')
    if os.environ.get('COLLESPO_STYLE') != 'v2':
        raise ValueError('話題ショートは新しい見た目 COLLESPO_STYLE=v2 だけを使います')
    out = Path(out); out.mkdir(parents=True, exist_ok=True); common.ensure_ffmpeg(out)
    segments = narr['segments']
    frame_counts = [math.ceil(t * FPS) for t in common.durations(segments, audio)]
    times = [count / FPS for count in frame_counts]
    limit = topics.MLB_LIMIT if narr.get('program') == topics.MLB_PROGRAM else topics.LIMIT
    if sum(times) > limit:
        raise ValueError(f'{limit}秒を超えます: {sum(times):.2f}秒')
    short_content.require(narr, times, out, None, maximum=limit, video_name=video_name)
    track = vc.build_narration_track(audio, times, out)
    if not track:
        raise ValueError('実音声なし')
    hook_end = opening_frames(segments, frame_counts[0])
    cues = topic_transition_cues(segments, frame_counts, hook_end)
    track = short_common.add_audio(track, audio, times, out, cues=cues)
    clubs = clubs_for(narr); video = out / video_name; clock = 0; layouts = []
    timeline = render_timeline.Recorder(FPS, audio, narr)
    hook = segments[0]['meta'].get('hook')
    command = ['ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-r', str(FPS), '-i', '-',
               '-i', str(track), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
               '-t', str(sum(times)), '-movflags', '+faststart', str(video)]
    with (out / 'ffmpeg.log').open('w', encoding='utf8') as log:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i, (seg, duration, count) in enumerate(zip(segments, times, frame_counts)):
                timeline.select(audio[i], i)
                r3.set_program_clock(clock)
                r3.set_caption(seg['text'], duration, sum(times), speaker=seg['speaker'], duo=False, hide_caption=seg['kind'] == 'outro')
                seen = set()
                for k in range(count):
                    t = k / FPS
                    r3.set_program_clock(clock + t)
                    showing_hook = round(clock * FPS) + k < hook_end
                    im = frame(t, seg, narr, clubs, i, len(times), opening_hook=hook if showing_hook else None)
                    signature = json.dumps([showing_hook, im.info.get('bubble_style', {}).get('lines'),
                                            (im.info.get('v2_slide') or {}).get('phase')], ensure_ascii=False)
                    if (showing_hook or t >= .35) and signature not in seen:
                        seen.add(signature)
                        if seg['kind'] != 'outro':
                            errors = validate_frame(im, clubs, narr)
                            layouts.append(dict(scene=i, frame=k, errors=errors, layout=im.info.get('v3_layout'), lines=im.info.get('bubble_style', {}).get('lines')))
                            national.save(out / 'layout_checks.json', layouts)
                            if errors:
                                raise ValueError(f'画面{i}: {errors}')
                    if k == min(42, count - 1):
                        im.save(out / f'{i + 1:02d}.png')
                    timeline.write(proc.stdin, im.tobytes(), im)
                clock += duration
        finally:
            proc.stdin.close(); code = proc.wait(); r3.set_program_clock(None)
    if code:
        raise ValueError('ffmpegの制作に失敗')
    timeline.save(video, Path(audio[0]['file']).parent)
    report = short_content.validate_upload(video)
    if not sample:
        voice_manifest.save(Path(audio[0]['file']).parent, audio, narr)
    national.save(out / 'verification.json', dict(seconds=report['actual_seconds'], information=report['information_count'],
        scenes=len(times), layout_states=len(layouts), voice_seconds=sum(a['duration'] for a in audio),
        silent_sample=sample, publication='not performed'))
    return report


def render_settings():
    os.environ.update(COLLESPO_SOCCER_LOOK='v6', COLLESPO_SOCCER_FOCUS='on', COLLESPO_SHORT_LOOK='v4')


def asset_main(args):
    """今季比較の資産動画から、共通の掛け合い描画を呼ぶ入口。"""
    from phase2_shorts import season_narration

    if args.narration_out:
        national.save(Path(args.narration_out), season_narration(args.topic))
        return
    doc = national.read(Path(args.narration))
    if doc['topic'] != args.topic:
        raise ValueError('在庫の鍵が台本と一致しません')
    render_settings()
    os.environ['COLLESPO_STYLE'] = 'v2'
    audio = national.read(Path(args.audio_dir) / 'manifest.json')['segments']
    render(doc, audio, args.out, video_name=f'collespo_asset_{args.topic}.mp4')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/soccer_national_topics')
    ap.add_argument('--silent-sample', action='store_true', help='声が無い環境の見本（無音）。公開には使えない')
    args = ap.parse_args()
    render_settings()
    narr = national.read(args.out / 'narration.json')
    if args.silent_sample:
        audio = silent_audio(narr, args.out / 'audio')
    else:
        audio = national.read(args.out / 'audio/manifest.json')['segments']
    render(narr, audio, args.out, sample=args.silent_sample)


if __name__ == '__main__':
    main()
