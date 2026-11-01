#!/usr/bin/env python3
"""長編の構成表（1回目）と、その検査。**まだ本番にはつないでいない。**

なぜ要るのか:
  10/4、本人「台本だけでなく総合的な組み立てから動画制作する」「情報だけ与えて
  作る仕組みから、能動的に作る仕組みへ」→「やってみよう」。
  いまの長編は、材料を渡してAIが台本を1回で書き、画面は台詞に付けた札
  （[jp1] など）で切り替えるだけ。組み立ては台本の中に埋まっていて、
  章の区切りも、画面の型の選び分けも無い（本人「画面遷移が無さすぎる」）。

  そこで2回に分ける:
    1回目 構成表（この部品）: 章立て・各章の画面の型・言うこと・足りない材料の注文
    間   プログラムが注文の材料を公式APIから取る（取れなければその章を外す）
    2回目 台本: 構成表に沿って章ごとに台詞を書く

  **構成表はAIが書くが、形と中身はここで機械に確かめさせる。**画面の型・
  材料の鍵・注文の種類は、ここに書いたものしか通さない。

設計: docs/LONGFORM_PLAN_DESIGN_2026-10-05.md（PCの共有コピー）
"""

import json
import re

# 章の型。並びの決まり: 先頭は lead、最後は close。
CHAPTER_TYPES = {
    "lead": "その日いちばんの出来事を言い切る（最初の章）",
    "player": "日本人選手1人のその日の成績と場面",
    "ranking": "名前のある指標の順位（選手名と値→対象人数の中の順位→上下や1位との差）",
    "series": "ポストシーズン・進出争いの現在地",
    "compare": "2人以上の比較（同じ指標・同じ単位のときだけ）",
    "close": "締め（その日の中身を材料の数字のまま短く）",
}

# 画面の型。描画が持つ（これから作る）型だけ。新しい型はここと描画の両方に足す。
SCREENS = {
    "headline_card": "大きな見出し1つ（lead・章の頭）",
    "player_card": "選手の成績の大きな数字（打数・安打・本塁打…／投球回・被安打・自責…）",
    "ranking_table": "順位表（1位・上下の選手と値、対象の人数）",
    "compare_bar": "比較の棒（同じ単位の数字2〜4本）",
    "scoreboard": "試合・シリーズの勝敗（スコアボード型）",
    "quote": "引用（出典つき）",
    "summary": "締めの一覧（3行まで）",
}

# 足りない材料の注文。**プログラムが公式APIで取りに行ける形だけ。**
# 自由な検索はさせない（出典を確かめられない）。
REQUEST_KINDS = {
    "leaderboard": ("stat", "around"),   # 指標の順位表（around の選手の上下3人と1位）
    "game_log": ("player", "last"),      # 選手の直近N試合
    "series": ("team",),                 # PSのシリーズの全試合の結果
}

MIN_CHAPTERS, MAX_CHAPTERS = 3, 7
MAX_REQUESTS = 3
MAX_TITLE = 20
MAX_HEADLINE = 60
MAX_POINTS = 4

# 英字の人名（「Logan Henderson」）。音声はアルファベットを1文字ずつ読む。
_LATIN_NAME = re.compile(r"[A-Z][a-z]+(?:[ ・.-]+[A-Z][a-z]+)+")


PLAN_PROMPT = """あなたは、日本語のスポーツ番組（3分前後の長編）の構成作家です。
下の材料から、その日の回の**構成表**だけをJSONで書いてください。台詞は書きません。

## この番組
- MLBをある程度見ている人に向けて、その日の日本人選手の成績と、名前のある指標・
  ポストシーズンでの位置を、2人の会話で話す。**見どころが先、細部は後。**
- 材料に書いてあることだけが話の種。予想・先の話・理由の決めつけは章にしない。

## 構成の決まり
- 章は{min_ch}〜{max_ch}個。最初は "lead"（その日いちばんの出来事を1つ言い切る。
  材料に「場面」〔先制・決勝点など〕があれば、それを使う）、最後は "close"。
- 章の型（type）: {types}
- 画面の型（screen）: {screens}
- 各章の focus は、下の「画面に出せる札」の鍵（jp1・rare1 など）から1つ。lead と close は空でよい。
- title は{max_title}字以内の日本語。選手名はカタカナか漢字（英字のまま書かない）。
  見出しに読点で区切るキャッチコピーや語りかけを使わない。
- points はその章で言うことを{max_points}個まで、材料の言葉で短く。
- 材料が足りず、足せば話が良くなる所だけ requests で注文してよい（{max_req}個まで）。
  種類: {kinds}。取れなかった注文の章は、プログラムが外す。

## 出力（JSONだけ。前置き・説明・コードの囲みは書かない）
{{"headline": "…", "chapters": [{{"id": "c1", "type": "lead", "title": "…",
  "focus": "", "screen": "headline_card", "points": ["…"]}}],
  "requests": []}}

## 材料
{facts}

## 画面に出せる札
{menu}
"""


