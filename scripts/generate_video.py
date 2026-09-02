"""
ナレーション音声と試合データから、縦型のショート動画を生成する。

設計:
  ・音声の実測長(manifest.json)に合わせて各画面の表示時間を決めるため、
    ナレーションと画面がズレない。
  ・静止画の切り替えではなく、フレームを1枚ずつ描いて動かす
    (数字のカウントアップ、カードのスライドイン、ゆっくりした背景の動き)。
  ・画像素材は使わず、全てプログラムで描画する。
    著作権上の懸念が無く、毎日安定した品質で出せるため。

出力: build/video/collespo_short.mp4

使い方:
  python3 scripts/generate_video.py \
      --games notable_games.json --audio-dir build/audio --out build/video
"""

import argparse
import functools
import json
import os
import pathlib
import subprocess
import sys

import post_common  # noqa: E402
import video_common  # noqa: E402

# フォントと ease_out は video_common に1つだけ置いてある。
#
# ここに自前で持っていたときは、候補の一覧が3〜6件でばらつき、
# キャッシュが付いているものと付いていないものがあった。
# 直したものが他へ届かない、という形をここで断つ。
font = video_common.font
ease_out = video_common.ease_out
FONT_CANDIDATES = video_common.FONT_CANDIDATES


from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    from notability_engine import reason_label
except ImportError:  # ラベルが引けなくても動画自体は作れるようにする
    def reason_label(tag):
        return tag or "その他の理由"

W, H = 1080, 1920
# 24fpsにしているのは生成時間のため。フレームを1枚ずつPNGに書き出す方式なので、
# 枚数がそのまま時間に効く(30fpsだと約4分、24fpsだと約3分)。
# 情報番組的な内容では、なめらかさより生成の速さを優先してよいと判断した。
FPS = 24

# 各セグメントのアニメーションが完了する進捗。これを過ぎたフレームは
# 見た目が変わらないため、描き直さず直前のフレームを使い回す。
# 1枚ずつ描画すると枚数がそのまま生成時間になるので、
# 静止している区間を省くだけで大幅に短縮できる。
ANIM_END = 0.45

BG = (11, 14, 20)
SURF = (18, 22, 31)
SURF2 = (23, 28, 39)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
ACCENT_DIM = (74, 58, 26)
JP = (73, 197, 182)

# 日本語フォントの場所は環境によって違う(手元のコンテナとGitHub Actionsの
# ランナーでは入っているフォントが異なる)。決め打ちにすると片方で必ず落ちるため、
# 候補を順に探し、最後はfc-matchでシステムに問い合わせる。




def _resolve_font_file() -> str:
    """使える日本語フォントのパスを1つ決める。見つからなければ例外。"""
    global _FONT_FILE
    if _FONT_FILE:
        return _FONT_FILE

    # 手元(Windows等)で動作確認するとき用の逃げ道。
    # CIではLinuxの候補が先に見つかるので、本番の見た目は変わらない。
    env = os.environ.get("COLLESPO_FONT")
    if env and pathlib.Path(env).exists():
        _FONT_FILE = env
        print(f"[info] 使用フォント(COLLESPO_FONT): {env}")
        return _FONT_FILE

    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            _FONT_FILE = path
            print(f"[info] 使用フォント: {path}")
            return _FONT_FILE

    # 候補に無ければ、システムに日本語フォントを問い合わせる
    try:
        r = subprocess.run(
            ["fc-match", "-f", "%{file}", ":lang=ja"],
            capture_output=True, text=True, check=True,
        )
        candidate = r.stdout.strip()
        if candidate and pathlib.Path(candidate).exists():
            _FONT_FILE = candidate
            print(f"[info] 使用フォント(fc-match): {candidate}")
            return _FONT_FILE
    except Exception:
        pass

    raise RuntimeError(
        "日本語フォントが見つかりません。"
        "ワークフローで fonts-noto-cjk をインストールしてください。"
    )


# フォントは1度読んだら使い回す。
#
# ImageFont.truetype はそのつどファイルを開いて読む。描画1枚のうちに
# 何十回も呼ぶので、1本の動画で数万回ファイルを開いていた。
# 大きさの種類は10個ほどしかない。読み直す理由が無い。
def fit_size(draw, text: str, max_w: int, sizes) -> int:
    """その幅に収まる最大の文字サイズ。収まらなければ最小を返す。"""
    for s in sizes:
        if draw.textlength(text, font=font(s)) <= max_w:
            return s
    return sizes[-1]


# 折り返しは video_common の正本を使う。
# 4本が自前で持っていて、禁則を入れたのは1本だけだった。
wrap = video_common.wrap

# いま何枚目か。描画のたびに引数で回すと全関数の引数が増えるので、
# 1本を順に描くだけのこの処理では、ここに置いて描画側から読む。
_STEP = 0
_STEPS = 0


def set_step(step: int, steps: int) -> None:
    global _STEP, _STEPS
    _STEP, _STEPS = step, steps


