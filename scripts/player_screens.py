#!/usr/bin/env python3
"""
「今日の1人」の画面と読み上げ原稿。

generate_morning_short.py から使う。描画の道具(フォント・カード・
目盛り)はあちらに揃っているので、そこを借りて中身だけをここに書く。

何を書き、何を書かないか:
  数字と事実はMLB公式APIから引いたものだけ。
  「人となり」「評判」はAPIに無いので、こちらからは一切書かない。
  現地の番記者とファンが実際に書いた言葉を、出典つきでそのまま引く。
  扱うのは「そう言った人がいる」という事実だけで、その中身に
  こちらが同意も反論もしない。
"""

import generate_morning_short as ms
import post_common
from generate_narration import speech_name


def _hitting_line(s: dict) -> str:
    """打者の1行。数字が無い項目は出さない。"""
    if not s:
        return ""
    bits = [f"{s.get('games')}試合", f"打率{s.get('avg')}"]
    if s.get("hr"):
        bits.append(f"{s['hr']}本塁打")
    if s.get("rbi"):
        bits.append(f"{s['rbi']}打点")
    if s.get("ops"):
        bits.append(f"OPS{s['ops']}")
    # 盗塁は、走る選手のときだけ出す。1桁の選手まで並べると、
    # どの行にも同じ項目が並んで、その選手の特徴が見えなくなる。
    # 30本塁打30盗塁と書いた隣に盗塁数が無いのも、辻褄が合わない。
    if (s.get("sb") or 0) >= 10:
        bits.append(f"{s['sb']}盗塁")
    return "　".join(bits)


def _pitching_line(s: dict) -> str:
    if not s:
        return ""
    bits = [f"{s.get('games')}登板",
            f"{s.get('wins')}勝{s.get('losses')}敗",
            f"防御率{s.get('era')}"]
    if s.get("so"):
        bits.append(f"{s['so']}奪三振")
    return "　".join(bits)


def stat_line(prof: dict, s: dict) -> str:
    return (_pitching_line(s) if prof.get("group") == "pitching"
            else _hitting_line(s))


# 受賞名の読み。VOICEVOXは "NL All-Star" を「エヌエル、オールスター」と
# 読めず、アルファベットの1文字読みに落ちる。画面は英語のままでよいが、
# 読み上げには日本語を渡す。
AWARD_YOMI = [
    ("NL MVP", "ナ・リーグ最優秀選手"), ("AL MVP", "ア・リーグ最優秀選手"),
    ("NL Cy Young", "ナ・リーグ サイ・ヤング賞"),
    ("AL Cy Young", "ア・リーグ サイ・ヤング賞"),
    ("NL Rookie of the Year", "ナ・リーグ新人王"),
    ("AL Rookie of the Year", "ア・リーグ新人王"),
    ("NL All-Star", "ナ・リーグ オールスター"),
    ("AL All-Star", "ア・リーグ オールスター"),
    ("All-Star", "オールスター"),
    ("Silver Slugger", "シルバースラッガー賞"),
    ("Gold Glove", "ゴールドグラブ賞"),
    ("Hank Aaron Award", "ハンク・アーロン賞"),
    ("Player of the Month", "月間最優秀選手"),
    ("Pitcher of the Month", "月間最優秀投手"),
    ("Rookie of the Month", "月間最優秀新人"),
    ("Player of the Week", "週間最優秀選手"),
    ("World Series", "ワールドシリーズ"),
    ("MVP", "最優秀選手"),
]


# 守備位置。APIは英語で返す。画面も読み上げも日本語にする。
POSITION_JP = {
    "Two-Way Player": "二刀流", "Pitcher": "投手", "Catcher": "捕手",
    "First Base": "一塁手", "Second Base": "二塁手", "Third Base": "三塁手",
    "Shortstop": "遊撃手", "Outfielder": "外野手", "Left Field": "左翼手",
    "Center Field": "中堅手", "Right Field": "右翼手",
    "Designated Hitter": "指名打者", "Infielder": "内野手",
}


def position_jp(name: str) -> str:
    return POSITION_JP.get(name or "", name or "")


def award_yomi(name: str) -> str:
    """受賞名を読み上げ用に直す。当てはまらなければそのまま返す。"""
    for en, ja in AWARD_YOMI:
        if en in name:
            return ja
    return name


def yomi(text: str) -> str:
    """読み上げ用。画面の表記をそのまま読ませると崩れる箇所を直す。"""
    return ms.yomi_stats(text).replace("　", "、")


