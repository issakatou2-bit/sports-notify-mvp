#!/usr/bin/env python3
"""
動画を描くときに、2つの台本で共通に使うもの。

なぜ post_common と分けるのか:
  post_common は投稿する本文の組み立てで、健康診断や見張りも読む。
  そこへ PIL を要るものを置いたら、pillow を入れていない
  watchdog.yml が healthcheck.py を起動した時点で落ちる。
  実際 run_checks の「必要な物を入れ忘れていないか」がそれを捕まえた。

  描画に要るものは、描画をする台本だけが読む場所に置く。
"""

import functools
import os
from PIL import ImageFont
import wave
import subprocess
import pathlib
# ---------------------------------------------------------------------------
# 画面の切り替え
# ---------------------------------------------------------------------------
#
# これまで画面は瞬間的に入れ替わっていた。1フレームで別の絵になる。
#
# 実測の離脱曲線では、どの回も動画の12〜21%(およそ5〜14秒)で人が急に
# 減る。ちょうど1枚目が終わって次の画面が始まる位置。中身の問題も
# あるが、切り替えそのものが「終わった」という合図になっている面が
# ある。溶けて変わるなら、まだ続いていると読める。
#
# ffmpegのxfadeフィルタは入力を分ける必要があり、いまの
# 「生フレームを標準入力へ流し込む」作りとは噛み合わない。
# 描く側で混ぜれば同じことができて、しかも1行で済む。
FADE_SECONDS = 0.28

# 読み終わってから次の画面へ移るまでの間。
#
# 1.5秒だと、画面ごとに「読み終わって、待って、切り替わる」になる。
# 実測で73秒の動画のうち12秒(17%)が無音だった。息継ぎに要るのは
# それより短い。
#
# ここに置くのは、値が散らばっていたため。夕方の回だけ0.7に下げて、
# 答え合わせは1.5、週次は2.0のまま残っていた。答え合わせは
# 視聴継続15.2%でチャンネル最下位だが、その一因がこれになる。
# 同じチャンネルの動画が、画面ごとに別の長さ黙っている理由は無い。
SEGMENT_TAIL = 0.7


def crossfade(prev_bytes, im, k: int, fade_frames: int, size):
    """切り替わりの最初の数フレームだけ、前の画面と混ぜる。

    prev_bytes は直前の画面の最後のフレーム(生のRGB)。
    k はこの画面の何フレーム目か。返すのは書き出す生バイト。

    混ぜるのは頭だけで、そのあとは素通し。全編に効かせると
    動きのある画面(スコアボードが左から開く等)が濁る。
    """
    raw = im.tobytes()
    if not prev_bytes or k >= fade_frames or fade_frames <= 0:
        return raw
    from PIL import Image
    prev = Image.frombytes("RGB", size, prev_bytes)
    # 直線ではなく、後半で一気に切り替わる形にする。
    # 直線だと中間で両方が半分ずつ見えている時間が長く、
    # 文字が二重に読めて、かえって読みにくい。
    a = ((k + 1) / fade_frames) ** 0.6
    return Image.blend(prev, im, a).tobytes()


# ---------------------------------------------------------------------------
# 音声を尺に合わせる
# ---------------------------------------------------------------------------
#
# 画面ごとの尺は「読み上げ + 息継ぎ」で決まるが、音声そのものは
# 読み上げのぶんしか無い。そのまま繋ぐと音が先に尽きる。
#
# ffmpeg に -shortest を付けているので、音が尽きた時点で書き出しが
# 終わる。こちらはフレームを送り続けるので、配管が壊れて
# BrokenPipeError になる。長編の初回がこれで落ちた
# (動画は3MBできていたのに、最後まで書けずに異常終了した)。
#
# 足りないぶんを無音で埋めれば、音と画面の長さが揃う。
#
# 同じ処理が generate_asset_video / generate_morning_short /
# generate_verdict_short / generate_weekly の4本にもある。
# 4つとも少しずつ違っていて、統合は別途(短編を測っている最中に
# 4か所を同時に触らない)。ここは長編のための正本。
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


# ---------------------------------------------------------------------------
# 文字の折り返し
# ---------------------------------------------------------------------------
#
# 4本の動画台本が、それぞれ自前の wrap を持っていた。
#   generate_verdict_short  改行を落とさない → PILが幅を測れず落ちる
#   generate_video          改行で行を割る
#   generate_weekly         同上
#   generate_morning_short  空白に均す（＋禁則）
#
# 禁則を入れたのは1本だけで、他3本には届いていなかった。
# 日次動画は2番目に配られる枠なのに、そこでは「が行末に残ったまま。
#
# 正本をここに置く。改行は空白に均す（外から来る文章は改行を含み、
# 割ると1文が細切れになる）。
# 行末に置いてはいけない文字(始め括弧)と、行頭に置いてはいけない文字。
#
# 日本語の組版では、開き括弧で行を終えたり、句読点や閉じ括弧で
# 行を始めたりしない。折り返しがこれを知らないと、
# 「が1文字だけ行末に残って、次の行から本文が始まる。
# 1行まるごと無駄になるうえ、読み手には理由が分からない。
NO_LINE_END = "「『（〈《【〔［｛(["
NO_LINE_START = "。、．，」』）〉》】〕］｝)]！？!?ゝ々ー"


def wrap(d, text, fnt, max_w):
    """
    指定幅で折り返す。日本語なので単語境界は見ず1文字ずつ詰める。

    改行を含む文字列はPILが幅を測れずValueErrorになる。
    外部から来た文章(SNSの投稿など)は改行を含むので、ここで均す。

    禁則も見る。開き括弧で行を終えない、句読点で行を始めない。
    """
    text = " ".join(str(text).split())
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=fnt) > max_w and cur:
            # 開き括弧で終わりそうなら、それを次の行へ送る
            if cur[-1] in NO_LINE_END:
                lines.append(cur[:-1])
                cur = cur[-1] + ch
                continue
            # 句読点や閉じ括弧で次が始まりそうなら、無理にでも入れる
            if ch in NO_LINE_START:
                cur += ch
                continue
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# フォント
# ---------------------------------------------------------------------------
#
# 5本の動画台本が、それぞれ自前で持っていた。中身はほぼ同じだが、
# **キャッシュが付いているのは3本だけ**だった。
#
# ImageFont.truetype はそのつどファイルを開く。描画1枚で何十回も呼ぶので、
# 1本の動画で数万回開くことになる。それに気づいて lru_cache を足したのに、
# 週次と答え合わせには届いていなかった。長編は generate_weekly から
# 借りているので、そちらも遅いほうを使っていた。
#
# 直したものが他へ届かない、という同じ形。ここに1つ置く。
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


# フォントは1度読んだら使い回す。
#
# ImageFont.truetype はそのつどファイルを開いて読む。描画1枚のうちに
# 何十回も呼ぶので、1本の動画で数万回ファイルを開いていた。
# 大きさの種類は10個ほどしかない。読み直す理由が無い。


@functools.lru_cache(maxsize=64)
def font(size: int):
    path = _resolve_font()
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
    """0..1 を、最初速く最後ゆっくりに変換する。

    5本が同じ式を持っていた。1行なので害は小さいが、
    置き場が5つあると「どれが本物か」が決まらない。
    """
    return 1 - (1 - t) ** 3
