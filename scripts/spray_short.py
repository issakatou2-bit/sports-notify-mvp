"""本塁打の図（spray_chart.py）を使った縦長ショート（1080x1920、30fps、25〜35秒、無音）の見本。

公開しない・本番の型に繋がない。見た目は v2（style_v2.py）。
  0〜2秒   1枚目：選手名・「今季本塁打 全N本」・記念の1本の短い句（数字は材料の値だけ）
  2秒〜    球場の線 → 本塁打の点を日付順に1つずつ（約9秒で）。右上に「k/N」
  続けて    記念の1本（最大3本）を1本ずつ約3.6秒：他の点を薄く、本塁から黄の線、上に札（最長・最速の打球・
           弾丸ライナー・満塁・サヨナラ・最速の球）。弾丸ライナーの札だけ横から見た角度の図
  最後の約5秒 札3つ（最長・平均・左中右）＋「黄＝記念のN本」＋「勝ち越し・逆転 N本」
右下（EMPTY_BOX）はキャラ用に空ける。frame(plan, t) は時刻 t の純関数。

使い方:
  py -3 scripts/spray_short.py 808959 672960 660271     # build/spray_short_samples/ へ MP4・台本・コマの並び
"""
import datetime as dt
import json
import math
import subprocess
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spray_chart as sc  # noqa: E402
import style_v2 as sv  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

ROOT = sc.ROOT
OUT = ROOT / 'build/spray_short_samples'
W, H, FPS = 1080, 1920, 30
EMPTY_BOX = sc.EMPTY_BOX
T_TITLE = 2.0          # 1枚目の終わり
T_DOTS = 2.6           # 最初の点
DOTS_SPAN = 9.0        # 点を置く全体の目安（秒）。1本あたりの間隔は min(0.45, これ÷本数)
MAX_STEP = 0.45
SCENE_LEN = 3.6        # 記念の1本1つの長さ
SCENE_GAP = 0.4        # 点を置き終えてから最初の記念まで
MAX_MEMORIAL = 3
SUMMARY_LEN = 5.0      # まとめの最短
DIM = 0.3              # 記念の場面でのほかの点の濃さ
DIM_FADE = 0.3
LINE_GROW = 0.6
LINE_W = 6
DOT_R_Y = 17
DOT_FADE = 0.25
CARDS_FADE = 0.3
MIN_TOTAL, MAX_TOTAL = 25.0, 35.0
LEGEND_Y = 520
LONGEST_Y = 590

TEAM_JP = {
    'Diamondbacks': 'ダイヤモンドバックス', 'Braves': 'ブレーブス', 'Orioles': 'オリオールズ', 'Red Sox': 'レッドソックス',
    'Cubs': 'カブス', 'White Sox': 'ホワイトソックス', 'Reds': 'レッズ', 'Guardians': 'ガーディアンズ',
    'Rockies': 'ロッキーズ', 'Tigers': 'タイガース', 'Astros': 'アストロズ', 'Royals': 'ロイヤルズ',
    'Angels': 'エンゼルス', 'Dodgers': 'ドジャース', 'Marlins': 'マーリンズ', 'Brewers': 'ブリュワーズ',
    'Twins': 'ツインズ', 'Mets': 'メッツ', 'Yankees': 'ヤンキース', 'Athletics': 'アスレチックス',
    'Phillies': 'フィリーズ', 'Pirates': 'パイレーツ', 'Padres': 'パドレス', 'Giants': 'ジャイアンツ',
    'Mariners': 'マリナーズ', 'Cardinals': 'カージナルス', 'Rays': 'レイズ', 'Rangers': 'レンジャーズ',
    'Blue Jays': 'ブルージェイズ', 'Nationals': 'ナショナルズ',
}


def opponent_jp(en_name):
    for k, v in TEAM_JP.items():
        if en_name.endswith(k):
            return v
    return None


