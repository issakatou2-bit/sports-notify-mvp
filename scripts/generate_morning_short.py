"""
「昨夜の日本人選手」の縦型ショートを作る。

19時の予告(これから起きること)に対して、こちらは夕方の枠(終わったこと)。
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
import functools
import json
import os
import pathlib
import subprocess
import sys
import wave
from datetime import datetime
from morning_recap import jst_label as _jst_label  # noqa: E402
# 外国人選手はVOICEVOXがアクセント記号で読みを外す。日次と同じ処理を通す。
from generate_narration import speech_name  # noqa: E402

from PIL import Image, ImageDraw, ImageFont

import local_buzz
import mentioned
import post_common
import video_common
import local_voices
import mlb_buzz
import morning_recap

W, H = 1080, 1920
FPS = 24
ANIM_END = 0.45
# 読み終わってから次の画面へ移るまでの間。
#
# 1.5秒だと、画面ごとに「読み終わって、待って、切り替わる」になる。
# 実測で73秒の動画のうち12秒(17%)が無音だった。息継ぎに要るのは
# それより短い。
# 最短でも表示する秒数。読み上げが短い画面が一瞬で消えないための下限。
#
# 音声より長い分は、そのまま無音になる。「直近5試合」は読み上げ4.6秒に
# 対して9.0秒を取っていて、4.4秒が沈黙だった。画面に出ている量に対して
# 長すぎる。数字が並ぶだけの画面は、読むのにそこまで要らない。
#
# 翻訳した文章の画面(声・番記者・見出し)だけは長いままにする。
# あちらは目で追う文章量が違う。
MIN_DURATION = {"intro": 4.5, "list": 6.5, "buzz": 7.5,
                "talk": 7.5, "voices": 11.0, "outro": 4.0,
                # 翻訳した文章は読む時間が要るので、数字の画面より長く取る
                "reporters": 12.0, "headlines": 11.0,
                # 7日間の合計。5行を目で追う画面
                "week": 8.0,
                # 「今日の1人」の画面
                "p_intro": 5.0, "p_career": 6.0, "p_season": 6.0,
                "p_recent": 6.0, "p_awards": 6.0, "p_quotes": 12.0,
                # スコアボードは回ごとの数字を目で追うので、
                # 読み上げより長めに置く。
                # スコアボードは回の数で変わるので scoreboard_seconds で出す
                "scoreboard": 7.0,
                # 翻訳した文章なので、目で追う時間を取る。
                "praise": 10.0}

# --mode の名前と、投稿の記録に使う区分の対応。
# 締めの一覧から「いま見ている回」を外すのに使う。
# 自分が見ている動画を「毎日出しています」と案内されても意味が無い。
MODE_KIND = {
    "players": "morning",
    "player": "morning_player",
    "voices": "morning_voices",
    "local": "morning_local",
    "press": "morning_press",
}

# 声の画面に並べる件数。読み上げと画面で別々の数を持つと、
# 4件読んで3件しか映らない、という食い違いが静かに生まれる。
VOICES_SHOWN = 3

# 現地の報道で読む件数。
#
# 見出し3件と番記者2件で、読み上げが約500字・70秒になっていた。
# この枠は9本の実測で視聴継続16.4%と全枠で最も低く、しかも
# 最も長い。枠の中で短い回と長い回を比べても差が出なかったので、
# 数十秒の削りでは足りない。件数から減らす。
#
# 画面に出す数もここから取る。読み上げと画面がずれると、
# 「読まれていない言葉が映り、映っていない言葉が読まれる」状態になる。
# どちらが本当なのか、見ている側には確かめようがない。
HEADLINES_SHOWN = 2

# 見出しは切らない。長すぎるものは、その1件を飛ばして次を使う。
#
# 以前は70字で切っていた。今日の6件は19〜36字なので実害は出ていない
# ものの、切るという判断自体が危ない。同じことをハイライトの題で
# やっていて「CAL RALEIGH HOMERED IN FOUR STRAIGHT AT-」が
# そのまま動画の題になった。見出しは6件取れているので、
# 収まらないものは捨てて選び直せば済む。
HEADLINE_MAX = 60
REPORTERS_SHOWN = 1

# 「現地の声」だけは背景色を変える。
# 他の画面がAPIの数字だけで作られているのに対し、ここは翻訳を通した
# 誰かの感想なので、見た目で切り分けて、混ざって見えないようにする。
VOICE_BG = (20, 16, 28)

BG = (11, 14, 20)
SURF = (18, 22, 31)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
ACCENT_DIM = (74, 58, 26)
JP = (73, 197, 182)
# 前回との増減。上げは既存の緑、下げは背景から浮きすぎない赤にする。
# 落ちた日を責める画面にはしたくないので、彩度は抑える。
UP = (110, 205, 150)
DOWN = (200, 120, 120)

# 現地の声の調子。褒めているのか怒っているのかで、同じ一言の
# 意味が変わる。中立には色を付けない(付けると3色が並んで散らかる)。
TONE_COLOR = {"称賛": (110, 205, 150), "批判": (200, 120, 120)}

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
_FONT_FILE = None

# 1画面に載せる人数。多いと字が小さくなって読めない
PER_PAGE = 4

# 報道編を作る最低の素材数(番記者の投稿+現地の見出し)。
# 選手成績と違って毎日必ず湧く情報ではないので、下限を置く。
# 中身1件の動画に初見の人が当たると、そこで見限られる。
MIN_PRESS_ITEMS = 3

# コメント欄編を作る最低の件数。
# 3件あれば「賛否が並んでいる」形になる。1〜2件だと、
# 誰か1人の感想を読み上げただけの動画になってしまう。
MIN_VOICE_ITEMS = 3

# 画面下に出す読み上げ文の上限。超えたぶんは「…」で切る。
# 全文を出すと下半分が文字で埋まり、本題の数字が読めなくなる。
SPOKEN_MAX = 90

# 冒頭でそのまま読める長さ。これを超えるものは途中で切らずに見送る。
# 以前は44文字で機械的に切っており、「ブルワーズをドジャースの
# 大谷翔平を抑えて。」と文が壊れたまま読み上げていた。
INTRO_HEADLINE_MAX = 42
INTRO_VOICE_MAX = 46


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
        for i in (1, 2, 3):
            try:
                return ImageFont.truetype(path, size, index=i)
            except OSError:
                continue
        raise


def ease_out(t):
    return 1 - (1 - t) ** 3


def wrap(d, text, fnt, max_w):
    """
    指定幅で折り返す。日本語なので単語境界は見ず1文字ずつ詰める。

    改行を含む文字列はPILが幅を測れずValueErrorになる。
    外部から来た文章(SNSの投稿など)は改行を含むので、ここで均す。
    """
    text = " ".join(str(text).split())
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


# いま何枚目か。generate_video.py と同じ作り。
# 引数で回すと全描画関数の引数が増えるので、1本を順に描くだけの
# この処理ではここに置いて描画側から読む。
_STEP = 0
_STEPS = 0


def set_step(step: int, steps: int) -> None:
    global _STEP, _STEPS
    _STEP, _STEPS = step, steps


def draw_steps(d, color=None) -> None:
    """
    画面の上に、何枚中の何枚目かを出す。

    ショートは77.7%がスワイプで消される。あと何枚あるかが見えないと
    「まだ続くのか」で切られる。1枚ごとに1目盛り進める形にすれば、
    フレームごとに絵が変わらないので描画結果を使い回せる。
    """
    if _STEPS < 2:
        return
    on = color or ACCENT
    pad, gap, h = 48, 10, 8
    w = (W - pad * 2 - gap * (_STEPS - 1)) / _STEPS
    for i in range(_STEPS):
        x = pad + i * (w + gap)
        d.rounded_rectangle([x, 30, x + w, 30 + h], h // 2,
                            fill=on if i <= _STEP else (44, 52, 66))


def card(d, x0, y0, x1, y1, stripe=None, fill=None):
    """日次側と同じカード。角丸の面と、左端の色帯。"""
    d.rounded_rectangle([x0, y0, x1, y1], 26, fill=fill or SURF)
    if stripe:
        d.rounded_rectangle([x0, y0, x0 + 16, y1], 8, fill=stripe)


# いま読み上げている文。画面の下に出す。
#
# 読み上げだけで画面に何も無いと、聞き取れなかった人が確かめる先が無い。
# 音を切って見ている人には、そもそも届かない。
# YouTube側の字幕とは別に、画面へ焼き込む(切り替えても消えない)。
_SPOKEN = ""


def set_spoken(text: str) -> None:
    global _SPOKEN
    _SPOKEN = (text or "").strip()


def draw_spoken(d, color=None) -> None:
    """
    読み上げの文を画面の下に置く。長い回は先頭だけにする。

    全文を出すと下半分が文字で埋まる。読み上げに追いつくための
    手がかりなので、いま話している範囲が分かれば足りる。
    """
    if not _SPOKEN:
        return
    text = _SPOKEN
    if len(text) > SPOKEN_MAX:
        text = text[:SPOKEN_MAX].rstrip("、。") + "…"
    lines = wrap(d, text, font(34), W - 200)[:3]
    h = len(lines) * 46 + 36
    # 画面のいちばん下には、出典の断りと collespo.com が既に置いてある。
    # そこへ重ねると両方読めなくなるので、その上に載せる。
    y = H - 300 - h
    d.rounded_rectangle([60, y, W - 60, y + h], 18, fill=(16, 20, 28))
    d.rounded_rectangle([60, y, 68, y + h], 4, fill=color or ACCENT)
    for i, ln in enumerate(lines):
        d.text((92, y + 18 + i * 46), ln, font=font(34), fill=DIM)


def base(progress):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    off = int(min(progress, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(14, 18, 26))
    d.rectangle([0, H - 22, W, H], fill=ACCENT)
    draw_steps(d)
    draw_spoken(d)
    return im, d


def usable_headline(text: str) -> bool:
    """
    冒頭でそのまま読める見出しかどうか。

    翻訳や取得の都合で、本文の代わりに断り書きだけが入ることがある。
    それを冒頭で読むと「URLのため省略。8月16日、現地の報道です」になる。
    """
    if not text or len(text) < 12:
        return False
    if text.startswith(("(", "（")):
        return False
    return not any(w in text for w in ("省略", "取得できません", "翻訳できません"))


def sort_players(players: list) -> list:
    """
    その日の貢献度が高い順に並べる。

    これまでは「投手が先、打者は安打数順」で、その日いちばん効いた選手が
    何番目に出てくるか決まっていなかった。順番に意味が無いと、
    一覧はただの羅列になる。投手と打者を同じ物差しに載せて並べれば、
    「今日いちばんは誰か」という話になる。

    同点のときは投手を先にする。並びが実行ごとに変わらないようにするため。
    """
    return sorted(players,
                  key=lambda p: (-morning_recap.contribution(p),
                                 p.get("type") != "pitcher",
                                 p.get("name", "")))


def worth_speaking(player: dict, rank: int) -> bool:
    """
    その選手を読み上げるか。画面には全員を出したままにする。

    全員を読み上げると、5人いれば5回同じ形の文が続いてテンポが死ぬ。
    かといって画面から省くと、載っているのに触れられない選手が出る。
    画面は全部、音声は要点だけ、という分け方にする。

    読むのは次のいずれか:
      その日の1位 / 場面のついた一打 / 突き抜けたスコア
    """
    return (rank == 1
            or bool(player.get("clutch_label"))
            or morning_recap.contribution(player) >= morning_recap.STANDOUT)


def _surname_only(name: str) -> str:
    """読み上げ用の姓だけ。「オカモト・カズマ」ではなく「オカモト」。

    フルネームを3人ぶん並べると、そこだけ名簿の読み上げになる。
    姓で呼ぶのは中継でも普通で、聞いて誰か分かる単位でもある。
    """
    said = speech_name(name)
    return said.split("・")[0] if "・" in said else said


# 番記者の投稿の読み上げ上限。ここまでの範囲で文が終わっていれば使う。
REPORTER_MAX = 110


def clip_sentences(jp: str, limit: int = REPORTER_MAX) -> str:
    """収まる範囲で、文として終わっているところまで返す。無ければ空。

    以前は文字数で切っていた。実際に出たのがこれ:
      「カブスも今シーズン投球がタイプされており、最近は日曜日に今。」
    途中でぶつ切りにして句点を足しているので、意味の無い一文になる。

    読点でも切らない。upload_youtube._clip と同じ理由で、
    「…したのは融資のためではない」の否定が落ちると逆の意味になり、
    「ソーサが大谷翔平の落選を明かし」のように、残った側だけで
    別の意味が通ってしまう。

    句点まで戻れないほど1文が長い投稿は、丸ごと使わない。
    投稿は複数取れているので、次のものへ回せばよい。
    """
    jp = (jp or "").strip()
    if not jp:
        return ""
    if len(jp) <= limit:
        return jp.rstrip("。") + "。"
    cut = jp.rfind("。", 0, limit)
    return jp[:cut + 1] if cut >= 20 else ""


def week_line(players: list, days: int = 7) -> tuple:
    """今日の順位を、7日間の合計の中に置く。

    なぜ足すのか:
      この回はその日の数字と計算結果だけで終わる。1本1本は正しいが、
      毎日「今日は誰が何点」で完結していて、昨日との繋がりが無い。
      同じ順位でも、7日ずっと上位にいる人と今日だけ跳ねた人では
      意味が違う。手元に13日ぶんの履歴があるので、そこは出せる。

      新しい話題を足すのではなく、いま出している数字に奥行きを足す。
      足し算しかしていないので、間違えようもない。

    返すのは (読み上げる文, 画面に出す一覧)。
    """
    try:
        import morning_recap as _mr
        week = _mr.weekly_ranking(days=days)
    except Exception:                            # noqa: BLE001
        return "", []
    if len(week) < 3:
        return "", []
    top = week[0]
    today = players[0].get("name") if players else ""
    lead = f"この{days}日間の合計では、{speech_name(top['name'])}が"     f"{top['total']}点で1位です。"
    if today and today == top["name"]:
        # 今日の1位が週でも1位なら、そう言ったほうが強い。
        lead = (f"{speech_name(today)}は、この{days}日間の合計でも"
                f"{top['total']}点で1位です。")
    elif today:
        for i, w in enumerate(week, 1):
            if w["name"] == today:
                lead += f"今日1位の{speech_name(today)}は{i}位。"
                break
    return lead, week[:5]


def press_premise(heads: list) -> str:
    """今日の報道が何についてのものか。数えるだけで、評価はしない。

    なぜ要るのか:
      見出しを2件並べても、それがその日の全体の中でどういう位置に
      あるのかが分からない。1媒体だけが書いたことなのか、
      現地中が同じ話をしているのかで、同じ見出しでも重みが違う。

      記事の中身は取れない。Googleニュースのフィードが返すのは
      題と媒体名と時刻だけで、description の中はリンク1本しか入って
      いない。だから要約は作れないし、作ろうとすれば書いていない
      ことを足すことになる。

      代わりに数える。どの選手を引いた見出しが何件あったかは、
      集めた時点で分かっている事実で、そこは間違えようがない。
    """
    from collections import Counter
    pairs = [(h.get("query") or "", h.get("source") or "") for h in heads]
    counts = Counter(q for q, _ in pairs if q)
    if not counts:
        return ""
    top, n = counts.most_common(1)[0]
    outlets = {s for q, s in pairs if q == top and s}
    if n < 2 or len(outlets) < 2:
        return ""
    who = speech_name(top)
    return (f"今日は{who}の話題が最も多く、"
            f"{len(heads)}件のうち{n}件、{len(outlets)}媒体が報じています。")


def spoken_list(chunk: list, start: int, said_already: str = "") -> str:
    """1画面ぶんの読み上げ。触れない選手は人数だけ言う。

    said_already は、冒頭で既に成績まで読んだ選手の名前。
    その人はここで成績を繰り返さず、順位と点だけにする。

    冒頭は「山本由伸は6回3分の1 8奪三振 防御率1.42 4被安打。」で始まり、
    次の画面が「1位、山本由伸、6回3分の1 8奪三振 防御率1.42 4被安打。」
    だった。同じ数字を2回続けて聞かされることになる。
    """
    parts, skipped, names = [], 0, []
    for j, p in enumerate(chunk):
        rank = start + j + 1
        if said_already and p.get("name") == said_already:
            score = morning_recap.score_label(p)
            parts.append(f"{rank}位は{p['name']}。"
                         + (f"スコア{score}。" if score else ""))
            continue
        if worth_speaking(p, rank):
            score = morning_recap.score_label(p)
            parts.append(
                f"{rank}位、{p['name']}、{yomi_stats(p['headline'])}。"
                + (f"{p['clutch_label']}。" if p.get("clutch_label") else "")
                + (f"スコア{score}。" if score else "")
            )
        else:
            skipped += 1
            names.append(p.get("name", ""))

    # 誰も該当しない画面が無音にならないよう、先頭だけは必ず読む
    if not parts and chunk:
        p = chunk[0]
        parts.append(f"{start + 1}位、{p['name']}、{yomi_stats(p['headline'])}。")
        skipped -= 1
        if names and names[0] == p.get("name", ""):
            names.pop(0)

    if skipped > 0:
        # 名前だけは読む。
        #
        # 「ほか3人は画面のとおりです」だと、その日出ていた選手の
        # 名前が一度も声に出ない。検索で来る人が探しているのは
        # 名前なので、成績を飛ばすとしても名前は残す。
        said = [_surname_only(n) for n in names if n]
        if said:
            parts.append("ほか、" + "、".join(said) + "。")
        else:
            parts.append(f"ほか{skipped}人は画面のとおりです。")
    return "".join(parts)


def recap_day(data: dict) -> str:
    """
    画面に出す日付。米国日付ではなく、日本時間で試合が行われた日を使う。
    古い記録には date_jst が無いので、その場合は date から換算する。
    """
    return data.get("date_jst") or _jst_label(data.get("date", ""))


def jp_date(day: str) -> str:
    try:
        dt = datetime.strptime(day, "%Y-%m-%d")
        return f"{dt.month}月{dt.day}日"
    except ValueError:
        return day


def build_narration(data: dict, mode: str = "all") -> dict:
    """
    mode で扱う内容を切り替える。

    全部を1本に詰めると76秒・7画面になり、主題が3つ(選手成績・現地の注目度・
    現地の声)混ざる。1本にまとめると、タイトルもサムネイルもどれか1つしか
    表せない。実際、最も見られた動画は単一主題のもので、情報を詰めたものほど
    視聴率が落ちていた。

      players … 日本人選手の成績だけ
      local   … 現地の注目度だけ(再生回数・話題のチーム＝測った数字)
      press   … 現地の報道だけ(番記者の投稿・現地の見出し)
      voices  … その日いちばん見られたハイライトと、そのコメント欄
      all     … 従来どおり全部(検証用)
    """
    players = sort_players(data.get("players") or [])

    # 画面・原稿・タイトル・サムネイルで同じ日付になるよう、
    # ここで一度だけ日本時間へ直してから配る。
    day_iso = recap_day(data)
    day = jp_date(day_iso)
    # 冒頭で挙げる選手は、一覧の1位と同じにする。
    # pick_top() は別の基準(本塁打→好投→複数安打)で選んでいたため、
    # 「冒頭は大谷、でも一覧の1位は千賀」という食い違いが出ていた。
    top = players[0] if players else {}
    # 現地の素材を、数字と言葉で分ける。
    #
    # local に5種類(再生回数・話題のチーム・ファンの声・番記者・見出し)を
    # 詰めると、また主題が混ざる。以前76秒3主題の動画を2本に割ったのと
    # 同じ状態になっていた。
    #   local … 現地でどれだけ見られ、どれだけ語られたか(測った数字)
    #   press … 現地が何と言っているか(翻訳した言葉)
    # 画面の背景色も元から分かれているので、切り口としても素直。
    want_players = mode in ("all", "players")
    want_local = mode in ("all", "local")
    want_press = mode in ("all", "press")
    # ファンの声は、報道編から切り出して1本にした。
    #
    # 「現地メディアは何と言っているか」という題で、番記者・見出し・
    # ファンの声という3つの中身を抱えていた。題が指しているのは
    # 最初の2つで、いちばん反応が取れるファンの声が題からも
    # サムネイルからも見えない状態だった。
    # ファンの声はハイライト動画のコメント欄なので、
    # 「その日いちばん見られた試合」と組にすると1本として成立する。
    want_voices = mode in ("all", "voices")

    # 冒頭は「その日いちばん具体的な事実 → 何の動画か」の順にする。
    #
    # 以前は「8月11日のメジャーリーグ、日本人選手の成績です」と
    # 一般的な前置きから入り、具体的な成績はその後だった。
    # 日次ショートで同じ形を直したのと同じ理由で、ここも入れ替える。
    # 直近28日でショートの40.6%が途中でスワイプされている。
    if want_players:
        head = f"{top['name']}は{yomi_stats(top['headline'])}。" if top else ""
        segments = [{
            "kind": "intro",
            "text": f"{head}{day}、日本人選手{len(players)}人の成績です。",
            "meta": {"date": day_iso, "count": len(players),
                     "mode": mode},
        }]
    elif mode == "press":
        # 言葉の回。
        #
        # 冒頭が「◯◯などの記者。8月16日、現地では何と言われているか。
        # 番記者の投稿と現地の見出しから。」と、本題に入る前に3つ言っていた。
        # 誰の言葉かも、何の動画かも、後の画面を見れば分かる。
        # いちばん短い見出しを1本そのまま先に読む方が、1秒目に中身が来る。
        hd = (data.get("reporters") or {}).get("headlines") or []
        lead, lead_idx = "", None
        # 途中で切ると文が壊れるので、そのまま収まる見出しだけを選ぶ。
        # 並びは元のまま(関連の強い順)にする。短い順に見たときは
        # 「(URLのため省略)」のような中身の無いものが先頭に来た。
        for i, h in enumerate(hd):
            body = (h.get("jp") or h.get("title") or "").strip().rstrip("。")
            if not usable_headline(body):
                continue
            if len(body) <= INTRO_HEADLINE_MAX:
                lead, lead_idx = f"{body}。", i
                break
        segments = [{
            "kind": "intro",
            "text": f"{lead}{day}、現地の報道です。",
            "meta": {"date": day_iso, "count": len(players), "local": True,
                     "mode": mode,
                     # 冒頭で読んだ見出しは、本編でもう一度読まない
                     "used_headline": lead_idx},
        }]
    elif mode == "voices":
        # ファンの声の回。
        # その日いちばん見られたハイライトを先に立て、そのコメント欄を読む。
        # 数字(何回見られたか)と言葉(何と書かれたか)が1本で繋がる。
        # 冒頭は、その日いちばん支持された一言そのもの。
        #
        # 最初は試合名と再生回数を読ませていたが、直後の画面で
        # 同じことをもう一度言うことになり、1秒目が案内で潰れていた。
        # コメントそのものが中身なので、いきなりそこから入る。
        vs = ((data.get("voices") or {}).get("voices") or [])
        # 返信の付いた一言は、やり取りの画面のために取っておく。
        # 冒頭で先に読んでしまうと、そのあと同じ言葉をもう一度読むことになる。
        held = thread_index(vs)
        lead, lead_idx, led_thread = "", None, False
        # まず、返信のいちばん付いた一言そのもので入る。
        #
        # 以前はここで件数だけを予告していた(「返信が54件ついた一言が
        # あります」)。同じ言葉を二度読まないための工夫だったが、
        # 予告は中身が空で、聞いた側に引っかかりが残らない。
        # 中身から入って、件数はやり取りの画面へ送る。そちらでは
        # 「この一言に54件返ってきた」と、対象が目の前にある状態で言える。
        if held is not None:
            body = (vs[held].get("ja") or "").strip().rstrip("。！!、.")
            if body and len(body) <= INTRO_VOICE_MAX:
                lead, lead_idx, led_thread = f"{body}。", held, True
        for i, v in enumerate(vs):
            if led_thread or i == held:
                continue
            body = (v.get("ja") or "").strip().rstrip("。！!、.")
            if body and len(body) <= INTRO_VOICE_MAX:
                likes = v.get("likes") or 0
                lead, lead_idx = f"{body}。", i
                if likes >= 10:
                    lead += f"高評価{likes}件。"
                break
        # 返信の付いた一言が長すぎる日は、上の繰り返しが別の短い一言を
        # 拾っている。そちらで入る。どちらにしても冒頭は必ず誰かの言葉で、
        # 「返信が54件ついた一言があります」のような空の予告はもう出さない。
        teased = False
        segments = [{
            "kind": "intro",
            "text": f"{lead}現地で最も見られた試合のコメント欄です。",
            "meta": {"date": day_iso, "count": len(players), "local": True,
                     "mode": mode,
                     # 冒頭で読んだコメントは、本編でもう一度読まない
                     "used_voice": lead_idx, "teased_thread": teased,
                     "led_thread": led_thread},
        }]
    else:
        # 現地編は選手一覧を出さないので、冒頭も現地の話から入る。
        # 最も見られた試合が分かっていれば、それを先に言う。
        buzz = data.get("buzz") or []
        head = ""
        if buzz:
            head = f"現地で最も見られたのは{yomi_stats(buzz_label(buzz[0]))}。"
        segments = [{
            "kind": "intro",
            "text": f"{head}{day}、現地での注目度をまとめました。",
            "meta": {"date": day_iso, "count": len(players),
                     "local": True, "mode": mode},
        }]

    if want_players:
        for i in range(0, len(players), PER_PAGE):
            chunk = players[i:i + PER_PAGE]
            segments.append({
                "kind": "list",
                # 冒頭で成績まで読んだ選手は、ここで繰り返さない
                "text": spoken_list(chunk, i, top.get("name", "") if top else ""),
                "meta": {"start": i, "count": len(chunk)},
            })

    # その日の順位を、7日間の合計の中に置く。
    #
    # この回は数字と計算結果だけで終わっていて、昨日との繋がりが無い。
    # 同じ1位でも、ずっと上にいる人と今日だけ跳ねた人では意味が違う。
    if want_players and players:
        line, week = week_line(players)
        if line:
            segments.append({"kind": "week", "text": line,
                             "meta": {"week": week}})

    # ファンの声の回。コメントを読む前に、何の試合なのかを立てる。
    #
    # コメントだけを並べても、どの試合の話なのか分からないまま終わる。
    # 試合結果と目立った選手を1画面挟むと、その後の言葉が読める。
    if want_voices and not want_local:
        buzz = data.get("buzz") or []
        if buzz:
            top = buzz[0]
            parts = [f"MLB公式のハイライトで、{yomi_stats(buzz_label(top))}が"
                     f"{_yomi_views(top['views'])}再生でした。"]
            res = top.get("result") or {}
            # 点数は言わない。
            #
            # 対戦の呼び名に既に入っていて(「パイレーツ 4対5 ドジャース」)、
            # このあとスコアボードでも出る。同じ数字を3回聞かされる。
            # ここは「どれだけ見られたか」の画面なので、再生回数に絞る。
            if not scoreboard_ready(res) and res.get("away_score") is not None:
                parts.append(f"{res.get('away_jp')}が{res.get('away_score')}、"
                             f"{res.get('home_jp')}が{res.get('home_score')}。")
            if res.get("star_name"):
                parts.append(f"{speech_name(res['star_name'])}が"
                             f"{yomi_stats(res.get('star_line', ''))}でした。")
            segments.append({"kind": "buzz", "text": "".join(parts),
                             "meta": {"single": True}})

            # 試合の中身をひと目で。
            #
            # 「6対4でした」だけだと、どういう試合だったのかが残らない。
            # そのあとに読むコメントは試合の展開に対するものなので、
            # 展開を先に見せておかないと、言葉だけが宙に浮く。
            # 回ごとの得点があるときだけ出す(合わない日は描かない)。
            if scoreboard_ready(res):
                away, home = res.get("away_jp", ""), res.get("home_jp", "")
                turn = _turning_point(res)
                segments.append({
                    "kind": "scoreboard",
                    "text": f"試合はこうでした。{turn}",
                    "meta": {"away": away, "home": home},
                    "min_duration": scoreboard_seconds(res),
                })

    # 日本人選手が現地でどう言われたか。称賛だけを出す枠。
    #
    # 試合そのもののコメント欄(voices)とは別。あちらは賛否をそのまま
    # 見せる枠で、絞ると現地の空気ではなくこちらの編集になる。
    # こちらは「その選手が向こうでどう受け取られたか」という別の話で、
    # 貢献スコアの順位のすぐ後ろに置くのが自然な位置になる。
    if mode == "players":
        praise = ((data.get("voices") or {}).get("jp_praise") or [])[:2]
        if praise:
            parts = ["現地のコメント欄から、日本人選手への声です。"
                     "翻訳したものです。"]
            for v in praise:
                who = "、".join(v.get("jp_players") or [])
                body = (v.get("ja") or "").strip().rstrip("。！!、.")
                parts.append(f"{who}について、{body}。")
            segments.append({
                "kind": "praise",
                "text": "".join(parts),
                "meta": {"count": len(praise)},
            })

    # 現地でどれだけ見られたか。感想を代弁せず、数字だけを出す。
    buzz = (data.get("buzz") or []) if want_local else []
    if buzz:
        top = buzz[0]
        parts = ["現地で最も見られた試合です。",
                 f"MLB公式のハイライトで、{yomi_stats(buzz_label(top))}が"
                 f"{_yomi_views(top['views'])}再生でした。"]
        # 誰が目立った試合なのかまで言う。数字だけだと、
        # なぜ見られたのかが分からないまま終わる。
        star = (top.get("result") or {}).get("star_name")
        if star:
            parts.append(f"この試合は{speech_name(star)}が"
                         f"{yomi_stats(top['result']['star_line'])}でした。")
        # コレスポの選定と現地の注目を突き合わせる。
        # 一致しない方が普通で、そのずれ自体が見どころになる。
        for pk in (data.get("picks") or [])[:2]:
            parts.append(f"コレスポが注目試合に選んだ{pk['matchup']}は、"
                         f"現地では{pk['rank']}位でした。")
        segments.append({"kind": "buzz", "text": "".join(parts), "meta": {}})

    # 現地のコミュニティと報道で、どのチームの名前が挙がったか。
    # 投稿の文面は引用せず、回数だけを数えている。
    talk = (data.get("talk") or {}) if want_local else {}
    teams = talk.get("teams") or []
    if teams:
        top = teams[0]
        parts = ["現地で話題になっているチームです。",
                 f"レディットのアール・ベースボールと現地メディアの見出しで、"
                 f"{top['name']}が最も多く{top['mentions']}回名前が挙がりました。"]
        # 回数だけでは、勝ち続けているのか騒がれているのか区別できない。
        # 見出しが何を言っているのかを、断りつきで添える。
        if top.get("gist"):
            parts.append(f"見出しの多くは、{top['gist']}という内容でした。")
        for t in teams[1:3]:
            parts.append(f"次いで{t['name']}が{t['mentions']}回です。")
        segments.append({"kind": "talk", "text": "".join(parts), "meta": {}})

    # 1件のコメントと、それへの返信。
    #
    # 声を4つ並べる画面と materials は同じだが、読ませ方が違う。
    # あちらは賛同の多い順に並べるだけで、誰も誰にも答えていない。
    # こちらは1件に絞って、返ってきた言葉をぶら下げる。
    # ファンが盛り上がっているかは、断言の数より言い返しの側に出る。
    all_voices = ((data.get("voices") or {}).get("voices") or [])         if want_voices else []
    ti = thread_index(all_voices)
    if ti is not None:
        v = all_voices[ti]
        body = (v.get("ja") or "").strip().rstrip("。！!、.")
        # 冒頭で件数を言った回は、ここでは繰り返さずに本文から入る。
        m0 = segments[0].get("meta") or {}
        led = m0.get("led_thread")
        if led:
            # 冒頭で読んだ一言。ここでは繰り返さず、件数だけ足す。
            parts = [f"この一言に、返信が{v.get('replies', 0)}件つきました。"]
        elif m0.get("teased_thread"):
            parts = [f"{body}。"]
        else:
            parts = [f"返信が{v.get('replies', 0)}件ついたコメントです。{body}。"]
        rs = (v.get("reply_ja") or [])[:3]
        if rs:
            parts.append("これに、こう返っています。" if not led
                         else "こう返っています。")
            for r in rs:
                rb = (r.get("ja") or "").strip().rstrip("。！!、.")
                if rb:
                    parts.append(f"{rb}。")
        segments.append({"kind": "thread", "text": "".join(parts),
                         "meta": {"index": ti}})

    # 現地の声。ここだけは数字ではなく、翻訳を通した誰かの感想なので、
    # 読み上げでも「翻訳したもの」であることを先に断る。
    voices = ((data.get("voices") or {}).get("voices") or []) if want_voices else []
    if voices:
        # 断りは要るが、毎回同じ長さの前置きを読むのは尺の無駄。
        # ファンの声だけの回では、直前に試合を紹介した流れのまま
        # 短く断って本文へ入る。
        src = (data.get("voices") or {}).get("source", "")
        if want_local or want_press:
            parts = [f"ここからは現地の声です。{src}の投稿を"
                     "翻訳したもので、コレスポの見解ではありません。"]
        else:
            parts = ["コメント欄から。翻訳したものです。"]
        # どれだけ支持された言葉なのかを添える。同じ感想でも、
        # 1件と数百件では意味が違う。数字は取得済みのものをそのまま使う。
        used = (segments[0].get("meta") or {}).get("used_voice")
        held = thread_index(voices)
        picked = [i for i in range(len(voices)) if i not in (used, held)]
        rest = [voices[i] for i in picked]
        for v in rest[:VOICES_SHOWN]:
            # 「レンジャーズ頑張れ！。」のように記号が二重にならないよう、
            # 文末の記号を落としてから句点を足す。
            body = (v.get("ja") or "").strip().rstrip("。！!、.")
            if not body:
                continue
            likes = v.get("likes") or 0
            suffix = f"この投稿には高評価が{likes}件。" if likes >= 10 else ""
            parts.append(f"{body}。{suffix}")
        # 読んだものと同じ声を画面にも出す。
        #
        # ここは冒頭で使った1件とやり取りの1件を外して読んでいたのに、
        # 画面は元の並びの先頭3件をそのまま描いていた。
        # 声が「読まれていない言葉」を映し、読み上げは「映っていない言葉」を
        # 読む状態になる。どちらが本当なのか、見ている側には確かめようがない。
        segments.append({"kind": "voices", "text": "".join(parts),
                         "meta": {"picked": picked[:VOICES_SHOWN]}})

    # 現地で何が報じられたか。見出しだけを扱う。
    #
    # 番記者より先に置く。番記者の投稿は1件が長いので、いきなり誰かの
    # 長い所感から始まると入りが重い。短い見出しで「何が起きたか」を
    # 先に通してから、それについて誰が何と言ったかへ進む方がテンポが出る。
    heads = ((data.get("reporters") or {}).get("headlines") or []) \
        if want_press else []
    if heads:
        used = (segments[0].get("meta") or {}).get("used_headline")
        rest = [h for i, h in enumerate(heads) if i != used]
        parts = [press_premise(heads) or "現地の見出しです。"]
        # 収まらない見出しは切らずに飛ばす。6件取れているので選び直せる。
        fits = [h for h in rest
                if len((h.get("jp") or h.get("title", ""))) <= HEADLINE_MAX]
        for h in (fits or rest)[:HEADLINES_SHOWN]:
            body = h.get("jp") or h.get("title", "")
            parts.append(f"{h.get('source', '')}。{body}。")
        segments.append({"kind": "headlines", "text": "".join(parts),
                         "meta": {}})

    # 現地の番記者が書いたこと。ファンの声との違いは、
    # 実名で、その球団を毎日追っている人の言葉だという点。
    # ここも翻訳を通すので、数字のコーナーとは画面を分ける。
    reporters = ((data.get("reporters") or {}).get("posts") or []) \
        if want_press else []
    if reporters:
        parts = ["現地の番記者の投稿です。翻訳したもので、"
                 "コレスポの見解ではありません。"]
        # 文として終わるところまで取れた投稿だけを使う。
        # 途中で切って句点を足すと、意味の無い一文になる。
        usable = []
        for r in reporters:
            body = clip_sentences(r.get("jp") or r.get("text", ""))
            if body:
                usable.append((r, body))
            if len(usable) >= REPORTERS_SHOWN:
                break
        for r, body in usable:
            parts.append(f"{r.get('outlet', '')}の記者。{body}")
        segments.append({"kind": "reporters", "text": "".join(parts),
                         "meta": {}})

    segments.append({
        "kind": "outro",
        # アウトロは「何をしているか」の説明で終わっていた。
        # 次に何があるかを言い、登録を促す形に変える。
        # 登録が増えないと、毎日出しても毎日ゼロから始まる。
        # 時刻を1つ挙げるより、毎日何が届くのかを言う。
        # 「方」は「ほう」と読まれるので仮名で書く。
        "text": ("コレスポでは、"
                 + "、".join(post_common.lineup_names(MODE_KIND.get(mode, "")))
                 + "を毎日お届けしています。"
                 "見逃したくないかたは、チャンネル登録をお願いします。"),
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


def _ip_reading(m) -> str:
    frac = m.group(2)
    if frac == "1":
        return f"{m.group(1)}回3分の1"
    if frac == "2":
        return f"{m.group(1)}回3分の2"
    return f"{m.group(1)}回"


def yomi_stats(text: str) -> str:
    """
    成績の文字列を、読み上げ用に直す。画面表示には使わない。

    投球回は3進法で書かれている。"6.1回" は6回3分の1のことだが、
    VOICEVOXは小数として「ろくてんいちかい」と読む。
    数字の意味が変わってしまうので、分数の形に直す。

    スコアの "4 - 1" もそのままでは記号として読まれるため、
    「4対1」にする。
    """
    import re as _re
    t = _re.sub(r"(\d+)\.(\d)回", _ip_reading, str(text))
    t = _re.sub(r"(\d+)\s*-\s*(\d+)", r"\1対\2", t)
    return t


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------

def topic_band(d, text: str, y: int, note: str = "") -> int:
    """
    1枚目の主張を、いちばん目立つ形で置く。次の y を返す。

    なぜ塗りにするのか:
      ショートのサムネは1枚目そのもの。ところが今の1枚目は、見出し以外が
      全部くすんだ灰色で書かれていて、「なぜこれを見るのか」に当たる部分が
      見出しより弱い。暗い背景に暗い文字を並べると、小さく表示された
      一覧の中では何も読めない。

      面積のある明るい塊を1つ置くと、縮小しても残る。読ませたい1行だけを
      そこに入れる。2つ置くと、どちらも目立たなくなるので1つに絞る。
    """
    if not text:
        return y
    size = fit(d, text, W - 200, (58, 52, 46, 40, 36))
    h = 40 + size + 40 + (48 if note else 0)
    d.rounded_rectangle([60, y, W - 60, y + h], 24, fill=ACCENT)
    d.text((100, y + 34), text, font=font(size), fill=BG)
    if note:
        # 地がオレンジなので、注記も暗い色で置く。
        # ACCENT_DIM は暗い茶で、オレンジの上では沈んで読めなかった。
        d.text((100, y + 40 + size + 8), note, font=font(32),
               fill=(92, 58, 8))
    return y + h + 30


# 1枚目の帯に入れる項目数。
#
# 一覧に並ぶサムネは実際には数センチしかない。そこで読めるのは3つか4つで、
# 6つ並べると全部が小さくなって、結局どれも読まれない。
# 残りは後の画面に全部出るので、ここは代表だけにする。
TOPIC_ITEMS = 4


def topic_short(text: str) -> str:
    """全角空白で区切られた成績を、先頭のいくつかに絞る。"""
    parts = [x for x in (text or "").replace(chr(0x3000), " ").split() if x]
    return " ".join(parts[:TOPIC_ITEMS])


# 1枚目の見出しと、その下の一行。回ごとに変える。
# 名前は post_common.DAILY_LINEUP と揃える(あちらが説明文と読み上げの元)。
INTRO_HEADINGS = {
    "players": ("日本人選手の成績", "その日活躍した順に紹介します"),
    "local": ("現地での注目度", "見られた量と、語られた量"),
    "voices": ("ファンのコメント欄", "最も見られた試合の反応を翻訳"),
    "press": ("現地の報道", "番記者の投稿と、現地の見出し"),
}


def clip_phrase(text: str, limit: int) -> str:
    """
    長い文を、意味の切れ目で短くする。

    単に切ると「大谷翔平は計878フィートのホームランを放ち、火曜日」で
    終わってしまい、読んだ人には何の話か分からない。
    読点や助詞の手前で切って、そこまでで文として通る形にする。
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("、", "。", "で", "し", "が"):
        i = head.rfind(sep)
        if i >= limit // 2:
            return head[:i + (1 if sep in ("、", "。") else 1)].rstrip("、。")
    return head


