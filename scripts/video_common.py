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

import array
import functools
import os
import random
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


# 絵を描き直すのをやめる時点。
#
# ここが動画すべてに効く数字で、**長いあいだ間違っていた**。
#
# 何が起きていたか:
#   書き出す側はどれも `if p > ANIM_END: 前の絵を使い回す` と
#   書いてあった。ANIM_END は 0.45。つまり「45%で絵が止まる前提」。
#
#   ところが実際に測ると、どの画面も 0.45 では止まっていなかった。
#
#     選手一覧 0.455 / 再生回数 0.455 / スコアボード 0.465
#     ファンの声 0.455 / 番記者 0.455 / 見出し 0.455
#     話題のチーム 0.455 / アウトロ 0.646
#
#   1つずつ出す作りで、最後の1つは `(p - appear) * 9` の
#   立ち上がりの途中でしかない。そこで描くのをやめて、
#   **出かかった絵を区間の残り全部に使い回していた。**
#
#   結果、**どの尺でも最後の1つが画面に出ない**。
#     ・2行の台詞が1行で切れる（長編）
#     ・9回まである試合の推移が8回で終わる
#     ・一覧の最後の1件が薄いまま
#
#   スコアボードの件は前に「列の刻みが速すぎる」と読んで
#   刻みを直したが、直っていなかった。**原因はここだった。**
#
# 0.72 は、測った中でいちばん遅いもの(0.646)より後ろに取ってある。
# 描く枚数は 45%→72% に増えるが、実測で 1枚 7.5ms、
# 55秒の短編で 5.6秒 → 8.7秒。判断材料にならない差。
# 2026-09-01: フォントの候補を和集合にしたら太いものが選ばれて、
# 文字の幅が変わり、アウトロが 0.646 → 0.750 まで動くようになった。
# 検査が見つけた。0.80 へ上げる（描く枚数は80%になるが、
# 55秒の短編で1枚7.5ms、9.7秒。判断材料にならない）。
STILL_AFTER = 0.80


# ---------------------------------------------------------------------------
# 文字の大きさの階段
# ---------------------------------------------------------------------------
#
# 数えたら、7本の動画台本が **40種類の大きさ** を360箇所で使っていた。
#
#   22 24 26 28 30 32 34 36 38 40 42 44 46 48 50 52 54 56 58 60 62 64
#   66 70 72 74 76 80 84 88 96 104 112 120 124 132 140 150 180 240
#
# しかも隣り合う刻みの33件が1.08倍未満。**26と28は、並べても
# どちらが大きいか分からない。** 大きさが40種類あるのに、
# 見分けがつくのは10段階も無い、という状態だった。
#
# 「なんとなく素っ気ない」画面の正体はこれだと思う。
# 大小の差が付いていないので、どこを見ればいいか目が決められない。
#
# 1.25倍ずつの階段にする。1段違えば必ず見分けがつく。
#
#   20  補足の最小
#   26  出典・クレジット
#   32  ラベル・話題
#   40  小さめの本文
#   50  本文
#   64  小見出し
#   80  見出し
#   100 大きい数字
#   124 主役
#   156 サムネイルの主役
#   196 いちばん大きい
#
# 既にある7本を一度に揃えると、全部の画面が同時に変わって
# 何が効いたか分からなくなる。**新しいもの（長編・長編の
# サムネイル）から使い、古いほうは数えて出すだけにする。**
TYPE_SCALE = (20, 26, 32, 40, 50, 64, 80, 100, 124, 156, 196)


def type_size(size: int) -> int:
    """いちばん近い階段の大きさ。階段の外の値をここで丸める。

    名前を step にしていたら、run_checks.step(見出しを出す)と
    ぶつかって、持ち直しの検査が誤って引っかけた。
    検査は正しく、名前のほうが悪かった。
    """
    return min(TYPE_SCALE, key=lambda s: abs(s - size))


def anim_step(k: int, n: int, still_after: float = STILL_AFTER):
    """k枚目の進み具合と、そこで絵が止まったかどうか。

    戻り値は (p, 止まったか)。止まった最初の1枚を描いて、
    残りはそれを使い回す。

    **p は丸めない。** 丸めると、動きの途中から終点へ飛ぶ。
    止まる時点をちゃんと後ろに取れば、丸める必要は無い。
    """
    p = k / max(1, n - 1)
    return p, p >= still_after