def _draw_steps(d) -> None:
    """
    画面の上に、何枚中の何枚目かを出す。

    ショートは77.7%がスワイプで消される。残りがどれくらいかが分からないと、
    途中で「まだ続くのか」と思われて終わる。あと2枚だと見えていれば、
    そこまでは見てもらえる。

    連続して伸びるバーにしないのは、フレームごとに絵が変わると
    描画結果を使い回せなくなり、生成時間が跳ね上がるため。
    1枚ごとに1目盛り進む形なら、動きは十分に伝わって費用はかからない。
    """
    if _STEPS < 2:
        return
    pad, gap, h = 48, 10, 8
    w = (W - pad * 2 - gap * (_STEPS - 1)) / _STEPS
    for i in range(_STEPS):
        x = pad + i * (w + gap)
        col = ACCENT if i <= _STEP else (44, 52, 66)
        d.rounded_rectangle([x, 30, x + w, 30 + h], h // 2, fill=col)


# いま読み上げている文。画面の下に出す。
# 読み上げだけで画面に何も無いと、聞き取れなかった人が確かめる先が無い。
# 音を切って見ている人には、そもそも届かない。
_SPOKEN = ""

# 画面下に出す読み上げ文の上限。超えたぶんは「…」で切る。
SPOKEN_MAX = 90


def set_spoken(text: str) -> None:
    global _SPOKEN
    _SPOKEN = (text or "").strip()


def draw_spoken(d) -> None:
    """読み上げの文を画面の下に置く。長い回は先頭だけにする。"""
    if not _SPOKEN:
        return
    text = _SPOKEN
    if len(text) > SPOKEN_MAX:
        text = text[:SPOKEN_MAX].rstrip("、。") + "…"
    lines = wrap(d, text, font(34), W - 200)[:3]
    h = len(lines) * 46 + 36
    # いちばん下には collespo.com が置いてある。その上に載せる。
    y = H - 260 - h
    d.rounded_rectangle([60, y, W - 60, y + h], 18, fill=(16, 20, 28))
    d.rounded_rectangle([60, y, 68, y + h], 4, fill=ACCENT)
    for i, ln in enumerate(lines):
        d.text((92, y + 18 + i * 46), ln, font=font(34), fill=DIM)


def base_frame(progress: float):
    """全画面共通の下地。背景がゆっくり動いて単調さを避ける。"""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # ゆっくり流れる斜めのアクセント
    # 背景はANIM_ENDで動きを止める。ここが動き続けると全フレームが
    # 微妙に異なり、描画結果を使い回せなくなるため。
    offset = int(min(progress, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + offset
        d.polygon(
            [(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
            fill=(14, 18, 26),
        )
    # 下地に、競技そのものの線を薄く敷く。
    #
    # 写真もAIが描いた絵も使わない。前者は権利の管理が毎日の負債になり、
    # 後者は「実在しない球場」を事実の隣に置くことになる。
    # 内野のダイヤモンドなら、線を数本引くだけで何の番組かが伝わる。
    # 背景との差を小さく取って、文字の邪魔をしない濃さにする。
    _draw_field(d)

    # 下端の帯は、単色から左端だけ明るい段階にする。
    # 平らな1色より奥行きが出るが、色数は増やさない。
    # 視聴者の73.5%が45歳以上なので、派手さより輪郭の明快さを優先する。
    for i in range(24):
        x0 = int(W * i / 24)
        x1 = int(W * (i + 1) / 24)
        k = 1.0 - i / 40
        d.rectangle([x0, H - 22, x1, H],
                    fill=tuple(int(c * k) for c in ACCENT))
    _draw_steps(d)
    draw_spoken(d)
    return im, d


# 下地の線の濃さ。背景(11,14,20)からわずかに上げるだけ。
# ここを上げると文字が読みにくくなる。装飾ではなく、質感として置く。
FIELD_LINE = (27, 34, 47)


def _draw_field(d) -> None:
    """
    内野のダイヤモンドを、画面の下側に薄く敷く。

    素材を持たないので、線で描く。実在の球場を模したものではなく、
    競技の記号として置く。毎日同じものが出るので、生成の費用も増えない。
    """
    cx, cy, r = W // 2, int(H * 0.78), 430
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
              outline=FIELD_LINE, width=6)
    # 内側にもう1つ。二重にすると、ただの菱形ではなく塁線に見える。
    r2 = int(r * 0.62)
    d.polygon([(cx, cy - r2), (cx + r2, cy), (cx, cy + r2), (cx - r2, cy)],
              outline=FIELD_LINE, width=4)


def card(d, x0, y0, x1, y1, stripe=None, fill=None):
    """
    このチャンネルのカード。角丸の面と、左端の色帯。

    画面ごとにばらばらの箱を置いていたので、揃えた。同じ形が並ぶと
    「どこからどこまでが1つの話か」が一目で分かる。
    視聴者の73.5%が45歳以上なので、装飾ではなく区切りとして効かせる。
    """
    d.rounded_rectangle([x0, y0, x1, y1], 26, fill=fill or SURF)
    if stripe:
        d.rounded_rectangle([x0, y0, x0 + 16, y1], 8, fill=stripe)


def label_chip(d, x, y, text, color, fg=None):
    """小さな見出しの札。「先発予定」のような区分に使う。"""
    f = font(30)
    w = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + w + 32, y + 46], 10, fill=color)
    d.text((x + 16, y + 4), text, font=f, fill=fg or (11, 14, 20))
    return y + 62


def draw_brand(d, small=False):
    d.text((70, 70), "コレスポ", font=font(46 if small else 56), fill=ACCENT)


def team_badge(d, x, y, abbr, color, w=118, h=64):
    if not abbr:
        return
    col = color or (60, 66, 80)
    if isinstance(col, str) and col.startswith("#"):
        col = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
    lum = (0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]) / 255
    fg = (17, 17, 17) if lum > 0.6 else (255, 255, 255)
    d.rounded_rectangle([x, y, x + w, y + h], 12, fill=col)
    f = font(34)
    tw = d.textlength(abbr, font=f)
    d.text((x + (w - tw) / 2, y + 12), abbr, font=f, fill=fg)


def render_intro(progress: float, date_label: str, meta: dict = None):
    """
    1枚目。ここで視聴者はスワイプするかどうかを決める。

    以前は「コレスポ」のロゴと日付だけを出していたが、それは視聴者にとって
    情報がゼロで、最も離脱されやすい入り方だった。今はその日いちばん具体的な
    事実(選手名+記録、連勝数など)を最初に大きく出し、名乗りは下に小さく置く。

    文字だけで成立させているのは、ショートの多くが音声を切って見られるため。
    ナレーションと同じ内容を画面にも出しておけば、無音でも意味が通る。
    """
    im, d = base_frame(progress)
    hook = (meta or {}).get("hook") or {}
    big = hook.get("big") or f"{date_label} の注目試合"
    # カタカナがあればそちら(読み上げと同じ表記にする)
    sub = hook.get("sub_jp") or hook.get("sub") or ""

    e = ease_out(min(1.0, progress * 2.6))
    slide = int((1 - e) * 70)

    # 見出しは1行で見せたい。文字数から推測するとフォントによって外すので、
    # 実際に幅を測って収まる最大のサイズを選ぶ。
    # (「4試合連続安打中」の「中」だけが次行に落ちる、といったことを防ぐ)
    max_w = W - 160
    size = 72
    for s in (128, 116, 104, 92, 80, 72):
        if d.textlength(big, font=font(s)) <= max_w:
            size = s
            break
    lines = wrap(d, big, font(size), max_w)[:3]

    # 塊は上寄せにする。
    #
    # 以前は縦の中央に置いていたが、上に600ピクセル近い空白ができていた。
    # ショートの画面はいちばん下がUIに隠れ、実際に読めるのは上から2/3。
    # 中央に置くと、その読める範囲の下端に文字が来ることになる。
    line_h = int(size * 1.22)
    y = 380

    if sub:
        d.text((80, y + slide), sub, font=font(72), fill=JP)
        y += 120

    for line in lines:
        d.text((80, y + slide), line, font=font(size), fill=ACCENT)
        y += line_h

    if progress > 0.14:
        # 見出しの材料が無い日は big がこの文言に落ちる。
        # そのまま下にも同じものを出すと、1枚目で同じ行を2回読ませることになる。
        sub_line = f"{date_label} の注目試合"
        if big != sub_line:
            d.text((80, y + 40), sub_line, font=font(52), fill=TEXT)

    # 空いた下半分に、その日いちばんの試合を置く。
    # 1枚目で「で、どの試合なの」に答えられていなかった。
    # ここが埋まっていれば、音を切って見ている人にも用件が伝わる。
    #
    # 塗りにしているのは、ショートのサムネがこの1枚目そのものだから。
    # 以前は暗い面に灰色の文字で置いていたが、一覧に小さく並んだときに
    # 何も読めない。明るい塊を1つ作ると、縮小しても残る。
    top = (meta or {}).get("top_game") or {}
    if top.get("matchup") and progress > 0.22:
        e2 = ease_out(min(1.0, (progress - 0.22) * 4))
        y2 = 1020 + int((1 - e2) * 50)
        mf = font(fit_size(d, top["matchup"], W - 240, (66, 58, 50, 44)))
        d.rounded_rectangle([60, y2, W - 60, y2 + 250], 26, fill=ACCENT)
        d.text((110, y2 + 36), top.get("time") or "", font=font(44),
               fill=(92, 58, 8))
        d.text((110, y2 + 110), top["matchup"], font=mf, fill=BG)

    d.text((80, H - 170), "コレスポ　collespo.com", font=font(38), fill=DIM)
    return im


_PS_TEAMS = None


def ps_teams() -> dict:
    """球団IDで引く、いまの勝敗と立ち位置。無ければ空。

    進出争いの回のために毎日取っている順位表を、そのまま使う。
    「73勝67敗・3連敗中・ワイルドカードまで0.5」は、
    APIを叩き直さずにここで出せる。
    """
    global _PS_TEAMS
    if _PS_TEAMS is None:
        try:
            _PS_TEAMS = json.loads(pathlib.Path(
                "data/postseason.json").read_text(encoding="utf-8")
            ).get("teams") or {}
        except (OSError, ValueError):
            _PS_TEAMS = {}
    return _PS_TEAMS


@functools.lru_cache(maxsize=64)
def team_jp_names(tid: str) -> list:
    """その球団にいる日本人選手。取れなければ空。

    フレームごとに呼ばれるので、球団IDで覚えておく
    (1本の動画で数千回になる)。

    試合データの jp_players は両チーム分がひとまとめなので、
    どちらの球団の選手かが分からない。球団ごとの一覧は
    進出争いのために毎日作っているので、そちらから引く。
    """
    try:
        js = json.loads(pathlib.Path("data/postseason.json").read_text(
            encoding="utf-8")).get("japanese") or []
    except (OSError, ValueError):
        return []
    for x in js:
        if str(x.get("team_id")) == str(tid):
            return list(x.get("players") or [])
    return []


def flag_jp(d, x, y, w=46, h=32):
    """日の丸。**絵文字は日本語フォントに無い**ので、描く。

    「JP」の札より、こちらのほうが一瞬で分かる。
    日本人投手が投げる日だとひと目で伝わることが、この枠の要。
    """
    d.rounded_rectangle([x, y, x + w, y + h], 5, fill=(250, 250, 250))
    r = int(h * 0.32)
    cx, cy = x + w / 2, y + h / 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(188, 0, 45))
    return x + w + 12


