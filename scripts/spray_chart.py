"""日本人選手の今季本塁打を、方向と飛距離で球場の形に描く素材（縦長 1080x1920、見た目は v2）。

材料は MLB Stats API（statsapi.mlb.com の読み取りだけ）。取った材料は build/spray/raw/ に保存し、
再実行では取り直さない。数字は取った材料だけ。座標のない本塁打は「座標なし」と数えて図から外し、
本数の合計が gameLog の本塁打数と合わなければ描かない（SprayMismatch）。

使い方:
  py -3 scripts/spray_chart.py fetch 660271 ...      # 取得（1秒に1回）→ build/spray/raw/
  py -3 scripts/spray_chart.py render 660271 ...     # build/spray_samples/ へ PNG
  py -3 scripts/spray_chart.py top 3                 # 日本人打者の本塁打の多い順（手元の jp_player_logs_2026.json）
"""
import datetime as dt
import json
import math
import statistics
import sys
import time
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_v2 as sv  # noqa: E402  v2 の色・Oswald・Noto Sans JP・地

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'build/spray/raw'
OUT = ROOT / 'build/spray_samples'
LOGS = ROOT / 'data/jp_player_logs_2026.json'
API = 'https://statsapi.mlb.com'
SEASON = 2026
W, H = 1080, 1920

# --- 座標の変換 ---------------------------------------------------------------
# coordX/coordY は本塁がおおよそ (125, 199)、y は下ほど本塁に近い。1 単位あたりの ft は
# totalDistance と本塁からの座標距離の比の中央値で確かめた値（fit_scale。2026 の日本人打者の本塁打で約 2.4〜2.5）。
HOME_X, HOME_Y = 125.0, 199.0
FT_PER_UNIT = 2.47

# --- 球場の形（汎用。特定の球場をまねない）------------------------------------
FOUL_FT, CENTER_FT = 330.0, 400.0
PX_PER_FT = 1.65
HOME_PX = (540, 1590)

YELLOW = sv.ACCENT          # (214, 250, 70)
WHITE, GREY = sv.WHITE, sv.GREY
LINE = (96, 110, 140)
EMPTY_BOX = (760, 1500, 1080, 1920)   # キャラの入る右下。何も描かない


class SprayMismatch(Exception):
    pass


def to_xy_ft(coord_x, coord_y, ft_per_unit=FT_PER_UNIT):
    """本塁＝原点、x は右（ライト側）、y は中堅方向（真上が正）の ft。"""
    return (coord_x - HOME_X) * ft_per_unit, (HOME_Y - coord_y) * ft_per_unit


def angle_deg(coord_x, coord_y):
    """中堅方向を 0 度、右が正、左が負。"""
    x, y = to_xy_ft(coord_x, coord_y)
    return math.degrees(math.atan2(x, y))


def fit_scale(homers):
    """totalDistance ÷ 座標上の距離（単位）の中央値と、そのばらつき（四分位幅）。"""
    r = [h['dist'] / math.hypot(h['x'] - HOME_X, HOME_Y - h['y']) for h in homers
         if math.hypot(h['x'] - HOME_X, HOME_Y - h['y']) > 20]
    q = statistics.quantiles(r, n=4) if len(r) >= 4 else [min(r), statistics.median(r), max(r)]
    return statistics.median(r), (q[0], q[-1]), len(r)


def to_px(dist_ft, ang_deg):
    a = math.radians(ang_deg)
    return (HOME_PX[0] + dist_ft * PX_PER_FT * math.sin(a), HOME_PX[1] - dist_ft * PX_PER_FT * math.cos(a))


def side(ang):
    return 'L' if ang < -15 else 'R' if ang > 15 else 'C'


