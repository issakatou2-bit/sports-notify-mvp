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
import os
import pathlib
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageFont

import weekly_ops
import weekly_stats as ws

import video_common  # noqa: E402

# 横型(通常動画向け)
W, H = 1920, 1080
FPS = 24

# 各セグメントのアニメーションが完了する進捗。これを過ぎたフレームは
# 見た目が変わらないため、描き直さず直前のフレームを使い回す。
# 1枚ずつ描画すると枚数がそのまま生成時間になるので、
# 静止している区間を省くだけで大幅に短縮できる。
ANIM_END = 0.45

# 読み上げが終わってから画面が切り替わるまでの余白。
# 0にすると語尾と同時に切り替わって忙しないが、長く取ると沈黙になる。

# セグメント種別ごとの最低表示秒数。原稿が短かった場合の下支えでしかなく、
# 通常はナレーションの実測長が上回るのでこちらは効かない。
MIN_DURATION = {"intro": 5.0, "day": 10.0, "ranking": 9.0, "ops": 10.0,
                "league_ops": 10.0, "verdict": 10.0, "news": 8.0, "outro": 6.0}

# 以前はここに TARGET_SECONDS = 500 を置き、尺が足りなければ day セグメントを
# 引き伸ばして8分(ミッドロール広告の条件)に届かせていた。これをやめた理由:
#   ・広告収入が有効になるのは登録者1,000人・総再生時間4,000時間からで、
#     そこに届いていない段階では8分を満たしても収益は発生しない
#   ・一方で引き伸ばした分はそのまま無音になり、実際に8分19秒の動画のうち
#     4分近くが沈黙という状態になっていた。視聴維持率が落ちれば、
#     1,000人へ近づくどころか遠のく
# 尺は原稿の厚みから決まるべきもので、目標秒数から逆算するものではない。

