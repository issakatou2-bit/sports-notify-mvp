#!/usr/bin/env python3
"""順位表の「境目」を扱う。MLBとサッカーで共通。

なぜ要るのか:
  実測でいちばん強い枠は、数字が主役のもの。

    成績ランキング   平均411再生 / 登録0.72(千再生あたり)
    現地の報道       272 / 0.15
    明日の注目試合   241 / 0.58
    コメント欄       112 / 0.00
    長編(コメント欄)   2 / 0.00

  **コメント欄を読み解く枠は、ショートも長編もいちばん弱い。**
  9/10の長編では「先発投手の中4日」を「5日ぶりの復帰」と言う事故も
  起きた。材料を厚く渡すほど、組み合わせを間違える余地が増える。

  数字が主役の枠に寄せる。その中でも**順位の争い**は、
  MLBの進出争い(9〜10月だけ)に対してサッカーは9月から5月まで
  ずっと材料がある。期間がいちばん長い。

何が共通なのか:
  リーグの形はまるで違う。MLBは2リーグ×3地区で上位6が進出、
  サッカーは1リーグ20クラブで上位4がCL・下位3が降格。
  **枠の数も条件も共通化できない。**

  共通なのは「**線の前後**」という見方だけ。

    ・その線の上にいるか、下にいるか
    ・線までの差はどれだけか
    ・昨日から線をまたいだか

  ここではその3つだけを扱う。リーグごとの事情は呼ぶ側が持つ。

**順位は一覧の添字ではなく、position の値で見る。**
  最初は「上からat件が圏内」と添字で切っていた。同順位があると
  必ずずれる。9/11の実データでは6大会のうち5つで同順位が出ていて、
  プレミアは17位が2クラブ、チャンピオンズリーグは36行のうち18行が
  添字とずれていた。その結果「17位のトッテナムは残留圏外」という、
  順位表を見れば誰でも分かる間違いが出ていた。

  同勝点・同得失点のクラブにAPIが同じ順位を付けて返すのは
  ふつうのことなので、こちらが順位を数え直してはいけない。
"""


def _pos(row: dict, fallback: int) -> int:
    """その行の順位。position が無ければ並び順から。

    昔のMLBの記録には position が無い。無い場合だけ添字で補う。
    """
    try:
        v = row.get("position")
    except AttributeError:
        return fallback
    try:
        return int(v)
    except (TypeError, ValueError):
        return fallback


def split(rows: list, at: int) -> tuple:
    """線の内と外に分ける。at は「ここまでが圏内」の順位(1から数える)。

    同順位が線にかかる日は、**両方とも圏内**になる。
    4位が2クラブいてCL圏内が4位までなら、5クラブが圏内。
    それが順位表の読み方で、こちらで順位を付け直す話ではない。
    """
    inside, outside = [], []
    for i, r in enumerate(rows or []):
        (inside if _pos(r, i + 1) <= at else outside).append(r)
    return inside, outside


def around(rows: list, at: int, span: int = 2) -> dict:
    """線の前後を切り出す。

    rows は上位から順に並んだ一覧。at は「ここまでが圏内」の順位
    (1から数える)。span は線の上下に何件ずつ見るか。

    返すのは {"inside": [...], "outside": [...], "line": at}。
    線が一覧の外にあるときは、あるぶんだけ返す。
    """
    if not rows or at < 1:
        return {"inside": [], "outside": [], "line": at}
    inside, outside = split(rows, at)
    return {"inside": inside[-span:] if span else inside,
            "outside": outside[:span],
            "line": at}


def gap(rows: list, at: int, key: str = "points") -> dict:
    """線をまたぐ差。

    「あと勝点2でCL圏内」のような言い方の材料。
    同じ数のときは0を返す（"並んでいる"は呼ぶ側の言葉）。
    """
    if not rows or at < 1:
        return {}
    inside, outside = split(rows, at)
    if not inside or not outside:
        return {}
    last_in, first_out = inside[-1], outside[0]
    try:
        d = int(last_in.get(key) or 0) - int(first_out.get(key) or 0)
    except (TypeError, ValueError):
        return {}
    return {"line": at, "diff": d,
            "inside": last_in, "outside": first_out}