def milestone(prof: dict) -> str:
    """
    今季の到達点で、ひとことで言えるもの。無ければ空。

    30本塁打30盗塁は、走れて長打も打てる打者にしか届かない。
    通算71本塁打より、こちらの方がその選手が何者かを短く伝える。
    数えているのはAPIの数字そのもので、こちらの評価は入れない。
    """
    if prof.get("group") == "pitching":
        s = prof.get("this_season") or {}
        so = s.get("so") or 0
        if so >= 200:
            return f"今シーズン{so}奪三振"
        return ""
    s = prof.get("this_season") or {}
    hr, sb = s.get("hr") or 0, s.get("sb") or 0
    for n in (50, 40, 30, 20):
        if hr >= n and sb >= n:
            return f"今シーズン{n}本塁打{n}盗塁"
    return ""


def build_narration(prof: dict) -> dict:
    """今日の1人ぶんの原稿。画面と1対1で対応させる。"""
    name = prof.get("name", "")
    # 画面はそのままの綴りで出す。読み上げだけカタカナに替える。
    # 綴りを変えると、検索してきた人が見ている名前と違うものになる。
    said = speech_name(name)
    bio = prof.get("bio") or {}
    team = prof.get("team", "")

    # 冒頭は、その選手のいちばん大きい1つだけ。
    #
    # 最初は通算成績を丸ごと読ませていたが、次の画面で同じ文を
    # もう一度読むことになり、1枚目が目次になっていた。
    # 数字は1つに絞って、内訳は次の画面に任せる。
    career = stat_line(prof, prof.get("career") or {})
    c = prof.get("career") or {}
    if prof.get("group") == "pitching":
        big = f"通算{c['wins']}勝" if c.get("wins") else ""
    else:
        big = f"通算{c['hr']}本塁打" if c.get("hr") else ""
    # 到達点があれば、通算の数字よりそちらを先に出す。
    # 「通算71本塁打」は4年目の選手ならありふれた数字だが、
    # 「30本塁打30盗塁」は誰にでも届くものではない。
    ms_line = milestone(prof)
    if ms_line:
        big = ms_line
    aw = prof.get("awards") or []
    if not big and aw:
        big = award_yomi(aw[0]["name"])
    head = f"{said}、{team}。" + (f"{big}。" if big else "")
    segments = [{"kind": "p_intro", "text": head + "今日はこの選手です。",
                 "meta": {}}]

    if prof.get("career"):
        parts = [f"{said}の通算成績です。{yomi(career)}。"]
        if bio.get("debut"):
            parts.append(f"デビューは{bio['debut'][:4]}年。")
        segments.append({"kind": "p_career", "text": "".join(parts),
                         "meta": {}})

    this_s = stat_line(prof, prof.get("this_season") or {})
    last_s = stat_line(prof, prof.get("last_season") or {})
    if this_s or last_s:
        parts = []
        if this_s:
            parts.append(f"今シーズンは{yomi(this_s)}。")
        if last_s:
            parts.append(f"昨シーズンは{yomi(last_s)}でした。")
        if ms_line:
            parts.append(f"{ms_line}に到達しています。")
        segments.append({"kind": "p_season", "text": "".join(parts),
                         "meta": {}})

    recent = prof.get("recent") or []
    if recent:
        # 5試合すべてを読むと同じ形の文が5回続く。画面には全部出し、
        # 読み上げは直近1試合と、まとめだけにする。
        parts = [f"直近{len(recent)}試合はこうです。"
                 f"最新は{yomi(recent[0]['line'])}。"]
        segments.append({"kind": "p_recent", "text": "".join(parts),
                         "meta": {}})

    aw = prof.get("awards") or []
    if aw:
        top = aw[0]
        parts = [f"受賞歴です。{top['season']}年の{award_yomi(top['name'])}"
                 f"をはじめ、主なものが{len(aw)}件あります。"]
        segments.append({"kind": "p_awards", "text": "".join(parts),
                         "meta": {}})

    qs = prof.get("quotes") or []
    if qs:
        parts = ["現地では、こう書かれています。翻訳したもので、"
                 "コレスポの見解ではありません。"]
        for q in qs[:3]:
            parts.append(q["text"].strip().rstrip("。！!") + "。")
        segments.append({"kind": "p_quotes", "text": "".join(parts),
                         "meta": {}})

    segments.append({
        "kind": "outro",
        # この動画自体が「今日の1人」なので、そこだけ外して読む。
        "text": ("コレスポでは、"
                 + "、".join(post_common.lineup_names("morning_player"))
                 + "を毎日お届けしています。"
                 "見逃したくないかたは、チャンネル登録をお願いします。"),
        "meta": {},
    })
    return {"label": prof.get("date_jst", ""), "segments": segments}


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