def build_prompt(facts: str, menu: str) -> str:
    return PLAN_PROMPT.format(
        min_ch=MIN_CHAPTERS, max_ch=MAX_CHAPTERS, max_title=MAX_TITLE,
        max_points=MAX_POINTS, max_req=MAX_REQUESTS, facts=facts, menu=menu,
        types="、".join(f"{k}（{v}）" for k, v in CHAPTER_TYPES.items()),
        screens="、".join(f"{k}（{v}）" for k, v in SCREENS.items()),
        kinds="、".join(f"{k}（{'・'.join(v)}）" for k, v in REQUEST_KINDS.items()))


def parse(text: str) -> dict:
    """モデルの返事から構成表を取り出す。コードの囲みが付いていても読む。"""
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("構成表のJSONがありません")
    return json.loads(s[start:end + 1])


def validate(plan: dict, panels: dict) -> list:
    """構成表の問題の一覧。空なら通す。"""
    bad = []
    if not isinstance(plan, dict):
        return ["構成表がJSONのオブジェクトではありません"]
    head = plan.get("headline")
    if not isinstance(head, str) or not head.strip():
        bad.append("headline がありません")
    elif len(head) > MAX_HEADLINE:
        bad.append(f"headline が{MAX_HEADLINE}字を超えています")
    elif _LATIN_NAME.search(head):
        bad.append(f"headline に英字の人名があります（{_LATIN_NAME.search(head).group(0)}）")
    chapters = plan.get("chapters")
    if not isinstance(chapters, list) or not (MIN_CHAPTERS <= len(chapters) <= MAX_CHAPTERS):
        bad.append(f"章は{MIN_CHAPTERS}〜{MAX_CHAPTERS}個にしてください")
        chapters = chapters if isinstance(chapters, list) else []
    seen = set()
    for i, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict):
            bad.append(f"{i}章: オブジェクトではありません")
            continue
        cid = ch.get("id") or ""
        if not cid or cid in seen:
            bad.append(f"{i}章: id が無いか重複しています")
        seen.add(cid)
        kind = ch.get("type")
        if kind not in CHAPTER_TYPES:
            bad.append(f"{i}章: type「{kind}」は使えません")
        if ch.get("screen") not in SCREENS:
            bad.append(f"{i}章: screen「{ch.get('screen')}」は使えません")
        title = ch.get("title") or ""
        if not title or len(title) > MAX_TITLE:
            bad.append(f"{i}章: title は1〜{MAX_TITLE}字にしてください")
        if _LATIN_NAME.search(title):
            bad.append(f"{i}章: title に英字の人名があります（{_LATIN_NAME.search(title).group(0)}）")
        focus = ch.get("focus") or ""
        if (focus or kind not in ("lead", "close")) and focus not in panels:
            bad.append(f"{i}章: focus「{focus}」は札にありません")
        points = ch.get("points") or []
        if not isinstance(points, list) or len(points) > MAX_POINTS \
                or not all(isinstance(p, str) and p.strip() for p in points):
            bad.append(f"{i}章: points は文字列を{MAX_POINTS}個まで")
    if chapters:
        if (chapters[0] or {}).get("type") != "lead":
            bad.append("最初の章は lead にしてください")
        if (chapters[-1] or {}).get("type") != "close":
            bad.append("最後の章は close にしてください")
    # 日本人選手の札は、どこかの章で扱う（言わない選手を材料に入れていないので）。
    used = {(ch or {}).get("focus") for ch in chapters if isinstance(ch, dict)}
    for key in panels:
        if key.startswith("jp") and key not in used:
            bad.append(f"日本人選手の札 {key}（{panels[key].get('name', '')}）を扱う章がありません")
    reqs = plan.get("requests") or []
    if not isinstance(reqs, list) or len(reqs) > MAX_REQUESTS:
        bad.append(f"requests は{MAX_REQUESTS}個まで")
        reqs = []
    for j, r in enumerate(reqs, 1):
        kind = (r or {}).get("kind")
        if kind not in REQUEST_KINDS:
            bad.append(f"注文{j}: 種類「{kind}」は取りに行けません")
            continue
        for field in REQUEST_KINDS[kind]:
            if not (r or {}).get(field):
                bad.append(f"注文{j}: {field} がありません")
    return bad


def outline(plan: dict, panels: dict) -> str:
    """2回目（台本）に渡す、構成表の読みやすい形。"""
    lines = ["## この回の構成（この順に、章ごとに話す）",
             f"いちばんの出来事: {plan.get('headline', '')}"]
    for i, ch in enumerate(plan.get("chapters") or [], 1):
        focus = ch.get("focus") or ""
        who = (panels.get(focus) or {}).get("name", "") if focus else ""
        lines.append(f"{i}. [{focus or '-'}] {ch.get('title', '')}"
                     + (f"（{who}）" if who else "")
                     + "：" + "／".join(ch.get("points") or []))
    return "\n".join(lines)