BG = (11, 14, 20)
SURF = (18, 22, 31)
SURF2 = (23, 28, 39)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
ACCENT_DIM = (74, 58, 26)
JP = (73, 197, 182)
# 答え合わせの勝敗を示す色。
# 「注目理由が継続したか(held)」ではなく「そのチームが勝ったか(won)」で
# 塗り分ける。連敗中のチームが連敗を伸ばした場合、理由としては継続だが
# 視聴者から見れば悪い結果であり、継続=好結果の色で塗ると意味が逆に伝わる。
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
    # 由来つきのライバル理由文は長いので、動画では見出し部分だけ使う
    for i, r in enumerate([x["text"].split(" — ")[0]
                           for x in (game.get("reasons") or [])
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
        if p < 0.04 + i * 0.05:
            continue
        # バーの伸びは ANIM_END までに必ず終わらせる。
        # ANIM_END を過ぎたフレームは描き直さず使い回すため、そこまでに
        # 伸び切っていないバーは、以降ずっとその途中の幅で固まってしまう。
        # 以前は 0.1 + i*0.13 から始めていたので、4本目(0.49)と5本目(0.62)は
        # 開始前の状態のまま凍り付き、最低幅の2pxで表示され続けていた。
        e = ease_out(min(1.0, max(0.0, (p - (0.04 + i * 0.05)) * 9)))
        # アニメーション開始直後は幅が0になり、rounded_rectangleが
        # 「x1がx0より小さい」で例外を投げるため、最低幅を確保する
        bar_w = max(2, int((W - 700) * (count / max(1, ranking[0][1])) * e))
        d.text((120, yy), f"{i + 1}", font=font(44), fill=DIM)
        # 色チップは幅20pxで描かれるので、球団名はその右端より先から始める。
        # 以前は200pxから書き始めており、1文字目にチップが重なっていた。
        badge(d, 190, yy - 4, None, color)
        d.text((232, yy), name, font=font(46), fill=TEXT)
        d.rounded_rectangle([620, yy + 8, 620 + bar_w, yy + 46], 8, fill=ACCENT_DIM)
        d.text((640, yy + 8), f"{count}回", font=font(34), fill=ACCENT)
        yy += 110
    return im


def render_ops(p, players):
    """
    今週の日本人打者をOPS順に並べる。

    OPSは初心者向けの指標ではないので、見出しの下に一言で説明を置く。
    数字だけ並べても「で、これは良いの?」が分からないため。
    """
    im, d = base(p)
    d.text((100, 70), "コレスポ", font=font(44), fill=ACCENT)
    d.text((100, 180), "今週の日本人打者", font=font(70), fill=ACCENT)
    d.text((104, 268), "OPS = 出塁率 + 長打率。打者の総合力を表す数字",
           font=font(32), fill=DIM)

    y = 360
    for i, pl in enumerate(players[:5]):
        if p < 0.05 + i * 0.05:
            continue
        d.rounded_rectangle([100, y, W - 100, y + 108], 16, fill=SURF)
        d.text((132, y + 26), f"{i + 1}", font=font(44), fill=DIM)
        d.text((210, y + 22), pl.get("name", ""), font=font(50), fill=TEXT)
        # OPSは右揃えにして、桁を見比べられるようにする
        ops = str(pl.get("ops") or "")
        f_ops = font(54)
        d.text((W - 470 - d.textlength(ops, font=f_ops), y + 22), ops,
               font=f_ops, fill=ACCENT if i == 0 else TEXT)
        detail = (f"{pl.get('hits', 0)}安打 {pl.get('hr', 0)}本塁打 "
                  f"/ {pl.get('pa', 0)}打席")
        d.text((W - 430, y + 34), detail, font=font(32), fill=DIM)
        y += 128
    return im


def render_league_ops(p, players):
    """
    今週のMLB全体で最も打った打者。

    日本人選手だけだと「今週いちばん打ったのは誰か」が分からない。
    名前の通っている選手が上位に来れば、それ自体が見どころになる。
    """
    im, d = base(p)
    d.text((100, 70), "コレスポ", font=font(44), fill=ACCENT)
    d.text((100, 180), "今週もっとも打った打者", font=font(70), fill=ACCENT)
    d.text((104, 268), "MLB全体 / 15打席以上", font=font(32), fill=DIM)

    y = 360
    for i, pl in enumerate(players[:5]):
        if p < 0.05 + i * 0.05:
            continue
        d.rounded_rectangle([100, y, W - 100, y + 108], 16, fill=SURF)
        d.text((132, y + 26), f"{i + 1}", font=font(44), fill=DIM)
        name = pl.get("name", "")
        ns = 48
        for s in (48, 42, 36, 32):
            if d.textlength(name, font=font(s)) <= 620:
                ns = s
                break
        d.text((210, y + 26), name, font=font(ns), fill=TEXT)
        d.text((880, y + 34), pl.get("team", ""), font=font(34), fill=JP)

        ops = str(pl.get("ops") or "")
        f_ops = font(54)
        d.text((W - 470 - d.textlength(ops, font=f_ops), y + 22), ops,
               font=f_ops, fill=ACCENT if i == 0 else TEXT)
        detail = (f"{pl.get('hits', 0)}安打 {pl.get('hr', 0)}本塁打 "
                  f"/ {pl.get('pa', 0)}打席")
        d.text((W - 430, y + 34), detail, font=font(32), fill=DIM)
        y += 128
    return im


def render_verdict(p, verdict):
    """
    今週の答え合わせ。

    左に週全体の集計、右に「連勝中だから注目」として取り上げた試合の行方を出す。
    どちらも、コレスポが自分で書いた注目理由と、後から埋めた最終スコアの
    両方が揃っているからこそ言える内容で、他所には無い。
    """
    im, d = base(p)
    d.text((100, 70), "コレスポ", font=font(44), fill=ACCENT)
    d.text((100, 190), "今週の答え合わせ", font=font(70), fill=ACCENT)

    # --- 左: 週全体の集計 ---
    y = 350
    for i, (big, small) in enumerate(ws.verdict_lines(verdict)[:5]):
        if p < 0.05 + i * 0.05:
            continue
        d.text((120, y), big, font=font(62), fill=TEXT)
        d.text((124, y + 76), small, font=font(30), fill=DIM)
        y += 128

    # --- 右: 連勝・連敗として取り上げた試合の行方 ---
    streaks = verdict.get("streaks") or []
    if not streaks:
        return im

    x = 1010
    d.text((x, 350), "注目理由の行方", font=font(40), fill=JP)
    y = 430
    for i, s in enumerate(streaks[:4]):
        if p < 0.12 + i * 0.06:
            continue
        col = WIN_COL if s["won"] else LOSE_COL
        d.rounded_rectangle([x, y, W - 100, y + 128], 16, fill=SURF)
        d.text((x + 28, y + 18), f"{s['team']} {s['n']}{s['kind']}中",
               font=font(36), fill=DIM)
        d.text((x + 28, y + 68), s["result"], font=font(42), fill=col)
        # 結果が一目で分かるよう、右端に色の帯を置く
        d.rounded_rectangle([W - 130, y + 18, W - 118, y + 110], 6, fill=col)
        y += 150
    return im


def render_outro(p):
    im, d = base(p)
    d.text((140, 360), "コレスポ", font=font(140), fill=ACCENT)
    d.text((140, 540), "collespo.com", font=font(64), fill=TEXT)
    d.text((140, 640), "毎日19時 更新", font=font(48), fill=DIM)
    d.text((140, 800), "音声: VOICEVOX:ずんだもん", font=font(38), fill=DIM)
    d.text((140, 860), "データ: MLB Stats API", font=font(38), fill=DIM)
    return im


def plan_durations(segs: list) -> list:
    """
    各セグメントの表示秒数を先に決める。

    描画ループの中で都度計算すると、音声側の尺合わせと計算が食い違いやすい。
    ここで1本のリストとして確定させ、映像も音声もこれだけを見るようにする。

    尺はナレーションの実測長で決まる。目標秒数から逆算して引き伸ばすことは
    しない(そうすると差がそのまま無音になる)。原稿を厚くすれば動画は
    自然に長くなり、薄ければ短くなる、という素直な関係にしてある。
    """
    durations = []
    for seg in segs:
        kind = seg.get("kind") or "day"
        audio_len = float(seg.get("duration") or 0)
        durations.append(max(MIN_DURATION.get(kind, 8.0), audio_len + video_common.SEGMENT_TAIL))

    total = sum(durations)
    spoken = sum(float(s.get("duration") or 0) for s in segs)
    silence = total - spoken
    print(f"[info] 尺の内訳: 合計{total:.0f}秒 "
          f"(読み上げ{spoken:.0f}秒 / 間{silence:.0f}秒 = {silence / total * 100:.0f}%)")
    if spoken and silence / total > 0.35:
        print("::warning title=無音が多い::"
              f"全体の{silence / total * 100:.0f}%が無音です。"
              "原稿が薄いか、音声合成に失敗している可能性があります")
    return durations


def build_narration_track(segs: list, durations: list, out_dir: pathlib.Path):
    """
    セグメントごとの音声を、その区間の長さぴったりまで無音で埋めてから連結する。

    なぜ無音を挟むのか:
      各画面は「ナレーションの実測長」ではなく「下限秒数」で表示されるため、
      読み上げ(例:16秒)より画面(例:30秒)の方が長い。音声をそのまま
      詰めて連結すると、その差が毎セグメント積み上がり、最後の試合の画面では
      ナレーションが3分以上先行してしまう(=別の試合の音声が乗る)。
      さらに音声トラック全体が映像より短くなるため、ffmpegの -shortest が
      音声の長さで出力を打ち切り、8分のはずの動画が4分で終わっていた。

      各区間の余りを無音で埋めれば、音声の総尺は映像と一致し、
      どの画面でもその画面のナレーションが流れる状態になる。

    戻り値: 連結済みwavのパス。音声が1つも無ければ None。
    """
    if not any(s.get("file") for s in segs):
        return None

    # 無音は、実際に合成された音声と同じ形式で作る。
    # 形式が揃っていれば concat の -c copy がそのまま使え、再エンコードによる
    # 劣化も追加の依存も無しに連結できる。
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
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--news", default="public/news.json")
    parser.add_argument("--news-log", default="data/news_log.json")
    parser.add_argument("--weekly-ops", default="data/weekly_ops.json")
    parser.add_argument("--audio-dir", default="build/weekly_audio")
    parser.add_argument("--out", default="build/weekly")
    args = parser.parse_args()

    archive_dir = pathlib.Path(args.archive_dir)
    if not archive_dir.exists():
        print("[warn] アーカイブが無いため、週次動画は作りません")
        return

    week = ws.load_week(archive_dir)
    if len(week) < 2:
        print(f"[info] アーカイブが{len(week)}日分しか無いため、"
              "週次動画はまだ作りません(2日分以上必要)")
        return

    news_items = ws.load_news_items(args.news, args.news_log, week[0][0], week[-1][0])
    print(f"[info] 今週の動き: {len(news_items)}件")

    # 答え合わせ。原稿側(generate_weekly_narration.py)も同じ関数を呼ぶので、
    # 画面に出る数字と読み上げられる数字は必ず一致する。
    verdict = ws.compute_verdict(week)
    print(f"[info] 答え合わせ: {verdict['decided']}/{verdict['picked']}試合で結果あり、"
          f"連勝・連敗の検証{len(verdict['streaks'])}件")

    # 原稿側(generate_weekly_narration.py)と同じ条件で読む
    ops_players = weekly_ops.load(args.weekly_ops, until=week[-1][0])[:5]
    league_players = weekly_ops.load_league(args.weekly_ops, until=week[-1][0])[:5]
    print(f"[info] 週間OPS: 日本人{len(ops_players)}名 / "
          f"MLB全体{len(league_players)}名")

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
        # 音声が無い場合の構成。generate_weekly_narration.py が作る
        # セグメントの並び(intro / day×N / ranking / verdict / news / outro)と
        # 揃えておかないと、後で音声が付いたときにずれる。
        segs = [{"kind": "intro", "duration": 0.0, "file": None, "meta": {}}]
        for i in range(len(week)):
            segs.append({"kind": "day", "duration": 0.0, "file": None,
                         "meta": {"day_index": i}})
        if ranking:
            segs.append({"kind": "ranking", "duration": 0.0, "file": None, "meta": {}})
        if ops_players:
            segs.append({"kind": "ops", "duration": 0.0, "file": None, "meta": {}})
        if league_players:
            segs.append({"kind": "league_ops", "duration": 0.0,
                         "file": None, "meta": {}})
        if verdict["decided"]:
            segs.append({"kind": "verdict", "duration": 0.0, "file": None, "meta": {}})
        if news_items:
            segs.append({"kind": "news", "duration": 0.0, "file": None, "meta": {}})
        segs.append({"kind": "outro", "duration": 0.0, "file": None, "meta": {}})

    # 存在しない試合を指すセグメントは、映像も音声も作れない。
    # 描画ループの中だけで弾くと音声側とセグメント数が食い違い、
    # 以降のナレーションが1つずつずれるため、ここで先に落としておく。
    segs = [s for s in segs
            if (s.get("kind") or "day") != "day"
            or (s.get("meta") or {}).get("day_index", 0) < len(week)]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_weekly.mp4"

    durations = plan_durations(segs)
    audio_path = build_narration_track(segs, durations, out_dir)

    # -nostats/-loglevel error で、ffmpegが標準エラーへ書く量を最小限にする。
    # 出力が多いとパイプのバッファが埋まり、ffmpegが停止して
    # こちらの書き込みも止まる(デッドロック)。
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
                    # 動きが止まった区間は描き直さず、直前のフレームを使い回す
                    proc.stdin.write(cached)
                    total += 1
                    continue
                if kind == "intro":
                    im = render_intro(pp, label)
                elif kind == "day":
                    di = meta.get("day_index", 0)
                    im = render_day(pp, week[di][0], week[di][1])
                elif kind == "ranking":
                    im = render_ranking(pp, ranking)
                elif kind == "ops":
                    im = render_ops(pp, ops_players)
                elif kind == "league_ops":
                    im = render_league_ops(pp, league_players)
                elif kind == "verdict":
                    im = render_verdict(pp, verdict)
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

    # 実際に書き出されたmp4の長さを測る。書き込んだフレーム数から計算した秒数と
    # 食い違う場合、-shortest が音声側の長さで打ち切っている(過去にこれで
    # 8分のはずの動画が4分になっていた)。数えた枚数ではなく成果物を見る。
    actual = secs
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, check=True,
        )
        actual = float(r.stdout.strip())
    except Exception:
        pass

    if abs(actual - secs) > 2:
        print(f"::warning title=尺が想定と食い違う::"
              f"描画した{secs:.0f}秒に対し、mp4は{actual:.0f}秒しかありません"
              "(音声トラックが短く、-shortestで打ち切られた可能性)")
    if actual < 480:
        print(f"::warning title=8分未満::"
              f"{480 - actual:.0f}秒不足しています"
              "(ミッドロール広告は8分以上が条件)")
    else:
        print(f"[info] ミッドロール広告の条件(8分以上)を満たしています"
              f"({actual:.0f}秒)")


if __name__ == "__main__":
    main()