def moved(now: list, before: list, at: int, key: str = "team") -> dict:
    """昨日から線をまたいだクラブ。

    **入った側と出た側を、名前で突き合わせる。**順位で比べると、
    同じ順位に別のクラブが来た日に「動いていない」と読める。

    before が空の日（初回・取得に失敗した日）は空を返す。
    「変化なし」と「分からない」を混ぜない。
    """
    if not now or not before or at < 1:
        return {}
    a = {r.get(key) for r in split(now, at)[0] if r.get(key)}
    b = {r.get(key) for r in split(before, at)[0] if r.get(key)}
    if not a or not b:
        return {}
    return {"line": at,
            "in": sorted(a - b),
            "out": sorted(b - a)}


def distance_to(rows: list, at: int, team: str, key: str = "points",
                name_key: str = "team") -> dict:
    """あるクラブ（チーム）から、その線までの差。

    なぜ要るのか:
      線の前後だけを見ると、**日本人選手がそこにいない日は
      名前が1つも出ない。**9/11のラ・リーガはCL圏内の4位と5位に
      日本人がおらず、久保建英は9位、佐藤龍之介は20位だった。
      実測では題に日本人選手の名前がある動画が平均395再生、
      無い動画が192再生。名前を出せるかで倍ちがう。

      「9位のレアル・ソシエダは、CL圏内まで勝ち点5」なら、
      順位争いの話のまま名前を出せる。

    返すのは
      {"line": at, "position": 9, "side": "outside", "diff": 5}
    side は線のどちら側にいるか。圏内なら「落ちるまで何点」、
    圏外なら「入るまで何点」で、同じ数字でも意味が逆になる。
    見つからなければ空。
    """
    if not rows or at < 1 or not team:
        return {}
    me = None
    for i, r in enumerate(rows):
        if (r.get(name_key) or "") == team:
            me = (i, r)
            break
    if me is None:
        return {}
    i, row = me
    pos = _pos(row, i + 1)
    inside, outside = split(rows, at)
    in_side = pos <= at
    # 圏内なら、線の外側の先頭との差。圏外なら、圏内の最後との差。
    # 相手側が空（線が一覧の外にある）なら差は出せない。
    other = None
    if in_side and outside:
        other = outside[0]
    elif not in_side and inside:
        other = inside[-1]
    if other is None:
        return {}
    try:
        mine = int(row.get(key) or 0)
        theirs = int(other.get(key) or 0)
    except (TypeError, ValueError):
        return {}
    return {"line": at,
            "position": pos,
            "side": "inside" if in_side else "outside",
            "diff": abs(mine - theirs)}


# サッカーの主な境目。リーグによって枠の数が違う。
#
# CL圏内は4（プレミア・ラ・リーガ・セリエA・ブンデス）だが、
# リーグ・アンは3+プレーオフの年がある。**年ごとに変わるので、
# ここは既定値**。呼ぶ側が上書きできるようにしてある。
SOCCER_LINES = {
    "PL": [(4, "CL圏内"), (5, "EL圏内"), (17, "残留")],
    "PD": [(4, "CL圏内"), (5, "EL圏内"), (17, "残留")],
    "SA": [(4, "CL圏内"), (5, "EL圏内"), (17, "残留")],
    "BL1": [(4, "CL圏内"), (6, "EL圏内"), (15, "残留")],
    "FL1": [(3, "CL圏内"), (5, "EL圏内"), (15, "残留")],
    "ELC": [(2, "自動昇格"), (6, "昇格プレーオフ"), (21, "残留")],
    "BL2": [(2, "自動昇格"), (3, "昇格プレーオフ"), (15, "残留")],
}


def lines_for(code: str) -> list:
    """その大会の境目。知らない大会は空。"""
    return list(SOCCER_LINES.get(code) or [])
