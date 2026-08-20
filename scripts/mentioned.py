#!/usr/bin/env python3
"""
ファンのコメントに出てくる選手名を拾って、その日の成績と繋ぐ。

なぜ要るのか:
  コメント欄の回は、訳した一言を並べるだけだった。
  ところが実際のコメントを読むと、ファンは選手の名前を挙げている:

    「Sanchezが今日の負けの唯一の理由だ」
    「Peteのヒットはひどい審判なら明らかにファウルだ」

  その選手がその日どうだったかは、こちらが既に持っている。
  言葉の隣に数字を置けば、怒っているのか称えているのかが
  数字の側からも見える。訳文だけでは分からなかったことが分かる。

  こちらの評価は書かない。コメントはコメント、成績は成績として
  並べるだけで、繋げて何かを言うことはしない。

照合について:
  コメントに出るのは姓か愛称("Sanchez" "Pete" "PCA")で、
  フルネームで書く人はまずいない。姓で引き、それでも複数当たる
  ときは諦める(誰のことか決められないなら、出さない方がよい)。

使い方(他のスクリプトから):
  import mentioned
  mentioned.find("Sanchez is the only reason we lost today")
  -> [{"name": "...", "line": "...", "team": "..."}]
"""

import functools
import json
import pathlib
import re

BEST = "data/best_of_day.json"

# 選手名として拾わない語。大文字で始まるが人名ではないもの。
STOP = {
    "The", "This", "That", "They", "There", "Then", "These", "Those",
    "What", "When", "Where", "Why", "How", "Who", "Which",
    "And", "But", "For", "Not", "All", "Just", "Also", "Now", "Still",
    "MLB", "AL", "NL", "ERA", "OPS", "RBI", "HR", "WS", "MVP",
    "Game", "Series", "Inning", "Ump", "Umpire", "Yankees", "Dodgers",
    "Cubs", "Mets", "Sox", "Jays", "Rays", "Angels", "Astros", "Braves",
    "Giants", "Padres", "Phillies", "Pirates", "Royals", "Tigers",
    "Twins", "Reds", "Marlins", "Nationals", "Orioles", "Guardians",
    "Rangers", "Mariners", "Athletics", "Brewers", "Cardinals",
    "Rockies", "Diamondbacks", "Yankee", "Prayers", "Thank", "Congrats",
    "I", "We", "You", "He", "She", "It", "My", "His", "Her", "Our",
}


@functools.lru_cache(maxsize=1)
def _roster(path: str = BEST) -> tuple:
    """
    その日出た全員。(姓 -> [選手...], 名前そのもの -> 選手) を返す。

    姓が同じ選手が複数いたら、その姓は使わない。誰のことか
    決められないまま片方の成績を出すと、そのまま嘘になる。
    """
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    by_last, by_full = {}, {}
    for row in d.get("everyone") or []:
        name = row.get("name") or ""
        if not name:
            continue
        by_full[name] = row
        parts = [x for x in name.replace(".", "").split()
                 if x not in ("Jr", "Sr", "II", "III", "IV")]
        if len(parts) >= 2:
            by_last.setdefault(parts[-1], []).append(row)
    # 同姓が2人以上いる姓は落とす
    by_last = {k: v[0] for k, v in by_last.items() if len(v) == 1}
    return by_last, by_full


def find(text: str, limit: int = 2) -> list:
    """
    その文に出てくる選手を、その日の成績つきで返す。

    英語の原文に対して使う。訳文は表記が揺れるので見ない。
    """
    if not text:
        return []
    by_last, by_full = _roster()
    if not by_last:
        return []
    out, seen = [], set()
    for word in re.findall(r"\b[A-Z][a-zA-Z'\-]{2,}\b", text):
        if word in STOP or word in seen:
            continue
        hit = by_last.get(word)
        if hit:
            seen.add(word)
            out.append(hit)
            if len(out) >= limit:
                break
    return out