def _head(d, prof, title):
    d.text((70, 70), "コレスポ", font=ms.font(46), fill=ms.ACCENT)
    d.text((70, 170), prof.get("name", ""), font=ms.font(76), fill=ms.TEXT)
    d.text((74, 268), title, font=ms.font(38), fill=ms.ACCENT)
    return 340


def render_intro(p, prof):
    im, d = ms.base(p)
    bio = prof.get("bio") or {}
    e = ms.ease_out(min(1.0, p * 2.6))
    dy = int((1 - e) * 60)

    d.text((70, 70), "コレスポ　今日の1人", font=ms.font(46), fill=ms.ACCENT)
    size = ms.fit(d, prof.get("name", ""), ms.W - 160, (128, 112, 96, 80))
    d.text((80, 360 + dy), prof.get("name", ""), font=ms.font(size),
           fill=ms.ACCENT)

    y = 360 + size + 30
    # 綴りの下にカタカナを添える。綴りを消さないのは、検索して
    # 来た人が見ている文字と揃えておくため。
    kana = speech_name(prof.get("name", "")).replace("、", "・")
    if kana and kana != prof.get("name", ""):
        d.text((84, y), kana, font=ms.font(52), fill=ms.JP)
        y += 74
    else:
        y += 30
    line = "　".join(x for x in (prof.get("team"), position_jp(bio.get("position")),
                                 f"背番号{bio['number']}" if bio.get("number")
                                 else "") if x)
    d.text((80, y), line, font=ms.font(46), fill=ms.TEXT)
    y += 100

    # なぜこの選手なのかを、いちばん目立つ形で置く。
    #
    # ここが空いていた。名前と所属だけの画面で、選ばれた理由 —— その日の
    # 成績も、今季の到達点も —— どこにも書かれていなかった。
    # 読み上げの帯に灰色で小さく出ているだけで、音を切って見ている人にも、
    # 一覧に並んだ小さなサムネを見ている人にも、何も届いていない。
    if p > 0.10:
        reach = milestone(prof)
        today = ms.topic_short(prof.get("headline") or "")
        # その日の成績を先に置く。「今日の1人」に選んだ理由そのもので、
        # 到達点(30本塁打30盗塁)は年間の話なので、下に小さく添える。
        y = ms.topic_band(d, today or reach, y,
                          note=(reach if today and reach else ""))

    # 通算をここで1つだけ大きく出す。名前だけの画面にしない。
    if p > 0.18:
        s = stat_line(prof, prof.get("career") or {})
        if s:
            y2 = max(y, 940)
            ms.card(d, 60, y2, ms.W - 60, y2 + 200, stripe=ms.JP) \
                if hasattr(ms, "card") else \
                d.rounded_rectangle([60, y2, ms.W - 60, y2 + 200], 26,
                                    fill=ms.SURF)
            d.text((100, y2 + 30), "通算", font=ms.font(36), fill=ms.DIM)
            # 1行で見せたい。折り返すと「OP / S.954」のように
            # 指標の途中で切れる。収まる大きさを実測して選ぶ。
            fs = ms.fit(d, s, ms.W - 220, (46, 42, 38, 34, 30))
            d.text((100, y2 + 90), s, font=ms.font(fs), fill=ms.TEXT)

    d.text((80, ms.H - 170), "collespo.com", font=ms.font(38), fill=ms.DIM)
    return im


def _stat_card(d, y, label, text, stripe):
    d.rounded_rectangle([60, y, ms.W - 60, y + 190], 26, fill=ms.SURF)
    d.rounded_rectangle([60, y, 76, y + 190], 8, fill=stripe)
    d.text((100, y + 24), label, font=ms.font(36), fill=ms.DIM)
    fs = ms.fit(d, text, ms.W - 220, (46, 42, 38, 34, 30))
    d.text((100, y + 84), text, font=ms.font(fs), fill=ms.TEXT)
    return y + 220


def render_career(p, prof):
    im, d = ms.base(p)
    y = _head(d, prof, "通算成績")
    bio = prof.get("bio") or {}
    y = _stat_card(d, y + 40, "通算", stat_line(prof, prof.get("career") or {}),
                   ms.ACCENT)
    rows = [("デビュー", bio.get("debut")), ("出身", bio.get("birth_city")),
            ("年齢", f"{bio['age']}歳" if bio.get("age") else None)]
    for i, (k, v) in enumerate([r for r in rows if r[1]]):
        if p < 0.12 + i * 0.08:
            continue
        d.text((100, y + 20), k, font=ms.font(36), fill=ms.DIM)
        d.text((320, y + 14), str(v), font=ms.font(46), fill=ms.TEXT)
        y += 74
    return im


