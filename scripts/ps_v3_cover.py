#!/usr/bin/env python3
"""試合の話題・2勝0敗（0勝2敗）の話題に、新デザイン「電光掲示板」の表紙の材料（v3）を足す。

なぜ要るのか:
  新デザイン（review_render_v3、style="v3"）は、いま連勝の話題（ps_momentum）だけ。
  本人「各種動画で使っていきたい」（10/6）。試合の話題（ps_game_story）と
  2勝0敗・0勝2敗の話題（ps_odds）も、同じ表紙で出せるようにする。

決まり（Opus-17）:
  - 表紙に置く数字・言葉は、その話題の材料（items・題・見出し・紹介文・日本人選手の行）に
    あるものだけ。計算で新しい数を作らない（得点差・割合は出さない）。
  - 書き方を変えるのは数字の並べ方だけ: 「4対3」→「4-3」、「2勝0敗」→「2-0」、
    「70チーム中63チーム」→「63」「/70」。check() がこの対応を1つずつ確かめる。
  - 材料に無いものは出さない（空にする）。描画（review_render_v3.intro）は、空の欄を飛ばす。
  - 読み上げ・項目・尺は変えない（v3 は表紙と、全画面の下のテロップだけに使う）。

この1ファイルを本番の scripts/ps_v3_cover.py として置き、ps_game_story.py・ps_odds.py の
最後で apply() を呼ぶ（変更案は patches/ps_game_story.diff・ps_odds.diff）。外のモジュールは使わない。

使い方:
  import ps_v3_cover as cover
  topic["v3"] = cover.game_v3(topic, series_rows)   # 試合の話題（series_rows は postseason.json の series）
  topic["v3"] = cover.odds_v3(topic)                # 2勝0敗・0勝2敗の話題
  cover.apply(topic, series_rows)                   # 上のどちらかを付け、合えば style を "v3" に（本番はこれ）
  problems = cover.check(topic)                     # 空なら、表紙の数字・言葉は全部材料にある
"""
import re
import sys

# ps_story.ROUND_SHORT の逆引き（試合の話題の label「地区シリーズ第2戦」→ postseason.json の round）
ROUND_CODE = {"WCS": "F", "地区シリーズ": "D", "リーグ優勝決定シリーズ": "L", "ワールドシリーズ": "W"}

# 札（chips）は2列×2段まで（review_render_v3.intro が描くのは4枚まで）
MAX_CHIPS = 4
# 帯（tag）の長さの目安。全角1・半角0.6で数える。48pxの書体で、帯（文字＋56px）が
# 安全域の右端（940px）に収まる長さ（(940 - 72 - 56) / 48 ≒ 16.9）。
TAG_MAX_EM = 16.9
# 札の上の小さな文字の長さの目安（これより長いと、選手名などのかっこ書きを落とす）
CHIP_LABEL_MAX = 16
# 大きな数字の長さ。これより長いスコア（10-9 など）は「10」「対9」に分ける（画面の幅に収める）
BIG_MAX_CHARS = 3

# 材料に無いが、テロップの区切りとして使う言葉（数字は含まない）
FRAME_WORDS = ("次の試合",)


def _em(text):
    return sum(0.6 if ord(c) < 0x80 else 1.0 for c in text)


def _body(items, head):
    return next((b for h, b in items if h == head), None)


def _short(name):
    """「チェイス・マイドロス」→「マイドロス」（題の「マイドロスの決勝打」と同じ縮め方）。"""
    return name.split("・")[-1]


def _round_and_number(label):
    """試合の話題の label「地区シリーズ第2戦」→（「地区シリーズ」, 2）。"""
    m = re.fullmatch(r"(.+?)第(\d+)戦", label or "")
    return (m.group(1), int(m.group(2))) if m else (label or "", None)


# ---------------------------------------------------------------- 試合の話題

RESULT_RE = re.compile(r"^(?P<win>\S+) (?P<W>\d+)対(?P<L>\d+) (?P<lose>\S+)　(?P<where>敵地で|本拠地で)勝利"
                       r"(?:　(?P<series>.+))?$")