def team_standing(tid: str) -> list:
    """その球団のいまを、短い部品に分けて返す。

    「82勝56敗」「3連勝中」「ナ・リーグ第2シード」の3つ。
    毎日変わる数字なので、同じ対戦カードでも画面が同じにならない。

    1本の文字列で返さないのは、**右に日本人選手の名前が入る日**が
    あるため。幅が足りない日は、呼ぶ側が後ろから落とす。
    大事な順に並べてある(勝敗 → 立ち位置 → 連勝)。
    """
    t = ps_teams().get(str(tid)) or {}
    if not t.get("w"):
        return []
    out = ["%d勝%d敗" % (t["w"], t.get("l") or 0)]
    # 「ナ・リーグ第2シード」だけだと、もう決まった順位に読める。
    # シードは毎日入れ替わるもので、**今日終わったらこうなる**という
    # 途中経過でしかない。「現在」を付けて、そこを曖昧にしない。
    if t.get("clinched"):
        out.append("進出決定")
    elif t.get("seed"):
        out.append("現在%s第%dシード" % (t.get("league_jp") or "", t["seed"]))
    elif t.get("wc_gb") not in (None, "-"):
        out.append("現在ワイルドカードまで%s" % t["wc_gb"])
    s = t.get("streak") or ""
    if len(s) >= 2 and s[0] in "WL" and s[1:].isdigit() and int(s[1:]) >= 2:
        out.append("%d%s中" % (int(s[1:]), "連勝" if s[0] == "W" else "連敗"))
    return out


