#!/usr/bin/env python3
"""MLBの選手について、切り口ごとの成績を取る。

何のためのものか:
  「昼より夜のほうが打てる」「今月は落ちている」「直近10試合は上げている」
  といった、解説が話題にする角度の材料。すべて MLB Stats API の
  1リクエストで取れる（キー不要・無料）。

**取れることと、言えることは別。**

  同じAPIで曜日別も取れる。村上宗隆の実データ（2026-09-15）:

      1日目 40打数 打率.300（OPS 1.066）
      4日目 39打数 打率.103（OPS  .505）

  差は.197で、昼夜の差（.091）より大きく出る。**それでもこれは
  言ってはいけない。**40打数は偶然の幅が広く、7通り試せば1つくらい
  極端な値が出るのが当たり前だから。

  昼夜が言えて曜日が言えないのは統計ではなく「意味が想像できるか」の
  違いで、計算では決まらない。**だから切り口を登録制にする。**
  下の SPLITS に無いものは、取れても出さない。

投手と打者:
  投手の `avg` は被打率、`hits` は被安打。**同じ名前で反対の意味。**
  group を間違えると、山本由伸に「打率.185」が付く（実際に起きた）。
"""

import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 20

# 見てよい切り口。**ここに無いものは取れても出さない。**
#
# (APIの符号A, 符号B, Aの日本語, Bの日本語, なぜ意味があるか)
SPLITS = (
    ("d", "n", "昼の試合", "夜の試合",
     "光の見え方と体調。デーゲームが苦手な打者は昔から言われる"),
    ("h", "a", "ホーム", "ビジター",
     "球場の形と移動。本拠地の広さは打者ごとに向き不向きがある"),
    ("vl", "vr", "対左投手", "対右投手",
     "投げる腕と打つ側の関係。打者の得手不得手が最も出る切り口"),
    ("g", "t", "天然芝", "人工芝",
     "打球の速さと弾み方が変わる。内野安打の出方に響く"),
    ("h1", "h2", "前半戦", "後半戦",
     "オールスターを挟んで、疲れと対策の両方が出る"),
)

# 場面ごとの成績。**比べる相手は今季全体。**
#
# 対比型（上のSPLITS）と違い、片方しかない切り口。「得点圏で.160」は
# それ単体では読めず、今季全体の.204と並べて初めて意味を持つ。
#
# (符号, 日本語, なぜ見るか)
SITUATIONS = (
    ("risp", "得点圏", "走者を還す場面。打線の中心ほど問われる"),
    ("o2", "2アウト", "ここで打てるかで、イニングが終わるか続くかが決まる"),
    ("lo", "イニングの先頭", "出塁すれば、その回の得点確率が大きく動く"),
    ("ig07", "7回以降", "終盤は相手の継投が変わり、疲れも出る"),
    ("sah", "リードしている場面", "追加点が要る場面での働き"),
    ("sbh", "ビハインドの場面", "追う展開で、どれだけ食い下がれるか"),
)

# **持たない切り口。**取れるが出さない。
#
# 曜日別（dmo〜dsu）… 意味が想像できない。7通り試せば1つは極端に出る
# 満塁（r123）      … 村上宗隆で今季5打数。打席が集まらない
# 初球（fp）        … 29打数。同上
# 終盤の接戦（lc）  … 42打数。惜しいが、この打数では読めない
#
# サンプルで落ちるものは下限で自動的に落ちる。曜日別だけは
# 打数が集まってしまうので、**最初から取らない**しかない。
NOT_TAKEN = ("dmo", "dtu", "dwe", "dth", "dfr", "dsa", "dsu")

# 切り口ごとに、これだけの打数が無ければ比べない。
#
# 80は「打率の偶然の揺れが.045前後に収まる」あたり。これを下回ると、
# 差が出ても中身を読めない。投手は打者と数が違うので別に持つ。
MIN_AB_SPLIT = 80
MIN_IP_SPLIT = 20

# 直近N試合。Nは2つ持つ。
#
# **短いほうは傾向ではなく「事実」として出す。**
# 40打数8安打は偶然の範囲で普通に起きるので「上げてきている」とは
# 言えないが、「直近10試合は40打数8安打」と事実を置くのは構わない。
RECENT_GAMES = (10, 30)