def intro_topic(mode: str, meta: dict, top: dict, extra: dict) -> tuple:
    """
    その回いちばんの事実。(帯に入れる本文, 添え書き) を返す。

    材料が無ければ空を返して、帯そのものを出さない。
    無いものを埋めるために言葉を作らない。
    """
    if mode == "players" and top:
        head = topic_short(top.get("headline") or "")
        if head:
            return (f"{top.get('name', '')}　{head}",
                    "コレスポが選ぶ、今日いちばん活躍した選手")
        return "", ""

    if mode == "local":
        b = (extra.get("buzz") or [])
        if b:
            # 呼び名は buzz_label を通す。mlb_buzz.json は英語の対戦名で
            # 持っているので、そのまま出すと1枚目だけ英語になる。
            card = buzz_label(b[0])
            views = b[0].get("views")
            note = f"MLB公式ハイライト {views:,}回" if views else ""
            return card[:26], note
        return "", ""

    if mode == "voices":
        vs = (extra.get("voices") or {}).get("voices") or []
        i = thread_index(vs)
        if i is not None:
            return (f"返信{vs[i].get('replies', 0)}件ついた一言",
                    _jp_matchup(vs[i].get("matchup", "")))
        if vs:
            return topic_short(vs[0].get("ja", ""))[:26], "現地のファンの声"
        return "", ""

    if mode == "press":
        hs = (extra.get("reporters") or {}).get("headlines") or []
        if hs:
            # 読み上げが選んだ見出しを、そのまま帯にも出す。
            #
            # 以前は帯だけ「いちばん短い見出し」を選んでいて、
            # 読み上げは1件目を読んでいた。画面に見出しが2つ並び、
            # 声は下の方だけを読む形になっていた。
            i = meta.get("used_headline")
            h = hs[i] if isinstance(i, int) and i < len(hs) else hs[0]
            head = h.get("jp") or h.get("title") or ""
            return clip_phrase(head, 26), f"現地の見出し {len(hs)}件を翻訳"
        return "", ""

    return "", ""