SERIES_RE = re.compile(r"^シリーズは(?P<team>.+)の(?P<w>\d+)勝(?P<l>\d+)敗$")
CLINCH_RE = re.compile(r"^(?P<team>.+)が(?P<w>\d+)勝(?P<l>\d+)敗で(?P<rnd>.+)突破$")
SCENE_RE = re.compile(r"^(?P<inn>\d+回[表裏])　(?P<who>.+?)の(?P<what>[^（]+)(?:（.*）)?$")
HR_RE = re.compile(r"^(?P<team>[^（\d]+)(?P<n>\d+)本(?:（(?P<names>.+)）)?$")


def _game_result(items):
    body = _body(items, "試合の結果")
    m = RESULT_RE.match(body or "")
    return m.groupdict() if m else None


def _series_state(res):
    """試合の結果の行の後ろ（シリーズの勝敗）。勝った側から見た (勝, 敗, 突破したか)。"""
    s = (res or {}).get("series") or ""
    m = SERIES_RE.match(s)
    if m:
        return int(m["w"]), int(m["l"]), False
    m = CLINCH_RE.match(s)
    if m:
        return int(m["w"]), int(m["l"]), True
    return None


def _scene_tag(items):
    """決勝点の場面を、帯に入る長さで。無ければ None。"""
    for head, prefix in (("先制で決勝の一打", "先制で決勝"), ("決勝点", "決勝点")):
        body = _body(items, head)
        m = SCENE_RE.match(body or "")
        if not m:
            continue
        scene = f"{_short(m['who'])}の{m['what']}"
        for cand in (f"{prefix} {m['inn']} {scene}", f"{prefix} {scene}", f"{prefix} {m['inn']}"):
            if _em(cand) <= TAG_MAX_EM:
                return cand
    return None


def _hr_chips(items):
    body = _body(items, "本塁打")
    out = []
    for part in (body or "").split("　"):
        m = HR_RE.match(part)
        if not m:
            continue
        label = f"本塁打　{m['team']}"
        if m["names"] and len(label) + len(m["names"]) + 2 <= CHIP_LABEL_MAX:
            label += f"（{m['names']}）"
        out.append({"label": label, "score": m["n"]})
    return out


def _next_row(topic, series_rows, res):
    """postseason.json の series から、この試合の次の試合（このシリーズの第N+1戦）。

    つじつまが合うときだけ使う: 同じ2球団・同じラウンド・まだ決着していない・
    終わった試合の数がこの試合の番号と同じ・次の番号が N+1。合わなければ None（言わない）。
    """
    rnd, num = _round_and_number(topic.get("label"))
    code = ROUND_CODE.get(rnd)
    if not (code and num and res):
        return None
    names = {res["win"], res["lose"]}
    for row in series_rows or []:
        nxt = row.get("next") or {}
        if (row.get("round") == code and not row.get("over")
                and {t.get("name") for t in row.get("teams") or []} == names
                and row.get("played") == num and nxt.get("game") == num + 1 and nxt.get("day")):
            return {"day": nxt["day"], "game": nxt["game"]}
    return None


def next_game_text(topic):
    """next_game_jp（postseason.json から写したもの）を、テロップの文に。"""
    nxt = topic.get("next_game_jp") or {}
    rnd, _ = _round_and_number(topic.get("label"))
    if not (nxt.get("day") and nxt.get("game")):
        return ""
    return f"日本時間{nxt['day']}　{rnd}第{nxt['game']}戦"


def game_v3(topic, series_rows=()):
    """ps_game_story の話題 → 表紙の材料。series_rows を渡すと、つじつまの合う次の試合を
    topic["next_game_jp"] に写し、テロップに使う。読めない形の話題には {}（v2 のまま描く）。"""
    items = [tuple(x) for x in topic.get("items") or []]
    res = _game_result(items)
    if not res:
        return {}
    rnd, num = _round_and_number(topic.get("label"))
    W, L = res["W"], res["L"]
    score = f"{W}-{L}"
    if len(score) <= BIG_MAX_CHARS:
        big, unit = score, ""
    else:
        big, unit = W, f"対{L}"
    v3 = {"who": f"{res['win']}　{topic.get('label', '')}".strip("　"),
          "big": big, "unit": unit, "sub": f"{res['where']}勝利"}

    state = _series_state(res)
    if state:
        w, l, over = state
        series_tag = f"{rnd}突破" if over else (f"{rnd}先勝" if (w, l) == (1, 0) else f"{rnd}{w}勝{l}敗")
    else:
        series_tag = None
    tag = _scene_tag(items) or series_tag
    if tag:
        v3["tag"] = tag

    chips = []
    if state:
        w, l, over = state
        chips.append({"label": f"{rnd}突破　{res['win']}" if over else f"{rnd}　{res['win']}",
                      "score": f"{w}-{l}", "win": w > l})
    chips += _hr_chips(items)
    if chips:
        v3["chips"] = chips[:MAX_CHIPS]

    nxt = _next_row(topic, series_rows, res)
    if nxt:
        topic["next_game_jp"] = nxt
    else:
        topic.pop("next_game_jp", None)
    ticker = []
    if nxt:
        ticker.append("次の試合　" + next_game_text(topic))
    jps = topic.get("japanese") or []
    if jps:
        ticker.append("日本人選手　" + "　".join(f"{j['name']} {j['line']}" for j in jps[:3]))
    if not ticker:
        ticker.append(_body(items, "試合の結果"))
    v3["ticker"] = "　　".join(ticker)
    return v3


