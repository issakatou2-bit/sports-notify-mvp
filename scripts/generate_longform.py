#!/usr/bin/env python3
"""
対話の台本から、16:9の通常動画を作る。

なぜ短編と別の台本にするのか:
  画面の比が違う(1080×1920 と 1920×1080)。座標がまるごと変わるので、
  同じ関数に両方を通すと分岐だらけになる。
  下地・色・フォントは generate_weekly.py と同じものを使う。

画面の作り:
  左に喋っている人、右に台詞。喋っていない側は暗くする。
  誰が喋っているかを、聞かなくても分かる状態にしておきたい。

  立ち絵は置ける場所を空けてある(--portrait-dir)。無くても成立する
  ように、名前と色の丸で代用する。絵が無いから作れない、にはしない。

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

from PIL import Image, ImageDraw  # noqa: E402

import video_common  # noqa: E402

# 週次動画と同じ寸法・色・フォントを使う。
# 同じチャンネルの通常動画が、2つ別の見た目を持つ理由が無い。
from generate_weekly import (  # noqa: E402
    W, H, FPS, ANIM_END, BG, SURF, TEXT, DIM, ACCENT, JP,
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

# 台詞の1画面に置く最大の行数。超えたら小さくする。
MAX_LINES = 5


def _speaker(seg: dict) -> dict:
    sid = seg.get("speaker")
    return SPEAKERS.get(sid) or SPEAKERS[DEFAULT_SPEAKER]


def _portrait(who: str, portrait_dir: str):
    """立ち絵。無ければ None。

    公式配布のものだけを想定している。二次創作の立ち絵は
    配布者ごとに規約が違うので、自動で投稿する仕組みには入れない。
    """
    if not portrait_dir:
        return None
    for ext in (".png", ".webp"):
        p = pathlib.Path(portrait_dir) / (who + ext)
        if p.exists():
            try:
                return Image.open(p).convert("RGBA")
            except Exception:                    # noqa: BLE001
                return None
    return None


def render_line(p, seg, portrait_dir="", topic=""):
    """1つの台詞。喋っている側を明るく、もう片方を暗くする。"""
    im, d = base(p)
    who = _speaker(seg)
    text = seg.get("text", "")

    if topic:
        d.text((60, 44), topic[:44], font=font(34), fill=DIM)

    # 立っている2人。喋っているほうだけ色が付く。
    for sid, s in SPEAKERS.items():
        talking = s["name"] == who["name"]
        x = 150 if s["side"] == "left" else W - 150
        col = s["color"] if talking else (52, 58, 72)

        art = _portrait(s["name"], portrait_dir)
        if art:
            k = 620 / art.height
            art = art.resize((int(art.width * k), 620))
            if not talking:
                # 喋っていない側は暗く落とす。消さない(そこに居るので)
                dark = Image.new("RGBA", art.size, (0, 0, 0, 150))
                art = Image.alpha_composite(art, dark)
            im.paste(art, (int(x - art.width / 2), H - 700), art)
        else:
            # 絵が無くても成立させる。色の丸と名前で代用する。
            r = 74 if talking else 62
            d.ellipse([x - r, 300 - r, x + r, 300 + r], fill=col)

        nm = s["name"]
        f = font(40 if talking else 34)
        d.text((x - d.textlength(nm, font=f) / 2, 400),
               nm, font=f, fill=col if talking else DIM)

    # 台詞。喋っている側に寄せて置く。
    left = who["side"] == "left"
    x0 = 330 if left else 60
    x1 = W - 60 if left else W - 330
    size = 52
    lines = wrap(d, text, font(size), x1 - x0 - 80)
    while len(lines) > MAX_LINES and size > 32:
        size -= 6
        lines = wrap(d, text, font(size), x1 - x0 - 80)
    lines = lines[:MAX_LINES]

    h = len(lines) * (size + 18) + 60
    y0 = H - 330
    d.rounded_rectangle([x0, y0, x1, y0 + h], 24, fill=SURF)
    # 喋っている側の縁に色の帯。吹き出しの尻尾の代わり。
    if left:
        d.rounded_rectangle([x0, y0, x0 + 10, y0 + h], 5, fill=who["color"])
    else:
        d.rounded_rectangle([x1 - 10, y0, x1, y0 + h], 5, fill=who["color"])

    # 動きは文字が出そろうまで。ANIM_END を過ぎたら固定して、
    # フレームを使い回せるようにする。
    shown = len(lines) if p >= ANIM_END else max(
        1, int(len(lines) * (p / ANIM_END)))
    yy = y0 + 28
    for ln in lines[:shown]:
        d.text((x0 + 40, yy), ln, font=font(size), fill=TEXT)
        yy += size + 18

    d.text((60, H - 62), "コレスポ  collespo.com", font=font(30), fill=DIM)
    d.text((W - 560, H - 62),
           "音声: VOICEVOX ずんだもん / 四国めたん", font=font(28), fill=DIM)
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
        dia = json.loads(pathlib.Path(args.dialogue).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[info] 台本を読めません({e})。作りません")
        return 0
    topic = dia.get("top") or ""

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

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_longform.mp4"

    # 台詞ごとの尺。読み終わりに息継ぎを足す。
    durations = [max(1.6, float(s.get("duration") or 0)
                     + video_common.SEGMENT_TAIL) for s in segs]
    total = sum(durations)
    print(f"[info] {len(segs)}台詞 / {total:.0f}秒")

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
    try:
        for i, (seg, dur) in enumerate(zip(segs, durations)):
            n = int(dur * FPS)
            fade = 0 if i == 0 else int(video_common.FADE_SECONDS * FPS)
            cached = None
            for k in range(n):
                p = k / max(1, n - 1)
                if p > ANIM_END and cached is not None:
                    proc.stdin.write(cached)
                    continue
                im = render_line(p, seg, args.portrait_dir, topic)
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