def _get(path: str, params: dict) -> dict:
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Collespo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print("[info] 取れません(%s): %s" % (e, path))
        return {}


def _stat(row: dict) -> dict:
    return (row or {}).get("stat") or {}


def _f(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def situations(player_id, season, group: str = "hitting") -> dict:
    """登録した切り口を**まとめて1回で**取る。

    sitCodesはカンマ区切りで何個でも渡せる。実際に23個を1リクエストで
    取れることを確認した（19個ぶんの打席があった）。**切り口を増やしても
    API回数は増えない**ので、費用も実行時間もほぼ変わらない。
    """
    codes = [c for pair in SPLITS for c in pair[:2]]
    codes += [c for c, _, _ in SITUATIONS]
    data = _get("/people/%s/stats" % player_id,
                {"stats": "statSplits", "season": season, "group": group,
                 "sitCodes": ",".join(codes)})
    got = {}
    for block in data.get("stats") or []:
        for row in block.get("splits") or []:
            code = ((row.get("split") or {}).get("code") or "").lower()
            if code and code not in NOT_TAKEN:
                got[code] = _stat(row)
    return got


def splits(player_id, season, group: str = "hitting", got: dict = None):
    """対比型（AとBを並べる）。**差が小さいものはここでは落とさない。**

    落とすのは `insight` の役目。ここは取れたものをそのまま返す。
    """
    got = situations(player_id, season, group) if got is None else got
    out = []
    for a, b, ja, jb, why in SPLITS:
        if a not in got or b not in got:
            continue
        out.append({"kind": "%s_%s" % (a, b), "why": why,
                    "a": {"label": ja, **got[a]},
                    "b": {"label": jb, **got[b]}})
    return out


def scenes(got: dict) -> list:
    """場面型（今季全体と比べる）。比べる相手は呼ぶ側が持つ。"""
    out = []
    for code, ja, why in SITUATIONS:
        if code in got:
            out.append({"kind": code, "label": ja, "why": why, **got[code]})
    return out


def by_month(player_id, season, group: str = "hitting") -> list:
    """月ごとの成績。新しい月が後ろに来るよう並べ替える。"""
    data = _get("/people/%s/stats" % player_id,
                {"stats": "byMonth", "season": season, "group": group})
    out = []
    for block in data.get("stats") or []:
        for row in block.get("splits") or []:
            month = row.get("month")
            if month is None:
                continue
            out.append({"month": int(month), **_stat(row)})
    out.sort(key=lambda r: r["month"])
    return out


def last_games(player_id, season, limit: int, group: str = "hitting") -> dict:
    """直近N試合の合計。取れなければ空。"""
    data = _get("/people/%s/stats" % player_id,
                {"stats": "lastXGames", "season": season, "group": group,
                 "limit": limit})
    for block in data.get("stats") or []:
        for row in block.get("splits") or []:
            return {"games": limit, **_stat(row)}
    return {}


def season_total(player_id, season, group: str = "hitting") -> dict:
    """今季の合計。比べる相手として要る。"""
    data = _get("/people/%s/stats" % player_id,
                {"stats": "season", "season": season, "group": group})
    for block in data.get("stats") or []:
        for row in block.get("splits") or []:
            return _stat(row)
    return {}


def collect(player_id, season, group: str = "hitting") -> dict:
    """1人ぶんをまとめて。**APIは4回まで。**

    毎日全選手ぶん叩くものではない。問い合わせられた選手だけ。
    """
    got = situations(player_id, season, group)
    out = {"player_id": str(player_id), "season": str(season),
           "group": group,
           "season_total": season_total(player_id, season, group),
           "splits": splits(player_id, season, group, got=got),
           "scenes": scenes(got),
           "months": by_month(player_id, season, group),
           "recent": {}}
    for n in RECENT_GAMES:
        got = last_games(player_id, season, n, group)
        if got:
            out["recent"][n] = got
    return out


if __name__ == "__main__":
    import sys
    pid = sys.argv[1] if len(sys.argv) > 1 else "808959"   # 村上宗隆
    group = sys.argv[2] if len(sys.argv) > 2 else "hitting"
    got = collect(pid, "2026", group)
    print(json.dumps(got, ensure_ascii=False, indent=2)[:2400])
