#!/usr/bin/env python3
"""
MLBの球場ごとに、資産動画1本ぶんの材料を作る。

なぜ要るのか:
  資産動画は24本作って、24本とも投稿し終えた。在庫がゼロになった。
  常緑ものは実測で維持率76.3%と、日次の倍以上まで見られている。
  見られれば最後まで見られるのに、出す玉が無い。

  手で書くと1本ずつ調べることになり、毎日は続かない。
  球場は30あって、収容人数もフィールドの寸法も標高も
  MLB公式APIから取れる。しかも全部の球場で数字が違う。
  1つの型で30本ぶん、中身の違うものが作れる。

何を書くか:
  APIの数字と、notability_engine が既に持っている球場の一文だけ。
  こちらで新しく評価や解釈を書き足さない。
  「◯番目に深い」は30球場を並べれば決まる事実なので入れる。

  手書きで作った5球場(クアーズ、フェンウェイ、オラクル、リグレー、
  ヤンキー)は既に出しているので飛ばす。あちらの方が踏み込んでいる。

出力: data/venue_topics.json

使い方:
  python3 scripts/venue_topics.py
  python3 scripts/venue_topics.py --out data/venue_topics.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import MLB_VENUE_NOTES  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

# 手書きで作って投稿済みの球場。あちらの方が踏み込んだ内容なので出さない。
ALREADY = {"Coors Field", "Fenway Park", "Oracle Park",
           "Wrigley Field", "Yankee Stadium"}

FT_TO_M = 0.3048

ROOF_JP = {"Open": "屋根なし", "Dome": "ドーム",
           "Retractable": "開閉式の屋根"}
TURF_JP = {"Grass": "天然芝", "Artificial": "人工芝"}


def m(feet) -> int:
    """フィートをメートルに。日本の視聴者にはこちらが通じる。"""
    return round((feet or 0) * FT_TO_M)


def fetch() -> list:
    """現用30球場ぶんの、寸法と所在地。"""
    teams = requests.get(f"{API}/teams", params={"sportId": 1},
                         headers=UA, timeout=30).json().get("teams", [])
    home = {}
    for t in teams:
        v = t.get("venue") or {}
        if v.get("id"):
            home[v["id"]] = t.get("name", "")

    vs = requests.get(f"{API}/venues",
                      params={"sportId": 1,
                              "hydrate": "location,fieldInfo"},
                      headers=UA, timeout=30).json().get("venues", [])
    out = []
    for v in vs:
        if v["id"] not in home:
            continue
        f = v.get("fieldInfo") or {}
        if not f.get("capacity") or not f.get("center"):
            continue
        out.append({"name": v["name"], "team_en": home[v["id"]],
                    "field": f, "loc": v.get("location") or {}})
    return out


def rank_of(value, values, high_first=True) -> int:
    """その数字が何番目か。同値は同順位にする。"""
    ordered = sorted(values, reverse=high_first)
    return ordered.index(value) + 1


def build_items(v: dict, all_v: list, where: str = "") -> list:
    """その球場の項目。数字と、30球場の中での位置だけ。"""
    f, loc = v["field"], v["loc"]
    n = len(all_v)
    items = []

    cap = f["capacity"]
    cr = rank_of(cap, [x["field"]["capacity"] for x in all_v])
    items.append((f"収容 {cap:,}人",
                  f"MLB{n}球場のなかで{cr}番目の大きさです"))

    cen = f["center"]
    dr = rank_of(cen, [x["field"]["center"] for x in all_v])
    deep = "いちばん深い" if dr == 1 else f"{dr}番目に深い"
    items.append((f"中堅まで {cen}フィート",
                  f"およそ{m(cen)}メートル。{n}球場で{deep}中堅です"))

    left, right = f.get("leftLine"), f.get("rightLine")
    if left and right:
        gap = abs(left - right)
        note = (f"左翼線が{gap}フィート長い" if left > right
                else f"右翼線が{gap}フィート長い") if gap >= 5 else \
            "左右がほぼ同じ長さです"
        items.append((f"両翼 {left} / {right}フィート",
                      f"左が約{m(left)}メートル、右が約{m(right)}メートル。"
                      f"{note}"))

    elev = loc.get("elevation")
    if elev is not None:
        er = rank_of(elev, [x["loc"].get("elevation") or 0 for x in all_v])
        items.append((f"標高 {elev}フィート",
                      f"およそ{m(elev)}メートル。{n}球場で{er}番目に"
                      "高い場所にあります"))

    roof = ROOF_JP.get(f.get("roofType"), "")
    turf = TURF_JP.get(f.get("turfType"), "")
    if roof or turf:
        # 所在地は日本語の表記を使う。APIの city は "Anaheim" のままで、
        # 画面にも読み上げにも英語がそのまま出てしまう。
        items.append(("　".join(x for x in (roof, turf) if x),
                      f"{where or loc.get('city', '')}にあります"))
    return items


def hook_of(v: dict, all_v: list, gist: str = "") -> str:
    """1枚目に出す、その球場でいちばん際立つ数字。"""
    f, loc = v["field"], v["loc"]
    n = len(all_v)
    cen_rank = rank_of(f["center"], [x["field"]["center"] for x in all_v])
    cap_rank = rank_of(f["capacity"], [x["field"]["capacity"] for x in all_v])
    el = loc.get("elevation") or 0
    el_rank = rank_of(el, [x["loc"].get("elevation") or 0 for x in all_v])
    gap = abs((f.get("leftLine") or 0) - (f.get("rightLine") or 0))

    # 順位が上か下に振り切れているものを選ぶ。真ん中の数字は特徴にならない。
    #
    # 数字の大小だけを見ていたら、19球場が「収容4万人、中堅400フィート」で
    # 終わった。どこも同じくらいの大きさなのだから当然で、その球場を
    # 他と分けているのは大小ではなく、屋根や芝のような「少数派かどうか」。
    cands = []
    if cen_rank <= 3:
        cands.append((cen_rank, f"中堅{f['center']}フィート、{n}球場で"
                                + ("いちばん深い" if cen_rank == 1
                                   else f"{cen_rank}番目に深い")))
    if cen_rank >= n - 2:
        cands.append((1, f"中堅{f['center']}フィート、"
                         f"{n}球場でいちばん浅い部類"))
    if cap_rank <= 3:
        cands.append((cap_rank, f"収容{f['capacity']:,}人、"
                                f"{n}球場で{cap_rank}番目に大きい"))
    if cap_rank >= n - 2:
        cands.append((1, f"収容{f['capacity']:,}人、"
                         f"{n}球場でいちばん小さい部類"))
    if el_rank <= 3:
        cands.append((el_rank, f"標高{el}フィート、"
                               f"{n}球場で{el_rank}番目に高い"))
    # 少数派の設備。数がそのまま珍しさなので、何球場あるかを添える。
    roofs = [x["field"].get("roofType") for x in all_v]
    turfs = [x["field"].get("turfType") for x in all_v]
    roof, turf = f.get("roofType"), f.get("turfType")
    # 開閉式は7球場ある。珍しくはあるが、7本の動画が同じ言葉で始まると
    # チャンネルの一覧に同じ絵が並ぶ。その球場だけの数字を先に使う。
    if roof == "Dome":
        cands.append((2, f"{ROOF_JP[roof]}　{n}球場で{roofs.count(roof)}つだけ"))
    if turf == "Artificial":
        cands.append((2, f"人工芝　{n}球場で{turfs.count(turf)}つだけ"))
    if gap >= 8:
        cands.append((3, f"両翼の差が{gap}フィート"))
    if roof == "Retractable":
        cands.append((6, f"{ROOF_JP[roof]}　{n}球場で{roofs.count(roof)}つだけ"))
    if cands:
        return sorted(cands)[0][1]

    # どの数字も30球場の真ん中なら、その球場が何で知られているかを使う。
    # 「収容4万人、中堅400フィート」はどこの球場にも当てはまってしまい、
    # 1枚目に置く言葉としては何も言っていないのと同じ。
    if gist:
        # 読点で切らない。「外野が広く、本塁打が出にくい球場」を「、」で
        # 切ると「外野が広く」で終わり、言いかけたまま画面に残る。
        # 1文まるごと入るときだけ使い、入らなければ数字に落とす。
        head = gist.split("。")[0].strip().rstrip("、")
        if head.endswith("の本拠地"):
            head = ""   # 球場名の言い換えでしかなく、特徴になっていない
        if 6 <= len(head) <= 26:
            return head
    return f"収容{f['capacity']:,}人　中堅{f['center']}フィート"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/venue_topics.json")
    args = ap.parse_args()

    vs = fetch()
    print(f"[info] 現用の球場: {len(vs)}")

    topics = []
    for v in vs:
        # 命名権で名前が変わることがある("UNIQLO Field at Dodger Stadium")。
        # 完全一致で引けなければ、元の球場名を含むものを探す。
        note = MLB_VENUE_NOTES.get(v["name"])
        if not note:
            for en, row in MLB_VENUE_NOTES.items():
                if en in v["name"]:
                    note = row
                    break
        if not note:
            print(f"[info] 日本語名が無いため飛ばします: {v['name']}")
            continue
        if v["name"] in ALREADY:
            continue
        jp, gist, _team_id, where = note
        key = "venue_" + v["name"].lower().replace(" ", "_").replace(".", "")
        topics.append({
            "key": key,
            "label": jp,
            "heading": jp,
            "hook": hook_of(v, vs, gist),
            "venue_en": v["name"],
            "where": where,
            "intro": f"{where}。{gist}。数字で見ていきます。",
            "items": [list(x) for x in build_items(v, vs, where)],
        })

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "MLB Stats API",
        "topics": topics,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[info] {len(topics)}球場ぶんを書き出しました -> {p}\n")
    for t in topics[:5]:
        print(f"  {t['label']}  ({t['hook']})")
        for head, body in t["items"][:2]:
            print(f"     {head} … {body}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
