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
from morning_recap import jst_label as _jst_label  # noqa: E402
# 外国人選手はVOICEVOXがアクセント記号で読みを外す。日次と同じ処理を通す。
from generate_narration import speech_name  # noqa: E402

from PIL import Image, ImageDraw, ImageFont

import local_buzz
import local_voices
import mlb_buzz
import morning_recap

W, H = 1080, 1920
FPS = 24
ANIM_END = 0.45
SEGMENT_TAIL = 1.5
MIN_DURATION = {"intro": 5.0, "list": 8.0, "buzz": 9.0,
                "talk": 9.0, "voices": 11.0, "outro": 5.0,
                # 翻訳した文章は読む時間が要るので、数字の画面より長く取る
                "reporters": 12.0, "headlines": 11.0}

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

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
_FONT_FILE = None

# 1画面に載せる人数。多いと字が小さくなって読めない
PER_PAGE = 4

# 現地の声編を作る最低の素材数(番記者+見出し+ファンの声の合計)。
# 選手成績と違って毎日必ず湧く情報ではないので、下限を置く。
# 中身1件の動画に初見の人が当たると、そこで見限られる。
MIN_PRESS_ITEMS = 3


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


def spoken_list(chunk: list, start: int) -> str:
    """1画面ぶんの読み上げ。触れない選手は人数だけ言う。"""
    parts, skipped = [], 0
    for j, p in enumerate(chunk):
        rank = start + j + 1
        if worth_speaking(p, rank):
            score = morning_recap.score_label(p)
            parts.append(
                f"{rank}位、{p['name']}、{yomi_stats(p['headline'])}。"
                + (f"{p['clutch_label']}。" if p.get("clutch_label") else "")
                + (f"スコア{score}。" if score else "")
            )
        else:
            skipped += 1

    # 誰も該当しない画面が無音にならないよう、先頭だけは必ず読む
    if not parts and chunk:
        p = chunk[0]
        parts.append(f"{start + 1}位、{p['name']}、{yomi_stats(p['headline'])}。")
        skipped -= 1

    if skipped > 0:
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


def pick_top(players: list) -> dict:
    """
    その日いちばん目立った1人を、数字だけで機械的に選ぶ。

    「誰が良かったか」を語らずに済むよう、順番を先に決めてある。
    投手は好投した場合のみ候補にする(登板しただけで上位に来ないように)。

      1. 本塁打を打った打者(本数 → 安打数)
      2. 5回以上を自責2以下で投げた投手(奪三振の多い順)
      3. 2安打以上の打者(安打数)
      4. 奪三振が最も多い投手
    """
    if not players:
        return {}
    batters = [p for p in players if p["type"] == "batter"]
    pitchers = [p for p in players if p["type"] == "pitcher"]

    hr = [p for p in batters if p.get("hr")]
    if hr:
        return max(hr, key=lambda p: (p["hr"], p["hits"]))

    def _ip(p):
        try:
            return float(p.get("ip") or 0)
        except (TypeError, ValueError):
            return 0.0

    quality = [p for p in pitchers if _ip(p) >= 5 and p.get("er", 99) <= 2]
    if quality:
        return max(quality, key=lambda p: p.get("so", 0))

    multi = [p for p in batters if p.get("hits", 0) >= 2]
    if multi:
        return max(multi, key=lambda p: p["hits"])
    if pitchers:
        return max(pitchers, key=lambda p: p.get("so", 0))
    return players[0]


# ---------------------------------------------------------------------------
# 原稿
# ---------------------------------------------------------------------------

