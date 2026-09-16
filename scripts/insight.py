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
from math import comb, sqrt

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import mlb_trends as mt  # noqa: E402

# 差がこれ未満なら、そもそも言わない。
#
# OPSを主に見る。打率だけだと長打が消える（対右投手は打率で.026しか
# 違わないのにOPSでは.136違う、という日がある）。
# 月別だけはOPSの差で切る（月は打数が揃わないので確率が粗くなる）。
# 切り口と場面は chance() / gap_chance() の確率で切る。
MIN_DIFF_OPS = 0.120

# 月の成績を比べるのに要る打数。月の途中は届かない日がある。
MIN_AB_MONTH = 50

# 「傾向」と言ってよい打数。これ未満は事実として置くだけ（sure=low）。
SURE_AB = 80

POSITIVE, NEUTRAL, NEGATIVE = "positive", "neutral", "negative"

# 投手と打者で、同じ項目が反対の意味を持つ。
#
# **投手の `avg` は被打率。**「山本由伸は初球で打率.338」と書いて
# しまった回があった。しかも「今季全体を上回っている」は、投手には
# 「打たれている」という意味で、褒め言葉ではない。
#
# 数字は正しく、**呼び方と向きだけが逆**なので、検算では捕まらない。
AVG_WORD = {"hitting": "打率", "pitching": "被打率"}
OPS_WORD = {"hitting": "OPS", "pitching": "被OPS"}


def _avg_word(group: str) -> str:
    return AVG_WORD.get(group, "打率")


def _ops_word(group: str) -> str:
    return OPS_WORD.get(group, "OPS")


def _tone(up: bool, group: str) -> str:
    """上回っていることが、良いことか悪いことか。

    打者は上回れば良い。**投手は被打率が上回れば悪い。**
    """
    good = up if group != "pitching" else not up
    return POSITIVE if good else NEGATIVE


# 偶然でそうなる確率がこれ以下なら「傾向」として語ってよい。
TREND_P = 0.05
# これ以下なら「事実として置く」ところまで。これを超えたら出さない。
FACT_P = 0.20
# 打席がこれ未満だと、確率そのものが意味を持たない（1打数1安打など）。
# **低くしてある。**落とすのは確率の側の仕事で、ここではない。
# 満塁5打数.400は「偶然でも27%」として計算し、FACT_P を超えるから
# 落ちる。打席数で先に切ると、5打数と29打数の区別がつかなくなる。
MIN_AB_ANY = 3


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def chance(n: int, hits: int, base: float) -> float:
    """その成績が偶然で起きる確率。**小さいほど珍しい。**

    打数と打率だけで判定していたのを、ここに置き換えた。
    ユーザーの問い:「満塁で強いって情報、何がだめ？」への答えがこれ。

      今季.204の打者が、満塁5打数で2安打（.400）以上打つ確率 … 27.1%
      同じ打者が、初球29打数で10安打（.345）以上打つ確率     …  5.5%
      同じ打者が、終盤の接戦42打数で9安打（.214）以上       … 49.5%

    27%は「4人に1人はそう見える」ということで、30球団の主力を並べれば
    8人が「満塁に強い」ことになる。**情報量がほぼ無い。**
    一方で初球の5.5%は珍しく、捨てるほうが惜しい。

    打数の下限で切ると、この2つを区別できない（5打数と29打数はどちらも
    「少ない」）。確率で切れば、少ない打数でも極端なものは拾える。

    期待より上なら上側、下なら下側の確率を返す（両方見る）。
    """
    if n < MIN_AB_ANY or not 0 < base < 1:
        return 1.0
    hits = max(0, min(n, int(hits)))
    expected = n * base
    if hits >= expected:
        rng = range(hits, n + 1)
    else:
        rng = range(0, hits + 1)
    return sum(comb(n, i) * base ** i * (1 - base) ** (n - i) for i in rng)


def gap_chance(na, ha, nb, hb) -> float:
    """2つの群の打率の差が、偶然で起きる確率（正規近似）。

    対比型（昼と夜、対左と対右）はどちらも標本なので、片方を真の値と
    みなす計算は使えない。差のzを見る。
    """
    if min(na, nb) < MIN_AB_ANY:
        return 1.0
    pa, pb = ha / na, hb / nb
    var = pa * (1 - pa) / na + pb * (1 - pb) / nb
    if var <= 0:
        return 1.0
    z = abs(pa - pb) / sqrt(var)
    # 正規分布の両側確率。誤差関数を使わずに済ませる近似。
    return max(0.0, min(1.0, 2 * (1 - _phi(z))))