def pop_text(d, xy, text, fnt, fill, stroke=None, stroke_w=0,
             shadow=None, shadow_off=(4, 5), anchor=None):
    """縁取りと影をつけて文字を置く。

    なぜ要るのか:
      サムネイルの書体は既に源ノ角ゴシック Heavy(Noto Sans CJK Black)で、
      これは「YouTubeサムネにいちばん薦められている書体」そのもの。
      それでも素っ気なく見えるのは、**書体ではなく処理**のため。

      よく見るサムネの文字は、たいてい
        ・太い縁取り(白か黒)で背景から切り離す
        ・少しずらした影で浮かせる
        ・1語だけ色を変える
      をやっている。3つとも道具の話で、書体を替えなくてもできる。

      縁取りには実利もある。**立ち絵の上に文字が乗っても読める。**
      いまは重ならないよう避けているが、避けるほど画面が狭くなる。

    stroke_w は太さ(px)。0なら縁取りなし。
    """
    x, y = xy
    if shadow:
        d.text((x + shadow_off[0], y + shadow_off[1]), text, font=fnt,
               fill=shadow, anchor=anchor,
               stroke_width=stroke_w, stroke_fill=shadow)
    d.text((x, y), text, font=fnt, fill=fill, anchor=anchor,
           stroke_width=stroke_w,
           stroke_fill=stroke if stroke_w else None)


def mix_wavs(paths, out_path):
    """複数の読み上げを重ねて1つにする。無理なら None。

    VOICEVOXは1回に1人しか喋らないので、2人が同時に言う形は
    こちらで重ねるしかない。冒頭の「コレスポ」で使う。

    そのまま足すと振り切れるので、本数で割ってから少し戻す。
    長さは長いほうに合わせ、短いほうは無音で埋める。
    """
    files = [p for p in paths if p and pathlib.Path(p).exists()]
    if not files:
        return None
    tracks, params = [], None
    for p in files:
        try:
            with wave.open(str(p), "rb") as w:
                if w.getsampwidth() != 2:
                    return None
                if params is None:
                    params = w.getparams()
                elif (w.getframerate(), w.getnchannels()) != (
                        params.framerate, params.nchannels):
                    return None
                a = array.array("h")
                a.frombytes(w.readframes(w.getnframes()))
                tracks.append(a)
        except Exception:                        # noqa: BLE001
            return None
    if not tracks:
        return None
    n = max(len(t) for t in tracks)
    # 割ってから 1.4 倍戻す。半分にしたままだと、続く台詞より
    # 明らかに小さくなって、冒頭だけ音量が違って聞こえる。
    k = 1.4 / len(tracks)
    mixed = array.array("h", bytes(2 * n))
    for t in tracks:
        for i, v in enumerate(t):
            s = mixed[i] + int(v * k)
            mixed[i] = 32767 if s > 32767 else (-32768 if s < -32768 else s)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(2)
        w.setframerate(params.framerate)
        w.writeframes(mixed.tobytes())
    return out_path