def render_intro(p, meta, top, extra=None):
    """
    1枚目。ショートのサムネはこの絵そのものなので、ここで見る理由を出す。

    以前は local / voices / press の3つが同じ "local": True しか持って
    おらず、3本とも見出しが「現地での注目度」になっていた。タイトルは
    「現地のファンは何と言ったか」なのに、開くと別の名前が出る。

    見出しの下に、その回いちばんの事実を明るい帯で1つだけ置く。
    暗い背景に灰色の字を並べても、一覧に並んだ小さなサムネでは読めない。
    """
    im, d = base(p)
    e = ease_out(min(1.0, p * 2.6))
    slide = int((1 - e) * 70)
    mode = meta.get("mode") or ("local" if meta.get("local") else "players")
    heading, lede = INTRO_HEADINGS.get(mode, INTRO_HEADINGS["players"])

    d.text((80, 430 + slide), jp_date(meta.get("date", "")),
           font=font(64), fill=DIM)
    d.text((80, 530 + slide), heading, font=font(96), fill=ACCENT)
    d.text((84, 660 + slide), lede, font=font(44), fill=DIM)

    y = 760
    if p > 0.10:
        text, note = intro_topic(mode, meta, top, extra or {})
        y = topic_band(d, text, y, note=note)

    if mode == "players":
        d.text((80, max(y, 1180)), f"出場 {meta.get('count', 0)}人",
               font=font(52), fill=TEXT)
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

        # 順位。並び順の意味が画面からも分かるようにする
        rank = start + i + 1
        d.text((100 - dx, y + 30), f"{rank}", font=font(64), fill=ACCENT)

        # 投手か打者かが一目で分かるよう、色を分ける。
        # 投げて打った日は、どちらでもないので目立つ色にする。
        kind = pl.get("type")
        col = ACCENT if kind == "two_way" else (JP if kind == "pitcher" else TEXT)
        d.text((180 - dx, y + 26), pl.get("name", ""), font=font(58), fill=col)

        # 勝利貢献スコア。投手と打者を同じ物差しに載せた、コレスポ独自の数字。
        # 右端に置いて、名前と成績の邪魔をしないようにする。
        #
        # 100超えは色と大きさを変えて、ひと目で分かるようにする。
        # 完封や3本塁打、投げて打った日がここに入る。
        # 低い日は数字を出さない(成績はそのまま載る)。
        label = morning_recap.score_label(pl)
        if label:
            score = morning_recap.contribution(pl)
            big = score >= morning_recap.STANDOUT
            size = 84 if big else 66
            col = JP if big else ACCENT
            sw = d.textlength(label, font=font(size))
            d.text((W - 110 - dx - sw, y + (14 if big else 24)), label,
                   font=font(size), fill=col)
            d.text((W - 108 - dx, y + 48), "点", font=font(30),
                   fill=col if big else DIM)

            # 点数だけでは高いのか低いのか伝わらない。前回と並べて初めて
            # 「伸びた」「落ちた」が読める。投手は前回登板、打者は前試合。
            # 主役は今日の数字なので、こちらは小さく暗く置く。
            prev = pl.get("prev_score")
            if prev is not None:
                diff = score - prev
                mark = "▲" if diff > 0 else ("▼" if diff < 0 else "±")
                sub = f"前回{prev} {mark}{abs(diff)}"
                dc = UP if diff > 0 else (DOWN if diff < 0 else DIM)
                sw2 = d.textlength(sub, font=font(28))
                d.text((W - 108 - dx - sw2, y + 96), sub,
                       font=font(28), fill=dc)

            # 直近の平均。1試合の上下ではなく、いまの調子そのもの。
            avg = pl.get("avg_score")
            if avg is not None:
                n = pl.get("avg_games", 0)
                unit = "登板" if pl.get("type") == "pitcher" else "試合"
                sub2 = f"直近{n}{unit} 平均{avg}"
                sw3 = d.textlength(sub2, font=font(26))
                d.text((W - 108 - dx - sw3, y + 132), sub2,
                       font=font(26), fill=DIM)

        head = pl.get("headline", "")
        # 右に前回・直近を置いた分だけ、成績の使える幅が狭くなる。
        # 詰めずに書くと重なって両方読めなくなる。
        right_used = pl.get("prev_score") is not None or \
            pl.get("avg_score") is not None
        # 下限を36までしか用意していなかったので、長い行が入りきらずに
        # そのまま右へはみ出していた。投手の行に被安打と防御率を足して
        # 28字を超えた日に出た。fit は入らなければ最小を返すだけで、
        # 収まったかどうかは教えてくれない。刻みを下まで用意する。
        s = fit(d, head, (W - 560) if right_used else (W - 300),
                (48, 44, 40, 36, 32, 28, 24))
        d.text((180 - dx, y + 118), head, font=font(s), fill=TEXT)

        # 場面(逆転・勝ち越し・同点)。点数がなぜ高いのかの説明になる。
        role = {"pitcher": "投手", "two_way": "投打"}.get(kind, "打者")
        # 所属も添える。名前を知らない選手が出た日に、どのチームの話なのかが
        # 分からないままになる。小さく置いて、成績の邪魔はしない。
        team = pl.get("team_jp")
        if team:
            role = f"{role}・{team}"
        d.text((180 - dx, y + 180), role, font=font(30), fill=DIM)
        clutch_label = pl.get("clutch_label")
        if clutch_label:
            d.text((180 - dx + d.textlength(role, font=font(30)) + 24,
                    y + 178), clutch_label, font=font(32), fill=ACCENT)
            # 用語の説明を小さく添える。「先頭打者本塁打」のような言葉で
            # 止まらないようにするため。
            note = pl.get("clutch_note")
            if note:
                d.text((180 - dx, y + 214), note, font=font(24), fill=DIM)
        y += 258

    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def buzz_label(b: dict) -> str:
    """
    その試合をどう呼ぶか。結果が取れていればスコアの形にする。

    画面と読み上げで別々に組み立てると、片方だけスコア入りになって
    食い違う。実際、順位を別々に並べ替えて「1位 34点、3位 44点」と
    表示した事故が起きている。呼び名は必ずここを通す。
    """
    res = b.get("result") or {}
    if res.get("away_jp") and res.get("away_score") is not None:
        return (f"{res['away_jp']} {res['away_score']}"
                f" - {res['home_score']} {res['home_jp']}")
    # 選手個人のハイライトには対戦カードが無い。その日の題を訳した
    # ものが topic_jp に入っているので、そちらを読む。
    # 英語のまま読み上げると、何の動画なのかが分からないまま
    # コメントの訳だけが流れる。
    return b.get("topic_jp") or _jp_matchup(b.get("matchup", ""))


