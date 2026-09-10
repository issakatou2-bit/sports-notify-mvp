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
    ::昨日から線をまたいだか

  ここではその3つだけを扱う。リーグごとの事情は呼ぶ側が持つ。
"""


def around(rows: list, at: int, span: int = 2) -> dict:
    """線の前後を切り出す。

    rows は上位から順に並んだ一覧。at は「ここまでが圏内」の順位
    (1から数える)。span は線の上下に何件ずつ見るか。

    返すのは {"inside": [...], "outside": [...], "line": at}。
    線が一覧の外にあるときは、あるぶんだけ返す。
    """
    if not rows or at < 1:
        return {"inside": [], "outside": [], "line": at}
    inside = rows[max(0, at - span):at]
    outside = rows[at:at + span]
    return {"inside": inside, "outside": outside, "line": at}


def gap(rows: list, at: int, key: str = "points") -> dict:
    """線をまたぐ差。

    「あと勝点2でCL圏内」のような言い方の材料。
    同じ数のときは0を返す（"並んでいる"は呼ぶ側の言葉）。
    """
    if not rows or at < 1 or at >= len(rows):
        return {}
    last_in, first_out = rows[at - 1], rows[at]
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
    a = {r.get(key) for r in now[:at] if r.get(key)}
    b = {r.get(key) for r in before[:at] if r.get(key)}
    if not a or not b:
        return {}
    return {"line": at,
            "in": sorted(a - b),
            "out": sorted(b - a)}


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
