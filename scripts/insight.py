#!/usr/bin/env python3
"""主語を渡すと、いま言えることを返す。

何のためのものか:
  「LAD」「大谷翔平」「ペトコパーク」「サイクルヒット」のように主語を
  渡すと、膨大な材料の中から**意味のあるものだけ**を返す。
  返ってきたものを、動画の1枚に使うか、記事にするか、サイトの
  ページに載せるかは、呼んだ側が決める。

  出すのはJSONなので、**動画とサイトで同じものを読む。**
  同じことを2か所で決めない。

返すものに必ず付くもの:

  tone  … 向き。positive / neutral / negative
          日本人選手の成績やコメント欄のようなポジティブな枠では
          negative を外す。戦略や展望の回では negative も要る
          （「CWSがPSを勝ち抜くには村上の調子が上がることが必須」は
          下降を知らないと書けない）。**枠ごとに選べるようにする。**

  sure  … 傾向として語ってよいか。high / low
          low は「事実として置くだけ」。直近40打数8安打は偶然の
          範囲で普通に起きるので「上げてきている」とは言えないが、
          「直近10試合は35打数4安打」と事実を置くのは構わない。
          **言い方が変わるので、判定をここでやって渡す。**

  weight… 言う価値の目安（0-100）。呼ぶ側が並べ替えるため。

言わないことを決める:
  取れる切り口は他にもある（曜日別など）。**取れることと言えることは
  別。**どの切り口を持つかは mlb_trends.SPLITS の登録制で、
  意味が想像できないものは最初から取らない。
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import mlb_trends as mt  # noqa: E402

# 差がこれ未満なら、そもそも言わない。
#
# OPSを主に見る。打率だけだと長打が消える（対右投手は打率で.026しか
# 違わないのにOPSでは.136違う、という日がある）。
MIN_DIFF_OPS = 0.120
MIN_DIFF_AVG = 0.050

# 場面型（得点圏など）は、対比型より狭い幅で見る。
#
# 対比型は**独立した2つの群の差**なので、両方の揺れが乗る（√2倍）。
# 場面型は「その場面」と「今季全体」の比較で、場面は全体の一部だから
# 揺れが小さい。同じ基準で切ると、対比型に合わせて場面型が
# ほぼ全部落ちる（村上宗隆の得点圏.103、2アウト.100、先頭.103が
# すべて.120のすぐ下だった）。
#
# 0.120 / √2 ≈ 0.085。
MIN_DIFF_OPS_SCENE = 0.085

# 月の成績を比べるのに要る打数。月の途中は届かない日がある。
MIN_AB_MONTH = 50

# 「傾向」と言ってよい打数。これ未満は事実として置くだけ（sure=low）。
SURE_AB = 80

POSITIVE, NEUTRAL, NEGATIVE = "positive", "neutral", "negative"


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _ops(row: dict):
    return _f(row.get("ops"))


def _ab(row: dict) -> int:
    try:
        return int(row.get("atBats") or 0)
    except (TypeError, ValueError):
        return 0


def _say(kind, text, tone=NEUTRAL, sure="high", weight=50, detail="",
         why="", source="MLB Stats API") -> dict:
    return {"type": kind, "text": text, "tone": tone, "sure": sure,
            "weight": int(weight), "detail": detail, "why": why,
            "source": source}


def from_splits(rows: list, name: str) -> list:
    """昼夜・対左右・ホーム/ビジター。**差が小さければ黙る。**"""
    out = []
    for row in rows:
        a, b = row["a"], row["b"]
        if min(_ab(a), _ab(b)) < mt.MIN_AB_SPLIT:
            continue          # 片方が薄い切り口は比べない
        oa, ob = _ops(a), _ops(b)
        if oa is None or ob is None:
            continue
        gap = abs(oa - ob)
        avg_gap = abs((_f(a.get("avg")) or 0) - (_f(b.get("avg")) or 0))
        if gap < MIN_DIFF_OPS and avg_gap < MIN_DIFF_AVG:
            continue          # 違いと呼べるほど違わない
        hi, lo = (a, b) if oa > ob else (b, a)
        out.append(_say(
            "split",
            "%sは%sでOPS%s、%sでは%s" % (name, hi["label"], hi.get("ops"),
                                        lo["label"], lo.get("ops")),
            tone=NEUTRAL,     # どちらが良いという話ではなく、差の話
            sure="high",
            weight=min(100, 40 + gap * 200),
            detail="%s %s打数 打率%s ／ %s %s打数 打率%s"
                   % (hi["label"], _ab(hi), hi.get("avg"),
                      lo["label"], _ab(lo), lo.get("avg")),
            why=row.get("why", "")))
    return out


def from_scenes(rows: list, season_total: dict, name: str) -> list:
    """場面ごとの成績。**比べる相手は今季全体。**

    「得点圏で.160」はそれ単体では読めない。今季の.204と並べて初めて
    「チャンスで打てていない」という話になる。

    ここでいちばん効くのが打数の下限。村上宗隆の満塁は今季5打数で
    打率.400・OPS1.771。**これを「満塁に強い」と書いたら終わり。**
    """
    base = _ops(season_total)
    if base is None:
        return []
    out = []
    for row in rows:
        ab = _ab(row)
        if ab < mt.MIN_AB_SPLIT:
            continue          # 満塁5打数・初球29打数はここで落ちる
        cur = _ops(row)
        if cur is None:
            continue
        gap = cur - base
        if abs(gap) < MIN_DIFF_OPS_SCENE:
            continue
        up = gap > 0
        out.append(_say(
            "scene",
            "%sは%sでOPS%s。今季全体の%sを%s"
            % (name, row["label"], row.get("ops"), season_total.get("ops"),
               "上回っている" if up else "下回っている"),
            tone=POSITIVE if up else NEGATIVE,
            sure="high",
            weight=min(100, 45 + abs(gap) * 150),
            detail="%s %s打数 打率%s" % (row["label"], ab, row.get("avg")),
            why=row.get("why", "")))
    return out


def from_months(rows: list, season_total: dict, name: str) -> list:
    """月別。**今月と今季全体を比べる。**"""
    usable = [r for r in rows if _ab(r) >= MIN_AB_MONTH]
    if not usable:
        return []
    now = usable[-1]
    base = _ops(season_total)
    cur = _ops(now)
    if base is None or cur is None:
        return []
    gap = cur - base
    if abs(gap) < MIN_DIFF_OPS:
        return []
    up = gap > 0
    return [_say(
        "month",
        "%sの%d月はOPS%s。今季全体の%sより%s"
        % (name, now["month"], now.get("ops"), season_total.get("ops"),
           "高い" if up else "低い"),
        tone=POSITIVE if up else NEGATIVE,
        sure="high",
        weight=min(100, 40 + abs(gap) * 150),
        detail="%d月 %s打数 打率%s" % (now["month"], _ab(now),
                                      now.get("avg")),
        why="月単位は調子の波が見える長さ。1試合の上下には引きずられない")]


def from_recent(recent: dict, season_total: dict, name: str) -> list:
    """直近N試合。**短いほうは事実として置くだけ。**

    ユーザーの判断:「事実として、参考程度に直近40打数何安打っていうのは
    言ってもいいと思いますが、中長期的なところでは参考になりませんけどね」
    そのとおりなので、短いほうは sure=low にして、呼ぶ側が
    「参考程度に」と添えられるようにする。
    """
    out = []
    base = _ops(season_total)
    for games in sorted(recent):
        row = recent[games]
        ab = _ab(row)
        if not ab:
            continue
        cur = _ops(row)
        sure = "high" if ab >= SURE_AB else "low"
        gap = (cur - base) if (cur is not None and base is not None) else None
        if sure == "low":
            # 傾向とは言わない。**起きたことをそのまま置く。**
            out.append(_say(
                "recent",
                "%sの直近%d試合は%s打数%s安打" % (name, games, ab,
                                                row.get("hits")),
                tone=NEUTRAL, sure="low", weight=30,
                detail="打率%s OPS%s" % (row.get("avg"), row.get("ops")),
                why="この長さでは傾向とは言えない。事実として置くだけ"))
            continue
        if gap is None or abs(gap) < MIN_DIFF_OPS:
            continue
        up = gap > 0
        out.append(_say(
            "recent",
            "%sの直近%d試合はOPS%s。今季の%sを%s"
            % (name, games, row.get("ops"), season_total.get("ops"),
               "上回っている" if up else "下回っている"),
            tone=POSITIVE if up else NEGATIVE,
            sure="high",
            weight=min(100, 50 + abs(gap) * 150),
            detail="%s打数%s安打 打率%s" % (ab, row.get("hits"),
                                           row.get("avg")),
            why="今季全体と比べることで、いまどちらを向いているかが出る"))
    return out


def player(player_id, name: str, season="2026", group="hitting") -> list:
    """1人について、いま言えること。多い順に並べて返す。"""
    data = mt.collect(player_id, season, group)
    said = []
    said += from_splits(data["splits"], name)
    said += from_scenes(data.get("scenes") or [], data["season_total"], name)
    said += from_months(data["months"], data["season_total"], name)
    said += from_recent(data["recent"], data["season_total"], name)
    said.sort(key=lambda s: -s["weight"])
    return said


def pick(said: list, tone=None, sure=None, limit=None) -> list:
    """呼ぶ側の都合で絞る。

    日本人選手の成績（ポジティブな枠）なら tone=("positive","neutral")、
    戦略や展望の回なら全部、という使い分けを想定している。
    """
    out = said
    if tone:
        keep = (tone,) if isinstance(tone, str) else tuple(tone)
        out = [s for s in out if s["tone"] in keep]
    if sure:
        keep = (sure,) if isinstance(sure, str) else tuple(sure)
        out = [s for s in out if s["sure"] in keep]
    return out[:limit] if limit else out


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "808959"
    name = sys.argv[2] if len(sys.argv) > 2 else "村上宗隆"
    rows = player(pid, name)
    print("## %s について言えること（%d件）" % (name, len(rows)))
    for r in rows:
        print("\n[%s/%s/%d] %s" % (r["type"], r["tone"], r["weight"],
                                   r["text"]))
        if r["detail"]:
            print("   %s" % r["detail"])
        if r["why"]:
            print("   なぜ見るか: %s" % r["why"])
    print("\n--- ポジティブな枠に渡すなら ---")
    for r in pick(rows, tone=("positive", "neutral")):
        print("  %s" % r["text"])