def meters(ft):
    return float(Decimal(str(ft * 0.3048)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


# --- 取得（キャッシュ）---------------------------------------------------------
_last = [0.0]


def _get(url):
    wait = 1.05 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={'User-Agent': 'collespo-spray/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _cached(name, url, trim=None):
    p = RAW / name
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    data = _get(url)
    if trim:
        data = trim(data)
    RAW.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data


def _trim_pbp(data):
    """本塁打の打席だけ残す（容量を抑える）。"""
    return {'allPlays': [p for p in data.get('allPlays', []) if (p.get('result') or {}).get('eventType') == 'home_run']}


def fetch_player(pid, log=print):
    """gameLog と、本塁打のある試合の play-by-play を取り、データセットを返す。"""
    gl = _cached(f'{pid}_gamelog.json',
                 f'{API}/api/v1/people/{pid}/stats?stats=gameLog&group=hitting&season={SEASON}&gameType=R')
    splits = (gl.get('stats') or [{}])[0].get('splits') or []
    hr_games = [(s['date'], s['game']['gamePk'], s['stat'].get('homeRuns', 0)) for s in splits if s['stat'].get('homeRuns')]
    gl_total = sum(n for _, _, n in hr_games)
    homers, no_coords = [], 0
    for date, pk, n in sorted(hr_games):
        pbp = _cached(f'pbp_{pk}.json', f'{API}/api/v1/game/{pk}/playByPlay', _trim_pbp)
        found = 0
        for play in pbp['allPlays']:
            if play['matchup']['batter']['id'] != int(pid):
                continue
            found += 1
            ev = next((e for e in play.get('playEvents', []) if e.get('hitData')), None) or {}
            hd = ev.get('hitData')
            res, ab = play.get('result') or {}, play.get('about') or {}
            co = (hd or {}).get('coordinates') or {}
            if hd and co.get('coordX') is not None and co.get('coordY') is not None and hd.get('totalDistance'):
                homers.append(dict(date=date, game_pk=pk, at_bat=play['about']['atBatIndex'],
                                   x=co['coordX'], y=co['coordY'], dist=hd['totalDistance'],
                                   ls=hd.get('launchSpeed'), la=hd.get('launchAngle'),
                                   traj=hd.get('trajectory'),
                                   pitch_mph=(ev.get('pitchData') or {}).get('startSpeed'),
                                   pitch_type=((ev.get('details') or {}).get('type') or {}).get('code'),
                                   rbi=res.get('rbi'), inning=ab.get('inning'), top=ab.get('isTopInning'),
                                   home_after=res.get('homeScore'), away_after=res.get('awayScore')))
            else:
                no_coords += 1
        if found != n:
            log(f'  注意: {pid} {date} gameLog {n}本 / play-by-play {found}本')
    return dict(player_id=int(pid), season=SEASON, gamelog_hr=gl_total, no_coords=no_coords,
                homers=homers, acquired=dt.date.today().isoformat(), source='MLB Stats API')


def top_japanese(n=3):
    d = json.loads(LOGS.read_text(encoding='utf-8'))
    rows = [(sum(g['stat']['homeRuns'] for g in p['hitting']), pid, p['jp']) for pid, p in d['players'].items() if p['hitting']]
    return sorted(rows, reverse=True)[:n]


def check_counts(ds):
    """図の点＋座標なし＝gameLog の本塁打数。合わなければ描かない。"""
    got = len(ds['homers']) + ds['no_coords']
    if got != ds['gamelog_hr']:
        raise SprayMismatch(f"本数が合わない: 図{len(ds['homers'])}＋座標なし{ds['no_coords']} ≠ gameLog {ds['gamelog_hr']}")
    return got


# --- 描画 ----------------------------------------------------------------------
def _arc_points(step=1.0):
    pts, a = [], -45.0
    while a <= 45.0 + 1e-9:
        r = FOUL_FT + (CENTER_FT - FOUL_FT) * math.cos(math.radians(2 * a))
        pts.append(to_px(r, a))
        a += step
    return pts


def _chip(d, box, label, value, vsize=46):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=18, fill=(22, 36, 70), outline=(52, 68, 106), width=2)
    lf = sv.jp(28, 'Medium')
    d.text(((x0 + x1) / 2, y0 + 14), label, font=lf, fill=GREY, anchor='ma')
    size = vsize
    vf = sv.num(size)
    while vf.getlength(value) > (x1 - x0) - 24 and size > 24:
        size -= 2
        vf = sv.num(size)
    d.text(((x0 + x1) / 2, y1 - 14), value, font=vf, fill=WHITE, anchor='ms')


def render(ds, name_jp, today=None):
    """PNG（PIL.Image）と、描いた内容の記録を返す。"""
    from PIL import ImageDraw
    check_counts(ds)
    today = today or dt.date.today().isoformat()
    homers = sorted(ds['homers'], key=lambda h: (h['date'], h['at_bat']))
    for h in homers:
        h['ang'] = max(-44.0, min(44.0, angle_deg(h['x'], h['y'])))   # ポール際は線の内側に寄せて描く
    longest = max(homers, key=lambda h: h['dist'])
    latest = homers[-1]
    im = sv._base(W, H).copy()
    d = ImageDraw.Draw(im, 'RGBA')

    # 見出し
    size = 120 if len(name_jp) <= 6 else 96
    d.text((W / 2, 110), name_jp, font=sv.jp(size, 'Black'), fill=WHITE, anchor='ma')
    n = ds['gamelog_hr']
    nf, lf, uf = sv.num(260), sv.jp(50, 'Bold'), sv.jp(60, 'Bold')
    pre, post = '今季本塁打 全', '本'
    pw, nw, qw = lf.getlength(pre), nf.getlength(str(n)), uf.getlength(post)
    x = (W - (pw + nw + qw + 24)) / 2
    base_y = 520
    d.text((x, base_y), pre, font=lf, fill=GREY, anchor='ls')
    d.text((x + pw + 12, base_y + 22), str(n), font=nf, fill=WHITE, anchor='ls')
    d.text((x + pw + nw + 24, base_y), post, font=uf, fill=WHITE, anchor='ls')

    # 札3つ
    dist = [h['dist'] for h in homers]
    avg = sum(dist) / len(dist)
    cnt = {'L': 0, 'C': 0, 'R': 0}
    for h in homers:
        cnt[side(h['ang'])] += 1
    ft = lambda v: f'{round(v)}ft / {meters(round(v)):.1f}m'
    cx0, cw, gap, cy0, ch = 60, 300, 30, 580, 130
    chips = [('最長', ft(longest['dist'])), ('平均', ft(avg)), ('左・中・右', f"{cnt['L']} / {cnt['C']} / {cnt['R']}")]
    for i, (lab, val) in enumerate(chips):
        _chip(d, (cx0 + i * (cw + gap), cy0, cx0 + i * (cw + gap) + cw, cy0 + ch), lab, val, 40 if i < 2 else 56)

    # 黄の点の説明（何を示すか分からないと読めないため）
    lg = sv.jp(34, 'Medium')
    note = '最長の1本' if longest is latest else '最長の1本と最新の1本'
    tw = lg.getlength(note)
    lx = (W - tw - 40) / 2
    d.ellipse((lx, 762, lx + 26, 788), fill=YELLOW)
    d.text((lx + 40, 775), note, font=lg, fill=GREY, anchor='lm')

    # 球場（線だけ）
    arc = _arc_points()
    d.line(arc, fill=LINE, width=4, joint='curve')
    d.line([HOME_PX, arc[0]], fill=LINE, width=4)
    d.line([HOME_PX, arc[-1]], fill=LINE, width=4)
    for ring in (200, 300):   # 距離の目安（薄い円弧と ft）
        pts = [to_px(ring, a) for a in range(-45, 46, 3)]
        d.line(pts, fill=(60, 74, 108), width=2)
        d.text((pts[-1][0] + 8, pts[-1][1]), f'{ring}ft', font=sv.jp(24, 'Medium'), fill=sv.DIM, anchor='lm')
    d.text((to_px(CENTER_FT, 0)[0], to_px(CENTER_FT, 0)[1] + 34), f'{int(CENTER_FT)}ft', font=sv.jp(24, 'Medium'), fill=sv.DIM, anchor='ms')
    hx, hy = HOME_PX
    d.polygon([(hx, hy + 8), (hx - 10, hy - 2), (hx - 10, hy - 12), (hx + 10, hy - 12), (hx + 10, hy - 2)], fill=WHITE)

    # 点（最長と最新だけ黄。数字は載せない）
    marks = []
    for h in homers:
        px, py = to_px(h['dist'], h['ang'])
        yellow = h is longest or h is latest
        if yellow:
            marks.append((px, py))
            continue
        d.ellipse((px - 10, py - 10, px + 10, py + 10), fill=(244, 246, 250, 215))
    for px, py in marks:
        d.ellipse((px - 17, py - 17, px + 17, py + 17), fill=YELLOW)

    # 出典
    sf = sv.jp(28, 'Medium')
    lines = ['データ: MLB Stats API（座標と飛距離）', f'取得 {ds["acquired"]}']
    if ds['no_coords']:
        lines.append(f'座標なし {ds["no_coords"]}本は図から除く')
    for i, s in enumerate(lines):
        assert sf.getlength(s) < EMPTY_BOX[0] - 60, s   # 右下の空きに食い込まない
        d.text((60, 1810 + 40 * i), s, font=sf, fill=GREY, anchor='ls')
    info = dict(n=n, plotted=len(homers), no_coords=ds['no_coords'], yellow=[(round(x), round(y)) for x, y in marks],
                longest=longest['dist'], avg=avg, lcr=cnt)
    return im.convert('RGB'), info


def main(argv):
    cmd, ids = argv[1], argv[2:]
    if cmd == 'top':
        for r in top_japanese(int(ids[0]) if ids else 3):
            print(r)
        return
    names = {pid: p['jp'] for pid, p in json.loads(LOGS.read_text(encoding='utf-8'))['players'].items()}
    for pid in ids:
        ds = fetch_player(pid)
        print(pid, names.get(pid), 'gameLog', ds['gamelog_hr'], '図', len(ds['homers']), '座標なし', ds['no_coords'])
        if cmd == 'render':
            try:
                im, info = render(ds, names[pid])
            except SprayMismatch as e:
                print('  描かない:', e)
                continue
            OUT.mkdir(parents=True, exist_ok=True)
            im.save(OUT / f'spray_{pid}.png')
            print('  ', info)
    return


if __name__ == '__main__':
    main(sys.argv)
