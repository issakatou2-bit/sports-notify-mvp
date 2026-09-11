#!/usr/bin/env python3
"""サッカーの日本人選手が、いま出られる状態にあるか。

なぜ要るのか:
  題に「ブライトンの試合、三笘薫が所属」と出していた。ところが
  **三笘薫は今季まだ1分も出ていない。**ハムストリングの怪我で、
  復帰見込みは10月10日（プレミアリーグ公式の公表）。

  9/11にユーザーから、MLBについて同じ指摘を受けた。「明日今井達也が
  先発するわけでもないのにタイトルにそう書くのは釣り感がある」。
  サッカーは**もっと悪い**。投げない日があるのではなく、
  1か月以上出られないと公表されている選手を題に出していた。

  MLBは先発ローテを読んで外した。サッカーは推測が要らない。
  **プレミアリーグの公式が、怪我と復帰見込みを数字で公表している。**

どこから取るか:
  https://fantasy.premierleague.com/api/bootstrap-static/

  プレミアリーグ公式のファンタジー用のデータ。キーも登録も要らず、
  1回の呼び出しで全20クラブ655選手ぶんが返る。
  ファンタジー向けだが**中身は公式の登録・出場・故障情報**で、
  クラブが発表したものがそのまま入る。

    minutes                        今季の出場時間
    goals_scored / assists         得点・アシスト
    chance_of_playing_next_round   次節に出られる見込み(%)
    news                           "Hamstring injury - Expected back 10 Oct"

  football-data.org の無料枠には個人成績が無い。**ここにはある。**
  プレミアだけだが、日本人選手41人のうち6人がプレミアにいる。

何を返すか:
  「出られない」と分かった選手だけを止める。**分からない選手は
  止めない。**取得に失敗した日に全員を外すと、その日は日本人選手の
  名前が題から丸ごと消える。実測では題に名前がある動画が
  平均290再生、無い動画が171再生。黙って半分にしてはいけない。

使い方:
  python3 scripts/soccer_availability.py --out data/soccer_availability.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:
    from notability_engine import JP_PLAYERS_SOCCER
except ImportError:                                     # pragma: no cover
    JP_PLAYERS_SOCCER = []

API = "https://fantasy.premierleague.com/api/bootstrap-static/"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

# 「出られない」と判断する見込みの割合。
#
# 公式は 0 / 25 / 50 / 75 / 100 で出す。0%は出ない、25%は微妙。
# **題に出すかどうかの判断なので、0%だけを止める。**
# 25%を止めると、復帰間近の選手を逃す（そこはいちばん見たい日）。
OUT_BELOW = 25

# 出場時間がこれ未満で、かつ節が進んでいるなら「まだ出ていない」。
#
# 怪我の発表が無くても、実際に出ていない選手はいる（構想外、
# 移籍直後の登録待ちなど）。公式が理由を書かない場合もあるので、
# 出場時間そのものも見る。
NO_MINUTES = 1


def fetch(timeout: int = 25) -> list:
    """プレミアリーグの全選手。取れなければ空。"""
    try:
        r = requests.get(API, headers=UA, timeout=timeout)
        r.raise_for_status()
        return r.json().get("elements") or []
    except Exception as e:                              # noqa: BLE001
        print(f"[warn] プレミアリーグの情報を取れません: {e}", file=sys.stderr)
        return []


def _surname(name_en: str) -> str:
    return (name_en or "").split()[-1]


def build(elements: list) -> dict:
    """日本人選手の、いまの状態。

    突き合わせは姓で行う。公式の web_name は "Mitoma" のように
    姓だけのことが多い。名簿の name_en は "Kaoru Mitoma"。
    """
    by_surname = {}
    for e in elements:
        for key in (e.get("web_name"), e.get("second_name")):
            if key:
                by_surname.setdefault(key.strip(), e)

    out = {}
    for p in JP_PLAYERS_SOCCER:
        if p.get("league") != "PL":
            continue
        sur = _surname(p.get("name_en", ""))
        e = by_surname.get(sur)
        if not e:
            continue
        minutes = e.get("minutes") or 0
        chance = e.get("chance_of_playing_next_round")
        news = (e.get("news") or "").strip()
        # 「出られない」と言い切れるのは、公式が0%と書いた場合か、
        # 怪我の発表があって一度も出ていない場合。
        out_of_action = False
        reason = ""
        if chance is not None and chance < OUT_BELOW:
            out_of_action = True
            reason = news or "出場の見込みなし（公式発表）"
        elif news and minutes < NO_MINUTES:
            out_of_action = True
            reason = news
        out[p["name_jp"]] = {
            "name_en": p.get("name_en"),
            "club_jp": p.get("team_jp"),
            "minutes": minutes,
            "goals": e.get("goals_scored") or 0,
            "assists": e.get("assists") or 0,
            "chance_next": chance,
            "news": news,
            "out": out_of_action,
            "reason": reason,
        }
    return out


def unavailable(data: dict) -> set:
    """いま出られない選手の名前。

    **分からない選手は入れない。**取得に失敗した日は空になり、
    誰も止まらない（黙って名前を消さないため）。
    """
    return {name for name, x in (data.get("players") or {}).items()
            if x.get("out")}


def load(path: str = "data/soccer_availability.json") -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def summary(data: dict) -> str:
    lines = ["## サッカー 日本人選手の出場状況（プレミアリーグ）", ""]
    players = data.get("players") or {}
    if not players:
        lines.append("取れませんでした。**この日は誰も題から外しません。**")
        return "\n".join(lines)
    for name, x in sorted(players.items(), key=lambda kv: -kv[1]["minutes"]):
        mark = "**出られません**" if x["out"] else "出場可"
        line = ("- %s（%s）出場%d分 得点%d アシスト%d … %s"
                % (name, x["club_jp"], x["minutes"], x["goals"],
                   x["assists"], mark))
        if x.get("reason"):
            line += "\n  - %s" % x["reason"]
        lines.append(line)
    out = unavailable(data)
    lines.append("")
    lines.append("題から外す選手: %s" % ("、".join(sorted(out)) or "なし"))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/soccer_availability.json")
    args = ap.parse_args()

    els = fetch()
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": API,
        "players": build(els) if els else {},
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(summary(data))
    print(f"\n[done] {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
