"""
「昨夜の日本人選手」の縦型ショートを作る。

19時の予告(これから起きること)に対して、こちらは朝の枠(終わったこと)。
MLBは日本の朝に終わるので、起きた直後に結果を1本で確認できる。
結果は確定しているため推測が一切入らず、全部が検証済みの数字になる。

構成:
  1. 冒頭 … 一番目立った成績を大きく
  2. 一覧 … 出場した選手を投手・打者の順に
  3. アウトロ

使い方(2段階):
  python3 scripts/generate_morning_short.py --narration-out build/mr_narration.json
  python3 scripts/generate_morning_short.py --audio-dir build/mr_audio --out build/morning
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import wave
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

import local_buzz
import mlb_buzz
import morning_recap

W, H = 1080, 1920
FPS = 24
ANIM_END = 0.45
SEGMENT_TAIL = 1.5
MIN_DURATION = {"intro": 5.0, "list": 8.0, "buzz": 9.0,
                "talk": 9.0, "outro": 5.0}

BG = (11, 14, 20)
SURF = (18, 22, 31)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
ACCENT_DIM = (74, 58, 26)
JP = (73, 197, 182)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
_FONT_FILE = None

# 1画面に載せる人数。多いと字が小さくなって読めない
PER_PAGE = 4


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


def jp_date(day: str) -> str:
    try:
        dt = datetime.strptime(day, "%Y-%m-%d")
        return f"{dt.month}月{dt.day}日"
    except ValueError:
        return day


def pick_top(players: list) -> dict:
    """
    冒頭に出す1人。数字だけで機械的に決める(誰が良かったかの判断はしない)。
    本塁打 > 安打数 > 奪三振 の順で見る。
    """
    if not players:
        return {}
    batters = [p for p in players if p["type"] == "batter"]
    hr = [p for p in batters if p.get("hr")]
    if hr:
        return max(hr, key=lambda p: (p["hr"], p["hits"]))
    multi = [p for p in batters if p.get("hits", 0) >= 2]
    if multi:
        return max(multi, key=lambda p: p["hits"])
    pitchers = [p for p in players if p["type"] == "pitcher"]
    if pitchers:
        return max(pitchers, key=lambda p: p.get("so", 0))
    return players[0]


# ---------------------------------------------------------------------------
# 原稿
# ---------------------------------------------------------------------------

def build_narration(data: dict) -> dict:
    players = data.get("players") or []
    day = jp_date(data.get("date", ""))
    top = pick_top(players)

    segments = [{
        "kind": "intro",
        "text": f"{day}のメジャーリーグ、日本人選手の成績です。"
                + (f"{top['name']}は{top['headline']}。" if top else ""),
        "meta": {"date": data.get("date", ""), "count": len(players)},
    }]

    for i in range(0, len(players), PER_PAGE):
        chunk = players[i:i + PER_PAGE]
        segments.append({
            "kind": "list",
            "text": "".join(f"{p['name']}、{p['headline']}。" for p in chunk),
            "meta": {"start": i, "count": len(chunk)},
        })

    # 現地でどれだけ見られたか。感想を代弁せず、数字だけを出す。
    buzz = data.get("buzz") or []
    if buzz:
        top = buzz[0]
        parts = ["現地で最も見られた試合です。",
                 f"MLB公式のハイライトで、{_jp_matchup(top['matchup'])}が"
                 f"{_yomi_views(top['views'])}再生でした。"]
        # コレスポの選定と現地の注目を突き合わせる。
        # 一致しない方が普通で、そのずれ自体が見どころになる。
        for pk in (data.get("picks") or [])[:2]:
            parts.append(f"コレスポが注目試合に選んだ{pk['matchup']}は、"
                         f"現地では{pk['rank']}位でした。")
        segments.append({"kind": "buzz", "text": "".join(parts), "meta": {}})

    # 現地のコミュニティと報道で、どのチームの名前が挙がったか。
    # 投稿の文面は引用せず、回数だけを数えている。
    talk = data.get("talk") or {}
    teams = talk.get("teams") or []
    if teams:
        top = teams[0]
        parts = ["現地で話題になっているチームです。",
                 f"レディットのアール・ベースボールと現地メディアの見出しで、"
                 f"{top['name']}が最も多く{top['mentions']}回名前が挙がりました。"]
        for t in teams[1:3]:
            parts.append(f"次いで{t['name']}が{t['mentions']}回です。")
        segments.append({"kind": "talk", "text": "".join(parts), "meta": {}})

    segments.append({
        "kind": "outro",
        "text": "コレスポでは毎日午後7時に、その日の注目試合を"
                "理由つきでお届けしています。",
        "meta": {},
    })
    return {"label": day, "segments": segments}


# 球団名の対応表は mlb_buzz 側に集約した。
# 同じ表を2か所に持つと、球団が増えたときに片方だけ古くなる。
_jp_matchup = mlb_buzz.jp_matchup


def _yomi_views(n: int) -> str:
    """読み上げ用。万単位に丸める(桁が多いと耳で追えない)"""
    if n >= 10000:
        return f"およそ{n / 10000:.1f}万回".replace(".0万", "万")
    return f"{n}回"


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------

def render_intro(p, meta, top):
    im, d = base(p)
    e = ease_out(min(1.0, p * 2.6))
    slide = int((1 - e) * 70)

    d.text((80, 430 + slide), jp_date(meta.get("date", "")), font=font(64), fill=DIM)
    d.text((80, 530 + slide), "日本人選手の成績", font=font(96), fill=ACCENT)

    if top and p > 0.14:
        d.rounded_rectangle([70, 760, W - 70, 1120], 24, fill=SURF)
        d.text((110, 800), top.get("name", ""), font=font(72), fill=JP)
        head = top.get("headline", "")
        s = fit(d, head, W - 220, (68, 60, 52, 46))
        d.text((110, 920), head, font=font(s), fill=TEXT)
        d.text((110, 1030), "MLB Stats API の記録より", font=font(34), fill=DIM)

    d.text((80, 1210), f"出場 {meta.get('count', 0)}人", font=font(52), fill=TEXT)
    d.text((80, H - 170), "コレスポ　collespo.com", font=font(38), fill=DIM)
    return im


def render_list(p, players, start, count):
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 200), "今日の日本人選手", font=font(64), fill=ACCENT)

    y = 380
    for i in range(count):
        pl = players[start + i]
        appear = 0.05 + i * 0.07
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        dx = int((1 - e) * 110)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + 230], 20, fill=SURF)
        # 投手か打者かが一目で分かるよう、色を分ける
        col = JP if pl["type"] == "pitcher" else TEXT
        d.text((100 - dx, y + 26), pl.get("name", ""), font=font(58), fill=col)
        head = pl.get("headline", "")
        s = fit(d, head, W - 220, (48, 44, 40, 36))
        d.text((100 - dx, y + 118), head, font=font(s), fill=TEXT)
        d.text((100 - dx, y + 180),
               "投手" if pl["type"] == "pitcher" else "打者",
               font=font(30), fill=DIM)
        y += 258

    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_buzz(p, buzz, picks=None):
    """
    現地でどれだけ見られたか。

    「現地の反応」を語らず、公式ハイライトの再生回数だけを出す。
    誰でも同じ数字を確認でき、感想を代弁せずに注目度を示せる。
    ただしこれは注目度であって面白さや重要さではない
    (人気球団は内容に関わらず伸びる)。その断りを画面にも入れる。
    """
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 200), "現地で最も見られた試合", font=font(60), fill=ACCENT)
    d.text((74, 282), "MLB公式ハイライトの再生回数", font=font(32), fill=DIM)

    picks = picks or []
    # コレスポの比較を下に置くので、その分だけ一覧を減らす
    limit = 3 if picks else 4
    y = 400
    for i, b in enumerate(buzz[:limit]):
        appear = 0.06 + i * 0.07
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        dx = int((1 - e) * 110)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + 190], 20, fill=SURF)
        d.text((100 - dx, y + 22), f"{i + 1}", font=font(40),
               fill=ACCENT if i == 0 else DIM)

        name = _jp_matchup(b.get("matchup", ""))
        s = fit(d, name, W - 260, (48, 42, 38, 34))
        d.text((170 - dx, y + 24), name, font=font(s), fill=TEXT)

        views = f"{b.get('views', 0):,}回再生"
        d.text((100 - dx, y + 110), views, font=font(46),
               fill=ACCENT if i == 0 else TEXT)
        y += 218

    # コレスポが前日に選んだ試合が、現地で何位だったか。
    # 予告と結果の両方を持っているからこそ出せる比較になる。
    if picks:
        d.text((70, y + 20), "コレスポが選んだ試合は", font=font(36), fill=JP)
        yy = y + 76
        for p in picks[:2]:
            line = f"{p['matchup']}　現地{p['rank']}位"
            s = fit(d, line, W - 200, (40, 36, 32))
            d.text((100, yy), line, font=font(s), fill=TEXT)
            yy += 56

    d.text((70, H - 230), "※人気球団の試合は内容に関わらず伸びます",
           font=font(30), fill=DIM)
    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_talk(p, talk):
    """
    現地で名前が挙がったチーム。

    投稿の文面は一切引用せず、何回名前が出たかだけを数えている。
    翻訳を介さないので加減が入らず、誰でも同じ手順で再現できる。
    再生回数(見られた量)とは別の軸で、こちらは語られた量にあたる。
    """
    im, d = base(p)
    teams = talk.get("teams") or []
    players = talk.get("players") or []

    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 200), "現地で話題のチーム", font=font(64), fill=ACCENT)
    d.text((74, 282), "r/baseball と現地メディアの見出しから", font=font(30), fill=DIM)

    top = teams[0]["mentions"] if teams else 1
    y = 380
    for i, t in enumerate(teams[:5]):
        appear = 0.05 + i * 0.06
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        d.rounded_rectangle([60, y, W - 60, y + 108], 16, fill=SURF)
        d.text((100, y + 28), f"{i + 1}", font=font(38), fill=DIM)
        name = t.get("name", "")
        s = fit(d, name, 480, (48, 42, 36))
        d.text((170, y + 26), name, font=font(s), fill=TEXT)
        # 言及回数を棒で見せる。数字だけより差が分かりやすい
        bar = max(4, int(360 * (t["mentions"] / max(1, top)) * e))
        d.rounded_rectangle([680, y + 38, 680 + bar, y + 68], 6, fill=ACCENT_DIM)
        d.text((690, y + 34), f"{t['mentions']}回", font=font(34), fill=ACCENT)
        y += 126

    if players and p > 0.3:
        d.text((70, y + 20), "日本人選手の言及", font=font(36), fill=JP)
        line = "　".join(f"{q['name']} {q['mentions']}回" for q in players[:3])
        s = fit(d, line, W - 200, (38, 34, 30))
        d.text((100, y + 76), line, font=font(s), fill=TEXT)

    d.text((70, H - 230), "※見出しに名前が出た回数です", font=font(30), fill=DIM)
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
# 尺と音声(週次・答え合わせと同じ考え方)
# ---------------------------------------------------------------------------

def plan_durations(segs):
    return [max(MIN_DURATION.get(s.get("kind") or "list", 5.0),
                float(s.get("duration") or 0) + SEGMENT_TAIL)
            for s in segs]


def build_narration_track(segs, durations, out_dir):
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
    parser.add_argument("--recap", default="data/morning_recap.json")
    parser.add_argument("--buzz", default="data/mlb_buzz.json")
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--talk", default="data/local_buzz.json")
    parser.add_argument("--narration-out", default=None)
    parser.add_argument("--audio-dir", default="build/mr_audio")
    parser.add_argument("--out", default="build/morning")
    args = parser.parse_args()

    path = pathlib.Path(args.recap)
    if not path.exists():
        print(f"[info] {path} が無いため、朝のショートは作りません")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    players = data.get("players") or []
    if not players:
        print("[info] 出場した日本人選手がいないため作りません")
        return

    # 現地の注目度。取れていなければ、その画面を出さないだけ
    data["buzz"] = mlb_buzz.load(args.buzz)
    buzz = data["buzz"]
    picks = []
    if buzz:
        print(f"[info] 現地の注目度: {len(buzz)}件 / 最多 {buzz[0]['views']:,}回")
        # 前日にコレスポが選んだ試合が、現地で何位だったか。
        # 対象日(米国日付)のアーカイブが、そのまま前日の予告にあたる。
        ap = pathlib.Path(args.archive_dir) / f"{data.get('date', '')}.json"
        if ap.exists():
            try:
                games = [g for g in json.loads(ap.read_text(encoding="utf-8"))
                         .get("games", []) if g.get("is_notable")][:3]
                picks = mlb_buzz.cross_check(buzz, games)
                for p in picks:
                    print(f"[info] 突き合わせ: {p['matchup']} → 現地{p['rank']}位")
            except (json.JSONDecodeError, OSError) as e:
                print(f"[warn] アーカイブを読めませんでした: {e}")
    data["picks"] = picks

    # 現地で何が語られているか(再生回数とは別の軸)
    data["talk"] = local_buzz.load(args.talk)
    talk = data["talk"]
    if talk.get("teams"):
        print(f"[info] 現地の話題: {len(talk['teams'])}チーム / "
              f"{talk.get('titles_count', 0)}件の見出しから")

    narration = build_narration(data)
    if args.narration_out:
        p = pathlib.Path(args.narration_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(narration, ensure_ascii=False), encoding="utf-8")
        print(f"[info] 原稿を書き出しました: {p} "
              f"({len(narration['segments'])}セグメント)")
        return

    top = pick_top(players)
    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestが見つかりません: {manifest.resolve()}")
        segs = [{"kind": s["kind"], "file": None, "duration": 0.0,
                 "meta": s["meta"]} for s in narration["segments"]]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_morning.mp4"

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
                    im = render_intro(pp, meta, top)
                elif kind == "list":
                    im = render_list(pp, players, meta.get("start", 0),
                                     meta.get("count", 1))
                elif kind == "buzz":
                    im = render_buzz(pp, buzz, picks)
                elif kind == "talk":
                    im = render_talk(pp, talk)
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
    print(f"[info] 朝のショートを生成しました: {video_path} "
          f"({video_path.stat().st_size / 1024 / 1024:.1f}MB, {secs:.0f}秒)")


if __name__ == "__main__":
    main()