def render_game(progress: float, g: dict, index: int, total: int):
    im, d = base_frame(progress)
    draw_brand(d, small=True)

    # 上の1行に、何本目かと開始時刻を並べる。
    # 縦に2つ積んでいたが、どちらも「案内」で、中身ではない。
    d.text((70, 150), f"PICK {index + 1} / {total}", font=font(34),
           fill=ACCENT)
    # 未明の試合はそう書き添える。20時に見ている人にとって「4:00」は
    # 今夜の続きで、翌日の昼ではない。判定は post_common に1本化してある。
    when = post_common.kickoff_display(g.get("start_time_jst") or "") + " JST"
    d.text((W - 70 - d.textlength(when, font=font(38)), 148), when,
           font=font(38), fill=DIM)

    # --- 対戦カード ---
    #
    # 1枚の箱に2球団を積んでいた。球団ごとに言えること
    # (勝敗・連勝・先発・日本人選手)が増えたので、**球団ごとに1枚**にする。
    # 箱の色帯はその球団の色。並べたときにどちらの話か迷わない。
    e = ease_out(min(1.0, progress * 3.2))
    dx = int((1 - e) * 160)
    jp_names = list(g.get("jp_players") or [])
    starters = {s.get("name") for s in (g.get("jp_starters") or [])}
    # 日本人選手の名前を、球団の欄に置けたかどうか。
    # 置けた日は、下の理由の箱に「◯◯が所属」を書かない。
    # **置けなかった日(サッカー)は書く。**そこが唯一の手がかりなので、
    # 消すと日本人選手が出る試合だと分からなくなる。
    shown_jp = False
    # 箱の中身は、行ごとに置く。
    #
    # 1行に詰め込んで、入らないぶんを削っていた。実際に描いてみたら
    # 「82勝56敗・現在ナ・リーグ第2シード」から**シードのほうが落ちて**、
    # 残ったのが勝敗だけ。日本人選手が2人いる球団ほどそうなる。
    # 落とすのではなく、行を増やす。
    #
    # 高さも中身で決める。サッカーは先発も順位表も無いので、
    # MLBと同じ高さにすると名前1つの下に120pxの空白が残る。
    def rows_of(side):
        jp = [n for n in jp_names if n not in starters
              and n in team_jp_names(g.get(f"{side}_team_id"))]
        return (team_standing(g.get(f"{side}_team_id")), jp,
                g.get(f"{side}_probable") or {})

    tops, hs, rows = [], [], {}
    yy = 236
    for side in ("home", "away"):
        st, jp, p = rows_of(side)
        rows[side] = (st, jp, p)
        h = 118 + (54 if st else 0) + (50 if jp else 0) + (62 if p.get("name")
                                                           else 0)
        tops.append(yy)
        hs.append(h)
        yy += h + 20

    for i, side in enumerate(("home", "away")):
        col = g.get(f"{side}_color") or "#3C4250"
        if isinstance(col, str) and col.startswith("#"):
            col = tuple(int(col[k:k + 2], 16) for k in (1, 3, 5))
        col = video_common.lift_color(
            "#%02X%02X%02X" % col if isinstance(col, tuple) else col, ACCENT)
        top = tops[i]
        card(d, 60 - dx, top, W - 60 - dx, top + hs[i], stripe=col,
             fill=video_common.blend(SURF, col, 0.10))
        team_badge(d, 100 - dx, top + 24, g.get(f"{side}_abbr"),
                   g.get(f"{side}_color"))
        name = g.get(f"{side}_team_name", "")
        d.text((240 - dx, top + 18), name,
               font=font(fit_size(d, name, W - 540, (56, 50, 44, 38))),
               fill=TEXT)
        tag = "ホーム" if side == "home" else "ビジター"
        d.text((W - 100 - dx - d.textlength(tag, font=font(28)), top + 30),
               tag, font=font(28), fill=DIM)

        st, jp, p = rows[side]
        ry = top + 84
        # いまの勝敗と立ち位置
        if st:
            d.text((240 - dx, ry), "・".join(st), font=font(30), fill=DIM)
            ry += 54
        # 先発ではない日本人選手。**1行を与える。**
        # 「◯◯が所属」とは書かない。名前がそこにあれば所属は分かる。
        if jp:
            px = flag_jp(d, 104 - dx, ry - 2, 46, 30)
            d.text((px, ry - 6), "・".join(jp[:3]), font=font(34), fill=JP)
            ry += 50
            shown_jp = True
        # 先発予定。**球団の下に小さく。**日本人なら日の丸を先に置く。
        if p.get("name"):
            px = 104 - dx
            if p["name"] in starters or p.get("name_en") in starters:
                px = flag_jp(d, px, ry + 4)
                shown_jp = True
            d.text((px, ry + 2), "先発 " + str(p["name"]),
                   font=font(36), fill=TEXT)
            bits = []
            if p.get("era"):
                bits.append("防御率" + str(p["era"]))
            if p.get("wins") is not None and p.get("losses") is not None:
                bits.append("%d勝%d敗" % (p["wins"], p["losses"]))
            if p.get("strikeouts"):
                bits.append("%d奪三振" % p["strikeouts"])
            if bits:
                s = "　".join(bits)
                d.text((W - 100 - dx - d.textlength(s, font=font(30)),
                        ry + 8), s, font=font(30), fill=ACCENT)

    y = tops[-1] + hs[-1] + 22

    # --- どの大会か ---
    #
    # サッカーの画面がほぼ空になっていた。MLBには略称の色札・先発投手・
    # 球場の説明があるが、サッカーはどれも無い。昨季の順位すら、
    # 昇格クラブには存在しない。何も無いまま対戦名だけが浮いていた。
    # せめて「どのリーグの試合か」は必ず言える。リーグを見て選ぶ人には、
    # ここがいちばん要る情報でもある。
    league = g.get("league") or ""
    if league and league != "MLB":
        y = label_chip(d, 70, y, league, JP) + 10

    # --- 何連戦の何戦目か ---
    #
    # 同じ相手と3日続けてやるのがMLBで、そこが日本の視聴者に伝わりにくい。
    # 「昨日勝ったほうが今日も投げ勝てるか」は、この1行が無いと立たない。
    sc = g.get("series_context") or {}
    if sc.get("games_in_series") and progress > 0.06:
        s = "%d連戦の第%d戦" % (sc["games_in_series"],
                               sc.get("series_game_number") or 1)
        hw = sc.get("home_wins_in_stretch")
        aw = sc.get("away_wins_in_stretch")
        if hw is not None and aw is not None and (hw or aw):
            s += "　ここまで%s%d勝 - %s%d勝" % (
                g.get("home_team_name", ""), hw,
                g.get("away_team_name", ""), aw)
        d.text((78, y), s, font=font(30), fill=DIM)
        y += 52

    # --- 注目理由(1つずつ順に出す) ---
    # ライバル関係の理由文は「◯◯ vs ◯◯ は伝統の好カード — 由来…」の形で、
    # 由来まで入れると縦型の画面には収まらない。動画では見出し部分だけ使い、
    # 由来はサイト側(全文を出せる)に任せる。
    #
    # 「◯◯には△△が選手が所属」は、もう球団の欄に名前で出ている。
    # ここに文で書くと、いちばん大きい箱がいちばん薄い情報で埋まる。
    reasons = [r["text"].split(" — ")[0] for r in (g.get("reasons") or [])
               if r.get("visible", True) and r.get("text")
               and not (shown_jp and r.get("tag") == "jp_team")][:3]
    if reasons and progress > 0.10:
        # 1枚のカードにまとめる。以前は文字が地の上に直接置かれていて、
        # 上の対戦カードと作りが違い、どこまでが理由なのか曖昧だった。
        # 高さは中身から決める。決め打ちだと余白が出るか、はみ出す。
        wrapped = [wrap(d, "・" + r, font(42), W - 230) for r in reasons]
        h = sum(len(w) * 62 for w in wrapped) + 44
        card(d, 60, y, W - 60, y + h, stripe=JP)
        yy = y + 22
        for i, lines in enumerate(wrapped):
            appear = 0.12 + i * 0.08
            if progress < appear:
                yy += len(lines) * 62
                continue
            e2 = ease_out(min(1.0, (progress - appear) * 5))
            dx2 = int((1 - e2) * 26)
            for line in lines:
                d.text((100 + dx2, yy), line, font=font(42), fill=TEXT)
                yy += 62
        y += h + 26

    # --- 球場の見どころと、開始時刻の天気 ---
    #
    # **余ったときだけ出す。**
    # 球場の形はシーズンを通して変わらないので、その日の話ではない。
    # 先発・勝敗・連勝・順位争いを置いたあとに場所が残っていれば置く。
    # 無理に入れると、毎日変わる情報のほうが押し出される。
    if g.get("venue_note") and progress > 0.30:
        note = wrap(d, g["venue_note"], font(34), W - 220)[:2]
        # その時刻・その球場の天気。気温と風と降水確率だけを置く。
        # 「打者有利」のような判断は書かない。数字だけあれば、
        # どう読むかは見ている人が決められる。
        wx = venue_weather(g.get("game_id"), g.get("venue_name"))
        h = 56 + len(note) * 48 + 30 + (46 if wx else 0)
        y += 20
        # 読み上げの帯(3行で H-434 から)に食い込むなら、その日は出さない。
        if y + h > H - 460:
            return im
        card(d, 60, y, W - 60, y + h, stripe=ACCENT, fill=ACCENT_DIM)
        yy = y + 24
        # 球場名だけだと、どちらの本拠地なのかが分からない。
        # 対戦は「アウェー vs ホーム」なので、後ろのチームの球場になる。
        # そこまで書いて初めて、並びと球場が繋がる。
        home = g.get("home_team_name") or ""
        where = g.get("venue_jp", "")
        if home and where:
            where = f"{where}（{home}の本拠地）"
        d.text((100, yy), where,
               font=font(fit_size(d, where, W - 240, (38, 34, 30, 26))),
               fill=ACCENT)
        yy += 56
        for line in note:
            d.text((100, yy), line, font=font(34), fill=ACCENT)
            yy += 48
        if wx:
            d.text((100, yy + 2), wx, font=font(32), fill=TEXT)
            yy += 46
        # その球場が点の入る所か入らない所か。
        # 形の話(グリーンモンスター)だけだと毎日同じだが、
        # 平均得点は順位つきの数字なので、球場ごとに違う。
        runs = g.get("venue_runs_note") or ""
        if runs and yy + 60 < H - 460:
            for line in wrap(d, runs, font(30), W - 220)[:2]:
                d.text((100, yy + 8), line, font=font(30), fill=TEXT)
                yy += 42
    return im