def render_season(p, prof):
    im, d = ms.base(p)
    y = _head(d, prof, "今季と昨季")
    y += 40
    this_s = stat_line(prof, prof.get("this_season") or {})
    last_s = stat_line(prof, prof.get("last_season") or {})
    if this_s:
        y = _stat_card(d, y, "今シーズン", this_s, ms.ACCENT)
    reach = milestone(prof)
    if reach and p > 0.10:
        d.rounded_rectangle([60, y, ms.W - 60, y + 92], 18, fill=ms.SURF)
        d.rounded_rectangle([60, y, 68, y + 92], 4, fill=ms.ACCENT)
        d.text((100, y + 24), f"{reach}に到達", font=ms.font(44),
               fill=ms.ACCENT)
        y += 114
    if last_s and p > 0.14:
        _stat_card(d, y, "昨シーズン", last_s, ms.DIM)
    return im


def render_recent(p, prof):
    im, d = ms.base(p)
    y = _head(d, prof, f"直近{len(prof.get('recent') or [])}試合")
    y += 30
    for i, r in enumerate(prof.get("recent") or []):
        if p < 0.06 + i * 0.07:
            continue
        e = ms.ease_out(min(1.0, (p - 0.06 - i * 0.07) * 6))
        dx = int((1 - e) * 60)
        d.rounded_rectangle([60 - dx, y, ms.W - 60 - dx, y + 150], 20,
                            fill=ms.SURF)
        d.text((100 - dx, y + 22), (r.get("date") or "")[5:].replace("-", "/"),
               font=ms.font(34), fill=ms.DIM)
        d.text((100 - dx, y + 76), r.get("line", ""), font=ms.font(46),
               fill=ms.TEXT)
        y += 172
    return im


def render_awards(p, prof):
    im, d = ms.base(p)
    y = _head(d, prof, "主な受賞歴")
    y += 30
    for i, a in enumerate(prof.get("awards") or []):
        if p < 0.06 + i * 0.08:
            continue
        d.rounded_rectangle([60, y, ms.W - 60, y + 130], 20, fill=ms.SURF)
        d.rounded_rectangle([60, y, 76, y + 130], 8, fill=ms.ACCENT)
        d.text((100, y + 20), str(a.get("season", "")), font=ms.font(36),
               fill=ms.ACCENT)
        for ln in ms.wrap(d, a.get("name", ""), ms.font(42), ms.W - 220)[:1]:
            d.text((100, y + 66), ln, font=ms.font(42), fill=ms.TEXT)
        y += 152
    return im


def render_quotes(p, prof):
    """現地の言葉。数字の画面と混ざらないよう、背景を変える。"""
    im, d = ms.base(p)
    # 翻訳した誰かの言葉であることを、色でも分ける
    d.rectangle([0, 0, ms.W, ms.H - 22], fill=ms.VOICE_BG)
    ms.draw_steps(d, ms.JP)
    d.text((70, 70), "コレスポ", font=ms.font(46), fill=ms.JP)
    d.text((70, 170), prof.get("name", ""), font=ms.font(76), fill=ms.TEXT)
    d.text((74, 268), "現地では何と書かれているか", font=ms.font(38), fill=ms.JP)

    y = 360
    for i, q in enumerate(prof.get("quotes") or []):
        if p < 0.06 + i * 0.08:
            continue
        lines = ms.wrap(d, q.get("text", ""), ms.font(40), ms.W - 240)[:3]
        h = 76 + len(lines) * 54
        d.rounded_rectangle([60, y, ms.W - 60, y + h], 20, fill=(30, 25, 42))
        d.rounded_rectangle([60, y, 76, y + h], 8, fill=ms.JP)
        d.text((100, y + 18), q.get("who", ""), font=ms.font(32), fill=ms.JP)
        for j, ln in enumerate(lines):
            d.text((100, y + 62 + j * 54), ln, font=ms.font(40), fill=ms.TEXT)
        y += h + 22
    d.text((70, ms.H - 210), "※現地の投稿を翻訳したものです",
           font=ms.font(32), fill=ms.DIM)
    d.text((70, ms.H - 160), "　コレスポの見解ではありません",
           font=ms.font(32), fill=ms.DIM)
    return im


RENDERERS = {
    "p_intro": render_intro,
    "p_career": render_career,
    "p_season": render_season,
    "p_recent": render_recent,
    "p_awards": render_awards,
    "p_quotes": render_quotes,
}

# 読む量に対して要る秒数。翻訳文の画面は長めに取る。
MIN_DURATION = {"p_intro": 6.0, "p_career": 8.0, "p_season": 9.0,
                "p_recent": 9.0, "p_awards": 8.0, "p_quotes": 12.0}
