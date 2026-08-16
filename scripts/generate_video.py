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
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys

import post_common  # noqa: E402

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
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
]

_FONT_FILE = None


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


def font(size: int):
    path = _resolve_font_file()
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        # .ttc は複数フォントの束なので、先頭以外を試す
        for idx in (1, 2, 3):
            try:
                return ImageFont.truetype(path, size, index=idx)
            except OSError:
                continue
        raise


def ease_out(t: float) -> float:
    """0..1 を、最初速く最後ゆっくりに変換する"""
    return 1 - (1 - t) ** 3


def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if draw.textlength(cur + ch, font=fnt) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


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
    d.rectangle([0, H - 22, W, H], fill=ACCENT)
    return im, d


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
    sub = hook.get("sub") or ""

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

    # 文字の塊を画面の中央よりやや上に置く。縦型では視線がここに来る。
    line_h = int(size * 1.22)
    block_h = (120 if sub else 0) + len(lines) * line_h + 120
    y = max(320, (H - block_h) // 2 - 60)

    if sub:
        d.text((80, y + slide), sub, font=font(72), fill=JP)
        y += 120

    for line in lines:
        d.text((80, y + slide), line, font=font(size), fill=ACCENT)
        y += line_h

    if progress > 0.14:
        d.text((80, y + 40), f"{date_label} の注目試合", font=font(52), fill=TEXT)

    d.text((80, H - 170), "コレスポ　collespo.com", font=font(38), fill=DIM)
    return im


def render_game(progress: float, g: dict, index: int, total: int):
    im, d = base_frame(progress)
    draw_brand(d)

    d.text((70, 180), f"PICK {index + 1} / {total}", font=font(40), fill=ACCENT)
    # 未明の試合はそう書き添える。20時に見ている人にとって「4:00」は
    # 今夜の続きで、翌日の昼ではない。判定は post_common に1本化してある。
    d.text((70, 250),
           post_common.kickoff_display(g.get("start_time_jst") or "") + " JST",
           font=font(46), fill=DIM)

    # --- 対戦カード(左からスライドイン) ---
    e = ease_out(min(1.0, progress * 3.2))
    dx = int((1 - e) * 160)
    card_y = 380
    d.rounded_rectangle([60 - dx, card_y, W - 60 - dx, card_y + 300], 26, fill=SURF)

    for i, side in enumerate(("home", "away")):
        y = card_y + 40 + i * 120
        team_badge(d, 100 - dx, y, g.get(f"{side}_abbr"), g.get(f"{side}_color"))
        name = g.get(f"{side}_team_name", "")
        d.text((240 - dx, y + 4), name, font=font(58), fill=TEXT)
        if g.get(f"{side}_has_jp"):
            nw = d.textlength(name, font=font(58))
            d.rounded_rectangle(
                [250 - dx + nw, y + 12, 250 - dx + nw + 74, y + 54], 8, fill=JP
            )
            d.text((262 - dx + nw, y + 14), "JP", font=font(30), fill=(11, 14, 20))

    y = 740
    # --- 先発投手 ---
    pitchers = []
    for side, label in (("home", ""), ("away", "")):
        p = g.get(f"{side}_probable")
        if p and p.get("name"):
            era = f" ({p['era']})" if p.get("era") else ""
            pitchers.append(f"{p['name']}{era}")
    if pitchers and progress > 0.08:
        d.text((70, y), "先発予定", font=font(34), fill=DIM)
        y += 52
        for line in pitchers:
            d.text((70, y), line, font=font(42), fill=TEXT)
            y += 58
        y += 24

    # --- 注目理由(1つずつ順に出す) ---
    # ライバル関係の理由文は「◯◯ vs ◯◯ は伝統の好カード — 由来…」の形で、
    # 由来まで入れると縦型の画面には収まらない。動画では見出し部分だけ使い、
    # 由来はサイト側(全文を出せる)に任せる。
    reasons = [r["text"].split(" — ")[0] for r in (g.get("reasons") or [])
               if r.get("visible", True) and r.get("text")][:3]
    for i, r in enumerate(reasons):
        appear = 0.10 + i * 0.08
        if progress < appear:
            continue
        e2 = ease_out(min(1.0, (progress - appear) * 5))
        dy = int((1 - e2) * 24)
        for line in wrap(d, "・" + r, font(42), W - 190):
            d.text((80, y + dy), line, font=font(42), fill=TEXT)
            y += 62
        y += 14

    # --- 球場の見どころ ---
    if g.get("venue_note") and progress > 0.30:
        y = max(y + 30, 1480)
        d.rounded_rectangle([60, y, W - 60, y + 230], 20, fill=ACCENT_DIM)
        yy = y + 26
        d.text((90, yy), g.get("venue_jp", ""), font=font(38), fill=ACCENT)
        yy += 56
        for line in wrap(d, g["venue_note"], font(34), W - 200)[:3]:
            d.text((90, yy), line, font=font(34), fill=ACCENT)
            yy += 48
    return im


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

    y = 380
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
        score = row.get("score", "")
        d.text((W - 100 - dx - d.textlength(score, font=font(64)), y + 20),
               score, font=font(64), fill=ACCENT)
        if note:
            d.text((100 - dx, y + 108), note, font=font(38), fill=JP)
        y += h + 24

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

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_short.mp4"

    date_label = (games[0].get("start_time_jst") or "").split(" ")[0]
    total_games = len(games[:3])

    # --- 音声を先に連結しておく ---
    audio_files = [s["file"] for s in segments if s.get("file")]
    audio_path = None
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
    try:
        for seg in segments:
            dur = max(2.0, float(seg.get("duration") or 0) or 4.0)
            n = int(dur * FPS)
            kind = seg.get("kind")
            meta = seg.get("meta") or {}
            cached = None
            for k in range(n):
                p_ = k / max(1, n - 1)
                if p_ > ANIM_END and cached is not None:
                    # 動きが止まった区間は描き直さず、直前のフレームを使い回す
                    proc.stdin.write(cached)
                    frame_no += 1
                    continue
                if kind == "intro":
                    im = render_intro(p_, date_label, meta)
                elif kind == "game":
                    gi = meta.get("game_index", 0)
                    if gi >= len(games):
                        continue
                    im = render_game(p_, games[gi], gi, total_games)
                elif kind == "score":
                    im = render_score(p_, games)
                elif kind == "recap":
                    im = render_recap(p_, meta)
                elif kind == "news":
                    im = render_news(p_, seg.get("text", ""))
                else:
                    im = render_outro(p_)
                cached = im.tobytes()
                proc.stdin.write(cached)
                frame_no += 1
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
    main()
