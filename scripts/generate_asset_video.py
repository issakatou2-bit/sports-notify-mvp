"""
資産動画(日付に依存しない、作り置きできる動画)を生成する。

日次のショートとの違い:
  日次は「その日の試合」なので、翌日には価値が落ちる。
  こちらは「知識」を扱うため、1年後に見られても内容が古くならない。
  検索から継続的に流入することを狙う、いわば在庫になる動画。

第1弾: MLB30球団の略称
  中継のスコアボードやこのサイトの通知では、球団名が3文字前後の略称で
  出てくる。ここが読めないと情報が頭に入ってこないため、
  「野球に触れ始めた人が生中継をもっと楽しめるようになる」という
  コンセプトの入口として、まずここを扱う。

内容の作り方について:
  原稿はAIに書かせず、notability_engine.py が持っている球団テーブルから
  機械的に組み立てる。事実(略称・地区・球団名)の羅列でしかないため
  文章を考える余地が無く、AIを挟むと誤りが混ざる余地が増えるだけだから。
  結果としてAPIコストもゼロになる。

使い方(2段階):
  # 1. 読み上げ原稿を書き出す
  python3 scripts/generate_asset_video.py --topic mlb_abbr \
      --narration-out build/asset_narration.json
  # 2. synthesize_narration.py で音声化した後、動画を書き出す
  python3 scripts/generate_asset_video.py --topic mlb_abbr \
      --audio-dir build/asset_audio --out build/asset
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import (  # noqa: E402
    MLB_DIVISION_NAME_JP,
    MLB_DIVISIONS,
    MLB_RIVALRIES,
    MLB_RIVALRY_NOTES,
    MLB_TEAM_ABBR,
    MLB_TEAM_COLOR,
    MLB_TEAM_NAME_JP,
    MLB_VENUE_NOTES,
)

# 縦型(ショート向け)
W, H = 1080, 1920
FPS = 24
ANIM_END = 0.45

# 種別ごとの最低表示秒数。読み上げが終わった瞬間に切り替わると
# 略称を目で追う時間が無いため、下限を設けている。
MIN_DURATION = {"intro": 5.0, "division": 9.0, "venue": 10.0,
                "rivalry": 9.0, "outro": 6.0}

BG = (11, 14, 20)
SURF = (18, 22, 31)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
JP = (73, 197, 182)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
_FONT_FILE = None

# 略称を読み上げさせるためのアルファベット読み。
# VOICEVOXにローマ字をそのまま渡すと読み方が安定しないため、
# 日本語話者が実際に口にする読み(NYY→エヌワイワイ)へ開いておく。
LETTER_KANA = {
    "A": "エー", "B": "ビー", "C": "シー", "D": "ディー", "E": "イー",
    "F": "エフ", "G": "ジー", "H": "エイチ", "I": "アイ", "J": "ジェー",
    "K": "ケー", "L": "エル", "M": "エム", "N": "エヌ", "O": "オー",
    "P": "ピー", "Q": "キュー", "R": "アール", "S": "エス", "T": "ティー",
    "U": "ユー", "V": "ブイ", "W": "ダブリュー", "X": "エックス",
    "Y": "ワイ", "Z": "ゼット",
}

# 画面に出す地区の順番。ア・リーグ→ナ・リーグ、東→中→西で固定する。
DIVISION_ORDER = ["ALE", "ALC", "ALW", "NLE", "NLC", "NLW"]


def _resolve_font() -> str:
    global _FONT_FILE
    if _FONT_FILE:
        return _FONT_FILE
    # 手元で動作確認するとき用の逃げ道。CIではLinuxの候補が先に見つかる。
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


def spell(abbr: str) -> str:
    """'NYY' -> 'エヌワイワイ'"""
    return "".join(LETTER_KANA.get(c, c) for c in abbr)


def teams_by_division() -> dict:
    """地区コード -> [(abbr, 日本語名, 色), ...] を、画面順で返す"""
    out = {code: [] for code in DIVISION_ORDER}
    for team_id, div in MLB_DIVISIONS.items():
        if div not in out:
            continue
        out[div].append((
            MLB_TEAM_ABBR.get(team_id, ""),
            MLB_TEAM_NAME_JP.get(team_id, ""),
            MLB_TEAM_COLOR.get(team_id),
        ))
    # 同じ地区の中は略称のアルファベット順にする。
    # 順位で並べると毎回変わってしまい、作り置きできる動画にならない。
    for code in out:
        out[code].sort(key=lambda t: t[0])
    return out


# ---------------------------------------------------------------------------
# 原稿
# ---------------------------------------------------------------------------

def venue_items() -> list:
    """
    球場の特徴。notability_engine の MLB_VENUE_NOTES をそのまま使う。

    毎日の注目理由でも「本塁打が出やすい球場」といった形で触れているので、
    ここで一度まとめておくと、日々の配信の理解が深まる。
    表示順は登録順(打者有利→投手有利→その他)のまま固定し、
    作り置きできる動画として毎回同じ内容になるようにしている。
    """
    return [(jp, note) for jp, note in MLB_VENUE_NOTES.values()]


def rivalry_items() -> list:
    """伝統の一戦と、その由来"""
    out = []
    for pair, kind in MLB_RIVALRIES.items():
        note = MLB_RIVALRY_NOTES.get(pair)
        if not note:
            continue
        names = sorted(MLB_TEAM_NAME_JP.get(t, "") for t in pair)
        colors = [MLB_TEAM_COLOR.get(t) for t in sorted(pair)]
        out.append({
            "title": " vs ".join(n for n in names if n),
            "kind": "伝統の一戦" if kind == "historic" else "同都市対決",
            "note": note,
            "colors": colors,
        })
    # 由来の短いものから並べると尻すぼみになるので、種別でまとめる
    out.sort(key=lambda x: (x["kind"] != "伝統の一戦", x["title"]))
    return out


def build_narration(topic: str) -> dict:
    if topic == "mlb_venue":
        return _narration_venue()
    if topic == "mlb_rivalry":
        return _narration_rivalry()
    if topic != "mlb_abbr":
        raise ValueError(f"未対応のトピックです: {topic}")

    by_div = teams_by_division()
    segments = [{
        "kind": "intro",
        "text": "野球中継のスコアボードでは、球団名がアルファベットの略称で"
                "表示されます。三十球団ぶん、地区ごとに見ていきましょう。",
        "meta": {},
    }]

    for i, code in enumerate(DIVISION_ORDER):
        teams = by_div[code]
        parts = [MLB_DIVISION_NAME_JP[code] + "。"]
        for abbr, name_jp, _ in teams:
            parts.append(f"{name_jp}は、{spell(abbr)}。")
        segments.append({
            "kind": "division",
            "text": "".join(parts),
            "meta": {"division_index": i},
        })

    segments.append(_outro_segment())
    return {"label": "MLB30球団の略称", "segments": segments}


def _outro_segment() -> dict:
    return {
        "kind": "outro",
        "text": "コレスポでは、毎日午後七時に、その日の注目試合を"
                "理由つきでお届けしています。",
        "meta": {},
    }


def _narration_venue() -> dict:
    items = venue_items()
    segments = [{
        "kind": "intro",
        "text": "野球は、球場によって試合の性格が変わります。"
                "点が入りやすい球場と、入りにくい球場を見ていきましょう。",
        "meta": {},
    }]
    # 1画面に2球場ずつ。1つずつだと画面数が増えすぎて冗長になる
    for i in range(0, len(items), 2):
        chunk = items[i:i + 2]
        text = "".join(f"{jp}。{note}。" for jp, note in chunk)
        segments.append({
            "kind": "venue",
            "text": text,
            "meta": {"start": i, "count": len(chunk)},
        })
    segments.append(_outro_segment())
    return {"label": "球場でこんなに変わる", "segments": segments}


def _narration_rivalry() -> dict:
    items = rivalry_items()
    segments = [{
        "kind": "intro",
        "text": "MLBには、勝ち負け以上の意味を持つカードがあります。"
                "なぜ因縁の対決と呼ばれるのか、由来から見ていきましょう。",
        "meta": {},
    }]
    for i, it in enumerate(items):
        segments.append({
            "kind": "rivalry",
            "text": f"{it['title']}。{it['note']}。",
            "meta": {"index": i},
        })
    segments.append(_outro_segment())
    return {"label": "MLB 伝統の一戦", "segments": segments}


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------

def base(progress):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # 背景はANIM_ENDで動きを止める。動き続けると全フレームが微妙に異なり、
    # 描画結果を使い回せなくなって生成時間がそのまま伸びる。
    off = int(min(progress, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(14, 18, 26))
    d.rectangle([0, H - 22, W, H], fill=ACCENT)
    return im, d


def abbr_badge(d, x, y, abbr, color, w=250, h=130):
    col = color or (60, 66, 80)
    if isinstance(col, str) and col.startswith("#"):
        col = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
    lum = (0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]) / 255
    fg = (17, 17, 17) if lum > 0.6 else (255, 255, 255)
    d.rounded_rectangle([x, y, x + w, y + h], 18, fill=col)
    f = font(72)
    d.text((x + (w - d.textlength(abbr, font=f)) / 2, y + 24), abbr, font=f, fill=fg)


def render_intro(p, label):
    im, d = base(p)
    e = ease_out(min(1.0, p * 2.4))
    d.text((80, 620 + int((1 - e) * 90)), "コレスポ", font=font(64), fill=ACCENT)
    d.text((80, 740), label, font=font(104), fill=TEXT)
    if p > 0.12:
        d.text((80, 900), "中継が読めるようになる", font=font(56), fill=JP)
    d.text((80, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_division(p, code, teams):
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 210), MLB_DIVISION_NAME_JP[code], font=font(76), fill=ACCENT)

    # 「今どこまで来たか」を出す。6地区を順に流すだけの動画なので、
    # 残りが見えないと途中で離脱されやすい。
    idx = DIVISION_ORDER.index(code) + 1
    f = font(40)
    prog = f"{idx} / {len(DIVISION_ORDER)}"
    d.text((W - 70 - d.textlength(prog, font=f), 84), prog, font=f, fill=DIM)

    y = 420
    for i, (abbr, name_jp, color) in enumerate(teams):
        appear = 0.05 + i * 0.06
        if p < appear:
            continue
        # 行ごとのスライドインは ANIM_END までに終わらせる。
        # そこを過ぎたフレームは描き直さず使い回すため、間に合わないと
        # 途中の位置で固まってしまう。
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        dx = int((1 - e) * 120)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + 150], 20, fill=SURF)
        abbr_badge(d, 90 - dx, y + 10, abbr, color)
        d.text((370 - dx, y + 36), name_jp, font=font(58), fill=TEXT)
        y += 250

    # ショートは切り抜き・スクショで出回るので、どの画面にも出典を残す
    d.text((70, H - 130), "collespo.com", font=font(38), fill=DIM)
    return im


def _wrap(d, text, fnt, max_w):
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


def render_venue(p, items, start, count, page, pages):
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    f = font(40)
    prog = f"{page} / {pages}"
    d.text((W - 70 - d.textlength(prog, font=f), 84), prog, font=f, fill=DIM)
    d.text((70, 210), "球場でこんなに変わる", font=font(72), fill=ACCENT)

    y = 430
    for i in range(count):
        jp, note = items[start + i]
        appear = 0.06 + i * 0.10
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        dx = int((1 - e) * 120)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + 470], 22, fill=SURF)
        d.text((100 - dx, y + 34), jp, font=font(56), fill=JP)
        yy = y + 130
        for line in _wrap(d, note, font(42), W - 220)[:6]:
            d.text((100 - dx, yy), line, font=font(42), fill=TEXT)
            yy += 62
        y += 520

    d.text((70, H - 130), "collespo.com", font=font(38), fill=DIM)
    return im


def render_rivalry(p, item, index, total):
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    f = font(40)
    prog = f"{index + 1} / {total}"
    d.text((W - 70 - d.textlength(prog, font=f), 84), prog, font=f, fill=DIM)

    e = ease_out(min(1.0, p * 3))
    dx = int((1 - e) * 130)

    # 両球団のカラーを帯で示す。ロゴは使わず色だけを借りる
    for i, col in enumerate(item["colors"][:2]):
        c = col or "#3C4250"
        if isinstance(c, str) and c.startswith("#"):
            c = tuple(int(c[j:j + 2], 16) for j in (1, 3, 5))
        d.rounded_rectangle([70 - dx + i * 130, 210, 190 - dx + i * 130, 290], 12, fill=c)

    d.text((70 - dx, 340), item["kind"], font=font(44), fill=JP)

    y = 430
    for line in _wrap(d, item["title"], font(84), W - 160)[:3]:
        d.text((70 - dx, y), line, font=font(84), fill=ACCENT)
        y += 104

    if p > 0.14:
        y += 50
        d.rounded_rectangle([60, y - 30, W - 60, y + 350], 22, fill=SURF)
        yy = y + 10
        for line in _wrap(d, item["note"], font(46), W - 200)[:6]:
            d.text((100, yy), line, font=font(46), fill=TEXT)
            yy += 68

    d.text((70, H - 130), "collespo.com", font=font(38), fill=DIM)
    return im


def render_outro(p):
    im, d = base(p)
    d.text((80, 640), "コレスポ", font=font(120), fill=ACCENT)
    d.text((80, 800), "collespo.com", font=font(58), fill=TEXT)
    if p > 0.12:
        d.text((80, 910), "毎日19時 更新", font=font(46), fill=DIM)
    # VOICEVOXの利用規約で、動画内または説明欄へのクレジット表記が
    # 求められているため、アウトロに必ず表示する
    d.text((80, 1150), "音声: VOICEVOX:ずんだもん", font=font(40), fill=DIM)
    d.text((80, 1220), "データ: MLB Stats API", font=font(40), fill=DIM)
    return im


# ---------------------------------------------------------------------------
# 尺と音声
# ---------------------------------------------------------------------------

def plan_durations(segs: list) -> list:
    return [max(MIN_DURATION.get(s.get("kind") or "division", 6.0),
                float(s.get("duration") or 0), 3.0)
            for s in segs]


def build_narration_track(segs, durations, out_dir):
    """
    各セグメントの音声を、その区間の長さまで無音で埋めてから連結する。

    画面は下限秒数で表示されるので、読み上げより画面の方が長い。
    音声を詰めて繋ぐと差が積み上がって画面と音がずれ、さらに音声トラックが
    映像より短くなるため ffmpeg の -shortest が出力を音声の長さで
    打ち切ってしまう(週次動画で実際に起きた)。
    """
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
            frames = int(gap * params.framerate)
            w.writeframes(b"\x00" * (frames * params.nchannels * params.sampwidth))
        parts.append(sil.resolve())

    lst = out_dir / "audio_list.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    audio_path = out_dir / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(audio_path)],
                   check=True, capture_output=True)
    return audio_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="mlb_abbr")
    parser.add_argument("--narration-out", default=None,
                        help="指定すると原稿だけ書き出して終了する")
    parser.add_argument("--audio-dir", default="build/asset_audio")
    parser.add_argument("--out", default="build/asset")
    args = parser.parse_args()

    narration = build_narration(args.topic)

    if args.narration_out:
        p = pathlib.Path(args.narration_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(narration, ensure_ascii=False), encoding="utf-8")
        chars = sum(len(s["text"]) for s in narration["segments"])
        print(f"[info] 原稿を書き出しました: {p} "
              f"({len(narration['segments'])}セグメント / 計{chars}文字)")
        return

    by_div = teams_by_division()
    venues = venue_items()
    rivalries = rivalry_items()
    label = narration["label"]

    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestが見つかりません: {manifest.resolve()}")
        print("       音声なし・固定秒数で作ります")
        segs = [{"kind": s["kind"], "file": None, "duration": 0.0,
                 "meta": s["meta"]} for s in narration["segments"]]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"collespo_asset_{args.topic}.mp4"

    durations = plan_durations(segs)
    audio_path = build_narration_track(segs, durations, out_dir)

    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-"]
    if audio_path:
        cmd += ["-i", str(audio_path)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p"]
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
                    im = render_intro(pp, label)
                elif kind == "division":
                    code = DIVISION_ORDER[meta.get("division_index", 0)]
                    im = render_division(pp, code, by_div[code])
                elif kind == "venue":
                    im = render_venue(pp, venues, meta.get("start", 0),
                                      meta.get("count", 1),
                                      meta.get("start", 0) // 2 + 1,
                                      (len(venues) + 1) // 2)
                elif kind == "rivalry":
                    idx = meta.get("index", 0)
                    im = render_rivalry(pp, rivalries[idx], idx, len(rivalries))
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
    print(f"[info] 資産動画を生成しました: {video_path} "
          f"({size_mb:.1f}MB, {secs:.0f}秒)")


if __name__ == "__main__":
    main()