def attach_opponents(ds):
    """キャッシュした gameLog から、各本塁打に相手（日本語名）を足す。無ければ足さない。"""
    p = sc.RAW / f"{ds['player_id']}_gamelog.json"
    if not p.exists():
        return ds
    gl = json.loads(p.read_text(encoding='utf-8'))
    opp = {s['game']['gamePk']: (s.get('opponent') or {}).get('name', '')
           for s in (gl.get('stats') or [{}])[0].get('splits') or []}
    for h in ds['homers']:
        jp = opponent_jp(opp.get(h['game_pk'], ''))
        if jp:
            h['opp'] = jp
    return ds


def md(date):
    d = dt.date.fromisoformat(date)
    return f'{d.month}月{d.day}日'


def ft_text(v):
    return f'{round(v)}ft'


# --- 記念の1本（材料の値だけ。作らない）------------------------------------------------
def rhu(x):
    """四捨五入（0.5 は切り上げ）。"""
    return int(Decimal(str(x)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def kmh(mph):
    return rhu(mph * 1.609344)


def _own_opp(h):
    """打った後の（自軍点, 相手点）。材料が足りなければ None。"""
    top, ha, aa = h.get('top'), h.get('home_after'), h.get('away_after')
    if top is None or ha is None or aa is None:
        return None
    return (aa, ha) if top else (ha, aa)


def lead_kind(h):
    """打つ前の自軍点 ≤ 相手点 ＜ 打った後の自軍点 なら、負けていれば '逆転'、同点なら '勝ち越し'。それ以外は None。"""
    so = _own_opp(h)
    if so is None or h.get('rbi') is None:
        return None
    own, opp = so
    before = own - h['rbi']
    if before <= opp < own:
        return '逆転' if before < opp else '勝ち越し'
    return None


def is_walkoff(h):
    """打った側が裏・9回以上・打った1本で勝ち越し（打つ前は同点か負け）。"""
    return h.get('top') is False and (h.get('inning') or 0) >= 9 and lead_kind(h) is not None


def _pick(homers, val, big=True):
    """値のある本塁打から最大（big=False なら最小）。同値は日付の早い方。"""
    c = [h for h in homers if val(h) is not None]
    if not c:
        return None
    return min(c, key=lambda h: ((-val(h) if big else val(h)), h['date'], h.get('at_bat', 0)))


def _label(key, h, avg_la=None, name=None):
    if key == 'walkoff':
        return dict(key=key, name='サヨナラ本塁打', big=str(h['inning']), unit='回', sub=None, short='サヨナラ本塁打')
    if key == 'grand_slam':
        return dict(key=key, name='満塁本塁打', big='4', unit='打点', sub=None, short='満塁本塁打')
    if key == 'longest':
        ft = round(h['dist'])
        return dict(key=key, name='最長', big=str(ft), unit='ft', sub=f'約{sc.meters(ft):.1f}m', short=f'最長{ft}ft')
    if key == 'hardest':
        v = f'{h["ls"]:.1f}'
        return dict(key=key, name='最速の打球', big=v, unit='mph', sub=f'約{kmh(h["ls"])}km/h', short=f'最速の打球{v}mph')
    if key == 'liner':
        la = rhu(h['la'])
        return dict(key=key, name=name, big=str(la), unit='度', sub='打球角度', short=f'{name}{la}度', avg_la=avg_la)
    v = f'{h["pitch_mph"]:.1f}'
    return dict(key='fastest_pitch', name='最速の球を打った', big=v, unit='mph', sub=f'約{kmh(h["pitch_mph"])}km/h',
                short=f'最速の球を打った{v}mph')


def memorials(homers):
    """記念の1本を優先順（サヨナラ→満塁→最長→最速の打球→弾丸ライナー→最速の球）で最大3本選ぶ純関数。
    [{'h': 本塁打, 'labels': [札...]}] を返す。同じ1本が複数の鍵に当たるときは1本にまとめて札を並べる（最大2枚）。"""
    las = [h['la'] for h in homers if h.get('la') is not None]
    avg_la = sum(las) / len(las) if las else None
    wo = [h for h in homers if is_walkoff(h)]
    liners = [h for h in homers if h.get('traj') == 'line_drive']
    liner_name = '弾丸ライナー' if liners else '最も低い弾道'
    cands = [
        ('walkoff', _pick(wo, lambda h: 1)),
        ('grand_slam', _pick([h for h in homers if h.get('rbi') == 4], lambda h: 1)),
        ('longest', _pick(homers, lambda h: h.get('dist'))),
        ('hardest', _pick(homers, lambda h: h.get('ls'))),
        ('liner', _pick(liners or homers, lambda h: h.get('la'), big=False)),
        ('fastest_pitch', _pick(homers, lambda h: h.get('pitch_mph'))),
    ]
    if not liners:   # ライナーが無い選手の「最も低い弾道」は目玉にならないので、最速の球より後ろへ
        cands[4], cands[5] = cands[5], cands[4]
    out = []
    for key, h in cands:
        if h is None:
            continue
        lab = _label(key, h, avg_la, liner_name)
        card = next((m for m in out if m['h'] is h), None)
        if card is not None:
            if len(card['labels']) < 2:
                card['labels'].append(lab)
        elif len(out) < MAX_MEMORIAL:
            out.append(dict(h=h, labels=[lab]))
    return out


def lead_count(homers):
    return sum(1 for h in homers if lead_kind(h))


# --- 計画（材料から時刻・句を決める。時刻の純関数の元）----------------------------
def plan(ds, name_jp):
    sc.check_counts(ds)
    homers = sorted((dict(h) for h in ds['homers']), key=lambda h: (h['date'], h['at_bat']))
    for h in homers:
        h['ang'] = max(-44.0, min(44.0, sc.angle_deg(h['x'], h['y'])))
        h['px'] = sc.to_px(h['dist'], h['ang'])
    n_all = ds['gamelog_hr']
    k = len(homers)
    longest = max(homers, key=lambda h: h['dist'])
    latest = homers[-1]
    step = min(MAX_STEP, DOTS_SPAN / k)
    for i, h in enumerate(homers):
        h['t'] = T_DOTS + i * step
    dots_end = T_DOTS + k * step
    mem = memorials(homers)
    # 場面は優先順（1枚目の句と同じ順）に見せる
    ms_t0 = dots_end + SCENE_GAP
    for i, m in enumerate(mem):
        m['idx'] = i + 1
        m['start'] = ms_t0 + i * SCENE_LEN
        m['end'] = m['start'] + SCENE_LEN
    cards_t = ms_t0 + len(mem) * SCENE_LEN
    total = min(MAX_TOTAL, max(MIN_TOTAL, cards_t + SUMMARY_LEN))
    total = round(total * FPS) / FPS
    cnt = {'L': 0, 'C': 0, 'R': 0}
    for h in homers:
        cnt[sc.side(h['ang'])] += 1
    avg = sum(h['dist'] for h in homers) / k
    side_word = {'L': '左方向', 'C': '中堅方向', 'R': '右方向'}
    top = max('LCR', key=lambda s: (cnt[s], s == 'C'))
    flat = sorted((l for m in mem for l in m['labels']), key=lambda l: PRIORITY.index(l['key']))
    phrases = [flat[0]['short'] if flat else f'最長{ft_text(longest["dist"])}',
               flat[1]['short'] if len(flat) > 1 else f'最長{ft_text(longest["dist"])}']
    if len(flat) < 2 and flat:
        phrases[1] = f'{side_word[top]}へ{cnt[top]}本'
    return dict(name=name_jp, n=n_all, homers=homers, longest=longest, latest=latest, step=step,
                dots_end=dots_end, ms_t0=ms_t0, mem=mem, cards_t=cards_t, total=total, frames=round(total * FPS),
                cnt=cnt, avg=avg, phrases=phrases, side_phrase=f'{side_word[top]}へ{cnt[top]}本',
                lead=lead_count(homers), no_coords=ds['no_coords'], acquired=ds['acquired'])


PRIORITY = ['walkoff', 'grand_slam', 'longest', 'hardest', 'liner', 'fastest_pitch']


# --- 層 -------------------------------------------------------------------------
_cache = {}


def _header(p):
    key = ('h', p['name'])
    if key not in _cache:
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        size = 120 if len(p['name']) <= 6 else 96
        ImageDraw.Draw(lay).text((64, 70), p['name'], font=sv.jp(size, 'Black'), fill=sv.WHITE, anchor='la')
        _cache[key] = lay
    return _cache[key]


def _title_layer(p):
    key = ('t', p['name'], p['n'], tuple(p['phrases']))
    if key not in _cache:
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        nf, lf, uf = sv.num(380), sv.jp(54, 'Bold'), sv.jp(64, 'Bold')
        pre, post = '今季本塁打 全', '本'
        pw, nw, qw = lf.getlength(pre), nf.getlength(str(p['n'])), uf.getlength(post)
        x = (W - (pw + nw + qw + 24)) / 2
        base = 760
        d.text((x, base), pre, font=lf, fill=sv.GREY, anchor='ls')
        d.text((x + pw + 12, base + 26), str(p['n']), font=nf, fill=sv.WHITE, anchor='ls')
        d.text((x + pw + nw + 24, base), post, font=uf, fill=sv.WHITE, anchor='ls')
        pf = sv.jp(72, 'Bold')
        for i, s in enumerate(p['phrases']):
            d.text((W / 2, 900 + i * 110), s, font=pf, fill=sv.WHITE, anchor='ma')
        _cache[key] = lay
    return _cache[key]


def _field_layer(p):
    """球場の線・距離の目安・出典・小さな見出し（動かない部分は同じ絵を使い回す）。"""
    key = ('f', p['name'], p['n'], p['no_coords'], p['acquired'])
    if key not in _cache:
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.text((64, 250), f'今季本塁打 全{p["n"]}本', font=sv.jp(46, 'Bold'), fill=sv.GREY, anchor='la')
        arc = sc._arc_points()
        d.line(arc, fill=sc.LINE, width=4, joint='curve')
        d.line([sc.HOME_PX, arc[0]], fill=sc.LINE, width=4)
        d.line([sc.HOME_PX, arc[-1]], fill=sc.LINE, width=4)
        for ring in (200, 300):
            pts = [sc.to_px(ring, a) for a in range(-45, 46, 3)]
            d.line(pts, fill=(60, 74, 108), width=2)
            d.text((pts[-1][0] + 8, pts[-1][1]), f'{ring}ft', font=sv.jp(24, 'Medium'), fill=sv.DIM, anchor='lm')
        cx, cy = sc.to_px(sc.CENTER_FT, 0)
        d.text((cx, cy + 34), f'{int(sc.CENTER_FT)}ft', font=sv.jp(24, 'Medium'), fill=sv.DIM, anchor='ms')
        hx, hy = sc.HOME_PX
        d.polygon([(hx, hy + 8), (hx - 10, hy - 2), (hx - 10, hy - 12), (hx + 10, hy - 12), (hx + 10, hy - 2)], fill=sv.WHITE)
        sf = sv.jp(28, 'Medium')
        lines = ['データ: MLB Stats API（座標と飛距離）', f'取得 {p["acquired"]}']
        if p['no_coords']:
            lines.append(f'座標なし {p["no_coords"]}本は図から除く')
        for i, s in enumerate(lines):
            assert sf.getlength(s) < EMPTY_BOX[0] - 60, s
            d.text((60, 1810 + 40 * i), s, font=sf, fill=sv.GREY, anchor='ls')
        _cache[key] = lay
    return _cache[key]


def _cards_layer(p):
    key = ('c', p['name'], p['n'], p['longest']['dist'], round(p['avg']), tuple(p['cnt'].values()), len(p['mem']), p['lead'])
    if key not in _cache:
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        ft = lambda v: f'{round(v)}ft / {sc.meters(round(v)):.1f}m'
        cx0, cw, gap, cy0, ch = 60, 300, 30, 330, 130
        c = p['cnt']
        chips = [('最長', ft(p['longest']['dist'])), ('平均', ft(p['avg'])), ('左・中・右', f"{c['L']} / {c['C']} / {c['R']}")]
        for i, (lab, val) in enumerate(chips):
            x0 = cx0 + i * (cw + gap)
            sc._chip(d, (x0, cy0, x0 + cw, cy0 + ch), lab, val, 40 if i < 2 else 56)
        lg = sv.jp(34, 'Medium')
        note = f'黄＝記念の{len(p["mem"])}本'
        lx = (W - lg.getlength(note) - 40) / 2
        d.ellipse((lx, LEGEND_Y - 13, lx + 26, LEGEND_Y + 13), fill=sv.ACCENT)
        d.text((lx + 40, LEGEND_Y), note, font=lg, fill=sv.GREY, anchor='lm')
        d.text((W / 2, LONGEST_Y), f'勝ち越し・逆転 {p["lead"]}本', font=sv.jp(40, 'Bold'), fill=sv.WHITE, anchor='mm')
        _cache[key] = lay
    return _cache[key]


def detail_text(h):
    s = md(h['date']) + (f' {h["opp"]}戦' if h.get('opp') else '')
    if h.get('inning'):
        s += f' {h["inning"]}回'
    return s


def _angle_figure(d, x0, y0, la, avg_la):
    """横から見た角度の図（幅220・高さ130程度）。灰＝平均、黄＝この1本。(x0, y0) は図の左上。"""
    w, hh = 220, 130
    ox, oy = x0, y0 + hh
    d.line((ox, oy, ox + w, oy), fill=sv.GREY, width=3)
    L = 190
    for ang, col, wd in ((avg_la, sv.GREY, 5), (la, sv.ACCENT, 7)):
        if ang is None:
            continue
        a = math.radians(max(0.0, min(60.0, ang)))
        d.line((ox, oy, ox + L * math.cos(a), oy - L * math.sin(a)), fill=col, width=wd)
    return (ox, oy)


def _memorial_layer(p, m):
    h, labs = m['h'], m['labels']
    key = ('m', p['name'], m['idx'], tuple((l['name'], l['big']) for l in labs), detail_text(h), lead_kind(h))
    if key not in _cache:
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        x = 64
        tf = sv.jp(48, 'Black')
        for lab in labs:
            tw = tf.getlength(lab['name'])
            d.rounded_rectangle((x, 332, x + tw + 48, 408), radius=10, fill=sv.ACCENT)
            d.text((x + 24, 370), lab['name'], font=tf, fill=sv.NAVY_OUT, anchor='lm')
            x += tw + 48 + 16
        a = labs[0]
        nf = sv.num(160)
        base = 580
        d.text((64, base), a['big'], font=nf, fill=sv.WHITE, anchor='ls')
        nw = nf.getlength(a['big'])
        uf = sv.jp(56, 'Bold')
        d.text((64 + nw + 16, base), a['unit'], font=uf, fill=sv.WHITE, anchor='ls')
        if a.get('sub'):
            d.text((64 + nw + 16 + uf.getlength(a['unit']) + 28, base), a['sub'], font=sv.jp(40, 'Medium'), fill=sv.GREY, anchor='ls')
        y = 622
        df = sv.jp(42, 'Bold')
        d.text((64, y), detail_text(h), font=df, fill=sv.WHITE, anchor='la')
        lk = lead_kind(h)
        cx = 64 + df.getlength(detail_text(h)) + 24
        if lk:
            cf = sv.jp(32, 'Bold')
            cw = cf.getlength(lk) + 36
            d.rounded_rectangle((cx, y + 2, cx + cw, y + 52), radius=8, outline=sv.ACCENT, width=3)
            d.text((cx + cw / 2, y + 28), lk, font=cf, fill=sv.ACCENT, anchor='mm')
        if len(labs) > 1:
            b = labs[1]
            s = f'{b["name"]}  {b["big"]}{b["unit"]}' + (f'（{b["sub"]}）' if b.get('sub') else '')
            d.text((64, y + 66), s, font=sv.jp(38, 'Bold'), fill=sv.GREY, anchor='la')
        for lab in labs:
            if lab['key'] == 'liner':
                ox, oy = _angle_figure(d, 790, 430, h['la'], lab.get('avg_la'))
                d.text((ox, oy + 12), f'{lab["big"]}度', font=sv.jp(34, 'Bold'), fill=sv.ACCENT, anchor='la')
                if lab.get('avg_la') is not None:
                    d.text((ox + 220, oy + 12), f'平均{rhu(lab["avg_la"])}度', font=sv.jp(30, 'Bold'), fill=sv.GREY, anchor='ra')
        _cache[key] = lay
    return _cache[key]


def _dim(p, t):
    """記念の場面でのほかの点の濃さ（記念が始まるとき薄く、まとめで戻す）。"""
    if t < p['ms_t0']:
        return 1.0
    if t < p['cards_t']:
        return 1 - (1 - DIM) * sv.ease_out((t - p['ms_t0']) / DIM_FADE)
    return 1 - (1 - DIM) * (1 - sv.ease_out((t - p['cards_t']) / 0.4))


def current_scene(p, t):
    return next((m for m in p['mem'] if m['start'] <= t < m['end']), None)


def _dots_layer(p, t):
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    placed = 0
    ya = sv.ease_out((t - p['cards_t']) / CARDS_FADE)
    dim = _dim(p, t)
    cur = current_scene(p, t)
    yellow = []
    if cur:
        g = sv.ease_out((t - cur['start']) / LINE_GROW)
        hx, hy = sc.HOME_PX
        px, py = cur['h']['px']
        d.line([(hx, hy), (hx + (px - hx) * g, hy + (py - hy) * g)], fill=sv.ACCENT + (255,), width=LINE_W)
    mem_h = [m['h'] for m in p['mem']]
    for h in p['homers']:
        a = sv.ease_out((t - h['t']) / DOT_FADE)
        if a <= 0:
            continue
        placed += 1
        px, py = h['px']
        if cur and h is cur['h']:
            ys = sv.ease_out((t - cur['start']) / 0.2)
            r = 10 + (DOT_R_Y - 10) * ys
            if ys >= 1:
                yellow.append((round(px), round(py)))
            d.ellipse((px - r, py - r, px + r, py + r), fill=sv.mix(sv.WHITE, sv.ACCENT, ys) + (255,))
        elif t >= p['cards_t'] and any(h is mh for mh in mem_h) and ya > 0:
            r = 10 + (DOT_R_Y - 10) * ya
            if ya >= 1:
                yellow.append((round(px), round(py)))
            d.ellipse((px - r, py - r, px + r, py + r), fill=sv.mix(sv.WHITE, sv.ACCENT, ya) + (255,))
        else:
            r = 10 * (0.7 + 0.3 * a)
            d.ellipse((px - r, py - r, px + r, py + r), fill=(244, 246, 250, int(215 * a * dim)))
    return lay, placed, yellow


def _with_alpha(lay, a):
    if a >= 1:
        return lay
    out = lay.copy()
    out.putalpha(out.getchannel('A').point(lambda v: int(v * a)))
    return out


def frame(p, t):
    """時刻 t の絵（RGB）と記録（点の数・黄の点の位置・記念の場面の番号と札）を返す。"""
    im = sv.background(t, W, H)
    im.alpha_composite(_header(p))
    info = dict(placed=0, yellow=[], count_text=None, scene=None, scene_labels=[], scene_bigs=[])
    a = sv.slot(t, 0, T_TITLE)
    if a is not None:
        dx, al, _ = a
        s = sv.shifted(_title_layer(p), dx, al)
        if s:
            im.alpha_composite(s)
    b = sv.slot(t, T_TITLE, p['total'], last=True)
    if b is not None:
        dx, al, _ = b
        scene = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        scene.alpha_composite(_with_alpha(_field_layer(p), sv.ease_out((t - T_TITLE) / 0.5)))
        dots, placed, yellow = _dots_layer(p, t)
        scene.alpha_composite(dots)
        info.update(placed=placed, yellow=yellow)
        cur = current_scene(p, t)
        if cur:
            info.update(scene=cur['idx'], scene_labels=[l['name'] for l in cur['labels']], scene_bigs=[l['big'] for l in cur['labels']])
        d = ImageDraw.Draw(scene)
        if placed and t < p['ms_t0']:
            txt = f'{placed}/{len(p["homers"])}'
            d.text((W - 64, 70), txt, font=sv.num(96), fill=sv.WHITE, anchor='ra')
            info['count_text'] = txt
        elif cur:
            nf = sv.num(96)
            txt = f'{cur["idx"]}/{len(p["mem"])}'
            d.text((W - 64, 150), txt, font=nf, fill=sv.WHITE, anchor='rs')
            d.text((W - 64 - nf.getlength(txt) - 20, 146), '記念の1本', font=sv.jp(40, 'Bold'), fill=sv.GREY, anchor='rs')
            info['count_text'] = f'記念の1本 {txt}'
        for m in p['mem']:
            ms = sv.slot(t, m['start'], m['end'])
            if ms is not None:
                mdx, mal, _ = ms
                ml = sv.shifted(_memorial_layer(p, m), mdx, mal)
                if ml:
                    scene.alpha_composite(ml)
        ca = sv.ease_out((t - p['cards_t']) / CARDS_FADE)
        if ca > 0:
            scene.alpha_composite(_with_alpha(_cards_layer(p), ca))
        s = sv.shifted(scene, dx, al)
        if s:
            im.alpha_composite(s)
    return im.convert('RGB'), info


# --- 台本案 ----------------------------------------------------------------------
def _sentence(lab, h, first):
    where = f'{h["opp"]}戦' if h.get('opp') else ''
    on = f'{md(h["date"])}の{where}'
    k = lab['key']
    if k == 'walkoff':
        return f'{on}、{h["inning"]}回裏のサヨナラ本塁打だよ。' if first else f'この1本は、{h["inning"]}回裏のサヨナラ本塁打だったんだ。'
    if k == 'grand_slam':
        return f'{on}、満塁本塁打。4打点だよ。' if first else 'この1本は、満塁本塁打でもあるよ。'
    if k == 'longest':
        t = f'{lab["big"]}フィート、約{lab["sub"][1:-1]}メートル'
        return f'いちばん遠くへ飛んだのは、{on}の1本。{t}。' if first else f'この1本は、いちばん遠くへ飛んだ{t}でもあるよ。'
    if k == 'hardest':
        t = f'{lab["big"]}マイル、時速およそ{lab["sub"][1:-4]}キロ'
        return f'いちばん速い打球は{on}の1本、{t}。' if first else f'打球の速さもいちばんで、{t}。'
    if k == 'liner':
        avg = f'平均は{rhu(lab["avg_la"])}度だよ。' if lab.get('avg_la') is not None else ''
        word = '弾丸ライナー' if lab['name'] == '弾丸ライナー' else 'いちばん低い弾道'
        return f'{word}は{on}の1本、打球角度{lab["big"]}度。{avg}'
    t = f'{lab["big"]}マイル、時速およそ{lab["sub"][1:-4]}キロ'
    return f'いちばん速い球を打ったのは{on}の1本、{t}。' if first else f'この1本は、いちばん速い球を打った{t}でもあるよ。'


def script_text(p):
    c = p['cnt']
    lines = [
        f'{p["name"]}、今季の本塁打は全部で{p["n"]}本だよ。',
        '全部の打球を、球場の図に置いてみたよ。日付の順に出すね。',
        '',
        '（点が日付順に1つずつ出る間は、言葉を入れずに間をあける）',
        '',
        'この中から、記念の1本を見ていくよ。',
    ]
    for m in p['mem']:
        lines.append('')
        lines.append(f'（記念の1本 {m["idx"]}/{len(p["mem"])}：本塁から黄色い線）')
        for i, lab in enumerate(sorted(m['labels'], key=lambda l: PRIORITY.index(l['key']))):
            lines.append(_sentence(lab, m['h'], i == 0))
        lk = lead_kind(m['h'])
        if lk and not any(l['key'] == 'walkoff' for l in m['labels']):
            lines.append(f'この本塁打で{lk}したよ。')
    lines += [
        '',
        f'左方向に{c["L"]}本、中堅方向に{c["C"]}本、右方向に{c["R"]}本。',
        f'{p["side_phrase"]}がいちばん多いんだ。',
        f'平均は{ft_text(p["avg"])}。黄色い点が、記念の{len(p["mem"])}本だよ。',
        f'勝ち越しや逆転の本塁打は、{p["lead"]}本。',
        '',
        'コレスポでは毎日、MLBの数字を見せていくよ。',
    ]
    return '\n'.join(lines) + '\n'


# --- 書き出し ----------------------------------------------------------------------
def write_mp4(p, path, log=print):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
           '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(p['frames']):
        im, _ = frame(p, i / FPS)
        pr.stdin.write(im.tobytes())
    pr.stdin.close()
    if pr.wait() != 0:
        raise RuntimeError('ffmpeg が失敗')
    log(f'  {path.name}: {p["frames"]}コマ {p["total"]:.2f}秒')


def sheet_times(p):
    """1枚目・点の途中・記念の1本ごと・まとめ。"""
    return [1.0, T_DOTS + (p['dots_end'] - T_DOTS) / 2] + [m['start'] + 2.0 for m in p['mem']] + [p['total'] - 0.5]


def contact_sheet(p, path, times=None, scale=0.25):
    times = times or sheet_times(p)
    tiles = [frame(p, float(t))[0].resize((int(W * scale), int(H * scale)), Image.LANCZOS) for t in times]
    sheet = Image.new('RGB', (sum(t.width for t in tiles) + 12 * (len(tiles) - 1), tiles[0].height), (0, 0, 0))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width + 12
    sheet.save(path)


def main(argv):
    names = {pid: pl['jp'] for pid, pl in json.loads(sc.LOGS.read_text(encoding='utf-8'))['players'].items()}
    OUT.mkdir(parents=True, exist_ok=True)
    for pid in argv[1:]:
        ds = attach_opponents(sc.fetch_player(pid))
        p = plan(ds, names[pid])
        print(pid, names[pid], '全', p['n'], '点', len(p['homers']), '長さ', p['total'], '秒 点', f'{T_DOTS:.1f}〜{p["dots_end"]:.1f}', 'まとめ', f'{p["cards_t"]:.1f}', '勝ち越し・逆転', p['lead'])
        for m in p['mem']:
            h = m['h']
            print('  記念', m['idx'], [(l['key'], l['name'], l['big'] + l['unit']) for l in m['labels']], h['date'], h.get('opp'), h.get('inning'), lead_kind(h))
        (OUT / f'script_{pid}.txt').write_text(script_text(p), encoding='utf-8')
        contact_sheet(p, OUT / f'sheet_{pid}.png')
        write_mp4(p, OUT / f'spray_{pid}.mp4')


if __name__ == '__main__':
    main(sys.argv)