# ---------------------------------------------------------------- 2勝0敗・0勝2敗の話題

UP_RE = re.compile(r"^(?P<up>\d+)チーム中(?P<x>\d+)チーム（(?P<years>\d{4}〜\d{4}年)の.+）$")
AWAY_RE = re.compile(r"^(?P<away2>\d+)チーム中(?P<back>\d+)チーム$")
BACKED_RE = re.compile(r"^(?P<n>\d+)回　最近は(?P<season>\d{4})年（(?P<what>.+)）$")
EXAMPLE_RE = re.compile(r"(?P<season>\d{4})年の(?P<team>[^、（]+)")
NOW_RE = re.compile(r"^\S+ 2勝0敗 \S+　(?P<next>.+)$")


def odds_v3(topic):
    """ps_odds の話題 → 表紙の材料。読めない形の話題には {}。"""
    items = [tuple(x) for x in topic.get("items") or []]
    m = re.fullmatch(r"(.+)の(2勝0敗|0勝2敗)", topic.get("label") or "")
    if not m:
        return {}
    rnd, state = m.groups()
    head = f"{state}から勝ち上がったチーム"
    up = UP_RE.match(_body(items, head) or "")
    if not up:
        return {}
    hook = topic.get("hook") or ""
    suffix = f"が{rnd}{state}"
    who = hook[:-len(suffix)] if hook.endswith(suffix) else hook
    v3 = {"who": who, "big": up["x"], "unit": f"/{up['up']}", "sub": up["years"], "tag": head}

    # 相手の名前は紹介文の「〜で<相手>に2勝0敗」から
    opp = re.search(rf"{re.escape(rnd)}で(\S+?)に{state}", topic.get("intro") or "")
    chips = []
    if opp:
        chips.append({"label": f"いまのシリーズ　{opp.group(1)}に",
                      "score": "2-0" if state == "2勝0敗" else "0-2", "win": state == "2勝0敗"})
    if state == "2勝0敗":
        b = BACKED_RE.match(_body(items, "ひっくり返された例") or "")
        if b:
            chips.append({"label": "ひっくり返された例", "score": b["n"]})
            chips.append({"label": f"最近は　{b['what']}", "score": b["season"]})
    else:
        a = AWAY_RE.match(_body(items, "敵地で2連敗してから") or "")
        if a:
            chips.append({"label": "敵地で2連敗してから", "score": f"{a['back']}/{a['away2']}"})
        examples = _body(items, "最近の例") or ""
        for e in EXAMPLE_RE.finditer(examples):
            # 「どれも3連勝で突破」と材料にあるときだけ、突破の○を付ける
            chips.append({"label": f"最近の例　{e['team']}", "score": e["season"],
                          "win": "突破" in examples})
    if chips:
        v3["chips"] = chips[:MAX_CHIPS]
    now = NOW_RE.match(_body(items, "いまのシリーズ") or "")
    if now:
        v3["ticker"] = "次の試合　" + now["next"]
    return v3