def _turning_point(res) -> str:
    """試合が動いた回を、ひとことで。数えるだけで、評価はしない。"""
    innings = [i for i in (res.get("innings") or []) if i.get("num")]
    if not innings:
        return ""
    best, at, side = 0, None, ""
    for i in innings:
        for k, who in (("away", res.get("away_jp", "")),
                       ("home", res.get("home_jp", ""))):
            v = i.get(k) or 0
            if v > best:
                best, at, side = v, i["num"], who
    if not at or best < 2:
        return ""
    return f"{at}回に{side}が{best}点。ここが大きかった回です。"


# スコアボードの尺。9回ぶんを追うのに要る秒数と、1回あたりの足し前。
#
# 固定の9.0秒だと、読み上げが6秒前後で終わって2秒以上が無音になっていた。
# かといって縮めるだけでは、延長に入った日に列が増えて追いつかない。
# 列の数で決めるのが素直で、9回なら7.0秒、延長は1回ごとに0.5秒足す。
SCOREBOARD_BASE = 7.0
SCOREBOARD_PER_INNING = 0.5


def scoreboard_seconds(res) -> float:
    n = len([i for i in (res.get("innings") or []) if i.get("num")])
    return SCOREBOARD_BASE + SCOREBOARD_PER_INNING * max(0, n - 9)