def build_narration(data: dict, mode: str = "all") -> dict:
    """
    mode で扱う内容を切り替える。

    全部を1本に詰めると76秒・7画面になり、主題が3つ(選手成績・現地の注目度・
    現地の声)混ざる。1本にまとめると、タイトルもサムネイルもどれか1つしか
    表せない。実際、最も見られた動画は単一主題のもので、情報を詰めたものほど
    視聴率が落ちていた。

      players … 日本人選手の成績だけ
      local   … 現地の注目度だけ(再生回数・話題のチーム＝測った数字)
      press   … 現地の声と報道だけ(番記者・見出し・ファン＝翻訳した言葉)
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
            "meta": {"date": day_iso, "count": len(players)},
        }]
    elif mode == "press":
        # 言葉の回。
        # 冒頭で本文の引用をそのまま読むと、直後の画面で同じ文をもう一度
        # 読むことになる。冒頭は「誰の言葉が何件あるか」だけにして、
        # 中身は本文の画面に任せる。
        rp = (data.get("reporters") or {}).get("posts") or []
        hd = (data.get("reporters") or {}).get("headlines") or []
        who = ""
        if rp:
            outlets = []
            for r in rp[:3]:
                o = r.get("outlet", "")
                if o and o not in outlets:
                    outlets.append(o)
            if outlets:
                who = "、".join(outlets[:2]) + "などの記者。"
        segments = [{
            "kind": "intro",
            "text": f"{who}{day}、現地では何と言われているか。"
                    f"番記者の投稿と現地の見出しから。",
            "meta": {"date": day_iso, "count": len(players), "local": True},
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
                     "local": True},
        }]

    if want_players:
        for i in range(0, len(players), PER_PAGE):
            chunk = players[i:i + PER_PAGE]
            segments.append({
                "kind": "list",
                "text": spoken_list(chunk, i),
                "meta": {"start": i, "count": len(chunk)},
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

    # 現地の声。ここだけは数字ではなく、翻訳を通した誰かの感想なので、
    # 読み上げでも「翻訳したもの」であることを先に断る。
    voices = ((data.get("voices") or {}).get("voices") or []) if want_press else []
    if voices:
        parts = [f"ここからは現地の声です。"
                 f"{(data.get('voices') or {}).get('source', '')}の投稿を"
                 "翻訳したもので、コレスポの見解ではありません。"]
        for v in voices[:3]:
            parts.append(v.get("ja", "") + "。")
        segments.append({"kind": "voices", "text": "".join(parts), "meta": {}})

    # 現地で何が報じられたか。見出しだけを扱う。
    #
    # 番記者より先に置く。番記者の投稿は1件が長いので、いきなり誰かの
    # 長い所感から始まると入りが重い。短い見出しで「何が起きたか」を
    # 先に通してから、それについて誰が何と言ったかへ進む方がテンポが出る。
    heads = ((data.get("reporters") or {}).get("headlines") or []) \
        if want_press else []
    if heads:
        parts = ["現地の見出しです。"]
        for h in heads[:3]:
            body = h.get("jp") or h.get("title", "")
            parts.append(f"{h.get('source', '')}。{body[:80]}。")
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
        for r in reporters[:2]:
            body = r.get("jp") or r.get("text", "")
            # 訳が付いていない場合は原文が入る。原文は長いので、
            # 読み上げが尺を食いすぎないよう頭で切る。
            parts.append(f"{r.get('outlet', '')}の記者。{body[:90]}。")
        segments.append({"kind": "reporters", "text": "".join(parts),
                         "meta": {}})

    segments.append({
        "kind": "outro",
        # アウトロは「何をしているか」の説明で終わっていた。
        # 次に何があるかを言い、登録を促す形に変える。
        # 登録が増えないと、毎日出しても毎日ゼロから始まる。
        # 時刻を1つ挙げるより、毎日何が届くのかを言う。
        # 「方」は「ほう」と読まれるので仮名で書く。
        "text": "コレスポでは、日本人選手の成績、現地での注目度、"
                "明日の注目試合、欧州サッカー、現地メディアの声を"
                "毎日お届けしています。"
                "見逃したくないかたは、チャンネル登録をお願いします。",
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

def render_intro(p, meta, top):
    im, d = base(p)
    e = ease_out(min(1.0, p * 2.6))
    slide = int((1 - e) * 70)

    d.text((80, 430 + slide), jp_date(meta.get("date", "")), font=font(64), fill=DIM)
    # 現地編は主題が違うので見出しを変える
    heading = "現地での注目度" if meta.get("local") else "日本人選手の成績"
    d.text((80, 530 + slide), heading, font=font(96), fill=ACCENT)

    if top and p > 0.14 and not meta.get("local"):
        d.rounded_rectangle([70, 760, W - 70, 1120], 24, fill=SURF)
        # 「今日の1人」であることを明示する。数字で機械的に選んでいるので、
        # 主観の評価に見えないよう、下に選び方の根拠を添える
        d.text((110, 774), "今日の1人", font=font(34), fill=ACCENT)
        d.text((110, 820), top.get("name", ""), font=font(72), fill=JP)
        head = top.get("headline", "")
        s = fit(d, head, W - 220, (60, 54, 48, 42))
        d.text((110, 940), head, font=font(s), fill=TEXT)
        d.text((110, 1036), "成績から機械的に選んでいます", font=font(32), fill=DIM)

    if meta.get("local"):
        d.text((80, 800), "見られた量・語られた量・現地の声",
               font=font(46), fill=JP)
        d.text((80, 880), "数字と、翻訳した投稿で見ていきます",
               font=font(40), fill=DIM)
    else:
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
        s = fit(d, head, (W - 560) if right_used else (W - 300),
                (48, 44, 40, 36))
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
    return _jp_matchup(b.get("matchup", ""))


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

    d.text((70, 70), "コレスポ", font=font(46), fill=JP)
    d.text((70, 190), "現地の番記者", font=font(72), fill=JP)
    d.text((74, 278), "現地メディアの記者の投稿を翻訳", font=font(32), fill=DIM)

    y = 380
    for i, r in enumerate(posts[:2]):
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

    d.text((70, 70), "コレスポ", font=font(46), fill=JP)
    d.text((70, 190), "現地の見出し", font=font(72), fill=JP)
    d.text((74, 278), "現地メディアの見出しを翻訳", font=font(32), fill=DIM)

    y = 380
    for i, h in enumerate(heads[:3]):
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


def render_voices(p, voices):
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

    items = voices.get("voices") or []
    d.text((70, 70), "コレスポ", font=font(46), fill=JP)
    d.text((70, 190), "現地の声", font=font(72), fill=JP)
    d.text((74, 278), f"{voices.get('source', '')} の投稿を翻訳",
           font=font(32), fill=DIM)

    y = 380
    for i, v in enumerate(items[:3]):
        appear = 0.06 + i * 0.09
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 8)))
        dx = int((1 - e) * 110)
        ja = v.get("ja", "")
        lines = wrap(d, ja, font(42), W - 220)[:3]
        h = 60 + len(lines) * 58 + 46
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + h], 20, fill=(31, 26, 42))
        d.text((100 - dx, y + 18), "❝", font=font(44), fill=JP)
        yy = y + 66
        for line in lines:
            d.text((100 - dx, yy), line, font=font(42), fill=TEXT)
            yy += 58
        # 原文の一部を小さく添える。訳が気になる人が確かめられるように
        src = (v.get("title") or "")[:38]
        d.text((100 - dx, yy + 4), src, font=font(24), fill=DIM)
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
DAILY_LINEUP = [
    ("日本人選手の成績", "誰がいちばん効いたか"),
    ("現地での注目度", "向こうで何が見られたか"),
    ("明日の注目試合", "なぜ注目なのか"),
    ("欧州サッカー", "その夜の注目カード"),
    ("現地メディアの声", "番記者と見出しを翻訳"),
]


def render_outro(p):
    im, d = base(p)
    d.text((80, 300), "コレスポ", font=font(104), fill=ACCENT)
    d.text((80, 430), "毎日、更新中", font=font(64), fill=TEXT)

    # 1行ずつ滑り込ませる。全部を一度に出すと、ただの箇条書きに見える。
    y = 540
    for i, (title, note) in enumerate(DAILY_LINEUP):
        appear = 0.08 + i * 0.09
        if p < appear:
            continue
        e = ease_out(min(1.0, (p - appear) * 7))
        dx = int((1 - e) * 90)
        d.rounded_rectangle([70 - dx, y, W - 70 - dx, y + 150], 16, fill=SURF)
        d.text((104 - dx, y + 22), title, font=font(52), fill=TEXT)
        d.text((104 - dx, y + 92), note, font=font(38), fill=DIM)
        y += 166

    if p > 0.62:
        d.rounded_rectangle([70, 1610, W - 70, 1720], 18, fill=ACCENT)
        d.text((110, 1638), "チャンネル登録で毎日届きます", font=font(46), fill=BG)
    d.text((80, 1760), "collespo.com", font=font(42), fill=TEXT)
    # 出典はいちばん下に置く。一覧と重ならない位置。
    d.text((80, 1500), "音声: VOICEVOX:ずんだもん", font=font(34), fill=DIM)
    d.text((80, 1550), "データ: MLB Stats API", font=font(34), fill=DIM)
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
    parser.add_argument("--reporters", default="data/local_reporters.json")
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--talk", default="data/local_buzz.json")
    parser.add_argument("--voices", default="data/local_voices.json")
    parser.add_argument("--mode", default="players",
                        choices=["players", "local", "press", "all"],
                        help="players=選手成績 / local=現地の注目度(数字) / "
                             "press=現地の声と報道(言葉) / all=全部")
    parser.add_argument("--narration-out", default=None)
    parser.add_argument("--audio-dir", default="build/mr_audio")
    parser.add_argument("--out", default="build/morning")
    args = parser.parse_args()

    path = pathlib.Path(args.recap)
    if not path.exists():
        print(f"[info] {path} が無いため、朝のショートは作りません")
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
        vcs = (voices_data or {}).get("voices") or []
        items = len(rep) + len(hds) + len(vcs)
        if items < MIN_PRESS_ITEMS:
            print(f"[info] 現地の素材が{items}件しかないため、"
                  f"現地の声編は作りません(最低{MIN_PRESS_ITEMS}件)")
            return

    if args.mode in ("local", "press") and not body:
        print("[info] 現地のデータが1つも無いため、現地編は作りません")
        return

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
    # モードごとに別ファイルにする。同じ名前だと2本目が1本目を上書きする
    video_path = out_dir / (f"collespo_morning_{args.mode}.mp4"
                            if args.mode != "players"
                            else "collespo_morning.mp4")

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
                    im = render_intro(pp, meta, top)
                elif kind == "list":
                    im = render_list(pp, players, meta.get("start", 0),
                                     meta.get("count", 1))
                elif kind == "buzz":
                    im = render_buzz(pp, buzz, picks)
                elif kind == "talk":
                    im = render_talk(pp, talk)
                elif kind == "voices":
                    im = render_voices(pp, voices_data)
                elif kind == "reporters":
                    im = render_reporters(pp, reporters_data.get("posts") or [])
                elif kind == "headlines":
                    im = render_headlines(
                        pp, reporters_data.get("headlines") or [])
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
