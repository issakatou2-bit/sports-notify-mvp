"""
「先週の答え合わせ」の縦型ショートを作る。

なぜ独立させるのか:
  コレスポは毎日「なぜこの試合が注目なのか」を理由つきで予告し、
  その理由と結果の両方をアーカイブに残している。だから
  「◯連勝中だから注目、と書いた試合が実際どうなったか」を後から言える。
  これは毎日予告を出し続けて記録している者にしか出せない内容で、
  週次動画の一画面に埋もれさせるには惜しい。

  日次ショートが「これから」を扱うのに対し、こちらは「答え」を扱うので、
  同じチャンネルの中で性格が違う2本立てになる。

構成:
  1. 冒頭 … 「当たった / 外れた」を数で見せて引き込む
  2. 各判定 … 1件ずつ大きく(連勝が続いたのか、止まったのか)
  3. 集計 … その週の注目試合ぜんたいの数字
  4. アウトロ

使い方(2段階。日次・週次と同じ流れ):
  python3 scripts/generate_verdict_short.py --narration-out build/vs_narration.json
  python3 scripts/generate_verdict_short.py --audio-dir build/vs_audio --out build/verdict
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageFont

import weekly_stats as ws

W, H = 1080, 1920
FPS = 24
ANIM_END = 0.45
SEGMENT_TAIL = 1.5

MIN_DURATION = {"intro": 5.0, "check": 6.0, "totals": 7.0, "outro": 5.0}

BG = (11, 14, 20)
SURF = (18, 22, 31)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
WIN_COL = (73, 197, 182)
LOSE_COL = (232, 116, 116)

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
    env = os.environ.get("COLLESPO_FONT")
    if env and pathlib.Path(env).exists():
        _FONT_FILE = env
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


def ease_out(t):
    return 1 - (1 - t) ** 3


def wrap(d, text, fnt, max_w):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=fnt) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def fit(d, text, max_w, sizes):
    for s in sizes:
        if d.textlength(text, font=font(s)) <= max_w:
            return s
    return sizes[-1]


def base(progress):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    off = int(min(progress, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(14, 18, 26))
    d.rectangle([0, H - 22, W, H], fill=ACCENT)
    return im, d


# ---------------------------------------------------------------------------
# 原稿
# ---------------------------------------------------------------------------

def build_narration(verdict: dict, label: str) -> dict:
    streaks = verdict.get("streaks") or []
    hit = sum(1 for s in streaks if s["held"])

    segments = [{
        "kind": "intro",
        "text": f"コレスポが先週注目した試合、実際どうなったか。"
                f"連勝や連敗を理由に取り上げた{len(streaks)}件のうち、"
                f"{hit}件はそのまま続きました。",
        "meta": {"total": len(streaks), "hit": hit, "label": label},
    }]

    for i, s in enumerate(streaks[:4]):
        segments.append({
            "kind": "check",
            "text": f"{s['n']}{s['kind']}中として取り上げた{s['team']}は、"
                    f"{s['spoken']}。",
            "meta": {"index": i},
        })

    if verdict.get("decided"):
        segments.append({
            "kind": "totals",
            "text": f"先週の注目試合は{verdict['decided']}試合で結果が出て、"
                    f"ホームチームは{verdict['home_wins']}勝"
                    f"{verdict['away_wins']}敗でした。",
            "meta": {},
        })

    segments.append({
        "kind": "outro",
        # アウトロは「何をしているか」の説明で終わっていた。
        # 次に何があるかを言い、登録を促す形に変える。
        # 登録が増えないと、毎日出しても毎日ゼロから始まる。
        "text": "今夜7時には、明日の注目試合を理由つきで出します。"
                # 「方」は「ほう」と読まれる。読み上げ用の原稿なので仮名で書く。
        "見逃したくないかたは、チャンネル登録をお願いします。",
        "meta": {},
    })
    return {"label": label, "segments": segments}


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------

def render_intro(p, meta):
    im, d = base(p)
    total = meta.get("total", 0)
    hit = meta.get("hit", 0)

    e = ease_out(min(1.0, p * 2.6))
    slide = int((1 - e) * 70)

    # 「当たった?」とは書かない。コレスポは勝敗を予測しているのではなく、
    # 注目する理由を挙げているだけなので、的中/外れという枠組みが事実と合わない。
    d.text((80, 470 + slide), "先週の注目試合", font=font(64), fill=DIM)
    d.text((80, 570 + slide), "どうなった？", font=font(140), fill=ACCENT)

    if p > 0.14:
        # 「◯ / ◯」を大きく見せる。数字だけで内容が想像でき、
        # 音を切っていても何の動画かが分かる
        d.rounded_rectangle([70, 800, W - 70, 1120], 24, fill=SURF)
        big = f"{hit} / {total}"
        s = fit(d, big, W - 260, (180, 156, 132))
        tw = d.textlength(big, font=font(s))
        d.text(((W - tw) / 2, 840), big, font=font(s), fill=WIN_COL)
        sub = "連勝・連敗がそのまま続いた数"
        sw = d.textlength(sub, font=font(42))
        d.text(((W - sw) / 2, 1040), sub, font=font(42), fill=DIM)

    d.text((80, 1230), meta.get("label", ""), font=font(46), fill=TEXT)
    d.text((80, H - 170), "コレスポ　collespo.com", font=font(38), fill=DIM)
    return im


def render_check(p, s):
    im, d = base(p)
    col = WIN_COL if s["won"] else LOSE_COL

    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 200), "注目した理由", font=font(44), fill=DIM)

    e = ease_out(min(1.0, p * 3))
    dx = int((1 - e) * 130)

    # 予告した内容
    d.rounded_rectangle([60 - dx, 300, W - 60 - dx, 520], 22, fill=SURF)
    d.text((100 - dx, 330), s["team"], font=font(56), fill=TEXT)
    d.text((100 - dx, 415), f"{s['n']}{s['kind']}中", font=font(60), fill=ACCENT)

    if p > 0.16:
        # 結果。色で勝敗が一目で分かるようにする
        d.text((70, 640), "結果", font=font(44), fill=DIM)
        y = 730
        size = fit(d, s["result"], W - 160, (104, 92, 80, 68))
        for line in wrap(d, s["result"], font(size), W - 160)[:2]:
            d.text((70, y), line, font=font(size), fill=col)
            y += int(size * 1.25)

        d.rounded_rectangle([70, y + 50, W - 70, y + 190], 18, fill=SURF)
        d.text((110, y + 88), f"{s['matchup']}　{s['score']}",
               font=font(46), fill=TEXT)

    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_totals(p, verdict):
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 210), "先週ぜんたい", font=font(76), fill=ACCENT)

    y = 400
    for i, (big, small) in enumerate(ws.verdict_lines(verdict)[:4]):
        if p < 0.06 + i * 0.07:
            continue
        d.rounded_rectangle([60, y, W - 60, y + 220], 22, fill=SURF)
        d.text((100, y + 30), big, font=font(84), fill=TEXT)
        d.text((104, y + 140), small, font=font(38), fill=DIM)
        y += 250
    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_outro(p):
    im, d = base(p)
    d.text((80, 620), "コレスポ", font=font(120), fill=ACCENT)
    d.text((80, 780), "毎日19時", font=font(76), fill=TEXT)
    if p > 0.10:
        d.text((80, 880), "その日の注目試合を", font=font(50), fill=TEXT)
        d.text((80, 950), "「なぜ注目か」の理由つきで", font=font(50), fill=TEXT)
    if p > 0.20:
        d.rounded_rectangle([70, 1060, W - 70, 1170], 18, fill=ACCENT)
        d.text((110, 1088), "チャンネル登録で毎日届きます", font=font(46), fill=BG)
    d.text((80, 1220), "collespo.com", font=font(46), fill=TEXT)
    d.text((80, 1340), "音声: VOICEVOX:ずんだもん", font=font(38), fill=DIM)
    d.text((80, 1400), "データ: MLB Stats API", font=font(38), fill=DIM)
    return im


# ---------------------------------------------------------------------------
# 尺と音声(週次動画と同じ考え方)
# ---------------------------------------------------------------------------

def plan_durations(segs):
    return [max(MIN_DURATION.get(s.get("kind") or "check", 5.0),
                float(s.get("duration") or 0) + SEGMENT_TAIL)
            for s in segs]


def build_narration_track(segs, durations, out_dir):
    """各区間の余りを無音で埋める。詰めて繋ぐと画面と音がずれる。"""
    if not any(s.get("file") for s in segs):
        return None
    params = None
    for s in segs:
        if s.get("file") and pathlib.Path(s["file"]).exists():
            with wave.open(s["file"], "rb") as w:
                params = w.getparams()
            break
    if params is None:
        return None

    pad_dir = out_dir / "silence"
    pad_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, (seg, dur) in enumerate(zip(segs, durations)):
        spoken = 0.0
        path = seg.get("file")
        if path and pathlib.Path(path).exists():
            with wave.open(path, "rb") as w:
                spoken = w.getnframes() / float(w.getframerate())
            parts.append(pathlib.Path(path).resolve())
        gap = dur - spoken
        if gap <= 0.02:
            continue
        sil = pad_dir / f"pad_{i:03d}.wav"
        with wave.open(str(sil), "wb") as w:
            w.setnchannels(params.nchannels)
            w.setsampwidth(params.sampwidth)
            w.setframerate(params.framerate)
            n = int(gap * params.framerate)
            w.writeframes(b"\x00" * (n * params.nchannels * params.sampwidth))
        parts.append(sil.resolve())

    lst = out_dir / "audio_list.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    audio = out_dir / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(audio)],
                   check=True, capture_output=True)
    return audio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--narration-out", default=None)
    parser.add_argument("--audio-dir", default="build/vs_audio")
    parser.add_argument("--out", default="build/verdict")
    args = parser.parse_args()

    week = ws.load_week(pathlib.Path(args.archive_dir))
    if len(week) < 2:
        print("[info] アーカイブが足りないため、答え合わせショートは作りません")
        return

    verdict = ws.compute_verdict(week)
    streaks = verdict.get("streaks") or []
    if not streaks:
        # 連勝・連敗を理由に取り上げた試合が1件も無い週は、
        # 「答え合わせ」として見せるものが無い。無理に作らない。
        print("[info] 今週は連勝・連敗を理由にした試合が無いため作りません")
        return

    label = (f"{week[0][0][5:].replace('-', '/')}〜"
             f"{week[-1][0][5:].replace('-', '/')}")
    narration = build_narration(verdict, label)

    if args.narration_out:
        p = pathlib.Path(args.narration_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(narration, ensure_ascii=False), encoding="utf-8")
        chars = sum(len(s["text"]) for s in narration["segments"])
        print(f"[info] 原稿を書き出しました: {p} "
              f"({len(narration['segments'])}セグメント / {chars}文字)")
        return

    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestが見つかりません: {manifest.resolve()}")
        segs = [{"kind": s["kind"], "file": None, "duration": 0.0,
                 "meta": s["meta"]} for s in narration["segments"]]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_verdict.mp4"

    durations = plan_durations(segs)
    audio_path = build_narration_track(segs, durations, out_dir)

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

    err_path = out_dir / "ffmpeg_error.log"
    err_file = open(err_path, "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=err_file)
    total = 0
    try:
        for seg, dur in zip(segs, durations):
            n = int(dur * FPS)
            kind, meta = seg.get("kind"), seg.get("meta") or {}
            cached = None
            for k in range(n):
                pp = k / max(1, n - 1)
                if pp > ANIM_END and cached is not None:
                    proc.stdin.write(cached)
                    total += 1
                    continue
                if kind == "intro":
                    im = render_intro(pp, meta)
                elif kind == "check":
                    im = render_check(pp, streaks[meta.get("index", 0)])
                elif kind == "totals":
                    im = render_totals(pp, verdict)
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
    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"[info] 答え合わせショートを生成しました: {video_path} "
          f"({size_mb:.1f}MB, {secs:.0f}秒)")
    if secs > 180:
        print("::warning title=ショートの上限超過::"
              "3分を超えるとショートとして扱われません")


if __name__ == "__main__":
    main()