def apply(topic, series_rows=()):
    """話題に v3 を足し、style を "v3" にする。

    作れない・材料と合わない（check で問題が出た）ときは、v3 を付けず style もそのまま（v2 の画面）。
    ここで止まって話題ごと出なくなるのは困るので、例外も外へ出さない（警告だけ）。
    """
    try:
        v3 = (odds_v3(topic) if topic.get("odds") else
              game_v3(topic, series_rows) if topic.get("game") else {})
        problems = check(topic, v3) if v3 else []
    except Exception as e:                                  # noqa: BLE001
        v3, problems = {}, [f"作れません({e})"]
    if v3 and not problems:
        topic["v3"] = v3
        topic["style"] = "v3"
    else:
        topic.pop("v3", None)
        topic.pop("next_game_jp", None)
        # 再適用で材料が変わったときも、表紙なしのv3にしない。
        if topic.get("style") == "v3":
            topic["style"] = "v2"
        if problems:
            print(f"[warn] {topic.get('key')} の表紙（v3）を付けません: {'／'.join(problems)}", file=sys.stderr)
    return topic


# ---------------------------------------------------------------- 検査

NUM_RE = re.compile(r"\d+")
FORMATTED = re.compile(r"^\d+-\d+$|^/?\d+/?\d*$|^対\d+$")


def material_text(topic):
    """表紙に使ってよい文字（読み上げる項目・題・見出し・紹介文・日本人選手の行・次の試合）。"""
    parts = [topic.get(k) or "" for k in ("label", "hook", "heading", "intro", "title", "japanese_lead")]
    for head, body in topic.get("items") or []:
        parts += [head, body]
    for j in topic.get("japanese") or []:
        parts += [j.get("name", ""), j.get("line", "")]
    parts.append(next_game_text(topic))
    return "\n".join(parts)


def v3_texts(v3):
    out = [("who", v3.get("who")), ("big", v3.get("big")), ("unit", v3.get("unit")),
           ("sub", v3.get("sub")), ("tag", v3.get("tag")), ("ticker", v3.get("ticker"))]
    for i, c in enumerate(v3.get("chips") or []):
        out += [(f"chips[{i}].label", c.get("label")), (f"chips[{i}].score", c.get("score"))]
    return [(k, str(v)) for k, v in out if v not in (None, "")]


def _pair_ok(token, text):
    """書き方を変えた数字（4-3・2-0・/70・4/45・対10）が、材料のどの書き方と同じかを確かめる。"""
    m = re.fullmatch(r"(\d+)-(\d+)", token)
    if m:
        a, b = m.groups()
        return (f"{a}対{b}" in text or f"{a}勝{b}敗" in text
                or f"{b}勝{a}敗" in text)            # 0-2 は「ブリュワーズ 2勝0敗 パドレス」の負けた側
    m = re.fullmatch(r"(\d+)/(\d+)", token)
    if m:
        return f"{m.group(2)}チーム中{m.group(1)}チーム" in text
    return True


def check(topic, v3=None):
    """表紙の数字・言葉が材料にあるか。問題の一覧（空なら合格）。"""
    v3 = topic.get("v3") if v3 is None else v3
    if not v3:
        return []
    text = material_text(topic)
    nums = set(NUM_RE.findall(text))
    problems = []
    for key, value in v3_texts(v3):
        for n in NUM_RE.findall(value):
            if n not in nums:
                problems.append(f"{key}: 数字 {n} が材料に無い（{value}）")
        for frag in re.split(r"[\s　（）]+", value):
            if not frag or frag in FRAME_WORDS:
                continue
            if FORMATTED.match(frag):
                if not _pair_ok(frag, text):
                    problems.append(f"{key}: {frag} に当たる書き方が材料に無い（{value}）")
                continue
            if frag not in text:
                problems.append(f"{key}: 「{frag}」が材料に無い（{value}）")
    # 大きな数字と単位の組
    big, unit = str(v3.get("big") or ""), str(v3.get("unit") or "")
    if unit.startswith("/") and f"{unit[1:]}チーム中{big}チーム" not in text:
        problems.append(f"big/unit: {big}{unit} に当たる「{unit[1:]}チーム中{big}チーム」が材料に無い")
    if unit.startswith("対") and f"{big}{unit}" not in text:
        problems.append(f"big/unit: {big}{unit} が材料に無い")
    # 札の年は「2017年」の形で材料にあること
    for i, c in enumerate(v3.get("chips") or []):
        s = str(c.get("score") or "")
        if re.fullmatch(r"\d{4}", s) and f"{s}年" not in text:
            problems.append(f"chips[{i}].score: {s}年 が材料に無い")
    return problems
