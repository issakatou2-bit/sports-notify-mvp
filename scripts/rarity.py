#!/usr/bin/env python3
"""名前のある指標で、その選手がどれだけ極端かを数える。

なぜ要るのか:
  ユーザーの構想（9/11）:「反響を狙う手段として、やはり非日常で
  あること、例えば稀な記録であるとか、それがどうすごいのかとか
  （…）村上のアダム・ダン率がアダム・ダン超えだとか、そういう、
  公式記録でなくても、心に残るとか、話題性のあるトピック」。

  実際に計算したら、そのとおりだった。

    村上宗隆 2026   486打席 31本 82四球 170三振 → 58.2%
    今季のMLB        300打席以上139人のうち **1位**
    アダム・ダン本人  最高は2012年の56.7%

  **アダム・ダン率でアダム・ダンを超えている。**公式の記録では
  ないが、元の数字は全部公式。計算するだけで出てくる。

  実測でも裏付けがある。数字が主役の枠はいちばん強く（成績
  ランキング 平均410再生・登録8人）、順位表のような「確かめたく
  なる数字」は繰り返し見られる（進出争いの視聴率208.5%）。

何を数えるか:
  「名前のある指標」だけを扱う。**野球を見ている人のあいだで
  呼び名が決まっているもの**に絞る理由は2つ。

    ・呼び名があると、それだけで「めったにない」の目印になる
    ・こちらで新しい指標を作ると、good/badの判断が入り込む

  人名が由来の指標は、その本人と比べられる。それがいちばん
  伝わる形（「アダム・ダン率でアダム・ダンを超えた」）。

どこから取るか:
  MLB Stats API だけ。呼び出しは3回で足りる。

    /stats?stats=season&group=hitting&limit=400   リーグ全体（1回）
    /people/{id}/stats?stats=season               その選手の今季
    /people/{id}/stats?stats=yearByYear           比較相手の全シーズン

  キーは要らない。無料。

使い方:
  python3 scripts/rarity.py --season 2026
  python3 scripts/rarity.py --season 2026 --out data/rarity.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import mlb_splits  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

# リーグの中で比べるための最低打席・最低回。
#
# 規定打席（502）だと9月でも届かない選手が多く、村上（486打席）も
# 入らない。**「規定」ではなく「比べても意味がある量」**で切る。
# そのぶん、画面には必ず「300打席以上◯人のうち」と書く。
MIN_PA = 300
MIN_IP = 60


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


# ---- 指標の計算 -----------------------------------------------------------
#
# **式はここにしか書かない。**画面と読み上げで別々に計算すると、
# 片方だけ古い数字が残る。成績の回で一度それをやっている。


def tto(s: dict):
    """アダム・ダン率（Three True Outcomes）。

    本塁打・四球・三振が全打席に占める割合。守備が関与しない
    3つの結果だけで打席が終わる割合、という見方。
    アダム・ダンがその代名詞になっている。
    """
    pa = _i(s.get("plateAppearances"))
    if pa < 1:
        return None
    return (_i(s.get("homeRuns")) + _i(s.get("baseOnBalls"))
            + _i(s.get("strikeOuts"))) / pa


def iso(s: dict):
    """ISO（長打率 − 打率）。単打を除いた、純粋な長打力。"""
    slg, avg = _f(s.get("slg")), _f(s.get("avg"))
    if slg is None or avg is None:
        return None
    return slg - avg


def babip(s: dict):
    """BABIP。本塁打以外の打球が安打になった割合。

    長く見れば.300前後に寄るとされ、そこから離れている選手は
    「運が向いている／向いていない」と語られる。
    """
    ab = _i(s.get("atBats"))
    hits, hr = _i(s.get("hits")), _i(s.get("homeRuns"))
    so, sf = _i(s.get("strikeOuts")), _i(s.get("sacFlies"))
    den = ab - so - hr + sf
    if den < 1:
        return None
    return (hits - hr) / den


def bb_per_k(s: dict):
    """四球 ÷ 三振。選球眼の目安。1.00を超えるのは稀。"""
    so = _i(s.get("strikeOuts"))
    if so < 1:
        return None
    return _i(s.get("baseOnBalls")) / so


def k_rate(s: dict):
    """三振率。"""
    pa = _i(s.get("plateAppearances"))
    return _i(s.get("strikeOuts")) / pa if pa else None


def bb_rate(s: dict):
    """四球率。"""
    pa = _i(s.get("plateAppearances"))
    return _i(s.get("baseOnBalls")) / pa if pa else None


def _outs(ip) -> int:
    """投球回をアウト数に。"6.1" は19アウト（6回3分の1）。"""
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole) * 3 + (int(frac[0]) if frac else 0)
    except (ValueError, TypeError):
        return 0


def k_per_9(s: dict):
    """9回あたりの奪三振。"""
    o = _outs(s.get("inningsPitched"))
    return _i(s.get("strikeOuts")) * 27 / o if o else None


def k_per_bb(s: dict):
    """奪三振 ÷ 与四球。"""
    bb = _i(s.get("baseOnBalls"))
    return _i(s.get("strikeOuts")) / bb if bb else None


def whip(s: dict):
    """1回あたりに出した走者（被安打＋与四球）。"""
    o = _outs(s.get("inningsPitched"))
    if not o:
        return None
    return (_i(s.get("hits")) + _i(s.get("baseOnBalls"))) * 3 / o


# 扱う指標。
#
#   key      … 内部の名前
#   label    … 画面に出す呼び名
#   note     … 何を測っているか（1行で言えるものだけ扱う）
#   fn       … 計算
#   group    … hitting / pitching
#   high     … 大きいほうが極端か
#   fmt      … 出し方
#   namesake … 呼び名の由来になっている選手（比べる相手）
METRICS = [
    {"key": "tto", "label": "アダム・ダン率", "group": "hitting",
     "note": "本塁打・四球・三振で終わった打席の割合",
     "fn": tto, "high": True, "fmt": "pct",
     "namesake": {"id": 276055, "name": "アダム・ダン"}},
    {"key": "iso", "label": "ISO", "group": "hitting",
     "note": "長打率から打率を引いた、単打を除いた長打力",
     "fn": iso, "high": True, "fmt": "avg3"},
    {"key": "babip", "label": "BABIP", "group": "hitting",
     "note": "本塁打以外の打球が安打になった割合",
     "fn": babip, "high": True, "fmt": "avg3"},
    {"key": "bb_per_k", "label": "四球三振比", "group": "hitting",
     "note": "四球を三振で割った値。1.00を超えるのは稀",
     "fn": bb_per_k, "high": True, "fmt": "ratio"},
    {"key": "k_rate", "label": "三振率", "group": "hitting",
     "note": "三振で終わった打席の割合",
     "fn": k_rate, "high": True, "fmt": "pct"},
    {"key": "bb_rate", "label": "四球率", "group": "hitting",
     "note": "四球で終わった打席の割合",
     "fn": bb_rate, "high": True, "fmt": "pct"},
    {"key": "k_per_9", "label": "9回あたり奪三振", "group": "pitching",
     "note": "9回を投げた場合の奪三振数",
     "fn": k_per_9, "high": True, "fmt": "ratio"},
    {"key": "k_per_bb", "label": "奪三振四球比", "group": "pitching",
     "note": "奪三振を与四球で割った値",
     "fn": k_per_bb, "high": True, "fmt": "ratio"},
    {"key": "whip", "label": "WHIP", "group": "pitching",
     "note": "1回あたりに出した走者（被安打＋与四球）",
     "fn": whip, "high": False, "fmt": "ratio"},
]

# 打率.200の線。
#
# マリオ・メンドーサの打率から「メンドーサ・ライン」と呼ばれる。
# 公式の記録ではないが、**打者にとっての境目として広く知られて
# いる。**村上は今季.208で、この線のすぐ上にいる。
MENDOZA_LINE = 0.200


def fmt(value, how: str) -> str:
    """数字の出し方。指標によって桁が違う。"""
    if value is None:
        return ""
    if how == "pct":
        return "%.1f%%" % (value * 100)
    if how == "avg3":
        return ("%.3f" % value).lstrip("0")
    return "%.2f" % value


def league(season: str, group: str, timeout: int = 45) -> list:
    """リーグ全体。1回の呼び出しで400人ぶん返る。

    **移籍した選手は合計の行を使う。**球団ごとの行を足すと
    二重になる（9/8に「ルイス・ガルシア56本」を出した原因）。
    """
    try:
        r = requests.get(
            f"{API}/stats",
            params={"stats": "season", "group": group, "season": season,
                    "limit": 400, "sportId": 1},
            headers=UA, timeout=timeout)
        r.raise_for_status()
        stats = r.json().get("stats") or []
    except Exception as e:                              # noqa: BLE001
        print(f"[warn] リーグ全体を取れません: {e}", file=sys.stderr)
        return []
    out = []
    for st in stats:
        for sp in mlb_splits.prefer_total(st.get("splits")):
            s = sp.get("stat") or {}
            if group == "hitting":
                if _i(s.get("plateAppearances")) < MIN_PA:
                    continue
            elif _outs(s.get("inningsPitched")) < MIN_IP * 3:
                continue
            out.append({
                "player_id": str((sp.get("player") or {}).get("id") or ""),
                "name": (sp.get("player") or {}).get("fullName") or "",
                "stat": s,
            })
    return out


def rank(rows: list, metric: dict, player_id: str) -> dict:
    """その選手が、リーグの中で何位か。

    計算できない選手は並びに入れない（0として扱うと、
    出ていない選手が最下位に並ぶ）。
    """
    vals = []
    for r in rows:
        v = metric["fn"](r["stat"])
        if v is not None:
            vals.append((v, r["player_id"], r["name"]))
    if not vals:
        return {}
    vals.sort(reverse=bool(metric["high"]))
    for i, (v, pid, name) in enumerate(vals, 1):
        if pid == str(player_id):
            return {"value": v, "shown": fmt(v, metric["fmt"]),
                    "at": i, "of": len(vals),
                    # 同じ値の選手が何人いるか。
                    #
                    # **同じ値が並ぶ指標では、順位に意味がない。**
                    # 「◯位」と書いても、実際は「◯位タイ」で、
                    # 極端であることの証明にならない。
                    "ties": sum(1 for x, _, _ in vals if x == v),
                    # すぐ上・すぐ下。「2位との差」を言うため。
                    "above": ({"name": vals[i - 2][2],
                               "shown": fmt(vals[i - 2][0], metric["fmt"])}
                              if i >= 2 else None),
                    "below": ({"name": vals[i][2],
                               "shown": fmt(vals[i][0], metric["fmt"])}
                              if i < len(vals) else None)}
    return {}


def best_season(player_id: str, metric: dict, timeout: int = 45) -> dict:
    """その選手の全シーズンのうち、いちばん極端だった年。

    比較相手（アダム・ダンなど）に使う。呼び出しは1回。
    """
    group = metric["group"]
    try:
        r = requests.get(
            f"{API}/people/{player_id}/stats",
            params={"stats": "yearByYear", "group": group},
            headers=UA, timeout=timeout)
        r.raise_for_status()
        stats = r.json().get("stats") or []
    except Exception as e:                              # noqa: BLE001
        print(f"[warn] 過去の成績を取れません: {e}", file=sys.stderr)
        return {}
    best = None
    for st in stats:
        for sp in st.get("splits") or []:
            s = sp.get("stat") or {}
            if group == "hitting":
                if _i(s.get("plateAppearances")) < MIN_PA:
                    continue
            elif _outs(s.get("inningsPitched")) < MIN_IP * 3:
                continue
            v = metric["fn"](s)
            if v is None:
                continue
            if best is None or ((v > best["value"]) == bool(metric["high"])
                                and v != best["value"]):
                best = {"value": v, "shown": fmt(v, metric["fmt"]),
                        "season": sp.get("season")}
    return best or {}


def player_stat(player_id: str, group: str, season: str,
                timeout: int = 30) -> dict:
    """その選手の今季の成績。移籍していれば合計の行。"""
    try:
        r = requests.get(
            f"{API}/people/{player_id}/stats",
            params={"stats": "season", "group": group, "season": season},
            headers=UA, timeout=timeout)
        r.raise_for_status()
        stats = r.json().get("stats") or []
    except Exception:                                   # noqa: BLE001
        return {}
    for st in stats:
        rows = mlb_splits.prefer_total(st.get("splits"))
        if rows:
            return rows[0].get("stat") or {}
    return {}


# 上位何位までを「話にする価値がある」とみなすか。
#
# 139人中70位の指標を並べても、それは「ふつう」という意味しかない。
# 上位5位、または下位5位に入っているものだけを扱う。
NOTABLE_AT = 5


def notable(rows_by_group: dict, player_id: str,
            stat_by_group: dict) -> list:
    """その選手について、話にする価値がある指標だけ。"""
    out = []
    for m in METRICS:
        rows = rows_by_group.get(m["group"]) or []
        s = stat_by_group.get(m["group"]) or {}
        if not rows or not s:
            continue
        r = rank(rows, m, player_id)
        if not r:
            continue
        # 同じ値の選手が他にもいるなら、その順位は「◯位タイ」。
        # 極端であることの証明にならないので扱わない。
        if r.get("ties", 1) > 1:
            continue
        top = r["at"] <= NOTABLE_AT
        bottom = (r["of"] - r["at"] + 1) <= NOTABLE_AT
        if not (top or bottom):
            continue
        out.append({**r, "key": m["key"], "label": m["label"],
                    "note": m["note"], "group": m["group"],
                    "side": "top" if top else "bottom"})
    # **上位を先に。**「リーグ1位」のほうが「下から1番目」より
    # 先に伝わるべきこと。同じ側なら、より端にいるものから。
    out.sort(key=lambda x: (0 if x["side"] == "top" else 1,
                            x["at"] if x["side"] == "top"
                            else x["of"] - x["at"]))
    return out


def phrase(item: dict) -> str:
    """そのまま読める言い方。**1か所で作る。**"""
    if not item:
        return ""
    if item["side"] == "top":
        return "%s %s（%d人中%d位）" % (item["label"], item["shown"],
                                    item["of"], item["at"])
    return "%s %s（%d人中%d位＝下から%d番目）" % (
        item["label"], item["shown"], item["of"], item["at"],
        item["of"] - item["at"] + 1)


def namesake_phrase(metric: dict, mine: dict, theirs: dict) -> str:
    """呼び名の由来になっている選手との比較。

    「アダム・ダン率でアダム・ダンを超えた」が言えるのは、
    指標の名前が人名だからこそ。**超えていない年は言わない**
    （比較そのものが話題になるのは、超えたときだけ）。
    """
    ns = metric.get("namesake") or {}
    if not ns or not mine or not theirs:
        return ""
    better = ((mine["value"] > theirs["value"]) == bool(metric["high"]))
    if not better:
        return ""
    return ("%s本人の最高（%s年 %s）を上回っている"
            % (ns["name"], theirs.get("season", "?"), theirs["shown"]))


def load(path: str = "data/rarity.json") -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def for_player(data: dict, name_jp: str) -> dict:
    return (data.get("players") or {}).get(name_jp) or {}


def summary(data: dict) -> str:
    lines = ["## 名前のある指標での位置", ""]
    players = data.get("players") or {}
    if not players:
        lines.append("取れませんでした。")
        return "\n".join(lines)
    lines.append("比べたのは %d打席以上／%d回以上の選手。"
                 % (MIN_PA, MIN_IP))
    lines.append("")
    for name, x in players.items():
        items = x.get("items") or []
        if not items:
            continue
        lines.append("### %s" % name)
        for it in items:
            lines.append("- %s" % phrase(it))
            if it.get("namesake"):
                lines.append("  - **%s**" % it["namesake"])
            if it.get("note"):
                lines.append("  - %s" % it["note"])
        if x.get("mendoza"):
            lines.append("- %s" % x["mendoza"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=str(date_today_year()))
    ap.add_argument("--out", default="data/rarity.json")
    args = ap.parse_args()

    try:
        from notability_engine import JP_PLAYERS_MLB
    except ImportError:
        print("[warn] 名簿を読めません", file=sys.stderr)
        return 0

    rows_by_group = {}
    for g in ("hitting", "pitching"):
        rows_by_group[g] = league(args.season, g)
        print("[info] %s の比較対象: %d人" % (g, len(rows_by_group[g])))

    # 名簿の選手IDは roster_snapshot から引く。
    ids = {}
    try:
        snap = json.loads(pathlib.Path("data/roster_snapshot.json")
                          .read_text(encoding="utf-8"))
        for pid, v in (snap.get("players") or {}).items():
            ids[v.get("name")] = pid
    except (OSError, json.JSONDecodeError):
        pass

    out = {}
    for p in JP_PLAYERS_MLB:
        pid = ids.get(p.get("name_en"))
        if not pid:
            continue
        group = "pitching" if p.get("type") == "pitcher" else "hitting"
        s = player_stat(pid, group, args.season)
        if not s:
            continue
        items = notable({group: rows_by_group[group]}, pid, {group: s})
        if not items:
            continue
        # 人名が由来の指標だけ、本人と比べる。
        for it in items:
            m = next((x for x in METRICS if x["key"] == it["key"]), None)
            if not m or not m.get("namesake"):
                continue
            theirs = best_season(m["namesake"]["id"], m)
            txt = namesake_phrase(m, it, theirs)
            if txt:
                it["namesake"] = txt
        entry = {"player_id": pid, "items": items}
        # 打率.200の線。上にいるか下にいるかで意味が変わる。
        #
        # **打者だけ。**投手の avg は被打率で、打率ではない。
        # そこを分けずに書いたら、山本由伸に
        # 「打率.185。メンドーサ・ラインのすぐ下」が付いた。
        # 被打率.185は良い投球で、意味が逆になる。
        # この取り違えは過去に何度も出ている（hits も homeRuns も、
        # 投手では「打たれた数」）。
        avg = _f(s.get("avg")) if group == "hitting" else None
        if avg is not None and abs(avg - MENDOZA_LINE) < 0.020:
            side = "上" if avg >= MENDOZA_LINE else "下"
            entry["mendoza"] = (
                "打率%s。メンドーサ・ライン（.200）のすぐ%s"
                % (("%.3f" % avg).lstrip("0"), side))
        out[p["name_jp"]] = entry
        print("[info] %s: %d件" % (p["name_jp"], len(items)))

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season": args.season,
        "min_pa": MIN_PA,
        "min_ip": MIN_IP,
        "players": out,
    }
    dest = pathlib.Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print()
    print(summary(data))
    print(f"\n[done] {dest}")
    return 0


def date_today_year() -> int:
    return datetime.now(timezone.utc).year


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
