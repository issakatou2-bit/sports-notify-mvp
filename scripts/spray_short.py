"""本塁打の図（spray_chart.py）を使った縦長ショート（1080x1920、30fps、25〜35秒、無音）の見本。

公開しない・本番の型に繋がない。見た目は v2（style_v2.py）。
  0〜2秒   1枚目：選手名・「今季本塁打 全N本」・短い結論の句（数字は材料の値だけ）
  2秒〜    球場の線 → 本塁打の点を日付順に1つずつ（一定の間隔）。右上に「k/N」
  最後の8秒 札3つ（最長・平均・左中右）＋黄の点の説明＋最長の1本の日付と相手
右下（EMPTY_BOX）はキャラ用に空ける。frame(plan, t) は時刻 t の純関数。

使い方:
  py -3 scripts/spray_short.py 808959 672960 660271     # build/spray_short_samples/ へ MP4・台本・コマの並び
"""
import datetime as dt
import json
import math
import subprocess
import sys
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
DOTS_SPAN = 13.5       # 点を置く全体の目安（秒）。1本あたりの間隔は min(0.6, これ÷本数)
MAX_STEP = 0.6
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
    cards_t = dots_end + 0.5
    total = min(MAX_TOTAL, max(MIN_TOTAL, cards_t + 8.0))
    total = round(total * FPS) / FPS
    cnt = {'L': 0, 'C': 0, 'R': 0}
    for h in homers:
        cnt[sc.side(h['ang'])] += 1
    avg = sum(h['dist'] for h in homers) / k
    side_word = {'L': '左方向', 'C': '中堅方向', 'R': '右方向'}
    top = max('LCR', key=lambda s: (cnt[s], s == 'C'))
    phrases = [f'{side_word[top]}へ{cnt[top]}本', f'最長は{ft_text(longest["dist"])}']
    return dict(name=name_jp, n=n_all, homers=homers, longest=longest, latest=latest, step=step,
                dots_end=dots_end, cards_t=cards_t, total=total, frames=round(total * FPS),
                cnt=cnt, avg=avg, phrases=phrases, no_coords=ds['no_coords'], acquired=ds['acquired'])


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
    key = ('c', p['name'], p['n'], p['longest']['dist'], round(p['avg']), tuple(p['cnt'].values()))
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
        note = '最長の1本' if p['longest'] is p['latest'] else '最長の1本と最新の1本'
        lx = (W - lg.getlength(note) - 40) / 2
        d.ellipse((lx, LEGEND_Y - 13, lx + 26, LEGEND_Y + 13), fill=sv.ACCENT)
        d.text((lx + 40, LEGEND_Y), note, font=lg, fill=sv.GREY, anchor='lm')
        lo = p['longest']
        s = f'最長の1本は{md(lo["date"])}' + (f'　{lo["opp"]}戦' if lo.get('opp') else '')
        d.text((W / 2, LONGEST_Y), s, font=sv.jp(40, 'Bold'), fill=sv.WHITE, anchor='mm')
        _cache[key] = lay
    return _cache[key]


def _dots_layer(p, t):
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    placed = 0
    ya = sv.ease_out((t - p['cards_t']) / CARDS_FADE)
    yellow = []
    for h in p['homers']:
        a = sv.ease_out((t - h['t']) / DOT_FADE)
        if a <= 0:
            continue
        placed += 1
        px, py = h['px']
        is_y = h is p['longest'] or h is p['latest']
        if is_y and ya > 0:
            r = 10 + 7 * ya
            col = sv.mix(sv.WHITE, sv.ACCENT, ya)
            if ya >= 1:
                yellow.append((round(px), round(py)))
            d.ellipse((px - r, py - r, px + r, py + r), fill=col + (255,))
        else:
            r = 10 * (0.7 + 0.3 * a)
            d.ellipse((px - r, py - r, px + r, py + r), fill=(244, 246, 250, int(215 * a)))
    return lay, placed, yellow


def _with_alpha(lay, a):
    if a >= 1:
        return lay
    out = lay.copy()
    out.putalpha(out.getchannel('A').point(lambda v: int(v * a)))
    return out


def frame(p, t):
    """時刻 t の絵（RGB）と記録（点の数・黄の点の位置）を返す。"""
    im = sv.background(t, W, H)
    im.alpha_composite(_header(p))
    info = dict(placed=0, yellow=[], count_text=None)
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
        if placed:
            ImageDraw.Draw(scene).text((W - 64, 70), f'{placed}/{len(p["homers"])}', font=sv.num(96), fill=sv.WHITE, anchor='ra')
            info['count_text'] = f'{placed}/{len(p["homers"])}'
        ca = sv.ease_out((t - p['cards_t']) / CARDS_FADE)
        if ca > 0:
            scene.alpha_composite(_with_alpha(_cards_layer(p), ca))
        s = sv.shifted(scene, dx, al)
        if s:
            im.alpha_composite(s)
    return im.convert('RGB'), info


# --- 台本案 ----------------------------------------------------------------------
def script_text(p):
    lo, c = p['longest'], p['cnt']
    where = f'{lo["opp"]}戦の' if lo.get('opp') else ''
    lines = [
        f'{p["name"]}、今季の本塁打は全部で{p["n"]}本だよ。',
        f'全部の打球を、球場の図に置いてみたよ。日付の順に出すね。',
        '',
        '（点が日付順に1つずつ出る間は、言葉を入れずに間をあける）',
        '',
        f'左方向に{c["L"]}本、中堅方向に{c["C"]}本、右方向に{c["R"]}本。',
        f'{p["phrases"][0]}がいちばん多いんだ。',
        f'いちばん遠くへ飛んだのは、{md(lo["date"])}の{where}{ft_text(lo["dist"])}、約{sc.meters(round(lo["dist"])):.1f}メートル。',
        f'平均は{ft_text(p["avg"])}だよ。黄色い点が、最長の1本{"" if p["longest"] is p["latest"] else "と最新の1本"}。',
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


def contact_sheet(p, path, times=(1, 6, 14, 24), scale=0.25):
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
        print(pid, names[pid], '全', p['n'], '点', len(p['homers']), '長さ', p['total'], '秒 点', f'{T_DOTS:.1f}〜{p["dots_end"]:.1f}', '札', f'{p["cards_t"]:.1f}')
        (OUT / f'script_{pid}.txt').write_text(script_text(p), encoding='utf-8')
        contact_sheet(p, OUT / f'sheet_{pid}.png')
        write_mp4(p, OUT / f'spray_{pid}.mp4')


if __name__ == '__main__':
    main(sys.argv)