def mouth_levels(wav_path, fps: int, frames: int) -> list:
    """読み上げの音の大きさから、1枚ごとの口の開きを決める。

    戻り値は 0(閉じ) / 1(少し開き) / 2(大きく開き) の配列。

    決め打ちで口をパクパクさせると、喋っていない間も動いてしまう。
    音が既に手元にあるので、そこから取る。喋り出しと止まりが
    そのまま口に出る。

    大きさの目安はその区間の最大値からの割合にする。話者によって
    録れる音量が違うので、絶対値で閾値を置くと片方だけ口が
    開かなくなる。
    """
    quiet = [0] * frames
    if not wav_path:
        return quiet
    try:
        with wave.open(str(wav_path), "rb") as w:
            if w.getsampwidth() != 2:
                return quiet
            sr, ch = w.getframerate(), w.getnchannels()
            raw = w.readframes(w.getnframes())
    except Exception:                            # noqa: BLE001
        return quiet
    a = array.array("h")
    a.frombytes(raw[:len(raw) - len(raw) % 2])
    if ch > 1:
        a = a[::ch]
    per = max(1, int(sr / max(1, fps)))
    step = max(1, per // 24)                     # 間引く。形は変わらない
    rms = []
    for i in range(frames):
        seg = a[i * per:(i + 1) * per:step]
        if not seg:
            rms.append(0.0)
            continue
        rms.append((sum(x * x for x in seg) / len(seg)) ** 0.5)
    peak = max(rms) or 1.0
    out = []
    for r in rms:
        v = r / peak
        out.append(2 if v > 0.45 else (1 if v > 0.14 else 0))
    return out


def blink_frames(total_frames: int, fps: int, seed: str) -> set:
    """まばたきする枚。2.6〜5.2秒に1回、0.12秒。

    等間隔にすると機械が動いているように見える。人によって
    間合いを変えたいので、名前を種にして揺らす。
    乱数を使うが種は固定なので、同じ動画は何度作っても同じになる。
    """
    r = random.Random(seed)
    out, t = set(), r.uniform(0.8, 2.6)
    span = max(2, int(0.12 * fps))
    while t * fps < total_frames:
        k = int(t * fps)
        out.update(range(k, min(total_frames, k + span)))
        t += r.uniform(2.6, 5.2)
    return out


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

# 途中で切ってはいけない連なり。
#
# 「0.05動くだけでも」が「0.0」と「5動くだけでも」に割れて出ていた。
# 数字は割れると別の数字に見える。英字の名前も同じ(Skub / al)。
# 日本語は1文字ずつ詰めてよいが、ここだけは塊で送る。
WORD_CHARS = set("0123456789.,:%-/+")
WORD_CHARS |= set("abcdefghijklmnopqrstuvwxyz")
WORD_CHARS |= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


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
            # 数字や英字の途中なら、その塊ごと次の行へ送る。
            # ただし塊だけで1行を超えるなら、送っても直らないので切る。
            if ch in WORD_CHARS and cur[-1] in WORD_CHARS:
                i = len(cur)
                while i > 0 and cur[i - 1] in WORD_CHARS:
                    i -= 1
                head, tail = cur[:i], cur[i:]
                if head and d.textlength(tail + ch, font=fnt) <= max_w:
                    lines.append(head)
                    cur = tail + ch
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
    # 太い順。サムネイルも動画も、太いほうが小さくしても読める。
    # 源ノ角ゴシック Heavy(= Noto Sans CJK Black)を最優先にする。
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    # Windows(手元で確かめるとき用)
    "C:\\Windows\\Fonts\\meiryob.ttc",
    "C:\\Windows\\Fonts\\YuGothB.ttc",
    "C:\\Windows\\Fonts\\meiryo.ttc",
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


_PORTRAIT_CACHE = {}


def portrait(who: str, height: int, portrait_dir: str = "assets/portraits",
             flip: bool = False):
    """立ち絵の1枚絵を、その高さで返す。無ければ None。

    長編は部品（眉・目・口・腕）を組み合わせて表情を作るが、
    短編は**1枚絵で足りる**。短編の画面は動きが止まったところで
    描画結果を使い回していて、口を動かすとその仕組みが効かなくなる。
    1本あたりの生成時間が数倍になる。

    透明な余白は落とす。落とさないと、画面の端に寄せたつもりが
    余白ぶんだけ内側に入り、絵が中央へ寄って見える。
    """
    from PIL import Image
    ck = (who, height, portrait_dir, flip)
    if ck in _PORTRAIT_CACHE:
        return _PORTRAIT_CACHE[ck]
    im = None
    for ext in (".png", ".webp"):
        p = pathlib.Path(portrait_dir) / (who + ext)
        if p.exists():
            try:
                im = Image.open(p).convert("RGBA")
            except Exception:                        # noqa: BLE001
                im = None
            break
    if im is not None:
        box = im.getbbox()
        if box:
            im = im.crop(box)
        w = max(1, int(im.width * height / max(1, im.height)))
        im = im.resize((w, height), Image.LANCZOS)
        if flip:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
    _PORTRAIT_CACHE[ck] = im
    return im


def dim_art(art, amount: float = 0.45):
    """立ち絵を暗くする。**透明なところは透明のまま。**

    暗い幕を重ねる手もあるが、それだと絵の無いところにも幕が乗る。
    背景と同じ色の幕なら見えないので長編ではそれで済んでいるが、
    背景に模様がある画面では四角い影として出てしまう。
    ここは明るさだけを落とす。
    """
    from PIL import Image, ImageEnhance
    r, g, b, a = art.split()
    rgb = ImageEnhance.Brightness(Image.merge("RGB", (r, g, b))).enhance(amount)
    return Image.merge("RGBA", (*rgb.split(), a))


DEFAULT_TINT = (255, 176, 32)


def lift_color(hexv, fallback=DEFAULT_TINT):
    """「#0C2C56」を、暗い背景で読める明るさにして返す。

    公式の色をそのまま使うと、濃紺(#0C2C56)や濃緑(#003831)、
    濃茶(#2F241D)が背景(#0B0E14)に沈んで見えない。
    **色みは保ったまま、明るさだけ上げる。**
    ヤンキースの紺はヤンキースの紺のまま、見える濃さになる。

    色が無い球団や、球団の出てこない画面では既定の橙に落とす。
    """
    import colorsys
    hexv = hexv or ""
    if not (isinstance(hexv, str) and hexv.startswith("#") and len(hexv) == 7):
        return fallback
    try:
        r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except ValueError:
        return fallback
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r, g, b = colorsys.hsv_to_rgb(h, min(s, 0.78), max(v, 0.72))
    return (int(r * 255), int(g * 255), int(b * 255))


def blend(base, tint, amount: float):
    """base に tint を amount(0..1) だけ混ぜる。

    面で色を置くための道具。文字の下に敷く板を球団色に寄せると、
    白い板を並べるより**どこが誰の行か**が一目で分かる。
    濃く混ぜると文字が読めなくなるので、呼ぶ側で 0.1〜0.2 に留める。
    """
    return tuple(int(b + (t - b) * amount) for b, t in zip(base, tint))
