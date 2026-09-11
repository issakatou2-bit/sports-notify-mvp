#!/usr/bin/env python3
"""選手の登録・抹消・故障者リストの出入りを、公式の記録から読む。

なぜ要るのか:
  9/10の長編で「Bassoは5日ぶりの出場、9日に復帰しての1試合目」と
  言った。**先発投手の中4日を「復帰」と呼んでいた。**
  ユーザーから「本当に何を言ってるんだ」と指摘を受けた。

  そのときの直し方は「投手には back を出さない」だった。これは
  症状を止めただけで、**打者についても同じ推測が残っている。**
  試合に出ていない日が続く理由は、故障・休養・打順から外れた・
  マイナー降格など何通りもあり、出場記録の隙間からは区別できない。

  推測をやめる。MLBは登録の動きを公式の記録として公開している。

    https://statsapi.mlb.com/api/v1/transactions?startDate=&endDate=

  実際に9/11に叩いたところ、8/25〜9/11の18日間で2410件。日本人選手に
  ついては次の4件が入っていた。

    8/25  Recalled       ホワイトソックスが西田陸浮をメジャーへ
    8/27  Status Change  ドジャースが佐々木朗希を15日故障者リストへ
    8/27  Optioned       ホワイトソックスが西田陸浮をマイナーへ
    8/28  Status Change  シャーロット（3A）が西田陸浮を出場登録

  **「5日空いた」ではなく「故障者リストから復帰した」を言える。**
  キーも登録も要らず、無料。

使い方:
  python3 scripts/mlb_transactions.py --days 21
  python3 scripts/mlb_transactions.py --out data/transactions.json
"""

import argparse
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import requests

# notability_engine はリポジトリの直下にある。
# 入れておかないと日本人選手の名簿を引けず、japanese が黙って空になる。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

API = "https://statsapi.mlb.com/api/v1/transactions"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

# メジャーの30球団のID。
#
# **記録にはマイナーの球団も入る。**「シャーロット（3A）が西田陸浮を
# 出場登録」を「メジャーに復帰」と読むと嘘になる。8/28の記録が
# まさにそれで、実際には8/27にマイナーへ降格した翌日の話だった。
MAJOR_TEAM_IDS = frozenset({
    108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121,
    133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146,
    147, 158,
})

# 故障者リストへ入ったことを表す言い方。
#
# typeDesc は "Status Change" でひとまとめなので、説明の文を見る。
# 公式の文は定型で、"placed ... on the 15-day injured list" の形。
TO_IL = ("on the 7-day injured list", "on the 10-day injured list",
         "on the 15-day injured list", "on the 60-day injured list",
         "on the paternity list", "on the bereavement list",
         "on the restricted list", "on the family medical emergency list")

# 復帰を表す言い方。
FROM_IL = ("activated",)

# 何日前までの記録を見るか。
#
# 復帰の話は「何日ぶり」を言うためのものなので、長く遡る意味がない。
# 3週間あれば、10日・15日の故障者リストは両方入る。
DEFAULT_DAYS = 21


def fetch(start: str, end: str, timeout: int = 30) -> list:
    """その期間の登録の動き。取れなければ空。"""
    try:
        r = requests.get(API, params={"startDate": start, "endDate": end},
                         headers=UA, timeout=timeout)
        r.raise_for_status()
        return r.json().get("transactions") or []
    except Exception as e:                              # noqa: BLE001
        print(f"[warn] 登録の記録を取れません: {e}", file=sys.stderr)
        return []


def _is_major(t: dict) -> bool:
    """メジャー球団の動きか。マイナー同士の動きは見ない。"""
    for key in ("toTeam", "fromTeam"):
        tid = (t.get(key) or {}).get("id")
        if tid in MAJOR_TEAM_IDS:
            return True
    return False


def classify(t: dict) -> str:
    """その記録が何か。分からないものは空。

    見るのは4つだけ。
      to_il     故障者リストへ入った
      from_il   故障者リストから復帰した
      up        マイナーからメジャーへ
      down      メジャーからマイナーへ
    """
    desc = (t.get("description") or "").lower()
    kind = (t.get("typeDesc") or "")
    if kind == "Recalled" or "selected the contract" in desc:
        return "up"
    if kind == "Optioned" or "outrighted" in desc:
        return "down"
    if any(w in desc for w in TO_IL):
        return "to_il"
    if any(desc.startswith(w) or (" " + w) in desc for w in FROM_IL):
        # 「シャーロットが出場登録」はマイナーでの復帰。
        # メジャー球団が出場登録した場合だけを復帰として扱う。
        to_id = (t.get("toTeam") or {}).get("id")
        return "from_il" if to_id in MAJOR_TEAM_IDS else ""
    return ""