_WEATHER = None


def venue_weather(game_id, venue_name: str = "") -> str:
    """開始時刻の現地の天気。取れていない日は空。"""
    global _WEATHER
    if _WEATHER is None:
        try:
            _WEATHER = json.loads(pathlib.Path("data/venue_weather.json")
                                  .read_text(encoding="utf-8")).get("venues") or {}
        except (OSError, json.JSONDecodeError):
            _WEATHER = {}
    hit = _WEATHER.get(str(game_id or "")) or _WEATHER.get(venue_name or "")
    return (hit or {}).get("text", "")


def render_news(progress: float, text: str):
    im, d = base_frame(progress)
    draw_brand(d)
    d.text((70, 200), "最近の動き", font=font(52), fill=JP)
    e = ease_out(min(1.0, progress * 3))
    dy = int((1 - e) * 40)
    y = 420 + dy
    d.rounded_rectangle([60, y - 40, W - 60, y + 300], 24, fill=SURF)
    yy = y
    for line in wrap(d, text, font(50), W - 200):
        d.text((100, yy), line, font=font(50), fill=TEXT)
        yy += 74
    return im


def render_recap(progress: float, meta: dict):
    """
    昨日この番組で選んだ試合が、実際どうなったか。

    毎回その日で完結していると、明日また来る理由が無い。
    コレスポは「なぜ注目か」を書いて出しているので、その検算ができる。
    予想を当てにいくのではなく、書いたことの結果を並べるだけ。
    """
    im, d = base_frame(progress)
    draw_brand(d)
    d.text((70, 180), "昨日の答え合わせ", font=font(64), fill=ACCENT)
    d.text((74, 268), "この番組が選んだ試合は、こうなりました",
           font=font(34), fill=DIM)

    # 通算の記録を、答え合わせの上に置く。
    #
    # 1本ずつが完結していると、明日また来る理由が無い。この数字は
    # 毎日1つずつ増えるので、続けて見ている人にだけ「育っている」ことが
    # 見える。予想の的中率ではなく、書いたことの検算を数えた数。
    # 数字が上がりきる動きを見せるのは、増えることそのものが中身だから。
    base = meta.get("base") or {}
    y = 380
    if base.get("games"):
        e0 = ease_out(min(1.0, progress * 2.2))
        card(d, 60, y, W - 60, y + 150, stripe=JP)
        n = int(base["games"] * e0)
        d.text((100, y + 26), f"{n}", font=font(74), fill=ACCENT)
        nw = d.textlength(f"{n}", font=font(74))
        d.text((110 + nw, y + 58), "試合を記録しました", font=font(40), fill=TEXT)
        # 数えた結果を並べる。予想ではないので、外れることが無い。
        #
        # 「次はどうなるか」を言い出すと、当たり外れで見られることになり、
        # 外した日から見られなくなる。「これまでこうだった」なら、
        # 見る側が自分で先を考えられて、しかも古びない。
        bits = []
        if base.get("one_run_pct") is not None:
            bits.append(f"1点差 {base['one_run_pct']}%")
        if base.get("shutout_pct") is not None:
            bits.append(f"完封 {base['shutout_pct']}%")
        if base.get("avg_total") is not None:
            bits.append(f"平均 {base['avg_total']}点")
        d.text((100, y + 104), "　".join(bits) or "毎日、結果まで残しています",
               font=font(32), fill=DIM)
        y += 180

    for i, row in enumerate((meta.get("lines") or [])[:3]):
        appear = 0.08 + i * 0.10
        if progress < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (progress - appear) * 8)))
        dx = int((1 - e) * 110)
        note = row.get("note", "")
        # 添える一言が無い試合は、その分カードを詰める。
        # 高さを固定にすると、note の無い行だけ下半分が空いて間延びする。
        h = 190 if note else 130
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + h], 20, fill=SURF2)
        d.text((100 - dx, y + 28), row.get("matchup", ""), font=font(50),
               fill=TEXT)
        # スコアは「6 - 4」で、左が先に書いた側(対戦名の左と同じ)。
        # どちらが勝ったのかは数字を見比べないと分からないので、
        # 勝った側だけ色を残して、負けた側を落とす。
        # 場所を足さずに勝敗が分かる。
        score = row.get("score", "")
        sw = d.textlength(score, font=font(64))
        sx = W - 100 - dx - sw
        parts = score.split(" - ")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            left, right = int(parts[0]), int(parts[1])
            cx = sx
            for txt, win in ((parts[0], left > right), (" - ", None),
                             (parts[1], right > left)):
                d.text((cx, y + 20), txt, font=font(64),
                       fill=ACCENT if win else (DIM if win is False else TEXT))
                cx += d.textlength(txt, font=font(64))
        else:
            d.text((sx, y + 20), score, font=font(64), fill=ACCENT)
        if note:
            d.text((100 - dx, y + 108), note, font=font(38), fill=JP)
        y += h + 24

    # スコアの羅列だけだと「6対5でした」が3回続いて終わる。
    # その日いちばんの打者と投手を1人ずつ添える。
    # 読み上げでも同じ2人を呼んでいるので、耳と画面が食い違わない。
    for who, label, col in ((meta.get("best") or {}), "打者", ACCENT),                            ((meta.get("arm") or {}), "投手", JP):
        if not who or not who.get("headline"):
            continue
        if progress < 0.34:
            continue
        e = ease_out(min(1.0, max(0.0, (progress - 0.34) * 8)))
        dx = int((1 - e) * 90)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + 128], 18, fill=SURF2)
        d.rounded_rectangle([60 - dx, y, 68 - dx, y + 128], 4, fill=col)
        lw = d.textlength(label, font=font(26)) + 28
        d.rounded_rectangle([100 - dx, y + 20, 100 - dx + lw, y + 60], 11,
                            fill=col)
        d.text((114 - dx, y + 26), label, font=font(26), fill=BG)
        # 所属も出す。この1位はMLB全体から選んでいるので、上に並ぶ
        # 3試合とは関係が無い。球団名が無いと、直前に読み上げた
        # 試合の選手に見える(デグロムがそう読まれた)。
        name = who.get("name", "")
        team = (who.get("team") or "").strip()
        d.text((116 - dx + lw, y + 18),
               name, font=font(fit_size(d, name, W - 320 - lw,
                                        (44, 40, 36, 32))), fill=TEXT)
        if team:
            tw = d.textlength(team, font=font(30))
            d.text((W - 100 - dx - tw, y + 28), team, font=font(30), fill=DIM)
        d.text((100 - dx, y + 76), who["headline"][:32], font=font(34),
               fill=DIM)
        y += 148

    d.text((70, H - 240), "予想ではありません。選んだ理由を書いて出し、",
           font=font(32), fill=DIM)
    d.text((70, H - 190), "その結果を並べているだけです。",
           font=font(32), fill=DIM)
    return im


