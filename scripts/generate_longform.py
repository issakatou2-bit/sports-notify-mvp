#!/usr/bin/env python3
"""
対話の台本から、16:9の通常動画を作る。

なぜ短編と別の台本にするのか:
  画面の比が違う(1080×1920 と 1920×1080)。座標がまるごと変わるので、
  同じ関数に両方を通すと分岐だらけになる。
  下地・色・フォントは generate_weekly.py と同じものを使う。

画面の作り(初版から作り直した):

    ┌──────────────────────────────────────────┐
    │ 話題                                     │
    │        ┌────────────────────┐            │
    │        │   いま話している    │            │  ← 中央の札
    │  立ち  │   ことの、事実      │  立ち      │
    │  絵    └────────────────────┘  絵        │
    │        ┌────────────────────┐            │
    │        │  台詞               │            │
    │        └────────────────────┘            │
    │ コレスポ                      音声:VOICEVOX│
    └──────────────────────────────────────────┘

  初版は左右に人・下に台詞だけで、**画面の中央が丸ごと空いていた**。
  そして台詞の箱が高さを持たず、3行でフッターに重なり、4行で
  画面の外へ出て、5行を超えたぶんは黙って捨てていた。

  中央の札は、台本を書いたモデルが選ぶ。ただし**中身は選ばせない**。
  中身は generate_dialogue.panels() が事実から組み立てたもので、
  モデルは「どれを出すか」の鍵を指すだけ。画面に映る数字が
  台詞と違う根拠を持つ、ということが起きないようにしてある。

使い方(2段階。短編と同じ流れ):
  python3 scripts/generate_dialogue.py --out build/lf/dialogue.json
  python3 scripts/synthesize_narration.py \
      --narration build/lf/dialogue.json --out-dir build/lf/audio
  python3 scripts/generate_longform.py \
      --dialogue build/lf/dialogue.json --audio-dir build/lf/audio \
      --out build/lf
"""

import argparse
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from PIL import Image  # noqa: E402

import video_common  # noqa: E402

# 週次動画と同じ寸法・色・フォントを使う。
# 同じチャンネルの通常動画が、2つ別の見た目を持つ理由が無い。
from generate_weekly import (  # noqa: E402
    W, H, FPS, ANIM_END, SURF, TEXT, DIM, ACCENT, JP,
    base, font, wrap,
)

# 話者ごとの色と置き場所。
#
# 左右に分けるのは、聞かなくても誰が喋っているか分かるようにするため。
# 音を切って見ている人には、これしか手がかりが無い。
SPEAKERS = {
    3: {"name": "ずんだもん", "color": JP, "side": "left"},
    2: {"name": "四国めたん", "color": ACCENT, "side": "right"},
}
DEFAULT_SPEAKER = 3

# 画面の割りつけ。ここを1か所にまとめておく。
# 初版は箱の高さを中身から足し算していたので、行が増えると
# 下へ伸びて画面の外に出た。置ける場所を先に決めて、
# 中身をそこへ収めるほうにする。
COL_X0, COL_X1 = 420, 1500          # 中央の列(立ち絵の内側)
PANEL_Y0, PANEL_Y1 = 104, 556       # 情報の札
TALK_Y0, TALK_Y1 = 584, 1004        # 台詞
PORTRAIT_H = 690                    # 立ち絵の高さ(画面の下端まで)
PORTRAIT_X = 196                    # 左右の中心

TALK_PAD = 30
TALK_SIZES = (52, 46, 40)           # 上から順に試す
TALK_LEAD = 16                      # 行間

# 名前は台詞の箱の上端に付ける。
#
# 初版は立ち絵の足元に置いていて、フッターと重なっていた。
# 立ち絵を画面の下端まで伸ばすと、そこにはもう場所が無い。
# 箱の上に付けると、名前と台詞が繋がって読める。
NAME_H = 46


