#!/usr/bin/env python3
"""
タイトルと説明文が、その動画の中身と合っているかを見る。

なぜ要るのか:
  タイトルは upload_youtube.py、原稿は generate_narration.py と
  generate_morning_short.py、画面はまた別のファイルが作っている。
  同じ材料から作ってはいるが、選び方がそれぞれにある。

  実際に起きた食い違い:
    ・声を4つ読むのに画面は別の3つを出していた
    ・1枚目の帯と読み上げが別の見出しを指していた
    ・在籍しているだけの投手を「対決」と紹介した
    ・タイトルの選手名が動画の中に出てこなかった

  どれも「その回の主役が1つに決まっていない」という同じ形をしている。
  ここでは、タイトルに出した固有名詞が中身にも出てくるかを見る。

使い方:
  python3 scripts/test_title_matches.py
"""

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import upload_youtube as uy  # noqa: E402

fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok' if ok else 'NG'}  {label}: {got}")


def load(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def names_in(title: str) -> list:
    """タイトルから固有名詞を拾う。【】と区切りを外して見る。"""
    body = re.sub(r"【[^】]*】", "", title)
    body = body.replace("#Shorts", "")
    return [x.strip() for x in re.split(r"[｜|/、]", body) if x.strip()]


def main() -> int:
    prof = load("data/player_profile.json")

    print("--- 今日の1人 ---")
    meta = uy.build_metadata("notable_games.json", "8月20日", "morning",
                             morning_mode="player")["snippet"]
    title, desc = meta["title"], meta["description"]
    if prof.get("name"):
        check("タイトルに選手名が入っている", prof["name"] in title)
        check("説明文にも同じ選手名", prof["name"] in desc)
        check("タグに選手名", prof["name"] in meta["tags"])
    # 今季の数字を書くなら、いつ時点かも書く
    if "今シーズン" in title:
        check("今季の数字には時点が添えてある",
              "時点" in title)

    print("\n--- コメント欄 ---")
    vmeta = uy.build_metadata("notable_games.json", "8月20日", "morning",
                              morning_mode="voices")["snippet"]
    top = uy.buzz_top("data/mlb_buzz.json") or {}
    if top.get("matchup_jp"):
        # タイトルの対戦カードが、材料の試合と同じか
        card = top["matchup_jp"].split(" vs ")
        check("タイトルの対戦が、扱った試合と同じ",
              all(c in vmeta["title"] for c in card))
        check("タグにも同じ球団",
              all(c in vmeta["tags"] for c in card))

    print("\n--- 明日の注目試合 ---")
    dmeta = uy.build_metadata("notable_games.json", "8月20日",
                              "daily")["snippet"]
    games = (load("notable_games.json").get("games") or [])
    notable = [g for g in games if g.get("is_notable")][:3]
    if notable:
        # タイトルに出した対戦が、実際に扱う3試合のどれかであること
        parts = names_in(dmeta["title"])
        cards = [g.get("matchup") or "" for g in notable]
        hit = any(any(p in c or c in p for c in cards) for p in parts)
        check("タイトルの対戦が、紹介する試合に含まれる", hit)

    print("\n--- どの回も共通 ---")
    for kind, mode in (("morning", "players"), ("morning", "voices"),
                       ("morning", "local"), ("morning", "press"),
                       ("daily", None)):
        m = uy.build_metadata("notable_games.json", "8月20日", kind,
                              morning_mode=mode)["snippet"]
        label = f"{kind}/{mode}"
        if len(m["title"]) > 100:
            check(f"{label} タイトルが100字以内", False)
        if len(m["description"]) > 5000:
            check(f"{label} 説明文が5000字以内", False)
    check("タイトルと説明文の長さ", True)

    print("\nALL OK" if not fails else f"\n{fails} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
