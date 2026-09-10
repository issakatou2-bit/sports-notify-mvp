#!/usr/bin/env python3
"""欧州サッカーの公式ハイライトから、その日いちばん見られたものを選ぶ。

なぜ要るのか:
  10月にMLBのポストシーズンが終わると、3月まではサッカーが主になる。
  いまサッカーは「明日の注目試合」1本だけで、MLBは7本ある。
  **枠の数がそのまま差になっている。**

  MLB側で動いている仕組み——公式ハイライトのコメントを取って訳す、
  そこから長編を作る——は、材料が「公式チャンネルのハイライト」で
  あることしか前提にしていない。**サッカーでもそのまま動く。**

  ここはその入口。どの試合のコメントを読むかを決める。

MLB版との違い:
  ・チャンネルが1つではない。大会ごとに公式がある
  ・日本人選手がいるクラブは名簿から引ける(`jp_players_for_club`)。
    **題に名前が出るかどうかで再生が2.8倍違う**ので、
    日本人選手がいる試合を優先する
  ・題の形が大会ごとに違う。対戦カードの取り出しは緩く見る

使い方:
  python3 scripts/soccer_buzz.py --out data/soccer_buzz.json
"""

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from notability_engine import (  # noqa: E402
    club_name_jp,
    jp_players_for_club,
    normalize_club,
)

# 公式が題で使う略記 → 正式名。
#
# club_name_jp は "milan" を意図して持っていない。"Inter Milan" と
# 部分一致してしまうので、"acmilan" で登録してある（その理由は
# notability_engine の表のコメントに書いてある）。
# ところがセリエA公式は「JUVENTUS-MILAN」と書く。単独の MILAN は
# ACミランなので、ここで正式名に直してから渡す。
ALIAS = {
    "milan": "AC Milan",
    "inter": "FC Internazionale Milano",
    "atleti": "Atletico Madrid",
    "barca": "FC Barcelona",
    "psg": "Paris Saint-Germain",
    "bayern": "FC Bayern Munchen",
    "dortmund": "Borussia Dortmund",
    "spurs": "Tottenham",
}


def canon(name: str) -> str:
    """略記を正式名に。知らない名前はそのまま返す。"""
    return ALIAS.get(normalize_club(name), name)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

# 公式チャンネル。**手で書くのはハンドル名だけ。**
# チャンネルIDは一度引いたら保存先に覚える(MLB版と同じ考え方)。
#
# プレミアリーグは公式チャンネルでフルハイライトを出していない
# (放映権の扱いが他リーグと違う)。取れないものを並べても
# 毎日「0本」と出るだけなので、入れていない。
# ハンドル名は**候補を順に試す。**1つ書いて外すと、その大会が
# 丸ごと消えたまま毎日「0本」と出る。9/10に
# "UEFAChampionsLeague" で引けず、CLが取れなかった。
OFFICIAL = [
    (("ChampionsLeague", "uefachampionsleague", "UEFA"),
     "チャンピオンズリーグ"),
    (("LaLiga",), "ラ・リーガ"),
    (("SerieA",), "セリエA"),
    (("Bundesliga",), "ブンデスリーガ"),
    (("Ligue1",), "リーグ・アン"),
]

# 題にこれが入っていたら、試合のハイライトではない。
#
# 9/10に実際に拾ってしまったもの:
#   「Ordenamos los 15 GOLES de AUBAMEYANG」  選手のゴール集
#   「ALL ROUND 3 HIGHLIGHTS | PRIMAVERA 1」  ユースリーグ
# 公式チャンネルはトップチームの試合以外もたくさん出す。
NOT_MATCH = ("primavera", "youth", "u19", "u21", "u23", "femenino",
             "femminile", "frauen", "women", "academy", "futsal",
             "esports", "efootball", "best goals", "top 5", "top 10",
             "goals of the", "ordenamos", "compilation")

# 題にこれが入っているものだけをハイライトと見なす。
# 公式は記者会見・特集・過去の名場面も出す。
HIGHLIGHT_WORDS = ("highlight", "extended", "all goals", "resumen",
                   "goles", "zusammenfassung", "resume")


def _state(path: str) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def channel_id(api_key: str, handles, cache: dict) -> str:
    """ハンドル名の候補を順に試して、チャンネルID。一度引いたら覚える。"""
    if isinstance(handles, str):
        handles = (handles,)
    for h in handles:
        got = (cache.get("channel_ids") or {}).get(h)
        if got:
            return got
    for h in handles:
        cid = _one_handle(api_key, h)
        if cid:
            return cid
    print(f"[warn] {handles} のどれも引けません", file=sys.stderr)
    return ""