def render_score(progress: float, games: list):
    """
    コレスポ指数。なぜこの試合を選んだのかを、点数と内訳で見せる。

    選定は元から点数で決まっているのに、点数自体は内部に隠れていた。
    何にどれだけ加点したかまで出すことで、選定基準そのものが読み物になる。
    独自の指標なので、同じものは他所には無い。
    """
    im, d = base_frame(progress)
    draw_brand(d)
    d.text((70, 180), "コレスポ指数", font=font(64), fill=ACCENT)
    d.text((74, 268), "なぜこの試合を選んだか、点数で", font=font(34), fill=DIM)

    def reason_lines(g):
        """
        加点の内訳。理由文そのものが短ければそれを使い、長ければラベルに落とす。
        ラベルだけにすると「連勝・連敗中」が2行並ぶような、
        どのチームの話か分からない表示になってしまう。
        """
        out = []
        for r in (g.get("reasons") or [])[:3]:
            if not r.get("text"):
                continue
            text = r["text"].split(" — ")[0]
            out.append((r.get("weight", 0),
                        text if len(text) <= 18 else reason_label(r.get("tag"))))
        return out

    top_score = max((g.get("score") or 0) for g in games[:3]) or 1
    y = 360
    for i, g in enumerate(games[:3]):
        if progress < 0.06 + i * 0.07:
            continue
        e = ease_out(min(1.0, max(0.0, (progress - (0.06 + i * 0.07)) * 8)))
        dx = int((1 - e) * 120)
        sc = g.get("score") or 0

        # カードの高さは内訳の行数に合わせる。固定にすると行が少ない試合で
        # 下半分が空いて間延びする
        lines = reason_lines(g)
        card_h = 180 + max(1, len(lines)) * 56 + 24
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + card_h], 22, fill=SURF)
        name = g.get("abbr_matchup") or g.get("matchup") or ""
        d.text((100 - dx, y + 26), name, font=font(52), fill=TEXT)
        # 何戦目か。3連戦の初戦と最終戦では意味が違う。
        # データには最初から入っていて、サイトは出していたが動画は
        # 出していなかった。
        sc_ctx = g.get("series_context") or {}
        if sc_ctx.get("series_game_number") and sc_ctx.get("games_in_series"):
            tag = (f"第{sc_ctx['series_game_number']}戦"
                   f"/全{sc_ctx['games_in_series']}戦")
            d.text((100 - dx + d.textlength(name, font=font(52)) + 20,
                    y + 40), tag, font=font(30), fill=DIM)

        # 点数は右上に大きく。3試合を見比べられるようにする
        stxt = f"{sc}"
        f_s = font(88)
        d.text((W - 150 - dx - d.textlength(stxt, font=f_s), y + 16),
               stxt, font=f_s, fill=ACCENT)
        d.text((W - 138 - dx, y + 66), "点", font=font(38), fill=ACCENT)

        # 点数の比較バー
        bar_w = max(4, int((W - 220) * (sc / top_score) * e))
        d.rounded_rectangle([100 - dx, y + 120, 100 - dx + bar_w, y + 146],
                            6, fill=ACCENT_DIM)

        yy = y + 180
        for weight, label in lines:
            d.text((100 - dx, yy), f"+{weight}", font=font(40), fill=ACCENT)
            # 長い理由文でも収まるサイズを実測で選ぶ
            ls = 38
            for s in (38, 34, 30):
                if d.textlength(label, font=font(s)) <= W - 300:
                    ls = s
                    break
            d.text((180 - dx, yy + 4), label, font=font(ls), fill=TEXT)
            yy += 56
        y += card_h + 40
    return im


