"""
1週間分のアーカイブから、まとめ動画(横型・8分以上を狙う)を生成する。

なぜ横型・長尺なのか:
  YouTubeは8分以上の動画でミッドロール広告を設置できるため、
  収益性で有利になる。またショートと違い「じっくり見る」形式なので、
  横型(16:9)で情報量を増やす方が合う。

構成:
  1. オープニング
  2. 今週の注目試合(日ごとに1試合ずつ、7日分)
  3. 今週の結果ハイライト(スコアが記録されているもの)
  4. 今週の動き(ロースター変化)
  5. クロージング

  日次のショートと違い、既に結果が出ているため
  「注目された試合が実際どうだったか」まで語れるのが強み。

使い方:
  python3 scripts/generate_weekly.py --archive-dir archive --out build/weekly
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

# 横型(通常動画向け)
W, H = 1920, 1080
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

DATE_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.json$")
JST = timezone(timedelta(hours=9))

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
_FONT_FILE = None


def _resolve_font() -> str:
    global _FONT_FILE
    if _FONT_FILE:
        return _FONT_FILE
    for p in FONT_CANDIDATES:
        if pathlib.Path(p).exists():
            _FONT_FILE = p
            return p
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"],
                           capture_output=True, text=True, check=True)
        if r.stdout.strip():
            _FONT_FILE = r.stdout.strip()
            return _FONT_FILE
    except Exception:
        pass
    raise RuntimeError("日本語フォントが見つかりません")


def font(size: int):
    path = _resolve_font()
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        for i in (1, 2, 3):
            try:
                return ImageFont.truetype(path, size, index=i)
            except OSError:
                continue
        raise


def ease_out(t): return 1 - (1 - t) ** 3


def wrap(d, text, fnt, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if d.textlength(cur + ch, font=fnt) > max_w:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def base(progress):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # 背景はANIM_ENDで動きを止める。ここが動き続けると全フレームが
    # 微妙に異なり、描画結果を使い回せなくなるため。
    off = int(min(progress, ANIM_END) * 200)
    for i in range(-2, 8):
        x = i * 420 + off
        d.polygon([(x, H), (x + 180, H), (x + 480, 0), (x + 300, 0)], fill=(14, 18, 26))
    d.rectangle([0, H - 16, W, H], fill=ACCENT)
    return im, d


def badge(d, x, y, abbr, color, w=110, h=58):
    if not abbr and not color:
        return
    if not abbr:
        # ランキング表示など、色だけ小さく示したい場合
        w, h = 20, 44
    col = color or (60, 66, 80)
    if isinstance(col, str) and col.startswith("#"):
        col = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
    lum = (0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]) / 255
    fg = (17, 17, 17) if lum > 0.6 else (255, 255, 255)
    d.rounded_rectangle([x, y, x + w, y + h], 10, fill=col)
    if not abbr:
        return
    f = font(30)
    d.text((x + (w - d.textlength(abbr, font=f)) / 2, y + 11), abbr, font=f, fill=fg)


def render_intro(p, label):
    im, d = base(p)
    e = ease_out(min(1.0, p * 2.2))
    d.text((140, 380 + int((1 - e) * 60)), "コレスポ", font=font(150), fill=ACCENT)
    if p > 0.10:
        d.text((140, 580), f"{label} 週間まとめ", font=font(76), fill=TEXT)
    d.text((140, H - 140), "collespo.com", font=font(40), fill=DIM)
    return im


def render_day(p, date_str, game):
    im, d = base(p)
    d.text((100, 70), "コレスポ", font=font(44), fill=ACCENT)
    y, m, dd = date_str.split("-")
    d.text((100, 190), f"{int(m)}月{int(dd)}日", font=font(64), fill=ACCENT)

    e = ease_out(min(1.0, p * 3))
    dx = int((1 - e) * 140)
    d.rounded_rectangle([100 - dx, 300, W - 100 - dx, 520], 22, fill=SURF)
    for i, side in enumerate(("home", "away")):
        yy = 330 + i * 90
        badge(d, 140 - dx, yy, game.get(f"{side}_abbr"), game.get(f"{side}_color"))
        name = game.get(f"{side}_team_name", "")
        d.text((280 - dx, yy - 2), name, font=font(52), fill=TEXT)
        if game.get(f"{side}_has_jp"):
            nw = d.textlength(name, font=font(52))
            d.rounded_rectangle([300 - dx + nw, yy + 8, 300 - dx + nw + 66, yy + 46], 7, fill=JP)
            d.text((312 - dx + nw, yy + 10), "JP", font=font(26), fill=BG)

    fs = game.get("final_score")
    if fs and p > 0.12:
        winner = (game.get("home_team_name") if fs.get("winner") == "home"
                  else game.get("away_team_name"))
        d.rounded_rectangle([W - 640, 300, W - 100, 420], 18, fill=ACCENT_DIM)
        d.text((W - 600, 320), f"{fs.get('home')} - {fs.get('away')}", font=font(56), fill=ACCENT)
        d.text((W - 600, 385), f"{winner} 勝利", font=font(30), fill=ACCENT)

    yy = 600
    for i, r in enumerate([x["text"] for x in (game.get("reasons") or [])
                           if x.get("visible", True) and x.get("text")][:3]):
        if p < 0.12 + i * 0.07:
            continue
        for line in wrap(d, "・" + r, font(40), W - 300):
            d.text((120, yy), line, font=font(40), fill=TEXT)
            yy += 58
        yy += 10
    return im


def render_news(p, items):
    im, d = base(p)
    d.text((100, 70), "コレスポ", font=font(44), fill=ACCENT)
    d.text((100, 200), "今週の動き", font=font(70), fill=JP)
    yy = 360
    for i, t in enumerate(items[:4]):
        if p < 0.08 + i * 0.07:
            continue
        d.rounded_rectangle([100, yy - 18, W - 100, yy + 74], 16, fill=SURF)
        for line in wrap(d, t, font(42), W - 260)[:1]:
            d.text((140, yy), line, font=font(42), fill=TEXT)
        yy += 120
    return im


def render_ranking(p, ranking):
    """その週に注目試合として取り上げられた回数の多い球団を並べる"""
    im, d = base(p)
    d.text((100, 70), "コレスポ", font=font(44), fill=ACCENT)
    d.text((100, 190), "今週よく登場した球団", font=font(70), fill=ACCENT)
    yy = 340
    for i, (name, count, color) in enumerate(ranking[:5]):
        if p < 0.06 + i * 0.06:
            continue
        e = ease_out(min(1.0, (p - (0.1 + i * 0.13)) * 6))
        # アニメーション開始直後は幅が0になり、rounded_rectangleが
        # 「x1がx0より小さい」で例外を投げるため、最低幅を確保する
        bar_w = max(2, int((W - 700) * (count / max(1, ranking[0][1])) * e))
        d.text((120, yy), f"{i + 1}", font=font(44), fill=DIM)
        badge(d, 190, yy - 4, None, color)
        d.text((200, yy), name, font=font(46), fill=TEXT)
        d.rounded_rectangle([620, yy + 8, 620 + bar_w, yy + 46], 8, fill=ACCENT_DIM)
        d.text((640, yy + 8), f"{count}回", font=font(34), fill=ACCENT)
        yy += 110
    return im


def render_outro(p):
    im, d = base(p)
    d.text((140, 360), "コレスポ", font=font(140), fill=ACCENT)
    d.text((140, 540), "collespo.com", font=font(64), fill=TEXT)
    d.text((140, 640), "毎日19時 更新", font=font(48), fill=DIM)
    d.text((140, 800), "音声: VOICEVOX:ずんだもん", font=font(38), fill=DIM)
    d.text((140, 860), "データ: MLB Stats API", font=font(38), fill=DIM)
    return im


def load_week(archive_dir: pathlib.Path, days: int = 7):
    """直近days日分のアーカイブを、古い順に返す"""
    entries = []
    for f in sorted(archive_dir.glob("*.json")):
        m = DATE_FILE_RE.match(f.name)
        if not m:
            continue
        entries.append((f.name[:10], f))
    entries.sort(key=lambda x: x[0], reverse=True)
    out = []
    for date_str, path in entries[:days]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        games = [g for g in data.get("games", []) if g.get("is_notable")]
        # 1日あたり2試合まで扱う。1試合だけだと全体が3分程度にしかならず、
        # ミッドロール広告の条件(8分以上)に届かないため。
        for g in games[:2]:
            out.append((date_str, g))
    out.reverse()
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--news", default="public/news.json")
    parser.add_argument("--audio-dir", default="build/weekly_audio")
    parser.add_argument("--out", default="build/weekly")
    args = parser.parse_args()

    archive_dir = pathlib.Path(args.archive_dir)
    if not archive_dir.exists():
        print("[warn] アーカイブが無いため、週次動画は作りません")
        return

    week = load_week(archive_dir)
    if len(week) < 2:
        print(f"[info] アーカイブが{len(week)}日分しか無いため、"
              "週次動画はまだ作りません(2日分以上必要)")
        return

    news_items = []
    npath = pathlib.Path(args.news)
    if npath.exists():
        try:
            news_items = [n["text"] for n in
                          (json.loads(npath.read_text(encoding="utf-8")).get("news") or [])]
        except (json.JSONDecodeError, OSError):
            pass

    label = f"{week[0][0][5:].replace('-', '/')}〜{week[-1][0][5:].replace('-', '/')}"

    # 週間の登場回数ランキング(既にあるデータの集計だけなので追加コストなし)
    counts = {}
    for _, g in week:
        for side in ("home", "away"):
            n = g.get(f"{side}_team_name")
            if n:
                counts.setdefault(n, [0, g.get(f"{side}_color")])
                counts[n][0] += 1
    ranking = sorted(
        [(n, v[0], v[1]) for n, v in counts.items()], key=lambda x: -x[1]
    )

    # 音声があれば尺を合わせ、無ければ既定秒数で作る
    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        segs = [{"kind": "intro", "duration": 10.0, "file": None, "meta": {}}]
        for i in range(len(week)):
            segs.append({"kind": "day", "duration": 30.0, "file": None,
                         "meta": {"day_index": i}})
        if ranking:
            segs.append({"kind": "ranking", "duration": 30.0, "file": None, "meta": {}})
        if news_items:
            segs.append({"kind": "news", "duration": 20.0, "file": None, "meta": {}})
        segs.append({"kind": "outro", "duration": 10.0, "file": None, "meta": {}})

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_weekly.mp4"

    audio_files = [s["file"] for s in segs if s.get("file")]
    audio_path = None
    if audio_files:
        lst = out_dir / "audio_list.txt"
        lst.write_text("\n".join(f"file '{pathlib.Path(a).resolve()}'"
                                 for a in audio_files), encoding="utf-8")
        audio_path = out_dir / "narration.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(audio_path)],
                       check=True, capture_output=True)

    # -nostats/-loglevel error で、ffmpegが標準エラーへ書く量を最小限にする。
    # 出力が多いとパイプのバッファが埋まり、ffmpegが停止して
    # こちらの書き込みも止まる(デッドロック)。
    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-"]
    if audio_path:
        cmd += ["-i", str(audio_path)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [str(video_path)]

    # stderrはパイプではなくファイルへ逃がす。
    # パイプのままだと、こちらが読まない限りバッファが埋まって止まる。
    err_path = out_dir / "ffmpeg_error.log"
    err_file = open(err_path, "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=err_file)
    total = 0
    try:
        for seg in segs:
            dur = max(3.0, float(seg.get("duration") or 0) or 10.0)
            n = int(dur * FPS)
            kind, meta = seg.get("kind"), seg.get("meta") or {}
            cached = None
            for k in range(n):
                pp = k / max(1, n - 1)
                if pp > ANIM_END and cached is not None:
                    # 動きが止まった区間は描き直さず、直前のフレームを使い回す
                    proc.stdin.write(cached)
                    total += 1
                    continue
                if kind == "intro":
                    im = render_intro(pp, label)
                elif kind == "day":
                    di = meta.get("day_index", 0)
                    if di >= len(week):
                        continue
                    im = render_day(pp, week[di][0], week[di][1])
                elif kind == "ranking":
                    im = render_ranking(pp, ranking)
                elif kind == "news":
                    im = render_news(pp, news_items)
                else:
                    im = render_outro(pp)
                cached = im.tobytes()
                proc.stdin.write(cached)
                total += 1
            print(f"[info] {kind}: {dur:.1f}秒")
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait()
        err_file.close()

    if proc.returncode != 0:
        print(f"[error] 書き出しに失敗:\n"
              f"{err_path.read_text(encoding='utf-8', errors='ignore')[-1500:]}",
              file=sys.stderr)
        sys.exit(1)

    secs = total / FPS
    print(f"[info] 週次動画を生成しました: {video_path} ({secs / 60:.1f}分)")
    if secs < 480:
        print(f"[info] 8分に{480 - secs:.0f}秒不足しています"
              "(ミッドロール広告は8分以上が条件)")


if __name__ == "__main__":
    main()