def build(rows: list) -> dict:
    """選手ごとの、いちばん新しい動き。

    返すのは {player_id: {"kind": ..., "date": ..., "text": ...}}。
    **同じ選手に複数の記録がある日は、日付が新しいほうを残す。**
    8/27に降格して8/28に別の球団で登録された選手がいる。
    """
    out = {}
    for t in sorted(rows, key=lambda x: (x.get("effectiveDate")
                                         or x.get("date") or "")):
        if not _is_major(t):
            continue
        kind = classify(t)
        if not kind:
            continue
        pid = str((t.get("person") or {}).get("id") or "")
        if not pid:
            continue
        out[pid] = {
            "kind": kind,
            "date": t.get("effectiveDate") or t.get("date") or "",
            "name_en": (t.get("person") or {}).get("fullName") or "",
            "team": (t.get("toTeam") or {}).get("name") or "",
            "text": (t.get("description") or "")[:200],
        }
    return out


# 復帰から何日目までを「復帰明け」として扱うか。
#
# 復帰した当日と翌日は、その選手にとってその話が主題になる。
# それ以降は、復帰したこと自体はもう話題ではない。
BACK_WITHIN_DAYS = 3


def came_back(data: dict, player_id: str, on: str = "") -> dict:
    """その選手が、直前に故障者リストから復帰していたか。

    **推測しない。**公式が「activated」と記録した日だけを見る。
    記録が無ければ空を返す（「復帰ではない」ではなく「そうは
    言えない」）。

    on はその試合の日（省略すると今日）。
    """
    x = (data.get("players") or {}).get(str(player_id))
    if not x or x.get("kind") != "from_il":
        return {}
    try:
        back = datetime.strptime(x["date"][:10], "%Y-%m-%d").date()
        day = (datetime.strptime(on[:10], "%Y-%m-%d").date() if on
               else date.today())
    except (ValueError, TypeError, KeyError):
        return {}
    gap = (day - back).days
    if gap < 0 or gap > BACK_WITHIN_DAYS:
        return {}
    return {"date": x["date"], "days_since": gap, "text": x["text"],
            "name_en": x.get("name_en", "")}


def on_il(data: dict, player_id: str) -> dict:
    """その選手が、いま故障者リストに入っているか。"""
    x = (data.get("players") or {}).get(str(player_id))
    if not x or x.get("kind") != "to_il":
        return {}
    return {"date": x["date"], "text": x["text"]}


def load(path: str = "data/transactions.json") -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def summary(data: dict, limit: int = 12) -> str:
    lines = ["## 登録の動き（メジャー30球団）", ""]
    players = data.get("players") or {}
    if not players:
        lines.append("取れませんでした。**この日は誰の復帰も主張しません。**")
        return "\n".join(lines)

    label = {"to_il": "故障者リストへ", "from_il": "復帰",
             "up": "メジャー昇格", "down": "マイナー降格"}
    jp = data.get("japanese") or {}
    if jp:
        lines.append("### 日本人選手")
        for pid, x in sorted(jp.items(), key=lambda kv: kv[1]["date"],
                             reverse=True):
            lines.append("- %s **%s** %s … %s"
                         % (x["date"], x.get("name_jp") or x["name_en"],
                            label.get(x["kind"], x["kind"]), x["text"]))
        lines.append("")

    counts = {}
    for x in players.values():
        counts[x["kind"]] = counts.get(x["kind"], 0) + 1
    lines.append("### 全体")
    lines.append("　".join("%s %d人" % (label.get(k, k), v)
                           for k, v in sorted(counts.items())))
    backs = [x for x in players.values() if x["kind"] == "from_il"]
    if backs:
        lines.append("")
        lines.append("復帰した選手（新しい順に%d人まで）:" % limit)
        for x in sorted(backs, key=lambda y: y["date"], reverse=True)[:limit]:
            lines.append("- %s %s（%s）" % (x["date"], x["name_en"], x["team"]))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--out", default="data/transactions.json")
    args = ap.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days)
    rows = fetch(start.isoformat(), end.isoformat())
    print(f"[info] {start}〜{end} の記録: {len(rows)}件")
    players = build(rows)
    print(f"[info] メジャーの登録の動き: {len(players)}人")

    # 日本人選手ぶんは別に取り出しておく。読む側が毎回名簿を
    # 引き直さずに済む。
    jp = {}
    try:
        from notability_engine import JP_PLAYERS_MLB
        by_en = {p["name_en"]: p["name_jp"] for p in JP_PLAYERS_MLB}
        for pid, x in players.items():
            if x.get("name_en") in by_en:
                jp[pid] = {**x, "name_jp": by_en[x["name_en"]]}
    except ImportError:
        pass

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "players": players,
        "japanese": jp,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print()
    print(summary(data))
    print(f"\n[done] {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
