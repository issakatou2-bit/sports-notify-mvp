#!/usr/bin/env python3
"""
コレスポが取り上げた試合が、実際どうなってきたかを数える。

なぜ「予想」にしないのか:
  結果を当てにいくと、外れた日に他の全部の信頼まで落ちる。
  このチャンネルは「数えたことしか言わない」で立っているので、
  そこを崩す価値は無い。

  代わりに、同じ材料で言えることがある。毎日理由つきで試合を選び、
  結果まで記録し続けているので、「その条件の試合は、これまでどうだったか」
  を数えられる。これは予測ではなく、こちらの記録の集計にすぎない。

  見る人にとっての意味はほとんど同じで、しかも外れようがない。
  「ホームが勝ちます」ではなく「これまで62試合中36試合、58%でホームが
  勝っています」と言う。判断は見る人がする。

件数が少ないうちは何も言わない:
  3試合の平均を「この球場は打高」と読ませるのは、数字を装った印象論になる。
  必ず母数を添え、下限を下回るものは出さない。

出力: data/base_rates.json

使い方:
  python3 scripts/base_rates.py --archive-dir archive --out data/base_rates.json
"""

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import is_soccer_league  # noqa: E402

# これを下回る母数では何も言わない。
#
# 5にしているのは、3試合だと1試合の大差でひっくり返るため。
# 5試合でも十分ではないが、母数を必ず添えるので読む側が割り引ける。
MIN_SAMPLE = 5


def load_finished(archive_dir: pathlib.Path, sport: str = "mlb") -> list:
    """結果まで記録されている、取り上げた試合だけを返す。"""
    out = []
    for f in sorted(archive_dir.glob("????-??-??.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for g in data.get("games", []):
            if not g.get("is_notable"):
                continue
            soccer = is_soccer_league(g.get("league"))
            if (soccer if sport == "soccer" else not soccer) is False:
                continue
            fs = g.get("final_score") or {}
            if fs.get("winner"):
                out.append((f.name[:10], g, fs))
    return out


def _totals(rows: list) -> dict:
    if len(rows) < MIN_SAMPLE:
        return {}
    home = sum(1 for _, _, fs in rows if fs["winner"] == "home")
    draw = sum(1 for _, _, fs in rows if fs["winner"] == "draw")
    scores = [(fs.get("home") or 0) + (fs.get("away") or 0) for _, _, fs in rows]
    one = sum(1 for _, _, fs in rows
              if abs((fs.get("home") or 0) - (fs.get("away") or 0)) == 1)
    shut = sum(1 for _, _, fs in rows
               if min(fs.get("home") or 0, fs.get("away") or 0) == 0)
    return {
        "games": len(rows),
        "home_wins": home,
        "draws": draw,
        "away_wins": len(rows) - home - draw,
        "home_win_pct": round(100 * home / len(rows)),
        "avg_total": round(sum(scores) / len(scores), 1),
        "one_run": one,
        "one_run_pct": round(100 * one / len(rows)),
        "shutouts": shut,
        "shutout_pct": round(100 * shut / len(rows)),
    }


def build(archive_dir: pathlib.Path, sport: str = "mlb") -> dict:
    rows = load_finished(archive_dir, sport)

    venues = collections.defaultdict(list)
    for day, g, fs in rows:
        # 表記が2つある球場があるので、日本語名に寄せてから数える
        # (「Chase Field」と「チェイス・フィールド」が別々に溜まっていた)。
        name = g.get("venue_jp") or g.get("venue_name")
        if name:
            venues[name].append((day, g, fs))

    venue_out = {}
    for name, xs in venues.items():
        t = _totals(xs)
        if t:
            venue_out[name] = {"games": t["games"], "avg_total": t["avg_total"]}

    return {
        "sport": sport,
        "overall": _totals(rows),
        "same_division": _totals([r for r in rows if r[1].get("same_division")]),
        "venues": dict(sorted(venue_out.items(),
                              key=lambda kv: -kv[1]["avg_total"])),
        "min_sample": MIN_SAMPLE,
    }


def venue_line(data: dict, venue: str) -> str:
    """
    その球場について言えること。母数が足りなければ空。

    必ず件数を添える。「平均13.4得点」だけだと、5試合の平均なのか
    500試合の平均なのか分からず、読む側が割り引けない。
    """
    v = (data.get("venues") or {}).get(venue)
    if not v:
        return ""
    return (f"コレスポがこの球場で取り上げた{v['games']}試合は、"
            f"平均{v['avg_total']}得点でした")


def overall_lines(data: dict) -> list:
    """答え合わせ用の行。(値, 説明) の並び。"""
    o = data.get("overall") or {}
    if not o:
        return []
    lines = [(f"{o['home_win_pct']}%",
              f"取り上げた{o['games']}試合でのホーム勝率")]
    if o.get("one_run"):
        lines.append((f"{o['one_run_pct']}%", "1点差で決まった割合"))
    if o.get("shutouts"):
        lines.append((f"{o['shutout_pct']}%", "完封で決まった割合"))
    lines.append((f"{o['avg_total']}", "1試合の平均得点"))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive-dir", default="archive")
    ap.add_argument("--out", default="data/base_rates.json")
    ap.add_argument("--sport", default="mlb", choices=["mlb", "soccer"])
    args = ap.parse_args()

    data = build(pathlib.Path(args.archive_dir), args.sport)
    o = data.get("overall") or {}
    if not o:
        print(f"[info] 結果つきの試合が{MIN_SAMPLE}件に満たないため、"
              "まだ何も言えません")
    else:
        print(f"[info] {o['games']}試合を集計しました "
              f"(ホーム勝率{o['home_win_pct']}%、平均{o['avg_total']}得点)")
        for name, v in list((data.get("venues") or {}).items())[:5]:
            print(f"       {name}: {v['games']}試合 平均{v['avg_total']}得点")

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    print(f"[info] 書き出しました -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