def scoreboard_ready(res) -> bool:
    """スコアボードを描いてよい材料が揃っているか。

    回ごとの合計と最終スコアが合わない日は描かない。取り込みが途中で
    切れると、表のRと下の折れ線が別々の数字を出すことになる。
    画面の中で辻褄が合っていないのは、その画面が無いより悪い。
    """
    innings = [i for i in ((res or {}).get("innings") or []) if i.get("num")]
    if not innings:
        return False
    for side in ("away", "home"):
        final = res.get(side + "_score")
        if final is None:
            return False
        if sum((i.get(side) or 0) for i in innings) != final:
            return False
    return True


def render_week(p, rows, today: str = ""):
    """7日間の合計。今日の順位を、週の中に置いて見せる。

    その日の数字だけだと、毎日そこで完結して昨日と繋がらない。
    同じ1位でも、ずっと上にいる人と今日だけ跳ねた人では意味が違う。
    合計と試合数を並べれば、その差がそのまま出る。

    今日の1位には印を付ける。どこにいるのかが一目で分かる。
    """
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 180), "この7日間の合計", font=font(64), fill=ACCENT)
    d.text((74, 268), "勝利貢献スコアの積み上げ", font=font(32), fill=DIM)

    y = 360
    for i, r in enumerate(rows[:5]):
        if p < 0.08 + i * 0.09:
            continue
        me = today and r.get("name") == today
        d.rounded_rectangle([60, y, W - 60, y + 130], 18,
                            fill=ACCENT if me else SURF)
        fg = BG if me else TEXT
        d.text((100, y + 22), f"{i + 1}位", font=font(40),
               fill=BG if me else DIM)
        name = str(r.get("name", ""))
        ns = fit(d, name, W - 460, (56, 50, 44, 38))
        d.text((190, y + 16), name, font=font(ns), fill=fg)
        tot = f"{r.get('total', 0)}点"
        tw = d.textlength(tot, font=font(52))
        d.text((W - 110 - tw, y + 18), tot, font=font(52), fill=fg)
        d.text((190, y + 78), f"{r.get('games', 0)}試合　最高"
               f"{r.get('best', 0)}点", font=font(32),
               fill=BG if me else DIM)
        y += 146
    d.text((70, H - 120), "計算方法 collespo.com/score.html",
           font=font(32), fill=DIM)
    return im