def _one_handle(api_key: str, handle: str) -> str:
    try:
        r = requests.get(f"{YOUTUBE_API}/channels",
                         params={"key": api_key, "part": "id",
                                 "forHandle": handle}, timeout=20)
        r.raise_for_status()
        items = r.json().get("items") or []
        if items:
            cid = items[0].get("id") or ""
            if cid:
                print(f"[info] {handle} のチャンネルIDを覚えました: {cid}")
                return cid
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] {handle} を引けません: {e}", file=sys.stderr)
    return ""


def uploads_playlist(api_key: str, cid: str) -> str:
    """投稿一覧のプレイリストID。

    「UCの2文字目をUに変える」という対応は公開仕様で、MLB公式では
    そのまま通る。**だがCL公式では404だった。**
    (UCLcSuj4B8YyUVJdVDeozFQg → UULcSuj4B8YyUVJdVDeozFQg が Not Found)

    規則で当てずに、APIに聞く。1回の呼び出しで済むし、
    チャンネルIDと一緒に覚えておける。
    """
    try:
        r = requests.get(f"{YOUTUBE_API}/channels",
                         params={"key": api_key, "part": "contentDetails",
                                 "id": cid}, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items") or []:
            pl = ((it.get("contentDetails") or {})
                  .get("relatedPlaylists") or {}).get("uploads")
            if pl:
                return pl
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] 投稿一覧のIDを引けません: {e}", file=sys.stderr)
    # 引けなければ規則で当てる。MLB公式ではこれで通っている。
    return "UU" + cid[2:] if cid else ""


def recent(api_key: str, cid: str, hours: int, uploads: str = "") -> list:
    """そのチャンネルの直近の投稿。ハイライトだけ。"""
    if not cid:
        return []
    uploads = uploads or ("UU" + cid[2:])
    after = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        r = requests.get(f"{YOUTUBE_API}/playlistItems",
                         params={"key": api_key, "part": "snippet",
                                 "playlistId": uploads, "maxResults": 50},
                         timeout=20)
        r.raise_for_status()
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] 投稿一覧を取れません: {e}", file=sys.stderr)
        return []
    out = []
    for it in r.json().get("items", []):
        sn = it.get("snippet") or {}
        vid = (sn.get("resourceId") or {}).get("videoId")
        pub = sn.get("publishedAt", "")
        title = sn.get("title", "")
        if not (vid and pub):
            continue
        try:
            when = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < after:
            continue
        low = title.lower()
        if not any(w in low for w in HIGHLIGHT_WORDS):
            continue
        if any(w in low for w in NOT_MATCH):
            continue
        out.append({"video_id": vid, "title": title, "published_at": pub})
    return out


def views(api_key: str, items: list) -> dict:
    """再生回数をまとめて取る。1回で50本まで。"""
    if not items:
        return {}
    ids = ",".join(i["video_id"] for i in items[:50])
    try:
        r = requests.get(f"{YOUTUBE_API}/videos",
                         params={"key": api_key, "part": "statistics",
                                 "id": ids}, timeout=20)
        r.raise_for_status()
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] 再生回数を取れません: {e}", file=sys.stderr)
        return {}
    out = {}
    for it in r.json().get("items", []):
        try:
            out[it.get("id")] = int((it.get("statistics") or {})
                                    .get("viewCount", 0))
        except (TypeError, ValueError):
            continue
    return out


# 対戦カードの取り出し。大会ごとに題の形が違う。
#
#   "Liverpool 2-1 Atletico Madrid | Highlights"
#   "Real Madrid vs Barcelona | LaLiga 2026/27"
#   "Bayern - Dortmund | Highlights"
#
# 区切りは vs / - / 数字-数字 のどれか。**推測はここまで。**
# 取れなければ空にして、題をそのまま使う。
SPLIT = re.compile(r"\s+(?:vs\.?|v)\s+|\s+\d+\s*[-–]\s*\d+\s+"
                   r"|\s+[-–]\s+", re.I)


# 大文字だけのハイフン区切り。セリエAの公式がこの形。
#
#   "JUVENTUS-MILAN 1-1 | EXTENDED HIGHLIGHTS"
#   "Gattuso Vince Ancora | UDINESE-LAZIO | HIGHLIGHTS"
#
# スペースの無いハイフンを一律に切ると "Saint-Etienne" が
# 2つに割れる。**両側が大文字だけのときに限る。**
UPPER_PAIR = re.compile(r"^([A-Z][A-Z .'&]{2,})-([A-Z][A-Z .'&]{2,})$")


# 題の先頭に付く言い回し。セリエAの公式が使う。
#
#   "MAXI SINTESI ROMA-ATALANTA 2-1 | EXTENDED HIGHLIGHTS"
#
# これを落とさないと、対戦カードが「MAXI SINTESI ROMA」対
# 「ATALANTA」になる。クラブ名は2語のこともある（REAL MADRID）ので、
# 「最後の語だけ取る」ではなく、**知っている前置きを落とす。**
PREFIX = ("maxi sintesi", "sintesi", "extended highlights", "highlights")


