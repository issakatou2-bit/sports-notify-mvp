#!/usr/bin/env python3
"""Baseball Savant のパーセンタイル。**リーグの中での位置がそのまま入る。**

なぜ要るのか:
  ユーザーの指摘:「アダム・ダン率を持ってくるあたりは解説っぽくて
  よかったです。今日だけ、しかもアダム・ダン率しか話題に出せないとか
  じゃなければ良いんですけどね」。

  `rarity.py` は規定到達者の中での順位を出すが、**指標が9つしかなく、
  規定に届く日本人選手も少ない。**毎日同じ話になる。

  Savantのパーセンタイルは1回のリクエストで606人 × 18項目。
  打球速度・バレル率・空振り率・選球眼・走塁・守備まで入っていて、
  **どれも解説が使う語**。大谷翔平（2026-09-16時点）:

      期待wOBA 99 / 打球速度 97 / バレル率 96 / 四球率 93
      スイング長 91 / バットスピード 79 / 走塁 57
      三振率 30 / 空振り率 11

  パーセンタイルは**「上位ほど良い」に揃えてある**（三振が多ければ
  k_percent は低く出る）。そのまま順位として読める。

  キー不要・無料。1日1回取れば十分（シーズン通算の値）。
"""

import argparse
import csv
import functools
import io
import json
import pathlib
import urllib.request

URL = ("https://baseballsavant.mlb.com/leaderboard/percentile-rankings"
       "?type=%s&year=%s&position=&team=&csv=true")
UA = {"User-Agent": "Mozilla/5.0 (compatible; Collespo/1.0)"}
TIMEOUT = 30

# 日本語の呼び名と、**なぜ見るか**。
#
# 説明は画面に出す用（声では読まない）。解説が使う語をそのまま置く。
LABELS = {
    "exit_velocity": ("平均打球速度", "打球がどれだけ速いか"),
    "max_ev": ("最速の打球", "その選手が出せる最大値"),
    "hard_hit_percent": ("ハードヒット率",
                         "打球速度95マイル以上の打球が占める割合"),
    "brl_percent": ("バレル率",
                    "角度と速度が最も安打になりやすい組み合わせに"
                    "入った打球の割合"),
    "bat_speed": ("バットスピード", "スイングの速さ"),
    "squared_up_rate": ("芯で捉えた割合",
                        "その打球速度に対して、どれだけ芯に当たったか"),
    "swing_length": ("スイングの長さ",
                     "バットが描く軌道の長さ。短いほど速く振り出せる"),
    "whiff_percent": ("空振り率", "振ったうち空を切った割合"),
    "chase_percent": ("ボール球を振る割合", "選球眼の目安"),
    "k_percent": ("三振率", "打席のうち三振で終わった割合"),
    "bb_percent": ("四球率", "打席のうち四球で終わった割合"),
    "xba": ("期待打率", "打球の質から期待される打率"),
    "xslg": ("期待長打率", "打球の質から期待される長打率"),
    "xwoba": ("期待wOBA", "打席の結果を得点価値で重みづけた総合の指標"),
    "xiso": ("期待の純長打率", "単打を除いた長打の力"),
    "sprint_speed": ("走る速さ", "全力疾走したときの秒速"),
    "oaa": ("守備で防いだアウト", "平均的な野手と比べて何個多く取ったか"),
    "arm_strength": ("送球の強さ", "野手が投げる球の速さ"),
    # 投手側
    "fastball_velo": ("速球の球速", "いちばん速い球種の平均"),
    "fastball_spin": ("速球の回転数", "1分あたりの回転"),
    "curve_spin": ("カーブの回転数", "同上"),
    "xera": ("期待防御率", "打球の質から期待される防御率"),
    "gb_percent": ("ゴロの割合", "打たせて取る型かどうか"),
}

# 上位・下位これを超えたら「極端」とみなす。
TOP_AT = 90
BOTTOM_AT = 10


@functools.lru_cache(maxsize=4)
def fetch(year=2026, kind="batter") -> dict:
    """{選手ID: {項目: パーセンタイル}}。取れなければ空。

    **1回のリクエストで606人ぶん来る。**選手ごとに呼ぶと同じものを
    何度も取りに行くので、覚えておく（シーズン通算の値なので、
    1日のうちに変わらない）。
    """
    try:
        req = urllib.request.Request(URL % (kind, year), headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8-sig", errors="replace")
    except Exception as e:                               # noqa: BLE001
        print("[info] Savantのパーセンタイルを取れません(%s)"
              % type(e).__name__)
        return {}
    if not body.lstrip().lower().startswith(("player_name", '"player_name')):
        print("[info] Savantの返事がCSVではありません")
        return {}
    out = {}
    for row in csv.DictReader(io.StringIO(body)):
        pid = (row.get("player_id") or "").strip()
        if not pid:
            continue
        vals = {}
        for key, value in row.items():
            if key in ("player_name", "player_id", "year") or not value:
                continue
            try:
                vals[key] = int(float(value))
            except ValueError:
                continue
        if vals:
            out[pid] = {"name": row.get("player_name") or "", **vals}
    return out


def notable(row: dict, top=TOP_AT, bottom=BOTTOM_AT, limit=4) -> list:
    """その選手の、**極端な項目だけ**。真ん中は返さない。

    50前後の項目を並べても「平均です」としか言えない。
    上位と下位だけを、離れている順に返す。
    """
    out = []
    for key, value in (row or {}).items():
        if key == "name" or key not in LABELS:
            continue
        # 「上位0%」とは書かない。100パーセンタイルはリーグ最高のこと。
        if value >= 100:
            side = "リーグ最高"
        elif value >= top:
            side = "リーグ上位%d%%" % (100 - value)
        elif value <= 0:
            side = "リーグ最低"
        elif value <= bottom:
            side = "リーグ下位%d%%" % value
        else:
            continue
        label, why = LABELS[key]
        out.append({"key": key, "label": label, "why": why,
                    "percentile": value, "side": side,
                    "high": value >= top})
    # 端に近い順（50から遠い順）
    out.sort(key=lambda r: -abs(r["percentile"] - 50))
    return out[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2026")
    ap.add_argument("--kind", default="batter", choices=("batter", "pitcher"))
    ap.add_argument("--out", default="")
    ap.add_argument("--player", default="", help="選手IDを指定して中身を見る")
    args = ap.parse_args()

    rows = fetch(args.year, args.kind)
    print("%d人ぶん取れました（%s）" % (len(rows), args.kind))
    if args.player:
        row = rows.get(args.player) or {}
        print("== %s" % (row.get("name") or args.player))
        for x in notable(row, limit=8):
            print("   %-16s %3d（%s） … %s"
                  % (x["label"], x["percentile"], x["side"], x["why"]))
    if args.out and rows:
        pathlib.Path(args.out).write_text(
            json.dumps({"year": args.year, "kind": args.kind,
                        "players": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print("-> %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