def render_praise(p, rows):
    """日本人選手への称賛。翻訳であることを画面に必ず出す。

    数字の画面と同じ見た目にしない。ここは誰かの感想の訳で、
    確かめられる記録ではない。混ぜて見えると、どこまでが
    数字の話なのか区別がつかなくなる。
    """
    im = Image.new("RGB", (W, H), VOICE_BG)
    d = ImageDraw.Draw(im)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 190), "現地は何と言ったか", font=font(60), fill=ACCENT)
    d.text((74, 272), "MLB公式ハイライトのコメント欄・翻訳",
           font=font(30), fill=DIM)

    y = 380
    for i, v in enumerate(rows[:2]):
        if p < 0.08 + i * 0.10:
            continue
        who = "、".join(v.get("jp_players") or [])
        body = (v.get("ja") or "").strip()
        lines = wrap(d, body, font(38), W - 220)[:4]
        h = 92 + len(lines) * 52
        d.rounded_rectangle([60, y, W - 60, y + h], 20, fill=SURF)
        d.text((100, y + 22), who, font=font(38), fill=ACCENT)
        likes = v.get("likes") or 0
        if likes:
            tag = f"高評価{likes:,}"
            tw = d.textlength(tag, font=font(30))
            d.text((W - 100 - tw, y + 28), tag, font=font(30), fill=DIM)
        yy = y + 80
        for line in lines:
            d.text((100, yy), line, font=font(38), fill=TEXT)
            yy += 52
        y += h + 24

    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_scoreboard(p, res, away, home):
    """
    イニングごとの点を、球場の掲示板の形で出す。

    最終スコアだけだと「7対6だった」で終わるが、回ごとの並びがあれば
    どこで動いた試合なのかが一目で分かる。序盤に離して守り切ったのか、
    終盤にひっくり返したのかは、数字の列がそのまま語る。

    素材を一切借りずに作れるのも都合がよい。球団のロゴにも
    選手の写真にも触れずに、公式の数字だけで画になる。

    左から順に開く。全部同時に出すと、ただの表になる。
    """
    if not scoreboard_ready(res):
        return None

    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    innings = [i for i in (res.get("innings") or []) if i.get("num")]

    d.text((70, 190), "スコアボード", font=font(52), fill=ACCENT)

    # 球団名は表の左に置けない。「ダイヤモンドバックス」は
    # 縦画面の幅では1回の列まで食い込む。名前は上に大きく出して、
    # 表は数字だけにする。そのぶん1回ぶんの枠を広く取れる。
    aw, hm = res.get("away_score"), res.get("home_score")
    head = f"{away}  {aw} - {hm}  {home}"
    hs = fit(d, head, W - 140, (58, 52, 46, 40, 36))
    d.text((70, 300), head, font=font(hs), fill=TEXT)

    # 9回までは必ず枠を引く。延長した日はその分だけ伸ばす。
    cols = max(9, max(i["num"] for i in innings))
    x0, top = 70, 520
    label_w = 150
    rhe_w = 3 * 62
    cell = (W - 140 - label_w - rhe_w - 20) // cols
    rh = 130

    # 回の見出しと R H E
    for n in range(1, cols + 1):
        cx = x0 + label_w + (n - 1) * cell
        tw = d.textlength(str(n), font=font(36))
        d.text((cx + cell / 2 - tw / 2, top - 62), str(n),
               font=font(36), fill=DIM)
    for j, tag in enumerate(("R", "H", "E")):
        cx = x0 + label_w + cols * cell + 20 + j * 62
        tw = d.textlength(tag, font=font(36))
        d.text((cx + 31 - tw / 2, top - 62), tag, font=font(36), fill=ACCENT)

    for row, side in enumerate(("away", "home")):
        y = top + row * rh
        d.rounded_rectangle([x0, y, W - 70, y + rh - 14], 14,
                            fill=SURF if row == 0 else (24, 28, 36))
        d.text((x0 + 24, y + rh / 2 - 34), "先攻" if row == 0 else "後攻",
               font=font(34), fill=DIM)

        for n in range(1, cols + 1):
            # 左から順に開く。全部同時に出すと、ただの表になる。
            if p < 0.10 + (n - 1) * 0.045:
                continue
            got = next((i for i in innings if i["num"] == n), None)
            v = (got or {}).get(side)
            # 後攻がサヨナラや9回裏なしで打たなかった回は「-」。
            # 0と書くと、攻撃して取れなかったことになる。
            txt = "-" if v is None else str(v)
            cx = x0 + label_w + (n - 1) * cell
            tw = d.textlength(txt, font=font(52))
            d.text((cx + cell / 2 - tw / 2, y + rh / 2 - 40), txt,
                   font=font(52), fill=ACCENT if (v or 0) > 0 else DIM)

        for j, key in enumerate(("_score", "_hits", "_errors")):
            v = res.get(side + key)
            if v is None:
                continue
            cx = x0 + label_w + cols * cell + 20 + j * 62
            tw = d.textlength(str(v), font=font(52))
            d.text((cx + 31 - tw / 2, y + rh / 2 - 40), str(v),
                   font=font(52), fill=TEXT if key == "_score" else DIM)

    # 表は「何回に何点」までしか言わない。積み上げると、点差がいつ開いて
    # いつ詰まったのかが線になる。縦画面は下が余るので、そこに置く。
    cy0 = top + 2 * rh + 90
    ch = 420
    d.text((70, cy0), "得点の推移", font=font(38), fill=DIM)
    # 横位置は上の表の回に合わせる。ずれていると、線のどこが何回なのかを
    # 目で追えない。
    gx0 = x0 + label_w + cell // 2
    gw = (cols - 1) * cell
    gy0 = cy0 + 80
    run = {"away": 0, "home": 0}
    pts = {"away": [], "home": []}
    for n in range(1, cols + 1):
        got = next((i for i in innings if i["num"] == n), None)
        for side in ("away", "home"):
            run[side] += ((got or {}).get(side) or 0)
            pts[side].append(run[side])
    top_run = max(max(pts["away"]), max(pts["home"]), 1)

    # 目盛りは点数。線だけだと大きさが分からない。
    for v in (0, top_run):
        yy = gy0 + ch - int(ch * v / top_run)
        d.line([gx0, yy, gx0 + gw, yy], fill=(38, 44, 54), width=2)
        d.text((70, yy - 20), str(v), font=font(28), fill=DIM)

    for side, col in (("away", (120, 170, 255)), ("home", ACCENT)):
        pl = []
        for n in range(cols):
            if p < 0.10 + n * 0.045:
                break
            pl.append((gx0 + int(gw * n / max(1, cols - 1)),
                       gy0 + ch - int(ch * pts[side][n] / top_run)))
        if len(pl) > 1:
            d.line(pl, fill=col, width=6, joint="curve")
        if pl:
            d.ellipse([pl[-1][0] - 9, pl[-1][1] - 9,
                       pl[-1][0] + 9, pl[-1][1] + 9], fill=col)

    d.text((gx0, gy0 + ch + 24), away, font=font(30), fill=(120, 170, 255))
    hw = d.textlength(home, font=font(30))
    d.text((gx0 + gw - hw, gy0 + ch + 24), home, font=font(30), fill=ACCENT)

    if res.get("star_name"):
        star = f"{res['star_name']}　{res['star_line']}"
        d.text((70, H - 260), star,
               font=font(fit(d, star, W - 140, (44, 40, 36, 32))), fill=JP)

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

        res = b.get("result") or {}
        name = buzz_label(b)
        s = fit(d, name, W - 260, (48, 42, 38, 34))
        d.text((170 - dx, y + 24), name, font=font(s), fill=TEXT)

        views = f"{b.get('views', 0):,}回再生"
        d.text((100 - dx, y + 110), views, font=font(46),
               fill=ACCENT if i == 0 else TEXT)

        if res.get("star_name"):
            star = f"{res['star_name']}　{res['star_line']}"
            ss = fit(d, star, W - 620, (32, 28, 24))
            sw2 = d.textlength(star, font=font(ss))
            d.text((W - 110 - dx - sw2, y + 122), star,
                   font=font(ss), fill=JP)
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
        # 見出しが何を言っているかを添える行のぶん、背を高くする。
        # 回数だけでは、勝ち続けているのか騒がれているのか区別できない。
        gist = t.get("gist")
        tone = t.get("tone")
        h = 158 if (gist or tone) else 108
        d.rounded_rectangle([60, y, W - 60, y + h], 16, fill=SURF)
        d.text((100, y + 28), f"{i + 1}", font=font(38), fill=DIM)
        name = t.get("name", "")
        s = fit(d, name, 480, (48, 42, 36))
        d.text((170, y + 26), name, font=font(s), fill=TEXT)
        # 言及回数を棒で見せる。数字だけより差が分かりやすい
        bar = max(4, int(360 * (t["mentions"] / max(1, top)) * e))
        d.rounded_rectangle([680, y + 38, 680 + bar, y + 68], 6, fill=ACCENT_DIM)
        d.text((690, y + 34), f"{t['mentions']}回", font=font(34), fill=ACCENT)

        if gist or tone:
            x = 170
            if tone:
                tc = {"好調": UP, "不振": DOWN}.get(tone, ACCENT)
                tw = d.textlength(tone, font=font(30))
                d.rounded_rectangle([x, y + 96, x + tw + 28, y + 140], 10,
                                    outline=tc, width=2)
                d.text((x + 14, y + 100), tone, font=font(30), fill=tc)
                x += tw + 46
            if gist:
                gs = fit(d, gist, W - x - 100, (34, 30, 26))
                d.text((x, y + 102), gist, font=font(gs), fill=DIM)
        y += h + 18

    if players and p > 0.3:
        d.text((70, y + 20), "日本人選手の言及", font=font(36), fill=JP)
        line = "　".join(f"{q['name']} {q['mentions']}回" for q in players[:3])
        s = fit(d, line, W - 200, (38, 34, 30))
        d.text((100, y + 76), line, font=font(s), fill=TEXT)

    d.text((70, H - 230), "※見出しに名前が出た回数です", font=font(30), fill=DIM)
    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_reporters(p, posts):
    """
    現地の番記者が書いたこと。

    ファンの声と同じく翻訳を通しているので背景を分ける。
    ただしこちらは実名と媒体が出せるので、それを必ず添える。
    どこの誰が言ったのかが分かることが、この画面の価値そのもの。
    """
    im = Image.new("RGB", (W, H), VOICE_BG)
    d = ImageDraw.Draw(im)
    off = int(min(p, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(26, 21, 36))
    d.rectangle([0, H - 22, W, H], fill=JP)
    draw_steps(d, JP)
    draw_spoken(d, JP)

    d.text((70, 70), "コレスポ", font=font(46), fill=JP)
    d.text((70, 190), "現地の番記者", font=font(72), fill=JP)
    d.text((74, 278), "現地メディアの記者の投稿を翻訳", font=font(32), fill=DIM)

    y = 380
    for i, r in enumerate(posts[:REPORTERS_SHOWN]):
        appear = 0.06 + i * 0.10
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 8)))
        dx = int((1 - e) * 110)
        body = r.get("jp") or r.get("text", "")
        lines = wrap(d, body, font(42), W - 220)[:4]
        h = 150 + len(lines) * 56
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + h], 20, fill=(31, 25, 43))
        d.text((100 - dx, y + 26),
               f"{r.get('author', '')}（{r.get('outlet', '')}）",
               font=font(34), fill=JP)
        yy = y + 82
        for line in lines:
            d.text((100 - dx, yy), line, font=font(42), fill=TEXT)
            yy += 56
        d.text((100 - dx, y + h - 46),
               f"いいね {r.get('likes', 0)}　担当 {r.get('team', '')}",
               font=font(28), fill=DIM)
        y += h + 34

    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def render_headlines(p, heads):
    """現地で何が報じられたか。見出しだけを並べる。"""
    im = Image.new("RGB", (W, H), VOICE_BG)
    d = ImageDraw.Draw(im)
    off = int(min(p, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(26, 21, 36))
    d.rectangle([0, H - 22, W, H], fill=JP)
    draw_steps(d, JP)
    draw_spoken(d, JP)

    d.text((70, 70), "コレスポ", font=font(46), fill=JP)
    d.text((70, 190), "現地の見出し", font=font(72), fill=JP)
    d.text((74, 278), "現地メディアの見出しを翻訳", font=font(32), fill=DIM)

    y = 380
    for i, h in enumerate(heads[:HEADLINES_SHOWN]):
        appear = 0.06 + i * 0.08
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 8)))
        dx = int((1 - e) * 110)
        body = h.get("jp") or h.get("title", "")
        lines = wrap(d, body, font(40), W - 220)[:3]
        hh = 120 + len(lines) * 54
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + hh], 20,
                            fill=(31, 25, 43))
        d.text((100 - dx, y + 24), h.get("source", ""),
               font=font(32), fill=JP)
        yy = y + 76
        for line in lines:
            d.text((100 - dx, yy), line, font=font(40), fill=TEXT)
            yy += 54
        y += hh + 30

    d.text((70, H - 170), "collespo.com", font=font(38), fill=DIM)
    return im


def all_voices_replies(voices: list, i) -> int:
    """その一言に付いた返信の件数。"""
    try:
        return int(voices[i].get("replies") or 0)
    except (IndexError, TypeError, ValueError):
        return 0


def thread_index(voices: list):
    """返信の付いた一言が何番目か。無ければ None。"""
    for i, v in enumerate(voices or []):
        if v.get("is_thread") and v.get("reply_ja"):
            return i
    return None