def _pair(text: str) -> list:
    """1つの断片から2つのクラブ名。取れなければ空。"""
    text = text.strip()
    for w in PREFIX:
        if text.lower().startswith(w):
            text = text[len(w):].strip(" :-–")
            break
    if not text:
        return []
    m = UPPER_PAIR.match(re.sub(r"\s+\d+\s*[-–]\s*\d+\s*$", "", text).strip())
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    parts = [x.strip(" -–") for x in SPLIT.split(text) if x.strip(" -–")]
    if len(parts) != 2:
        return []
    return [x for x in parts if 2 <= len(x) <= 40]


def clubs(title: str) -> list:
    """題から2つのクラブ名。取れなければ空。

    **題の全部を見る。**先頭だけを見ていたので、セリエAの
    「Gattuso Vince Ancora | UDINESE-LAZIO | HIGHLIGHTS」のように
    見出しが先に来る形を1本も拾えなかった（9/10に11本落とした）。
    """
    for part in re.split(r"[|｜(]", title):
        got = _pair(part)
        if len(got) == 2:
            return [canon(x) for x in got]
    return []


def jp_in(title: str) -> list:
    """その試合に出ている日本人選手。名簿から引く。"""
    out = []
    for c in clubs(title):
        for p in jp_players_for_club(c):
            if p["name_jp"] not in out:
                out.append(p["name_jp"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/soccer_buzz.json")
    ap.add_argument("--hours", type=int, default=30)
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("[info] YOUTUBE_API_KEY がありません")
        return 0

    cache = _state(args.out)
    ids = dict(cache.get("channel_ids") or {})
    ups = dict(cache.get("uploads") or {})
    rows = []
    for handles, name_jp in OFFICIAL:
        cid = channel_id(api_key, handles, cache)
        uploads = ""
        if cid:
            ids[handles[0]] = cid
            uploads = (cache.get("uploads") or {}).get(cid) or                 uploads_playlist(api_key, cid)
            ups[cid] = uploads
        got = recent(api_key, cid, args.hours, uploads)
        print(f"[info] {name_jp}: ハイライト {len(got)}本")
        for g in got:
            g["competition"] = name_jp
        rows += got

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        print("[info] ハイライトが1本もありません")
        p.write_text(json.dumps(
            {"updated_at": datetime.now(timezone.utc).isoformat(),
             "channel_ids": ids, "uploads": ups, "videos": []}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 0

    counts = views(api_key, rows)
    keep = []
    for r in rows:
        cs = clubs(r["title"])
        # **対戦カードが取れないものは捨てる。**
        #
        # コメント欄の回は「◯◯対◯◯のファンが何と言ったか」で作る。
        # カードが分からないと、その名乗りが嘘になる。
        # 選手のゴール集やユースの回は、ここで落ちる。
        if not cs:
            print(f"[info] 対戦カードが取れないので外します: "
                  f"{r['title'][:52]}")
            continue
        r["views"] = counts.get(r["video_id"], 0)
        r["clubs"] = cs
        r["matchup_jp"] = " 対 ".join(club_name_jp(c) for c in cs)
        r["jp_players"] = jp_in(r["title"])
        keep.append(r)
    rows = keep
    if not rows:
        print("[info] 試合のハイライトが1本もありません")
        p.write_text(json.dumps(
            {"updated_at": datetime.now(timezone.utc).isoformat(),
             "channel_ids": ids, "uploads": ups, "videos": []}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 0

    # 再生順に並べ、**日本人選手がいる試合を先頭へ。**
    #
    # 8/11〜9/8のMLBの実測で、題に日本人選手の名前がある動画は
    # 平均395再生・登録+12、無い動画は192再生・登録0。
    # 名前を作るのではなく、あれば選ぶ。
    rows.sort(key=lambda x: -x["views"])
    named = [r for r in rows if r["jp_players"]]
    if named:
        top = named[0]
        rows.remove(top)
        rows.insert(0, top)
        print(f"[info] 日本人選手がいる試合を先頭へ: "
              f"{'・'.join(top['jp_players'])} / {top['title'][:48]}")

    out = {"updated_at": datetime.now(timezone.utc).isoformat(),
           "channel_ids": ids, "uploads": ups,
           "videos": rows[:args.top]}
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    print()
    for r in out["videos"]:
        jp = ""
        if r["jp_players"]:
            jp = "  [" + "・".join(r["jp_players"]) + "]"
        print(f"   {r['views']:>9,}回  {r['competition']}  "
              f"{r['matchup_jp'] or r['title'][:40]}{jp}")
    print(f"[done] {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