def _speaker(seg: dict) -> dict:
    sid = seg.get("speaker")
    return SPEAKERS.get(sid) or SPEAKERS[DEFAULT_SPEAKER]


_PORTRAIT_CACHE: dict = {}


def _portrait(who: str, portrait_dir: str):
    """立ち絵。無ければ None。

    毎フレーム開くと、3分の動画で数千回ファイルを読むことになる。
    大きさも決まっているので、縮めたものを持っておく。
    """
    if not portrait_dir:
        return None
    ck = (who, portrait_dir)
    if ck in _PORTRAIT_CACHE:
        return _PORTRAIT_CACHE[ck]
    art = None
    for ext in (".png", ".webp"):
        p = pathlib.Path(portrait_dir) / (who + ext)
        if p.exists():
            try:
                art = Image.open(p).convert("RGBA")
            except Exception:                    # noqa: BLE001
                art = None
            break
    if art is not None:
        k = PORTRAIT_H / art.height
        art = art.resize((max(1, int(art.width * k)), PORTRAIT_H),
                         Image.LANCZOS)
    _PORTRAIT_CACHE[ck] = art
    return art


_DARK_CACHE: dict = {}


def _dimmed(ck, art):
    """喋っていない側。消さずに落とす(そこに居るので)。"""
    if ck not in _DARK_CACHE:
        veil = Image.new("RGBA", art.size, (10, 12, 20, 165))
        _DARK_CACHE[ck] = Image.alpha_composite(art, veil)
    return _DARK_CACHE[ck]


# ---------------------------------------------------------------------------
# 台詞の割りつけ
# ---------------------------------------------------------------------------

def layout_talk(d, text: str):
    """台詞を、置ける高さに収まる形にする。

    戻り値は (文字の大きさ, [1画面ぶんの行, ...])。
    **入り切らなくても捨てない。** 入らなければ画面を分ける。
    初版は lines[:5] で黙って切っていて、長い台詞は
    読み上げだけが続いて画面が止まって見えた。
    """
    avail_w = COL_X1 - COL_X0 - TALK_PAD * 2
    avail_h = TALK_Y1 - TALK_Y0 - TALK_PAD * 2
    for size in TALK_SIZES:
        lines = wrap(d, text, font(size), avail_w)
        per = max(1, avail_h // (size + TALK_LEAD))
        if len(lines) <= per:
            return size, [lines]
    # いちばん小さくしても入らない。画面を分ける。
    size = TALK_SIZES[-1]
    lines = wrap(d, text, font(size), avail_w)
    per = max(1, avail_h // (size + TALK_LEAD))
    return size, [lines[i:i + per] for i in range(0, len(lines), per)]


def paginate(segs: list) -> list:
    """長い台詞を、複数の画面に割る。尺は文字数で按分する。

    音は1つの読み上げのまま。画面だけが途中で切り替わる。
    読んでいるところと画面が合うように、行数ではなく
    文字数で分ける(行によって字数が違うため)。
    """
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (W, H)))
    out = []
    for s in segs:
        size, pages = layout_talk(d, s.get("text", ""))
        if len(pages) == 1:
            out.append({**s, "_size": size, "_lines": pages[0], "_share": 1.0})
            continue
        chars = [sum(len(x) for x in pg) or 1 for pg in pages]
        total = sum(chars)
        for pg, c in zip(pages, chars):
            out.append({**s, "_size": size, "_lines": pg,
                        "_share": c / total})
    return out