def render_outro(progress: float):
    im, d = base_frame(progress)
    e = ease_out(min(1.0, progress * 2))
    d.text((80, 620), "コレスポ", font=font(120), fill=ACCENT)
    d.text((80, 780), "毎日19時", font=font(76), fill=TEXT)
    if progress > 0.10:
        d.text((80, 880), "その日の注目試合を", font=font(50), fill=TEXT)
        d.text((80, 950), "「なぜ注目か」の理由つきで", font=font(50), fill=TEXT)
    if progress > 0.20:
        # 何をしてほしいかを1つだけ明示する。複数並べるとどれも実行されない。
        d.rounded_rectangle([70, 1060, W - 70, 1170], 18, fill=ACCENT)
        d.text((110, 1088), "チャンネル登録で毎日届きます", font=font(46), fill=BG)
    d.text((80, 1220), "collespo.com", font=font(46), fill=TEXT)
    # VOICEVOXの利用規約で、動画内または説明欄へのクレジット表記が
    # 求められているため、アウトロに必ず表示する
    d.text((80, 1340), "音声: VOICEVOX:ずんだもん", font=font(38), fill=DIM)
    # 出典は競技で変わる。サッカーの動画にMLBのAPI名が出ていては嘘になる。
    d.text((80, 1400), DATA_SOURCE, font=font(38), fill=DIM)
    return im


