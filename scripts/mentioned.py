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
import sys

# 直下の notability_engine を読むので、経路を通す。
# 通していないと、scripts/ だけを sys.path に持つ呼び出し方
# （python scripts/local_voices.py など）で落ちる。
# 実際それでコメント欄の動画が3日止まったことがある。
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

import textkey

BEST = "data/best_of_day.json"
ROSTER = "data/roster_stats.json"

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
    # 姓と同じ綴りの普通の単語。大文字小文字を見なくしたぶん拾う。
    "Judge", "Price", "May", "Wood", "Bell", "Long", "Young", "Short",
    "Strong", "Hill", "Field", "Park", "Green", "White", "Brown", "Black",
    "Gray", "Best", "Love", "Story", "March", "Snow", "Win", "Call",
    "Hand", "Head", "Back", "Free", "Real", "Rich", "Wise", "Sharp",
    "Swift", "Beat", "Close", "Cross", "Hard", "Home", "Last", "Left",
    "Right", "Over", "Under", "Down", "Away", "Even", "Ever", "Every",
    "Much", "Many", "More", "Most", "Some", "Such", "Than", "Them", "Time",
    "Very", "Well", "Were", "Will", "With", "Would", "Your", "Been",
    "Come", "Does", "From", "Have", "Here", "Into", "Like", "Look", "Made",
    "Make", "Only", "Said", "Same", "Says", "Take", "Tell", "Their",
    "Think", "Want", "Went", "Good", "Great", "Better", "Nice", "Sure",
    "Feel", "Know", "Got",
}


# 正規化は textkey に1本化してある。名前を辞書のキーにするときは
# 必ずそこを通す。ここで独自に書くと、また綴り違いで割れる。
fold = textkey.fold
_surname = textkey.surname


@functools.lru_cache(maxsize=1)
def _roster(best: str = BEST, roster: str = ROSTER) -> tuple:
    """
    照合に使う選手表。(姓 -> 選手, 名前そのもの -> 選手) を返す。

    2つを重ねる:
      1. その日出た全員(best_of_day)      … その日の成績
      2. その試合の両チームの在籍(roster) … 今季の成績

    2が要るのは、コメントに出る名前が出場者とは限らないため。
    「Sanchezのために祈る。降格するから」「10回にDiazを出さなくて
    済んだ」——どちらも出ていない選手の話で、1だけでは何とも繋がらない。
    名前が挙がるのは所属しているからで、出場したからではない。

    その日出た選手が先。同じ選手なら、今季の平均より今日の内容の方が
    コメントの文脈に近い。

    姓が複数の選手に当たるときは、その姓を捨てる。誰のことか
    決められないまま片方の成績を出すと、そのまま嘘になる。
    """
    rows = []
    try:
        d = json.loads(pathlib.Path(best).read_text(encoding="utf-8"))
        rows += [{**r, "when": "today"} for r in (d.get("everyone") or [])]
    except (OSError, json.JSONDecodeError):
        pass
    try:
        d = json.loads(pathlib.Path(roster).read_text(encoding="utf-8"))
        rows += [{**r, "when": "season"} for r in (d.get("players") or [])]
        # リーグ全体の名簿。成績は無いが、誰なのかは決められる。
        #
        # 「10回にDiazを出さなくて済んだ」の Diaz は、コメントが付いていた
        # 8球団のどこにもいなかった。リーグ全体で見ると1人だけで、
        # 姓から一意に決まる。成績が無くても、所属は書ける。
        rows += [{**r, "when": "league", "line": "", "type": ""}
                 for r in (d.get("league") or [])]
    except (OSError, json.JSONDecodeError):
        pass

    by_last, by_full = {}, {}
    for row in rows:
        name = row.get("name") or ""
        if not name:
            continue
        by_full.setdefault(name, row)
        last = _surname(name)
        if last:
            by_last.setdefault(last, [])
            # 同じ選手が複数の表に載る。先に入れた方(その日の成績)を残す。
            if not any(x["name"] == name for x in by_last[last]):
                by_last[last].append(row)
    by_last = {k: v[0] for k, v in by_last.items() if len(v) == 1}
    return by_last, by_full


def find(text: str, limit: int = 2) -> list:
    """
    その文に出てくる選手を、成績つきで返す。

    英語の原文に対して使う。訳文は表記が揺れるので見ない。

    大文字小文字は見ない。ファンは気にせず書く。実際
    "thank goodness they didnt call up diaz in the 10th" は
    全部小文字で、大文字始まりだけを拾っていたら1件も当たらなかった。

    そのぶん、姓と同じ綴りの普通の単語(judge, price, may, wood)を
    拾うようになるので STOP で弾く。名簿の綴りと完全に一致する語だけを
    見るので、それ以外は元から当たらない。
    """
    if not text:
        return []
    by_last, _by_full = _roster()
    if not by_last:
        return []
    lower = {fold(k).lower(): v for k, v in by_last.items()}
    stop = {x.lower() for x in STOP}
    out, seen = [], set()
    for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text):
        key = fold(word).lower()
        if key in stop or key in seen:
            continue
        hit = lower.get(key)
        if hit:
            seen.add(key)
            # 成績が無い選手は出さない。
            #
            # リーグ全体の名簿は「誰なのか」を決めるために要る。
            # 同じ姓が2人いれば捨てる、という判定は、その2人が
            # どの球団にいようと効かないと意味が無いので、
            # 名寄せは全体で行う。ただし名前と所属だけを画面に出しても
            # 「なぜこの人が出てくるのか」になるだけなので、
            # 成績のある選手に限って返す。
            if hit.get("line"):
                out.append(hit)
                if len(out) >= limit:
                    break
    return out


def japanese_in(text: str) -> list:
    """その文に出てくる**日本人選手**の英語名。

    mentioned.find は MLB全体の名簿(best_of_day / roster_stats)を
    見るので、Tarik Skubal も返す。題やサムネイルに
    「日本人選手の名前」を出したいときは、これを使う。
    実際 mlb_buzz の並べ替えで Skubal を日本人扱いしかけた。

    姓だけでも当てる。動画の題は "Shohei Ohtani" とフルネームだが、
    コメントは "Ohtani" とだけ書かれることが多い。
    """
    if not text:
        return []
    try:
        from notability_engine import JP_PLAYERS_MLB
    except Exception:                            # noqa: BLE001
        return []
    low = str(text).lower()
    out = []
    for p in JP_PLAYERS_MLB:
        en = p.get("name_en") or ""
        if not en:
            continue
        last = en.split()[-1]
        if en.lower() in low or (len(last) >= 4 and last.lower() in low):
            if en not in out:
                out.append(en)
    return out