def render_thread(p, v):
    """
    1つの投稿と、それに返ってきた言葉を並べる。

    なぜ別の画面にするのか:
      「現地の声」は、賛同を集めた一言を4つ並べる作りになっている。
      それぞれは独立していて、誰も誰にも答えていない。
      並べるほど声の数は増えるが、会話にはならない。

      ファンの熱は、一人の断言ではなく言い返しの側に出る。
      1件に絞って、それへの返信をぶら下げる形にすると、
      同じ材料が「言い合い」として読める。

      訳を通しているのは他の声の画面と同じなので、背景も断りも揃える。
    """
    im = Image.new("RGB", (W, H), VOICE_BG)
    d = ImageDraw.Draw(im)
    off = int(min(p, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(26, 21, 36))
    d.rectangle([0, H - 22, W, H], fill=JP)
    draw_steps(d, JP)
    draw_spoken(d, JP)

    d.text((70, 70), "コレスポ", font=font(46), fill=JP)
    d.text((70, 190), "この一言に、こう返った", font=font(64), fill=JP)
    d.text((74, 288), "MLB公式ハイライトのコメント欄を翻訳",
           font=font(32), fill=DIM)

    if not v:
        return im

    # どの試合のコメント欄かを出す。訳文だけだと、何を見ての言葉なのかが
    # 画面から消えてしまう。
    y = 360
    if v.get("matchup"):
        d.text((74, y), v["matchup"][:44], font=font(30), fill=JP)
        y += 52

    # 元の投稿
    lines = wrap(d, v.get("ja") or "", font(44), W - 240)[:4]
    h = 30 + len(lines) * 60 + 52
    e = ease_out(min(1.0, max(0.0, p * 7)))
    dx = int((1 - e) * 110)
    d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + h], 20, fill=(33, 27, 45))
    d.rounded_rectangle([60 - dx, y, 70 - dx, y + h], 5, fill=JP)
    yy = y + 30
    for ln in lines:
        d.text((100 - dx, yy), ln, font=font(44), fill=TEXT)
        yy += 60
    d.text((100 - dx, yy + 6), (v.get("title") or "")[:40],
           font=font(24), fill=DIM)
    stat = f"♥ {v.get('likes', 0):,}　返信 {v.get('replies', 0)}件"
    d.text((W - 100 - dx - d.textlength(stat, font=font(28)), yy + 4),
           stat, font=font(28), fill=JP)

    # 返信。左に縦線を引いて、上の投稿にぶら下がっていることを見せる
    y += h + 34
    replies = (v.get("reply_ja") or [])[:3]
    for i, r in enumerate(replies):
        appear = 0.14 + i * 0.11
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 8)))
        dx = int((1 - e) * 90)
        # 右上に調子の札が載るので、そのぶん本文の幅を空けておく。
        # 同じ行に文字が来ると、札の下に文字が潜って読めなくなる。
        rl = wrap(d, r.get("ja") or "", font(38), W - 480)[:3]
        rh = 34 + len(rl) * 52 + 34
        d.rounded_rectangle([150 - dx, y, W - 60 - dx, y + rh], 18,
                            fill=(27, 22, 38))
        # 上の投稿から降りてくる線
        d.line([(112, y - 34), (112, y + 34)], fill=(60, 52, 78), width=4)
        d.line([(112, y + 34), (150 - dx, y + 34)], fill=(60, 52, 78), width=4)
        tone = r.get("tone")
        if tone in TONE_COLOR:
            tw = d.textlength(tone, font=font(26)) + 30
            d.rounded_rectangle([W - 60 - dx - tw - 28, y + 16,
                                 W - 60 - dx - 28, y + 56], 11,
                                fill=TONE_COLOR[tone])
            d.text((W - 60 - dx - tw - 13, y + 23), tone,
                   font=font(26), fill=BG)
        ry = y + 34
        for ln in rl:
            d.text((186 - dx, ry), ln, font=font(38), fill=TEXT)
            ry += 52
        d.text((186 - dx, ry + 2), (r.get("original") or "")[:36],
               font=font(22), fill=DIM)
        y += rh + 26

    return im


def render_voices(p, voices, picked=None):
    """
    現地のファンが何と言っているか。

    他の画面と違い、ここは翻訳を通した誰かの感想であって記録ではない。
    背景色を変え、出典と「翻訳」であることを画面に必ず出して、
    数字のコーナーと混ざって見えないようにする。
    原文も併記して、訳が気になる人が確かめられるようにしておく。
    """
    im = Image.new("RGB", (W, H), VOICE_BG)
    d = ImageDraw.Draw(im)
    off = int(min(p, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(26, 21, 36))
    d.rectangle([0, H - 22, W, H], fill=JP)
    draw_steps(d, JP)
    draw_spoken(d, JP)

    items = voices.get("voices") or []
    # 読み上げが選んだものと同じ並びにする。指定が無い日は元の並び。
    if picked is not None:
        items = [items[i] for i in picked if i < len(items)]
    d.text((70, 70), "コレスポ", font=font(46), fill=JP)
    d.text((70, 190), "現地の声", font=font(72), fill=JP)
    d.text((74, 278), f"{voices.get('source', '')}を翻訳",
           font=font(32), fill=DIM)

    y = 380
    for i, v in enumerate(items[:VOICES_SHOWN]):
        appear = 0.06 + i * 0.09
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 8)))
        dx = int((1 - e) * 110)
        ja = v.get("ja", "")
        lines = wrap(d, ja, font(42), W - 220)[:3]
        # コメントで名前が挙がった選手。成績を1行足すぶん、箱を高くする。
        who = (mentioned.find(v.get("title") or "", limit=1) or [None])[0]
        h = 60 + len(lines) * 58 + 46 + (38 if who else 0)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + h], 20, fill=(31, 26, 42))
        # ❝(U+275D)はNoto Sans CJKに無く、豆腐(□)になる。
        # 確実に持っている鉤括弧を使う。
        d.text((100 - dx, y + 14), "「", font=font(44), fill=JP)

        # 称賛か批判かを添える。同じ一言でも、褒めているのか怒っているのかで
        # 意味が変わる。訳文だけだと、どちらとも取れる書き方が残る。
        tone = v.get("tone")
        if tone in TONE_COLOR:
            tw = d.textlength(tone, font=font(28)) + 34
            d.rounded_rectangle([W - 60 - dx - tw - 34, y + 22,
                                 W - 60 - dx - 34, y + 68],
                                12, fill=TONE_COLOR[tone])
            d.text((W - 60 - dx - tw - 17, y + 30), tone,
                   font=font(28), fill=BG)

        yy = y + 66
        for line in lines:
            d.text((100 - dx, yy), line, font=font(42), fill=TEXT)
            yy += 58
        # 原文の一部を小さく添える。訳が気になる人が確かめられるように
        src = (v.get("title") or "")[:38]
        d.text((100 - dx, yy + 4), src, font=font(24), fill=DIM)
        # コメントで名前が挙がった選手の、その日の成績。
        #
        # 「Sanchezが今日の負けの唯一の理由だ」と書かれていても、
        # 訳文だけでは実際どうだったのかが分からない。数字を隣に置くと、
        # 怒っているのか称えているのかが数字の側からも見える。
        # こちらの評価は足さない。並べるだけにする。
        if who:
            d.text((100 - dx, yy + 38),
                   f"{who['name']}　{who['line'][:26]}",
                   font=font(26), fill=JP)

        # どれだけ賛同されたかは、その一言の重みそのもの。
        likes = v.get("likes")
        if likes:
            d.text((W - 100 - dx - d.textlength(f"♥ {likes:,}", font=font(26)),
                    yy + 2), f"♥ {likes:,}", font=font(26), fill=JP)
        y += h + 26

    d.text((70, H - 250), "※現地の投稿を翻訳したものです", font=font(30), fill=DIM)
    d.text((70, H - 200), "　コレスポの見解ではありません", font=font(30), fill=DIM)
    d.text((70, H - 140), "collespo.com", font=font(38), fill=DIM)
    return im


# 毎日出しているものの一覧。アウトロで順に出す。
#
# 以前は「毎日19時」とだけ書いていたが、いまは5本体制で19時はそのうちの
# 1本にすぎない。何が毎日届くのかが分からないままでは、登録する理由に
# ならない。時刻ではなく中身を並べる。
# 画面に並べる一覧。文言は post_common に1本化してある。
# 以前はここと説明文と「今日の1人」の締めで別々に書いていて、
# 3つとも中身が違っていた。
DAILY_LINEUP = [(name, what)
                for _, name, what, _ in post_common.DAILY_LINEUP]


def render_outro(p, mode: str = ""):
    """
    最後の画面。毎日出しているものを並べる。

    高さを固定で置いていたところ、一覧が6件から7件になった日に
    出典と登録の帯と読み上げの帯が全部同じところへ重なった。
    実際に投稿された動画でそうなっている。
    座標は積み上げで決めて、決め打ちを残さない。
    """
    im, d = base(p)
    d.text((80, 250), "コレスポ", font=font(104), fill=ACCENT)
    d.text((80, 380), "毎日、更新中", font=font(64), fill=TEXT)

    # 見ている回そのものは外す。読み上げと同じ扱いにする。
    rows = [(name, what) for kind, name, what, _ in post_common.DAILY_LINEUP
            if kind != MODE_KIND.get(mode, "")]

    # 1行ずつ滑り込ませる。全部を一度に出すと、ただの箇条書きに見える。
    y = 500
    h = 132 if len(rows) > 5 else 150
    for i, (title, note) in enumerate(rows):
        appear = 0.08 + i * 0.09
        if p < appear:
            y += h + 14
            continue
        e = ease_out(min(1.0, (p - appear) * 7))
        dx = int((1 - e) * 90)
        d.rounded_rectangle([70 - dx, y, W - 70 - dx, y + h], 16, fill=SURF)
        d.text((104 - dx, y + 18), title, font=font(46), fill=TEXT)
        d.text((104 - dx, y + 76), note, font=font(34), fill=DIM)
        y += h + 14

    y += 16
    if p > 0.62:
        d.rounded_rectangle([70, y, W - 70, y + 100], 18, fill=ACCENT)
        d.text((110, y + 26), "チャンネル登録で毎日届きます",
               font=font(44), fill=BG)
    y += 124

    # 出典はいちばん下。一覧の下に積むので、件数が変わっても重ならない。
    d.text((80, y), "音声: VOICEVOX:ずんだもん", font=font(30), fill=DIM)
    d.text((80, y + 42), "データ: MLB Stats API", font=font(30), fill=DIM)
    d.text((80, y + 96), "collespo.com", font=font(38), fill=TEXT)
    return im


# ---------------------------------------------------------------------------
# 尺と音声(週次・答え合わせと同じ考え方)
# ---------------------------------------------------------------------------

# 尺の予算は post_common に置いてある。日次の回も同じ上限を使う。
# 見る側にはどちらも同じチャンネルの1本でしかない。
from post_common import MAX_SECONDS, fit_budget          # noqa: E402

# 予算を超えたときに落とす順。前にあるものから落とす。
# 冒頭と締めは入れない。冒頭は最も見られる画面で、
# 締めは他の枠への案内なので、削ると回遊が止まる。
DROP_ORDER = ("talk", "headlines", "p_awards", "p_recent", "p_season",
              "praise", "reporters", "scoreboard", "voices", "buzz")