def _phi(z: float) -> float:
    """標準正規分布の累積。Zelen & Severo の近似（誤差 7.5e-8）。"""
    if z < 0:
        return 1 - _phi(-z)
    t = 1 / (1 + 0.2316419 * z)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (
        1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return 1 - 0.3989422804014327 * (2.718281828459045 ** (-z * z / 2)) * poly


def _ops(row: dict):
    return _f(row.get("ops"))


def _ab(row: dict) -> int:
    try:
        return int(row.get("atBats") or 0)
    except (TypeError, ValueError):
        return 0


def _hits(row: dict) -> int:
    try:
        return int(row.get("hits") or 0)
    except (TypeError, ValueError):
        return 0


def _say(kind, text, tone=NEUTRAL, sure="high", weight=50, detail="",
         why="", source="MLB Stats API") -> dict:
    return {"type": kind, "text": text, "tone": tone, "sure": sure,
            "weight": int(weight), "detail": detail, "why": why,
            "source": source}


def from_splits(rows: list, name: str, group: str = "hitting") -> list:
    """昼夜・対左右・ホーム/ビジター。**差が小さければ黙る。**"""
    out = []
    for row in rows:
        a, b = row["a"], row["b"]
        p = gap_chance(_ab(a), _hits(a), _ab(b), _hits(b))
        oa, ob = _ops(a), _ops(b)
        if oa is None or ob is None:
            continue
        if p > FACT_P:
            continue          # 差と呼べるほど違わない
        hi, lo = (a, b) if oa > ob else (b, a)
        if p <= TREND_P:
            text = ("%sは%sで%s%s、%sでは%s"
                    % (name, hi["label"], _ops_word(group), hi.get("ops"),
                       lo["label"], lo.get("ops")))
            sure, weight = "high", min(100, 55 + (TREND_P - p) * 700)
        else:
            text = ("%sは%sで%s打数%s安打、%sでは%s打数%s安打"
                    % (name, hi["label"], _ab(hi), _hits(hi),
                       lo["label"], _ab(lo), _hits(lo)))
            sure, weight = "low", 35
        out.append(_say(
            "split", text,
            tone=NEUTRAL,     # どちらが良いという話ではなく、差の話
            sure=sure, weight=weight,
            detail="%s %s打数 %s%s ／ %s %s打数 %s%s"
                   "（差が偶然で出る確率 %.0f%%）"
                   % (hi["label"], _ab(hi), _avg_word(group), hi.get("avg"),
                      lo["label"], _ab(lo), _avg_word(group), lo.get("avg"),
                      p * 100),
            why=row.get("why", "")))
    return out


def from_scenes(rows: list, season_total: dict, name: str,
                group: str = "hitting") -> list:
    """場面ごとの成績。**比べる相手は今季全体。**

    「得点圏で.160」はそれ単体では読めない。今季の.204と並べて初めて
    「チャンスで打てていない」という話になる。

    ここでいちばん効くのが打数の下限。村上宗隆の満塁は今季5打数で
    打率.400・OPS1.771。**これを「満塁に強い」と書いたら終わり。**
    """
    base_avg = _f(season_total.get("avg"))
    if base_avg is None:
        return []
    out = []
    for row in rows:
        ab, hits = _ab(row), _hits(row)
        p = chance(ab, hits, base_avg)
        if p > FACT_P:
            continue          # 満塁5打数(27%)・終盤の接戦42打数(50%)はここ
        cur = _f(row.get("avg"))
        up = cur is not None and cur > base_avg
        if p <= TREND_P:
            # 傾向として語ってよい。
            text = ("%sは%sで%s%s。今季全体の%sを%s"
                    % (name, row["label"], _avg_word(group), row.get("avg"),
                       season_total.get("avg"),
                       "上回っている" if up else "下回っている"))
            tone, sure = _tone(up, group), "high"
            weight = min(100, 60 + (TREND_P - p) * 600)
        else:
            # 珍しさが足りない。**起きたことをそのまま置く。**
            text = ("%sは%sで%s打数%s安打" % (name, row["label"], ab, hits))
            tone, sure = NEUTRAL, "low"
            weight = 35
        out.append(_say(
            "scene", text, tone=tone, sure=sure, weight=weight,
            detail="%s %s%s %s%s（偶然でこうなる確率 %.0f%%）"
                   % (row["label"], _avg_word(group), row.get("avg"),
                      _ops_word(group), row.get("ops"), p * 100),
            why=row.get("why", "")))
    return out


def from_months(rows: list, season_total: dict, name: str,
                group: str = "hitting") -> list:
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
        "%sの%d月は%s%s。今季全体の%sより%s"
        % (name, now["month"], _ops_word(group), now.get("ops"),
           season_total.get("ops"), "高い" if up else "低い"),
        tone=_tone(up, group),
        sure="high",
        weight=min(100, 40 + abs(gap) * 150),
        detail="%d月 %s打数 %s%s" % (now["month"], _ab(now),
                                     _avg_word(group), now.get("avg")),
        why="月単位は調子の波が見える長さ。1試合の上下には引きずられない")]


def from_recent(recent: dict, season_total: dict, name: str,
                group: str = "hitting") -> list:
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
                detail="%s%s %s%s" % (_avg_word(group), row.get("avg"),
                                      _ops_word(group), row.get("ops")),
                why="この長さでは傾向とは言えない。事実として置くだけ"))
            continue
        if gap is None or abs(gap) < MIN_DIFF_OPS:
            continue
        up = gap > 0
        out.append(_say(
            "recent",
            "%sの直近%d試合は%s%s。今季の%sを%s"
            % (name, games, _ops_word(group), row.get("ops"),
               season_total.get("ops"),
               "上回っている" if up else "下回っている"),
            tone=_tone(up, group),
            sure="high",
            weight=min(100, 50 + abs(gap) * 150),
            detail="%s打数%s安打 %s%s" % (ab, row.get("hits"),
                                          _avg_word(group), row.get("avg")),
            why="今季全体と比べることで、いまどちらを向いているかが出る"))
    return out


def player(player_id, name: str, season="2026", group="hitting") -> list:
    """1人について、いま言えること。多い順に並べて返す。"""
    data = mt.collect(player_id, season, group)
    said = []
    said += from_splits(data.get("pairs") or [], name, group)
    said += from_scenes(data.get("scenes") or [], data["season_total"],
                        name, group)
    said += from_months(data["months"], data["season_total"], name, group)
    said += from_recent(data["recent"], data["season_total"], name, group)
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