# 画面の隅に出す出典。競技で変わる。
# サッカーの動画に「データ: MLB Stats API」と出ていては嘘になる。
DATA_SOURCES = {
    "mlb": "データ: MLB Stats API",
    "soccer": "データ: football-data.org",
}
DATA_SOURCE = DATA_SOURCES["mlb"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", default="notable_games.json")
    parser.add_argument("--sport", default="mlb",
                        choices=list(DATA_SOURCES),
                        help="出典表記の切り替え")
    parser.add_argument("--audio-dir", default="build/audio")
    parser.add_argument("--require-audio", action="store_true",
                        help="音声が作れなければ動画を作らずに終わる")
    parser.add_argument("--out", default="build/video")
    args = parser.parse_args()
    global DATA_SOURCE
    DATA_SOURCE = DATA_SOURCES[args.sport]

    games_data = json.loads(pathlib.Path(args.games).read_text(encoding="utf-8"))
    games = [g for g in games_data.get("games", []) if g.get("is_notable")]
    if not games:
        print("[info] 注目試合が無いため、動画は作りません")
        return

    manifest_path = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest_path.exists():
        segments = json.loads(manifest_path.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestが見つかりません: {manifest_path.resolve()}")
        print("       音声なし・固定秒数で作ります"
              "(synthesize_narration.py のログを確認してください)")
        segments = [{"index": 0, "file": None, "duration": 4.0, "kind": "intro",
                     "meta": {}}]
        for i in range(len(games[:3])):
            segments.append({"index": i + 1, "file": None, "duration": 8.0,
                             "kind": "game", "meta": {"game_index": i}})
        segments.append({"index": len(segments), "file": None, "duration": 4.0,
                         "kind": "outro", "meta": {}})

    # 長すぎる回を、ここで削る。音声を繋ぐ前なので、落とした画面の
    # 音声は最初から入らない。
    #
    # この枠は実測で71秒・視聴継続23.7%。最も配られていて(中央値288回、
    # 最大847回)、最も残らない部類でもある。72秒の23.7%は、
    # 平均的な視聴者が17秒で離れているということで、
    # 「コレスポ指数」も「昨日の答え合わせ」も、そこまで届いていない。
    #
    # だから落とす順は、指数の自己説明 → ニュース → 答え合わせ。
    # 試合そのものは落とさない。冒頭で「注目の3試合を」と言ってあり、
    # 1つ減らすと読み上げが嘘になる。
    keep, dropped = post_common.fit_budget(
        segments, [max(2.0, float(s.get("duration") or 0) or 4.0)
                   for s in segments],
        ("score", "news", "recap"))
    if dropped:
        segments = [segments[i] for i in keep]
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"日次: {post_common.MAX_SECONDS:.0f}秒に収めるため"
                        f"{chr(12289).join(dropped)}を外しました{chr(10)}")

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_short.mp4"

    date_label = (games[0].get("start_time_jst") or "").split(" ")[0]
    total_games = len(games[:3])

    # --- 音声を先に連結しておく ---
    audio_files = [s["file"] for s in segments if s.get("file")]
    audio_path = None

    # 音声が無いまま書き出すと、無音の動画がそのまま投稿される。
    # VOICEVOXの起動は continue-on-error なので、失敗しても実行は緑で終わる。
    # 無音を出すくらいなら、その日は出さない方がよい。
    if args.require_audio and not audio_files:
        print("::error::音声が作れませんでした。無音のまま投稿しないよう、"
              "ここで中止します(VOICEVOXの起動を確認してください)")
        return 1

    if audio_files:
        concat_list = out_dir / "audio_list.txt"
        concat_list.write_text(
            "\n".join(f"file '{pathlib.Path(a).resolve()}'" for a in audio_files),
            encoding="utf-8",
        )
        audio_path = out_dir / "narration.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(audio_path)],
            check=True, capture_output=True,
        )

    # --- フレームをffmpegへ直接流し込む ---
    # PNGとしてディスクに書き出すと、2000枚超で圧縮とI/Oに3分近くかかる。
    # 生のRGBデータを標準入力経由で渡せば、その両方が不要になる。
    # -nostats/-loglevel error で、ffmpegが標準エラーへ書く量を最小限にする。
    # 出力が多いとパイプのバッファが埋まり、ffmpegが停止して
    # こちらの書き込みも止まる(デッドロック)。
    cmd = [
        "ffmpeg", "-y", "-nostats", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-framerate", str(FPS),
        "-i", "-",
    ]
    if audio_path:
        cmd += ["-i", str(audio_path)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [str(video_path)]

    # stderrはパイプではなくファイルへ逃がす。
    # パイプのままだと、こちらが読まない限りバッファが埋まって止まる。
    err_path = out_dir / "ffmpeg_error.log"
    err_file = open(err_path, "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=err_file)

    frame_no = 0
    # 直前の画面の最後のフレーム。切り替わりの頭だけ、これと混ぜる。
    last_frame = None
    try:
        for seg_i, seg in enumerate(segments):
            dur = max(2.0, float(seg.get("duration") or 0) or 4.0)
            n = int(dur * FPS)
            kind = seg.get("kind")
            # 何枚目かを画面上の目盛りに反映する
            set_step(seg_i, len(segments))
            # その画面で読み上げている文を、画面下に出す
            set_spoken(seg.get("text") or "")
            meta = seg.get("meta") or {}
            cached = None
            still = None
            # 最初の画面は前が無いので混ぜない
            fade = 0 if seg_i == 0 else int(video_common.FADE_SECONDS * FPS)
            for k in range(n):
                p_, settled = video_common.anim_step(k, n)
                if settled and still is not None:
                    # 動きが止まった区間は描き直さず、直前のフレームを使い回す
                    proc.stdin.write(still)
                    frame_no += 1
                    continue
                if kind == "intro":
                    im = render_intro(p_, date_label, meta)
                elif kind == "game":
                    # game_index は notable_games.json の中の位置。
                    # order は読み上げの順番で、画面の「PICK N/3」はこちら。
                    # 冒頭で名乗った試合を先頭へ動かすので、2つは一致しない。
                    gi = meta.get("game_index", 0)
                    if gi >= len(games):
                        continue
                    im = render_game(p_, games[gi],
                                     meta.get("order", gi), total_games)
                elif kind == "score":
                    im = render_score(p_, games)
                elif kind == "recap":
                    im = render_recap(p_, meta)
                elif kind == "news":
                    im = render_news(p_, seg.get("text", ""))
                else:
                    im = render_outro(p_)
                cached = video_common.crossfade(last_frame, im, k, fade, (W, H))
                proc.stdin.write(cached)
                # 動きが終わった最初の1枚。これを残りに使い回す。
                if settled:
                    still = cached
                frame_no += 1
            last_frame = cached
            print(f"[info] {kind}: {dur:.1f}秒 ({n}フレーム)")
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait()
        err_file.close()

    if proc.returncode != 0:
        err = err_path.read_text(encoding="utf-8", errors="ignore")[-2000:]
        print(f"[error] 動画の書き出しに失敗しました:\n{err}", file=sys.stderr)
        sys.exit(1)

    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"[info] 動画を生成しました: {video_path} ({size_mb:.1f}MB, "
          f"{frame_no / FPS:.1f}秒)")


if __name__ == "__main__":
    # main() の戻り値を終了コードにする。返すだけでは 0 で終わり、
    # 中止したつもりでも後続の投稿ステップが動いてしまう。
    raise SystemExit(main() or 0)