def plan_durations(segs):
    """各画面を何秒置くか。読み上げの長さと、目で追う量の大きいほう。

    min_duration を持つ段は、その値を下限に使う。画面に出る量が
    その日によって変わるものがあり(スコアボードの回数など)、
    表の固定値では、短い日は無音が伸び、長い日は追いつかない。
    """
    return [max(float(s.get("min_duration")
                      or MIN_DURATION.get(s.get("kind") or "list", 5.0)),
                float(s.get("duration") or 0) + video_common.SEGMENT_TAIL)
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


def build_player_video(args):
    """
    「今日の1人」。1人の選手を、数字と現地の言葉だけでまとめる。

    他の枠と違い、前夜の試合に依存しない。通算成績と経歴は翌日には
    古くならないので、あとから名前で検索した人にも同じだけ役に立つ。
    試合の予告が翌日に価値を失うのに対し、こちらは残る。
    """
    import player_screens as ps

    path = pathlib.Path(args.profile)
    if not path.exists():
        print(f"[info] {path} が無いため、今日の1人は作りません"
              "(scripts/player_profile.py を先に走らせてください)")
        return 0
    prof = json.loads(path.read_text(encoding="utf-8"))
    if not (prof.get("career") or prof.get("this_season")):
        print(f"[info] {prof.get('name')} の成績が取れていないため作りません")
        return 0

    narration = ps.build_narration(prof)
    kinds = [s["kind"] for s in narration["segments"]]
    print(f"[info] 今日の1人: {prof.get('name')}({prof.get('team')}) "
          f"/ 画面 {len(kinds)}枚: {kinds}")

    if args.narration_out:
        op = pathlib.Path(args.narration_out)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(narration, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        print(f"[info] 原稿を書き出しました: {op} ({len(kinds)}セグメント)")
        return 0

    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestが見つかりません: {manifest.resolve()}")
        segs = [{"kind": s["kind"], "file": None, "duration": 0.0,
                 "meta": s["meta"]} for s in narration["segments"]]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "collespo_morning_player.mp4"

    durations = plan_durations(segs)

    # 長すぎる回を、ここで削る。
    #
    # 音声ができたあとなので、本当の長さが分かる。捨てる音声は
    # VOICEVOXがローカルで作ったもので、費用はかからない。
    keep, dropped = fit_budget(segs, durations, DROP_ORDER)
    if dropped:
        segs = [segs[i] for i in keep]
        durations = [durations[i] for i in keep]
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"{args.mode}: {MAX_SECONDS:.0f}秒に収めるため"
                        f"{'、'.join(dropped)}を外しました"
                        f"(残り{sum(durations):.0f}秒){chr(10)}")

    audio_path = build_narration_track(segs, durations, out_dir)
    if args.require_audio and not audio_path:
        print("::error::音声が作れませんでした。無音のまま投稿しないよう、"
              "ここで中止します(VOICEVOXの起動を確認してください)")
        return 1

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

    err_file = open(out_dir / "ffmpeg_error.log", "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=err_file)
    # 直前の画面の最後のフレーム。切り替わりの頭だけ、これと混ぜる。
    last_frame = None
    try:
        for seg_i, (seg, dur) in enumerate(zip(segs, durations)):
            set_step(seg_i, len(segs))
            # その画面で読み上げている文を、画面下に出す
            set_spoken((narration["segments"][seg_i].get("text") or "")
                       if seg_i < len(narration["segments"]) else "")
            n = int(dur * FPS)
            kind = seg.get("kind")
            draw = ps.RENDERERS.get(kind)
            cached = None
            # 最初の画面は前が無いので混ぜない
            fade = 0 if seg_i == 0 else int(video_common.FADE_SECONDS * FPS)
            for k in range(n):
                pp = k / max(1, n - 1)
                if pp > ANIM_END and cached is not None:
                    proc.stdin.write(cached)
                    continue
                im = draw(pp, prof) if draw else render_outro(pp, "player")
                cached = video_common.crossfade(last_frame, im, k, fade, (W, H))
                proc.stdin.write(cached)
            last_frame = cached
            print(f"[info] {kind}: {dur:.1f}秒 ({n}フレーム)")
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait()
    err_file.close()
    if proc.returncode != 0:
        print(f"::error::ffmpegが失敗しました ({proc.returncode})")
        return 1
    print(f"[info] 書き出しました -> {video_path}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recap", default="data/morning_recap.json")
    parser.add_argument("--buzz", default="data/mlb_buzz.json")
    parser.add_argument("--reporters", default="data/local_reporters.json")
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--talk", default="data/local_buzz.json")
    parser.add_argument("--voices", default="data/local_voices.json")
    parser.add_argument("--profile", default="data/player_profile.json",
                        help="--mode player のときの、今日の1人の材料")
    parser.add_argument("--mode", default="players",
                        choices=["players", "player", "local", "press",
                                 "voices", "all"],
                        help="players=選手成績 / local=現地の注目度(数字) / "
                             "press=現地の報道(番記者と見出し) / "
                             "voices=ハイライトのコメント欄 / "
                             "player=今日の1人 / all=全部")
    parser.add_argument("--narration-out", default=None)
    parser.add_argument("--audio-dir", default="build/mr_audio")
    parser.add_argument("--require-audio", action="store_true",
                        help="音声が作れなければ動画を作らずに終わる")
    parser.add_argument("--out", default="build/morning")
    args = parser.parse_args()

    # 「今日の1人」は他の枠と材料が違うので、ここで分岐して先に処理する。
    # 前夜の出場に依存しないため、成績データが無い日でも作れる。
    if args.mode == "player":
        return build_player_video(args)

    path = pathlib.Path(args.recap)
    if not path.exists():
        print(f"[info] {path} が無いため、夕方のショートは作りません")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    # 並べ替えはここで一度だけ行う。
    # build_narration の中だけで並べ替えていたとき、原稿は貢献度順なのに
    # 画面は元の順のままで、「1位 34点、3位 44点」と食い違った。
    # 週次動画と資産動画で一度ずつ踏んだのと同じ失敗なので、
    # 原稿と画面が同じリストを見るようにする。
    players = sort_players(data.get("players") or [])
    data["players"] = players
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

    # 現地の声(翻訳)。数字のコーナーとは別枠として扱う
    data["voices"] = local_voices.load(args.voices)
    voices_data = data["voices"]

    # 現地の番記者と見出し。取れていなければ、その画面が出ないだけ。
    reporters_data = {}
    rp = pathlib.Path(args.reporters)
    if rp.exists():
        try:
            reporters_data = json.loads(rp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            reporters_data = {}
    data["reporters"] = reporters_data
    if reporters_data.get("posts"):
        print(f"[info] 現地の番記者: {len(reporters_data['posts'])}件 / "
              f"見出し {len(reporters_data.get('headlines') or [])}件")
    if voices_data.get("voices"):
        print(f"[info] 現地の声: {len(voices_data['voices'])}件")
    if talk.get("teams"):
        print(f"[info] 現地の話題: {len(talk['teams'])}チーム / "
              f"{talk.get('titles_count', 0)}件の見出しから")

    narration = build_narration(data, args.mode)
    kinds = [s["kind"] for s in narration["segments"]]
    print(f"[info] mode={args.mode} / 画面 {len(kinds)}枚: {kinds}")
    # 材料が1つも無い日は作らない。
    # 判定は「実際に画面ができたかどうか」で見る。素材の種類を並べて
    # 数えていたため、番記者と見出しを足したときに数え漏れて、
    # 中身のある動画を「材料が無い」として捨てていた。
    body = [k for k in kinds if k not in ("intro", "outro")]

    # 薄い日をどう扱うか。
    #
    # 毎日出ることに意味がある枠なので、少ない日も基本は出す。
    # ただし press は、選手成績のように必ず毎日発生する情報ではない。
    # 中身が1件しかない動画が、たまたま初めて見た人に当たると、
    # そこで見限られる。1本ぶんの体裁になる最低量だけは要る。
    #
    # 数えるのは画面の数ではなく素材の件数。見出し1件でも画面は作れてしまう。
    if args.mode == "press":
        rep = reporters_data.get("posts") or []
        hds = reporters_data.get("headlines") or []
        items = len(rep) + len(hds)
        if items < MIN_PRESS_ITEMS:
            print(f"[info] 現地の報道が{items}件しかないため、"
                  f"報道編は作りません(最低{MIN_PRESS_ITEMS}件)")
            return

    # コメント欄の回は、声が少ない日に出すと1件読んで終わってしまう。
    # 報道編と同じ理由で、1本ぶんの体裁になる最低量を求める。
    if args.mode == "voices":
        vcs = (voices_data or {}).get("voices") or []
        if len(vcs) < MIN_VOICE_ITEMS:
            print(f"[info] コメントが{len(vcs)}件しかないため、"
                  f"コメント欄編は作りません(最低{MIN_VOICE_ITEMS}件)")
            return

    if args.mode in ("local", "press", "voices") and not body:
        print("[info] 現地のデータが1つも無いため、現地編は作りません")
        return

    if args.narration_out:
        p = pathlib.Path(args.narration_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(narration, ensure_ascii=False), encoding="utf-8")
        print(f"[info] 原稿を書き出しました: {p} "
              f"({len(narration['segments'])}セグメント)")
        return

    # 画面の冒頭も、読み上げと同じ選手にする。
    #
    # 読み上げは players[0](貢献度順の1位)、画面は pick_top(本塁打を
    # 最優先する別の基準)を使っていた。本塁打が出た日だけ、
    # 「画面には大谷、音声は鈴木誠也」という食い違いが出る。
    # 以前 build_narration 側を直したときに、こちらを直し忘れていた。
    # 選び方が2つあると、いつかまた離れる。1つにする。
    top = players[0] if players else {}
    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestが見つかりません: {manifest.resolve()}")
        segs = [{"kind": s["kind"], "file": None, "duration": 0.0,
                 "meta": s["meta"]} for s in narration["segments"]]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # モードごとに別ファイルにする。同じ名前だと2本目が1本目を上書きする
    video_path = out_dir / (f"collespo_morning_{args.mode}.mp4"
                            if args.mode != "players"
                            else "collespo_morning.mp4")

    durations = plan_durations(segs)
    audio_path = build_narration_track(segs, durations, out_dir)

    # 音声が作れなかった場合、これまでは無音のまま書き出して投稿していた。
    # 無音の動画が出るくらいなら、その日は出さない方がよい。
    # VOICEVOXの起動は continue-on-error なので、失敗しても気づけない。
    if args.require_audio and not audio_path:
        print("::error::音声が作れませんでした。無音のまま投稿しないよう、"
              "ここで中止します(VOICEVOXの起動を確認してください)")
        return 1

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
    # 直前の画面の最後のフレーム。切り替わりの頭だけ、これと混ぜる。
    last_frame = None
    try:
        for seg_i, (seg, dur) in enumerate(zip(segs, durations)):
            set_step(seg_i, len(segs))
            # その画面で読み上げている文を、画面下に出す
            set_spoken((narration["segments"][seg_i].get("text") or "")
                       if seg_i < len(narration["segments"]) else "")
            n = int(dur * FPS)
            kind, meta = seg.get("kind"), seg.get("meta") or {}
            cached = None
            # 最初の画面は前が無いので混ぜない
            fade = 0 if seg_i == 0 else int(video_common.FADE_SECONDS * FPS)
            for k in range(n):
                pp = k / max(1, n - 1)
                if pp > ANIM_END and cached is not None:
                    proc.stdin.write(cached)
                    total += 1
                    continue
                if kind == "outro":
                    set_spoken("")
                if kind == "intro":
                    im = render_intro(pp, meta, top,
                                     {"buzz": buzz,
                                      "voices": voices_data,
                                      "reporters": reporters_data})
                elif kind == "list":
                    im = render_list(pp, players, meta.get("start", 0),
                                     meta.get("count", 1))
                elif kind == "buzz":
                    im = render_buzz(pp, buzz, picks)
                elif kind == "week":
                    im = render_week(pp, meta.get("week") or [],
                                     players[0].get("name") if players else "")
                elif kind == "praise":
                    im = render_praise(
                        pp, ((voices_data or {}).get("jp_praise") or [])
                        [:meta.get("count", 2)])
                elif kind == "scoreboard":
                    res = (buzz[0].get("result") or {}) if buzz else {}
                    im = render_scoreboard(pp, res, meta.get("away", ""),
                                           meta.get("home", ""))
                    if im is None:      # 材料が合わない日は前の画面を保つ
                        im = render_buzz(pp, buzz, picks)
                elif kind == "talk":
                    im = render_talk(pp, talk)
                elif kind == "thread":
                    vs = (voices_data or {}).get("voices") or []
                    i = meta.get("index")
                    im = render_thread(pp, vs[i] if i is not None
                                       and i < len(vs) else None)
                elif kind == "voices":
                    im = render_voices(pp, voices_data, meta.get("picked"))
                elif kind == "reporters":
                    im = render_reporters(pp, reporters_data.get("posts") or [])
                elif kind == "headlines":
                    im = render_headlines(
                        pp, reporters_data.get("headlines") or [])
                else:
                    im = render_outro(pp, args.mode)
                cached = video_common.crossfade(last_frame, im, k, fade, (W, H))
                proc.stdin.write(cached)
                total += 1
            last_frame = cached
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
    print(f"[info] 夕方のショートを生成しました: {video_path} "
          f"({video_path.stat().st_size / 1024 / 1024:.1f}MB, {secs:.0f}秒)")


if __name__ == "__main__":
    # main() の戻り値を終了コードにする。返すだけでは 0 で終わり、
    # 中止したつもりでも後続の投稿ステップが動いてしまう。
    raise SystemExit(main() or 0)
