"""欧州サッカー（5大リーグ）のショートの v4 の札（下書き）。

MLB のショート v4（`collespo/src/scripts/short_v4_cards.py`・`review_render_v3.py`）の部品を
そのまま呼ぶ。地・見出し・字幕・進み具合・立ち絵・帯・出典・締めは作り直さない。
ここで作るのは「真ん中の中身」だけ:
  cover       表紙（その日の主役と大きな数字）
  jp_roster   日本人選手の一覧（全員を先に1画面で）
  jp_player   日本人選手1人（名前＋クラブの札・数字の札）
  standings   順位表（上位と自分のクラブの周り・CL/EL/残留の線を色で・勝点の差）
  preview     週末の注目試合（日時を大きく・両クラブの札・日本人選手・順位）
  result      試合の結果（スコアボード・得点経過の時間軸。材料が無い項目は描かない）

どの関数も、材料の辞書 spec と、その画面が出てからの秒 t を受けて 1080×1920 の画像を返す。
数字は spec にあるものだけを描く（足さない・言い換えない）。
クラブ名を本文に出すときは、名前のすぐ左に同じクラブの札を添える（`club_name`）。

使う前に環境変数 COLLESPO_SHORT_LOOK=v4 にしておく（MLB と同じ切り替え）。
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
for p in (SRC, SRC / 'scripts'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from PIL import ImageColor, ImageDraw  # noqa: E402
import review_render_v3 as r3  # noqa: E402
import short_v4_cards as v4  # noqa: E402

L, R = v4.L, v4.R
LABEL = '欧州サッカー'
# 順位表の線の色（意味は文字でも書く。色だけに頼らない）
LINE_COLORS = {'CL': (64, 156, 255), 'EL': (255, 150, 60), '残留': (230, 70, 80),
               '直行': (64, 156, 255), 'プレーオフ': (255, 150, 60)}
NEUTRAL = ((40, 52, 64), (196, 206, 212))   # 色が分からないクラブの札


# ------------------------------------------------------------------ クラブの表
def load_clubs(path=HERE.parent / 'data/club_colors.json'):
    """club_colors.json を {名前: クラブ} の辞書にする。英語名・日本語名のどちらでも引ける。"""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    out = {}
    for code, league in data['leagues'].items():
        for c in league['clubs']:
            club = dict(c, league=code)
            out[c['team_en']] = club
            if c.get('name_jp'):
                out[c['name_jp']] = club
    return out


def club_colors(club):
    """札の地（主色）と縁（2色目）。表に無い色は中立の色にする（推測で埋めない）。"""
    base = ImageColor.getrgb(club['primary']) if club.get('primary') else NEUTRAL[0]
    second = ImageColor.getrgb(club['secondary']) if club.get('secondary') else NEUTRAL[1]
    if second == base:
        second = NEUTRAL[1]
    return base, second


def badge_width(club, size):
    return round(r3.font(max(14, round(size * .55))).getlength(club['abbr'])) + 16


def club_badge(im, x, y, club, size, height):
    """クラブ名の文字と同じ高さ・同じ行の札。検査のため club_id と一緒に記録する。"""
    base, second = club_colors(club)
    w = badge_width(club, size)
    box = [x, y, x + w, y + height]
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, radius=6, fill=base, outline=second, width=2)
    r3.record_box(im, 'team_badge', box)
    f = r3.font(max(14, round(size * .55)))
    dy = f.getbbox(club['abbr'])[1]
    h = f.getbbox(club['abbr'])[3] - dy
    ink = v4.badge_ink(base)
    r3._text(d, (x + 8, y + (height - h) / 2 - dy), club['abbr'], font=f, fill=ink)
    im.info.setdefault('v4_badges', []).append(
        dict(club_id=club['team_en'], abbr=club['abbr'], base=base, ink=ink, box=box, inline=True))
    return w


def club_name(im, x, y, club, size=40, color=None, suffix='', width=None):
    """札＋クラブ名（＋続きの文）。戻り値は右端の x。"""
    name = club.get('name_jp') or club['team_en']
    value = name + suffix
    while width and badge_width(club, size) + 12 + r3.font(size).getlength(value) > width and size > 18:
        size -= 2
    f = r3.font(size)
    # 札の高さは、記録する文字の箱（名前＋続きの文）と同じ字列で測る。Linux の Noto では
    # 「CL」「1」などで上下の出が名前と違い、札と文字の高さが 3px 以上ずれて検査で止まった（10/10）。
    dy = f.getbbox(value)[1]
    height = f.getbbox(value)[3] - dy
    w = club_badge(im, x, y, club, size, height)
    x += w + 12
    r3._text(ImageDraw.Draw(im), (x, y - dy), value, font=f, fill=color or r3.INK)
    im.info['v3_layout'][-1].update(club_id=club['team_en'], v4_font=size)
    return x + f.getlength(value)


def plain(im, x, y, value, size=40, color=None, width=None, number=False):
    """クラブ名を含まない文。クラブ名が入っていたら止める（札なしで出さない）。"""
    for name in _club_names(im):
        if name in str(value):
            raise ValueError('クラブ名は club_name で札と一緒に描く: ' + str(value))
    v4.text(im, x, y, value, size, color, width=width, number=number)


def _club_names(im):
    return im.info.get('soccer_club_names', ())


def canvas(t, clubs, label=LABEL):
    im = v4.canvas(t, label)
    names = sorted({k for k, c in clubs.items() if k in (c.get('name_jp'), c['team_en'])}, key=len, reverse=True)
    im.info['soccer_club_names'] = tuple(n for n in names if len(n) >= 2)
    return im


def finish(im, t, spec):
    return v4.finish(im, t, spec.get('ticker', ''), spec.get('source', ''))


def chips(im, y, values, x=L + 24, right=R - 24, height=148):
    """数字と単位の札を横に並べる（最大4つ）。values は [(数字, 単位)]。"""
    values = [v for v in values if v and str(v[0]) != ''][:4]
    if not values:
        return y
    gap = 14
    w = (right - x - gap * (len(values) - 1)) // len(values)
    for i, (number, unit) in enumerate(values):
        cx = x + i * (w + gap)
        v4.panel(im, (cx, y, cx + w, y + height))
        v4.text(im, cx + 16, y + 14, number, 76, r3.GOLD, width=w - 32, number=True)
        ImageDraw.Draw(im).line((cx + 16, y + height - 60, cx + w - 16, y + height - 60), fill=r3.GOLD, width=1)
        plain(im, cx + 16, y + height - 46, unit, 28, width=w - 32)
    return y + height


# ------------------------------------------------------------------ 画面
def cover(t, spec, clubs):
    """表紙。spec: kicker・name・club・big・unit・context・chips・ticker・source。"""
    im = canvas(t, clubs, spec.get('label', LABEL))
    v4.panel(im, (L, 258, R, 1120))
    plain(im, L + 28, 284, spec['kicker'], 36, r3.GOLD, width=R - L - 56)
    plain(im, L + 28, 344, spec['name'], 76, width=R - L - 56)
    club_name(im, L + 28, 458, clubs[spec['club']], 40, width=R - L - 56)
    if spec.get('big'):
        v4.stat(im, L + 40, 540, spec['big'], spec.get('unit', ''), 250, width=R - L - 100, unit_size=70)
        if spec.get('context'):
            v4.tag(im, L + 40, 820, spec['context'], r3.GOLD, r3.DARK_INK, 32, width=R - L - 80)
    chips(im, 930, spec.get('chips', []), height=150)
    return finish(im, t, spec)


def jp_roster(t, spec, clubs):
    """日本人選手の一覧。rows: name・club・values（[(数字, 単位)]）・note。全員を1画面に。"""
    im = canvas(t, clubs, spec.get('label', LABEL))
    plain(im, L, 258, spec['title'], 44, width=R - L)
    rows = spec['rows']
    step = min(108, (1140 - 330) // max(1, len(rows)))
    for i, row in enumerate(rows):
        y = 330 + i * step
        v4.panel(im, (L, y, R, y + step - 12))
        plain(im, L + 22, y + 14, row['name'], 36, width=250)
        club_name(im, L + 22, y + 60, clubs[row['club']], 24, r3.colors(None)[1], width=300)
        x = L + 330
        if row.get('note'):
            plain(im, x, y + 30, row['note'], 30, (255, 170, 160), width=R - x - 20)
            continue
        for number, unit in row.get('values', []):
            v4.text(im, x, y + 18, number, 54, r3.GOLD, number=True)
            x += r3.num_font(54).getlength(str(number)) + 6
            plain(im, x, y + 42, unit, 26, width=120)
            x += r3.font(26).getlength(unit) + 26
    return finish(im, t, spec)


def jp_player(t, spec, clubs):
    """日本人選手1人。big が無い日は札だけ。"""
    im = canvas(t, clubs, spec.get('label', LABEL))
    v4.panel(im, (L, 258, R, 1120))
    plain(im, L + 26, 282, spec['kicker'], 34, r3.GOLD, width=R - L - 52)
    plain(im, L + 26, 340, spec['name'], 66, width=R - L - 52)
    club_name(im, L + 26, 440, clubs[spec['club']], 36, width=R - L - 52)
    y = 520
    if spec.get('big'):
        v4.stat(im, L + 34, y, spec['big'], spec.get('unit', ''), 180, width=R - L - 80, unit_size=54)
        y = 740
    y = chips(im, y, spec.get('chips', []))
    if spec.get('notes'):
        body = v4.lines('\n'.join(spec['notes']), 32, R - L - 100)
        top = y + 28
        v4.panel(im, (L + 24, top, R - 24, top + 40 + len(body) * 44))
        for i, line in enumerate(body):
            plain(im, L + 48, top + 22 + i * 44, line, 32, width=R - L - 100)
    return finish(im, t, spec)


def _line_kind(label):
    for key in LINE_COLORS:
        if key in label:
            return key
    return None


def standings(t, spec, clubs):
    """順位表。rows: position・team・played・points（材料の表のまま）。
    shown: 見せる順位の範囲 [(1,6),(14,18)]。lines: [(この順位の下に線, 名前)]。
    focus: 自分のクラブ（英語名）と、その線までの勝点の差（gap）。"""
    im = canvas(t, clubs, spec.get('label', LABEL))
    plain(im, L, 252, spec['title'], 40, width=R - L)
    rows = {r['position']: r for r in spec['rows']}
    shown = [p for a, b in spec['shown'] for p in range(a, b + 1) if p in rows]
    lines = dict(spec.get('lines', []))
    d = ImageDraw.Draw(im)
    y = 316
    head = r3.colors(None)[1]
    plain(im, R - 250, y, '試合', 24, head, width=70)
    plain(im, R - 130, y, '勝点', 24, head, width=80)
    y += 40
    breaks = sum(1 for a, b in zip(shown, shown[1:]) if b != a + 1)
    room = 1110 - y - breaks * 30 - sum(38 for p in shown if p in lines) - (96 if spec.get('gap') else 0)
    row_h = max(44, min(62, room // max(1, len(shown))))
    size = 34 if row_h >= 56 else 28
    prev = None
    for p in shown:
        if prev is not None and p != prev + 1:
            plain(im, L + 30, y - 6, '…', 30, head, width=60)
            y += 30
        row = rows[p]
        club = clubs[row['team']]
        focus = row['team'] == spec.get('focus') or row['team'] in spec.get('highlights', [])
        if focus:
            d.rounded_rectangle((L, y - 6, R, y + row_h - 10), radius=12, fill=(70, 62, 30))
            r3.record_box(im, 'card', (L, y - 6, R, y + row_h - 10))
        v4.text(im, L + 14, y + 4, p, size + 6, r3.GOLD, number=True, width=60)
        club_name(im, L + 84, y + 8, club, size, width=R - L - 350)
        v4.text(im, R - 236, y + 4, row['played'], size + 6, r3.INK, number=True, width=60)
        v4.text(im, R - 120, y + 4, row['points'], size + 6, r3.GOLD, number=True, width=80)
        y += row_h
        if p in lines:
            label = lines[p]
            color = LINE_COLORS.get(_line_kind(label), r3.GOLD)
            # 線と、その意味の札（線の下の帯に置き、数字の列にかけない）
            d.line((L, y - 6, R, y - 6), fill=color, width=5)
            w = r3.font(22).getlength(label) + 24
            d.rounded_rectangle((R - w, y - 4, R, y + 28), radius=8, fill=color)
            r3.record_box(im, 'card', (L, y - 6, R, y + 28))
            plain(im, R - w + 12, y - 2, label, 22, r3.DARK_INK, width=w - 20)
            y += 38
        prev = p
    if spec.get('gap'):
        # 「〇〇はEL圏内まで勝点5」。クラブ名は札と一緒に（gap は名前の後ろの文だけ）
        top = y + 16
        v4.panel(im, (L, top, R, top + 64), (70, 62, 30), r3.GOLD)
        club_name(im, L + 20, top + 16, clubs[spec['focus']], 30, r3.GOLD, suffix=spec['gap'], width=R - L - 40)
    im.info['soccer_standings'] = dict(shown=shown, lines=lines)
    return finish(im, t, spec)


def preview(t, spec, clubs):
    """週末の注目試合。date・time（日本時間）・league・home・away・ranks・jp。"""
    im = canvas(t, clubs, spec.get('label', LABEL))
    v4.panel(im, (L, 258, R, 1120))
    plain(im, L + 28, 282, spec['league'] + '　' + spec['date'], 36, r3.GOLD, width=R - L - 56)
    v4.stat(im, L + 40, 340, spec['time'], '日本時間', 200, width=R - L - 100, unit_size=40)
    y = 600
    for side in ('home', 'away'):
        club = clubs[spec[side]]
        rank = (spec.get('ranks') or {}).get(side)
        club_name(im, L + 28, y, club, 48, width=R - L - 260)
        if rank:
            v4.stat(im, R - 200, y - 18, rank, '位', 76, width=160, unit_size=30)
        plain(im, L + 28, y + 66, 'ホーム' if side == 'home' else 'アウェー', 24, r3.GOLD, width=120)
        names = '・'.join((spec.get('jp') or {}).get(side, []))
        if names:
            size = 30
            body = v4.lines(names, size, R - L - 206)
            while len(body) > 2 and size > 18:
                size -= 2
                body = v4.lines(names, size, R - L - 206)
            if len(body) > 2:
                raise ValueError('日本人選手の名前が安全域を超える')
            for i, name in enumerate(body):
                plain(im, L + 160, y + 66 + i * 40, name, size, r3.colors(None)[1], width=R - L - 206)
        y += 210
        if side == 'home':
            plain(im, L + 28, y - 34, '対', 34, r3.GOLD, width=60)
            y += 20
    if spec.get('ranks_note'):
        plain(im, L + 28, 1060, spec['ranks_note'], 26, r3.colors(None)[1], width=R - L - 56)
    return finish(im, t, spec)


def result(t, spec, clubs):
    """試合の結果。score と goals（分・得点者・home/away）は材料にあるときだけ描く。
    材料に無いときは、そのことを文字で示す（0対0 などと埋めない）。"""
    im = canvas(t, clubs, spec.get('label', LABEL))
    v4.panel(im, (L, 258, R, 1120))
    plain(im, L + 28, 282, spec['league'] + '　' + spec.get('date', ''), 34, r3.GOLD, width=R - L - 56)
    club_name(im, L + 28, 350, clubs[spec['home']], 44, width=R - L - 240)
    club_name(im, L + 28, 430, clubs[spec['away']], 44, width=R - L - 240)
    score = spec.get('score')
    if score:
        v4.text(im, R - 150, 330, score['home'], 84, r3.GOLD, number=True, width=110)
        v4.text(im, R - 150, 410, score['away'], 84, r3.GOLD, number=True, width=110)
    else:
        plain(im, R - 240, 400, '結果は材料待ち', 28, r3.colors(None)[1], width=200)
    # 得点経過の時間軸（0〜90分。前半・後半の区切り。ホームは上、アウェーは下）
    top, mid, bottom = 600, 800, 1000
    left, right = L + 60, R - 60
    d = ImageDraw.Draw(im)
    d.line((left, mid, right, mid), fill=r3.colors(None)[1], width=4)
    half = left + (right - left) / 2
    d.line((half, mid - 30, half, mid + 30), fill=r3.GOLD, width=3)
    plain(im, left, mid + 40, '前半', 26, width=80)
    plain(im, half + 12, mid + 40, '後半', 26, width=80)
    goals = spec.get('goals') or []
    for g in goals:
        minute = int(re.match(r'\d+', str(g['minute']))[0])
        x = left + (right - left) * min(minute, 90) / 90
        up = g['side'] == 'home'
        y = top if up else bottom - 70
        d.line((x, mid, x, y + (60 if up else 0)), fill=r3.GOLD, width=2)
        d.ellipse((x - 8, mid - 8, x + 8, mid + 8), fill=r3.GOLD)
        label = f"{g['minute']}分 {g['scorer']}"
        w = min(300, r3.font(26).getlength(label) + 8)
        lx = max(L + 8, min(x - w / 2, R - 8 - w))
        plain(im, lx, y + 14, label, 26, width=w)
    if not goals:
        plain(im, left, top + 40, '得点経過は材料にありません', 30, r3.colors(None)[1], width=right - left)
    im.info['soccer_goals'] = goals
    return finish(im, t, spec)


# ------------------------------------------------------------------ 検査に使う
def club_mentions(im):
    """本文（帯・出典・字幕は除く）に出たクラブ名と、その行の記録。"""
    names = _club_names(im)
    out = []
    for e in im.info.get('v3_layout', []):
        if e['role'] != 'text':
            continue
        for n in names:
            if n in e.get('text', ''):
                out.append((n, e))
                break
    return out


def check_club_badges(im, clubs):
    """クラブ名の左（同じ行・間24px以内・同じ高さ）に同じクラブの札があるか。"""
    errors = []
    for name, e in club_mentions(im):
        club = clubs[name]
        x, y, right, bottom = e['box']
        ok = any(b.get('club_id') == club['team_en'] and b.get('inline') and
                 0 <= x - b['box'][2] <= 24 and abs(b['box'][1] - y) <= 3 and
                 abs((b['box'][3] - b['box'][1]) - (bottom - y)) <= 3
                 for b in im.info.get('v4_badges', []))
        if not ok or e.get('club_id') != club['team_en']:
            errors.append({'club': name, 'text': e['text'], 'box': e['box']})
    return errors


def drawn_numbers(im):
    """本文に描いた数字（帯・出典・字幕・見出しは除く）。"""
    found = []
    for e in im.info.get('v3_layout', []):
        if e['role'] in ('text',):
            found += re.findall(r'\d+(?:\.\d+)?', str(e.get('text', '')).replace(',', ''))
    return found
