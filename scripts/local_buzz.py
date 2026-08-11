"""
現地のコミュニティ・報道で、いま何が話題になっているかを数字で集める。

なぜこの形にするのか:
  「現地の反応」を伝えたいが、投稿の文面を翻訳して紹介するのは避ける。
  本物か・代表的かを確かめられず、翻訳の加減で印象が変わり、
  都合のいいものだけ拾えば実態と違うものになる。

  代わりに「何回名前が挙がったか」だけを数える。
  他人の文章を一切引用せず、誰でも同じ手順で再現できる数字になる。
  感想を代弁せずに、現地の関心がどこにあるかを示せる。

取得先:
  ・r/baseball … MLB全体の最大コミュニティ
  ・球団別サブレディット … 熱量はこちらが高い
  ・MLB公式 / ESPN … 報道側の関心
  いずれもRSSで、認証なしで取れる
  (RedditのJSON APIは認証が要るが、RSSは公開されている)。

出力: data/local_buzz.json

使い方:
  python3 scripts/local_buzz.py --out data/local_buzz.json
"""

import argparse
import json
import pathlib
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import (  # noqa: E402
    JP_PLAYERS_MLB,
    MLB_TEAM_NAME_EN,
    MLB_TEAM_NAME_JP,
)

UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

FEEDS = [
    ("r/baseball", "https://www.reddit.com/r/baseball/.rss"),
    ("r/mlb", "https://www.reddit.com/r/mlb/.rss"),
    ("MLB公式", "https://www.mlb.com/feeds/news/rss.xml"),
    ("ESPN", "https://www.espn.com/espn/rss/mlb/news"),
]

# 通称が2語になる球団。ここを1語(Sox / Jays)で数えると、
# レッドソックスとホワイトソックスが混ざってしまう。
# 実際に検証したとき "Sox 14回" となり、どちらの話か分からなくなった。
TWO_WORD_NICKNAMES = {"Red Sox", "White Sox", "Blue Jays"}


def nickname(full_name: str) -> str:
    parts = full_name.split()
    two = " ".join(parts[-2:])
    return two if two in TWO_WORD_NICKNAMES else parts[-1]


def city(full_name: str) -> str:
    """"Boston Red Sox" -> "Boston"。都市名だけの言及も拾うため。"""
    nick = nickname(full_name)
    return full_name[: -len(nick)].strip()


def fetch_titles(name: str, url: str, retries: int = 2) -> list:
    """
    RSSから見出しを取る。

    Redditは短時間に続けて叩くと429を返す(実際に2本目で発生した)。
    間隔を空けて数回だけ試し、それでも駄目なら諦めて次のフィードへ進む。
    1つ取れなくても、残りのフィードで話題は拾える。
    """
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if r.status_code == 429:
                if attempt < retries:
                    wait = 5 * (attempt + 1)
                    print(f"[info] {name}: 混み合っているため{wait}秒待ちます")
                    time.sleep(wait)
                    continue
                print(f"[warn] {name}: 混雑のため今回は飛ばします", file=sys.stderr)
                return []
            r.raise_for_status()
            root = ET.fromstring(r.content)
            break
        except Exception as e:
            print(f"[warn] {name} の取得に失敗しました: {e}", file=sys.stderr)
            return []
    # Atom(Reddit)とRSS2.0(MLB/ESPN)の両方に対応する
    titles = [e.text.strip() for e in root.iter()
              if e.tag.endswith("title") and e.text and e.text.strip()]
    return titles[1:]   # 先頭はフィード自体の名前


def count_mentions(text: str) -> tuple:
    """
    球団と日本人選手の言及数。長い表記から先に数え、
    数えた部分は伏せ字にして二重計上を防ぐ
    ("Boston Red Sox" を "Red Sox" と "Boston" で二度数えない)。
    """
    work = text
    teams = Counter()
    # 「都市+通称」→「通称」→「都市」の順に、長いものから消し込む
    patterns = []
    for tid, en in MLB_TEAM_NAME_EN.items():
        nick, c = nickname(en), city(en)
        patterns.append((len(en), tid, en))
        patterns.append((len(nick), tid, nick))
        if c and c not in ("New York", "Chicago", "Los Angeles"):
            # 同一都市に2球団ある場合、都市名だけでは特定できないので使わない
            patterns.append((len(c), tid, c))
    for _, tid, pat in sorted(patterns, key=lambda x: -x[0]):
        n = len(re.findall(rf"\b{re.escape(pat)}\b", work, re.I))
        if n:
            teams[tid] += n
            work = re.sub(rf"\b{re.escape(pat)}\b", "·", work, flags=re.I)

    players = Counter()
    for p in JP_PLAYERS_MLB:
        surname = p["name_en"].split()[-1]
        n = len(re.findall(rf"\b{re.escape(surname)}\b", text, re.I))
        if n:
            players[p["name_jp"]] = n
    return teams, players


def build() -> dict:
    all_titles = []
    sources = []
    for i, (name, url) in enumerate(FEEDS):
        if i:
            time.sleep(3)   # 続けて叩くと429になるので間を空ける
        titles = fetch_titles(name, url)
        if titles:
            sources.append({"name": name, "items": len(titles)})
            all_titles += titles
        print(f"[info] {name}: {len(titles)}件")

    if not all_titles:
        return {}

    teams, players = count_mentions(" ".join(all_titles))
    ranked = [{"team_id": tid, "name": MLB_TEAM_NAME_JP.get(tid, tid),
               "name_en": MLB_TEAM_NAME_EN.get(tid, ""), "mentions": n}
              for tid, n in teams.most_common(8)]

    print(f"\n[info] 集めた見出し: {len(all_titles)}件")
    print("[info] 話題になっている球団:")
    for t in ranked[:5]:
        print(f"   {t['mentions']:>3}回  {t['name']}")
    if players:
        print("[info] 日本人選手の言及:")
        for k, v in players.most_common():
            print(f"   {v:>3}回  {k}")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "titles_count": len(all_titles),
        "teams": ranked,
        "players": [{"name": k, "mentions": v} for k, v in players.most_common(6)],
    }


def load(path: str = "data/local_buzz.json", max_age_hours: int = 30) -> dict:
    """表示側から読む。古い記録は使わない。"""
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(data.get("updated_at", ""))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    if (datetime.now(timezone.utc) - updated).total_seconds() / 3600 > max_age_hours:
        print("[info] 現地の話題データが古いため使いません")
        return {}
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/local_buzz.json")
    args = parser.parse_args()

    data = build()
    if not data:
        print("[info] 取得できなかったため、ファイルは更新しません")
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[info] 現地の話題を出力しました -> {out}")


if __name__ == "__main__":
    main()
