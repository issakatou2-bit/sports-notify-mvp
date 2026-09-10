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
)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

# 公式チャンネル。**手で書くのはハンドル名だけ。**
# チャンネルIDは一度引いたら保存先に覚える(MLB版と同じ考え方)。
#
# プレミアリーグは公式チャンネルでフルハイライトを出していない
# (放映権の扱いが他リーグと違う)。取れないものを並べても
# 毎日「0本」と出るだけなので、入れていない。
OFFICIAL = [
    ("UEFAChampionsLeague", "チャンピオンズリーグ"),
    ("LaLiga", "ラ・リーガ"),
    ("SerieA", "セリエA"),
    ("Bundesliga", "ブンデスリーガ"),
    ("Ligue1", "リーグ・アン"),
]

# 題にこれが入っているものだけをハイライトと見なす。
# 公式は記者会見・特集・過去の名場面も出す。
HIGHLIGHT_WORDS = ("highlight", "extended", "all goals", "resumen",
                   "goles", "zusammenfassung", "resume")


def _state(path: str) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def channel_id(api_key: str, handle: str, cache: dict) -> str:
    """ハンドル名からチャンネルID。一度引いたら覚える。"""
    got = (cache.get("channel_ids") or {}).get(handle)
    if got:
        return got
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
        print(f"[warn] {handle} が見つかりません", file=sys.stderr)
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] {handle} を引けません: {e}", file=sys.stderr)
    return ""


def recent(api_key: str, cid: str, hours: int) -> list:
    """そのチャンネルの直近の投稿。ハイライトだけ。"""
    if not cid:
        return []
    uploads = "UU" + cid[2:]
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


def clubs(title: str) -> list:
    """題から2つのクラブ名。取れなければ空。"""
    head = re.split(r"[|｜(]", title)[0].strip()
    parts = [p.strip(" -–") for p in SPLIT.split(head)
             if p.strip(" -–")]
    if len(parts) != 2:
        return []
    return [p for p in parts if 2 <= len(p) <= 40]


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
    rows = []
    for handle, name_jp in OFFICIAL:
        cid = channel_id(api_key, handle, cache)
        if cid:
            ids[handle] = cid
        got = recent(api_key, cid, args.hours)
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
             "channel_ids": ids, "videos": []}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 0

    counts = views(api_key, rows)
    for r in rows:
        r["views"] = counts.get(r["video_id"], 0)
        cs = clubs(r["title"])
        r["clubs"] = cs
        r["matchup_jp"] = " 対 ".join(club_name_jp(c) for c in cs) if cs else ""
        r["jp_players"] = jp_in(r["title"])

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
           "channel_ids": ids, "videos": rows[:args.top]}
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