# ---------------------------------------------------------------------------
# 中央の札
# ---------------------------------------------------------------------------
def _block(d, text, y, y_max, sizes, fill=TEXT, lead=16, dry=False):
    """札の中の文章。置ける高さに収まる大きさを選んで描く。

    札ごとに「何行まで」と決め打ちしていたが、行の長さは日によって
    変わる。高さから決めるほうが外れない。

    dry=True のときは描かずに、書き終わりの y だけ返す。
    札の高さを中身に合わせるための下見に使う。
    """
    x, w = COL_X0 + 40, COL_X1 - COL_X0 - 80
    lines, size = [], sizes[-1]
    for s in sizes:
        lines, size = wrap(d, str(text), font(s), w), s
        if len(lines) * (s + lead) <= y_max - y:
            break
    per = max(1, (y_max - y) // (size + lead))
    for ln in lines[:per]:
        if not dry:
            d.text((x, y), ln, font=font(size), fill=fill)
        y += size + lead
    return y


def _one(d, text, y, size, fill=TEXT, dry=False):
    """1行だけ置く。戻り値は次の y。"""
    if not dry:
        d.text((COL_X0 + 40, y), str(text), font=font(size), fill=fill)
    return y + size + 14


# ---------------------------------------------------------------------------
# 札。すべて「上から順に置いて、書き終わりの y を返す」形にしてある。
#
# 初版は下端を PANEL_Y1 に貼り付けていたので、中身が短い札ほど
# 真ん中に穴が空いた。上から流して、札の高さを中身に合わせる。
# ---------------------------------------------------------------------------

def _panel_score(d, p, y, dry=False):
    inn = p.get("innings") or []
    n = len(inn)
    name_w = 260
    x0 = COL_X0 + 40
    right = COL_X1 - 40
    cell = max(40, min(74, (right - x0 - name_w) / max(1, n + 1)))
    rows = [(p.get("away", ""), "away", p.get("away_score")),
            (p.get("home", ""), "home", p.get("home_score"))]

    for i, ig in enumerate(inn):
        cx = x0 + name_w + cell * i + cell / 2
        t = str(ig.get("num", i + 1))
        if not dry:
            d.text((cx - d.textlength(t, font=font(28)) / 2, y),
                   t, font=font(28), fill=DIM)
    rx = x0 + name_w + cell * n + cell / 2
    if not dry:
        d.text((rx - d.textlength("計", font=font(28)) / 2, y),
               "計", font=font(28), fill=DIM)

    y += 58
    win = None
    a, h = p.get("away_score"), p.get("home_score")
    if isinstance(a, int) and isinstance(h, int):
        win = "away" if a > h else ("home" if h > a else None)
    for nm, side, total in rows:
        col = ACCENT if side == win else TEXT
        f = font(42)
        if not dry:
            nm = nm if d.textlength(nm, font=f) <= name_w - 20 else nm[:7]
            d.text((x0, y), nm, font=f, fill=col)
            for i, ig in enumerate(inn):
                v = ig.get(side)
                t = "-" if v is None else str(v)
                cx = x0 + name_w + cell * i + cell / 2
                fv = font(40)
                d.text((cx - d.textlength(t, font=fv) / 2, y),
                       t, font=fv, fill=TEXT if v else DIM)
            t = "-" if total is None else str(total)
            fb = font(58)
            d.text((rx - d.textlength(t, font=fb) / 2, y - 12),
                   t, font=fb, fill=col)
        y += 96

    if win:
        wn = p.get("away") if win == "away" else p.get("home")
        y = _one(d, f"{wn}の勝ち", y + 6, 38, ACCENT, dry)
    return y


def _panel_views(d, p, y, dry=False):
    y = _block(d, p.get("title", ""), y, y + 190, (42, 36, 32), dry=dry)
    v = int(p.get("views") or 0)
    big = f"{v / 10000:.1f}万回" if v >= 10000 else f"{v:,}回"
    y = _one(d, big, y + 10, 96, ACCENT, dry)
    return _one(d, "再生", y - 6, 32, DIM, dry)


def _panel_quote(d, p, y, dry=False):
    y = _block(d, "「" + str(p.get("text", "")) + "」", y, y + 300,
               (46, 42, 38, 34, 30), dry=dry)
    chips = []
    if p.get("tone"):
        chips.append(p["tone"])
    if p.get("likes"):
        chips.append(f"高評価 {int(p['likes']):,}")
    if p.get("replies"):
        chips.append(f"返信 {int(p['replies'])}")
    if chips:
        y = _one(d, "　·　".join(chips), y + 12, 30, DIM, dry)
    return y


def _panel_stat(d, p, y, dry=False):
    y = _block(d, p.get("name", ""), y, y + 130, (52, 44, 38), dry=dry)
    y = _one(d, p.get("stat", ""), y + 8, 34, DIM, dry)
    y = _one(d, p.get("value", ""), y + 4, 92, ACCENT, dry)
    if p.get("rank"):
        y = _one(d, f"リーグ{p['rank']}位", y + 6, 40, TEXT, dry)
    return y


def _panel_star(d, p, y, dry=False):
    y = _block(d, p.get("name", ""), y, y + 130, (56, 46, 40), dry=dry)
    if p.get("team"):
        y = _block(d, p["team"], y + 4, y + 100, (34, 30), fill=DIM, dry=dry)
    return _block(d, p.get("line", ""), y + 14, y + 200, (46, 40, 34),
                  fill=ACCENT, dry=dry)


def _panel_topic(d, p, y, dry=False):
    """札が指定されていないとき。空白にはしない。"""
    y = _block(d, p.get("topic") or "MLB", y, y + 260, (56, 48, 40), dry=dry)
    return _one(d, "コレスポ", y + 10, 36, ACCENT, dry)


_PANELS = {"score": _panel_score, "views": _panel_views,
           "quote": _panel_quote, "stat": _panel_stat,
           "star": _panel_star, "topic": _panel_topic}

_TITLES = {"score": "回ごとの得点",
           "views": "この日いちばん見られた（MLB公式）",
           "stat": "確かめた数字（MLB公式）",
           "star": "目立った選手",
           "topic": "きょうの話"}


def render_panel(d, panel, topic):
    kind = (panel or {}).get("type")
    if kind not in _PANELS:
        kind, panel = "topic", {"topic": topic}
    fn = _PANELS[kind]
    title = (f"{panel.get('source') or '現地のコメント欄'}（翻訳）"
             if kind == "quote" else _TITLES.get(kind, ""))
    try:
        # 下見。中身の高さを測ってから札の大きさを決める。
        top = PANEL_Y0 + (84 if title else 40)
        bottom = fn(d, panel, top, dry=True)
    except Exception as e:                       # noqa: BLE001
        # 札が1枚描けないだけで動画を落とさない。
        # ただし黙って空にはしない(何が起きたか分からなくなる)。
        print(f"[warn] 札を描けません({kind}): {e}")
        kind, panel, title = "topic", {"topic": topic}, _TITLES["topic"]
        fn = _PANELS["topic"]
        top = PANEL_Y0 + 84
        bottom = fn(d, panel, top, dry=True)

    y1 = min(PANEL_Y1, max(PANEL_Y0 + 220, bottom + 34))
    d.rounded_rectangle([COL_X0, PANEL_Y0, COL_X1, y1], 26, fill=SURF)
    d.rounded_rectangle([COL_X0, PANEL_Y0, COL_X0 + 8, y1], 4, fill=ACCENT)
    if title:
        d.text((COL_X0 + 40, PANEL_Y0 + 28), title, font=font(30), fill=DIM)
    fn(d, panel, top)


def render_line(p, seg, portrait_dir="", topic="", panel=None):
    """1つの台詞。喋っている側を明るく、もう片方を暗くする。"""
    im, d = base(p)
    who = _speaker(seg)

    if topic:
        d.text((60, 40), topic[:40], font=font(32), fill=DIM)
    t = "コレスポ  collespo.com"
    d.text((W - 60 - d.textlength(t, font=font(32)), 40),
           t, font=font(32), fill=DIM)

    render_panel(d, panel, topic)

    # 立っている2人。喋っているほうだけ色が付く。
    for s in SPEAKERS.values():
        talking = s["name"] == who["name"]
        x = PORTRAIT_X if s["side"] == "left" else W - PORTRAIT_X
        col = s["color"] if talking else (52, 58, 72)

        art = _portrait(s["name"], portrait_dir)
        if art is not None:
            ck = (s["name"], portrait_dir)
            shown = art if talking else _dimmed(ck, art)
            im.paste(shown, (int(x - shown.width / 2), H - PORTRAIT_H), shown)
        else:
            # 絵が無くても成立させる。色の丸と名前で代用する。
            r = 74 if talking else 62
            cy = H - PORTRAIT_H + 200
            d.ellipse([x - r, cy - r, x + r, cy + r], fill=col)
            f = font(38 if talking else 32)
            d.text((x - d.textlength(s["name"], font=f) / 2, cy + r + 24),
                   s["name"], font=f, fill=col if talking else DIM)

    # 台詞。置ける場所は決まっている。中身をそこへ収める。
    size = seg.get("_size")
    lines = seg.get("_lines")
    if lines is None:
        size, pages = layout_talk(d, seg.get("text", ""))
        lines = pages[0]

    h = min(TALK_Y1 - TALK_Y0,
            len(lines) * (size + TALK_LEAD) + TALK_PAD * 2 - TALK_LEAD)
    y0 = TALK_Y1 - h
    d.rounded_rectangle([COL_X0, y0, COL_X1, TALK_Y1], 24, fill=SURF)
    # 喋っている側の縁に色の帯。吹き出しの尻尾の代わり。
    left = who["side"] == "left"
    if left:
        d.rounded_rectangle([COL_X0, y0, COL_X0 + 10, TALK_Y1], 5,
                            fill=who["color"])
    else:
        d.rounded_rectangle([COL_X1 - 10, y0, COL_X1, TALK_Y1], 5,
                            fill=who["color"])

    # 名前の札。箱の上端に、喋っている側から出す。
    nm, fn = who["name"], font(30)
    nw = d.textlength(nm, font=fn) + 44
    nx = COL_X0 + 24 if left else COL_X1 - 24 - nw
    d.rounded_rectangle([nx, y0 - NAME_H + 12, nx + nw, y0 + 12], 12,
                        fill=who["color"])
    d.text((nx + 22, y0 - NAME_H + 20), nm, font=fn, fill=(12, 14, 20))

    # 動きは文字が出そろうまで。ANIM_END を過ぎたら固定して、
    # フレームを使い回せるようにする。
    shown = len(lines) if p >= ANIM_END else max(
        1, int(len(lines) * (p / ANIM_END)))
    yy = y0 + TALK_PAD
    for ln in lines[:shown]:
        d.text((COL_X0 + TALK_PAD, yy), ln, font=font(size), fill=TEXT)
        yy += size + TALK_LEAD

    # 音声の表記。立ち絵が画面の下端まで来ているので、
    # 左右の隅ではなく中央の列の下に置く(重ならない唯一の場所)。
    cr = "音声: VOICEVOX ずんだもん / 四国めたん"
    fc = font(26)
    d.text(((COL_X0 + COL_X1) / 2 - d.textlength(cr, font=fc) / 2, 1026),
           cr, font=fc, fill=DIM)
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogue", default="build/lf/dialogue.json")
    ap.add_argument("--audio-dir", default="build/lf/audio")
    ap.add_argument("--out", default="build/lf")
    ap.add_argument("--portrait-dir", default="assets/portraits",
                    help="立ち絵の置き場。無ければ丸と名前で代用する")
    ap.add_argument("--require-audio", action="store_true")
    args = ap.parse_args()

    try:
        dia = json.loads(
            pathlib.Path(args.dialogue).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[info] 台本を読めません({e})。作りません")
        return 0
    topic = dia.get("top") or ""
    cards = dia.get("panels") or {}

    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestがありません: {manifest}")
        segs = [{**s, "file": None, "duration": 0.0}
                for s in dia.get("segments", [])]
    if not segs:
        print("[info] 台詞がありません")
        return 0

    # 音声のmanifestは、台本の並びをそのまま持っている。
    # 札の指定は台本側にあるので、無くしていないか確かめてから移す。
    keys = [s.get("panel") for s in dia.get("segments", [])]
    if len(keys) == len(segs):
        for s, k in zip(segs, keys):
            s.setdefault("panel", k)
    else:
        print(f"[warn] 台本{len(keys)}行と音声{len(segs)}区間が合いません。"
              f"札は既定のものになります")

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_longform.mp4"

    # 台詞ごとの尺。読み終わりに息継ぎを足す。
    durations = [max(1.6, float(s.get("duration") or 0)
                     + video_common.SEGMENT_TAIL) for s in segs]
    total = sum(durations)

    audio_files = [s["file"] for s in segs if s.get("file")]
    if args.require_audio and not audio_files:
        print("::error::音声が作れませんでした。無音のまま出しません")
        return 1

    # 音を尺に合わせる。足りないぶんは無音で埋める。
    #
    # 素のまま繋ぐと、音は読み上げぶんしか無いのに画面には息継ぎが
    # 入るので、音のほうが短くなる。-shortest を付けてあるので
    # ffmpeg がそこで終わり、こちらは書き続けて配管が壊れる。
    # 初回はそれで BrokenPipeError になった。
    audio_path = video_common.build_narration_track(segs, durations, out_dir)

    # 画面の割りつけは、音を繋いだ**あと**でやる。
    # 長い台詞は画面を分けるので、音の区間数と画面の数が変わる。
    pages = []
    for s, dur in zip(segs, durations):
        for pg in paginate([s]):
            pages.append((pg, dur * pg["_share"]))
    split = len(pages) - len(segs)
    print(f"[info] {len(segs)}台詞 / {total:.0f}秒"
          + (f"（うち{split}回、長い台詞で画面を分けました）" if split else ""))

    shown = sum(1 for pg, _ in pages if pg.get("panel"))
    print(f"[info] 中央の札: {len(cards)}枚のうち {shown}回指定あり")

    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-"]
    if audio_path:
        cmd += ["-i", str(audio_path)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [str(video_path)]

    err = open(out_dir / "ffmpeg_error.log", "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=err)
    last = None
    current = None                      # 指定が無ければ直前の札が残る
    try:
        for i, (seg, dur) in enumerate(pages):
            if seg.get("panel"):
                current = cards.get(seg["panel"])
            n = int(dur * FPS)
            fade = 0 if i == 0 else int(video_common.FADE_SECONDS * FPS)
            cached = None
            for k in range(n):
                p = k / max(1, n - 1)
                if p > ANIM_END and cached is not None:
                    proc.stdin.write(cached)
                    continue
                im = render_line(p, seg, args.portrait_dir, topic, current)
                cached = video_common.crossfade(last, im, k, fade, (W, H))
                proc.stdin.write(cached)
            last = cached
    except BrokenPipeError:
        # ffmpeg が先に終わっている。何を言って終わったかを出す。
        # これを出さないと、こちらの traceback しか残らない。
        print("::error::ffmpegが先に終了しました。以下はその出力です")
        err.flush()
        print((out_dir / "ffmpeg_error.log").read_text(
            encoding="utf-8", errors="replace")[:800])
        return 1
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait()
        err.close()

    if proc.returncode or not video_path.exists():
        print("::error::動画を書き出せませんでした")
        print((out_dir / "ffmpeg_error.log").read_text(
            encoding="utf-8", errors="replace")[:600])
        return 1
    mb = video_path.stat().st_size / 1024 / 1024
    print(f"[info] 動画を出力しました -> {video_path} "
          f"({total:.0f}秒 / {mb:.1f}MB)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
