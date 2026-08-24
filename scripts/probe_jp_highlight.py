#!/usr/bin/env python3
"""
「日本人選手が活躍した試合のハイライトに、コメントが付いているか」を測る。

なぜ測るのか:
  日本人選手の称賛だけを別の動画にする案が出ている。作れるかどうかは、
  3つの条件が同じ日に揃うかで決まる。

    1. その日、貢献スコアが高い日本人選手がいる
    2. その選手が出た試合の公式ハイライトが上がっている
    3. そのハイライトにコメントが付いていて、選手の名前が出ている

  1は手元の履歴で測れる(9日で60点以上が8日)。2と3はAPIを叩かないと
  分からない。サッカーのときと同じで、作る前に確かめる。

  特に3が肝心で、公式ハイライトのコメントは試合全体への反応だから、
  日本人選手の名前が出ている割合が低ければ、集めても中身が薄い。
  注目カード(ドジャース戦)と、そうでないカードで差が出るはずで、
  そこも見たい。

出力: 何も保存しない。表と結論を出すだけ。

使い方:
  YOUTUBE_API_KEY=xxx python3 scripts/probe_jp_highlight.py
"""

import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import requests

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import morning_recap as mr          # noqa: E402
import mlb_buzz as mb               # noqa: E402
from textkey import fold, surname   # noqa: E402

API = "https://www.googleapis.com/youtube/v3"

# ここ以上を「活躍」とみなす下限。手元9日の最高点の中央値が82、
# 60点以上の日が8/9。低すぎると毎日出て日次動画と変わらなくなり、
# 高すぎると出ない日が続く。まず60で当ててみて、実際の頻度を見る。
FLOOR = 60


def out(line=""):
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + chr(10))


def uploads_items(key, cid, pages=3):
    """投稿一覧を複数ページ読む。1ページ50本、1ユニット。"""
    items, token = [], None
    for _ in range(pages):
        p = {"key": key, "part": "snippet", "playlistId": "UU" + cid[2:],
             "maxResults": 50}
        if token:
            p["pageToken"] = token
        r = requests.get(API + "/playlistItems", params=p, timeout=25)
        r.raise_for_status()
        d = r.json()
        for it in d.get("items", []):
            sn = it.get("snippet") or {}
            vid = (sn.get("resourceId") or {}).get("videoId")
            if vid and "Highlights" in sn.get("title", ""):
                items.append({"id": vid, "title": sn.get("title", ""),
                              "at": sn.get("publishedAt", "")})
        token = d.get("nextPageToken")
        if not token:
            break
    return items


def stats(key, ids):
    """再生数とコメント数。50本まで1ユニット。"""
    got = {}
    for i in range(0, len(ids), 50):
        r = requests.get(API + "/videos",
                         params={"key": key, "part": "statistics",
                                 "id": ",".join(ids[i:i + 50])}, timeout=25)
        r.raise_for_status()
        for it in r.json().get("items", []):
            s = it.get("statistics") or {}
            got[it["id"]] = (int(s.get("viewCount") or 0),
                             int(s.get("commentCount") or 0))
    return got


def comments(key, vid, n=100):
    got, token = [], None
    while len(got) < n:
        p = {"part": "snippet", "videoId": vid, "key": key,
             "order": "relevance", "maxResults": 100,
             "textFormat": "plainText"}
        if token:
            p["pageToken"] = token
        r = requests.get(API + "/commentThreads", params=p, timeout=25)
        if r.status_code == 403:
            return None                      # コメント無効
        r.raise_for_status()
        d = r.json()
        for it in d.get("items", []):
            c = ((it.get("snippet") or {}).get("topLevelComment")
                 or {}).get("snippet") or {}
            got.append({"t": (c.get("textOriginal") or "").strip(),
                        "likes": int(c.get("likeCount") or 0)})
        token = d.get("nextPageToken")
        if not token:
            break
    return got


def mentions(text, names_en):
    """本文にその選手の名字が出てくるか。textkey で表記ゆれを吸う。"""
    body = fold(text)
    for en in names_en:
        s = fold(surname(en))
        if len(s) >= 4 and s in body:
            return True
    return False


def main():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        out("YOUTUBE_API_KEY が未設定です")
        return 1

    out("## 日本人選手ハイライトの実測")
    out()

    cid = mb._official_channel_id(key, "data/mlb_buzz.json")
    if not cid:
        out("チャンネルIDが取れませんでした")
        return 1
    ups = uploads_items(key, cid)
    out("MLB公式の直近の投稿から取れたハイライト: **%d本**" % len(ups))
    out()

    # 日付ごとに、ハイライトのカードを日本語で持っておく
    by_day = {}
    for it in ups:
        try:
            d = datetime.fromisoformat(it["at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        jp = mb.jp_matchup(mb.extract_matchup(it["title"]))
        by_day.setdefault(d.strftime("%Y-%m-%d"), []).append(
            dict(it, jp=jp))

    rows, checked = [], []
    for f in sorted(pathlib.Path("data/recap_history").glob("*.json"))[-6:]:
        day = f.stem
        data = json.loads(f.read_text(encoding="utf-8"))
        players = sorted(data.get("players") or [],
                         key=lambda p: -mr.contribution(p))
        if not players:
            continue
        top = players[0]
        sc = mr.contribution(top)
        team = top.get("team_jp", "")
        # ハイライトは試合当日か翌日に上がる
        cands = by_day.get(day, []) + by_day.get(
            (datetime.strptime(day, "%Y-%m-%d")
             + timedelta(days=1)).strftime("%Y-%m-%d"), [])
        hit = next((c for c in cands if team and team in c["jp"]), None)
        rows.append((day, top.get("name", ""), sc, team,
                     hit["jp"] if hit else "—", hit["id"] if hit else ""))
        if hit and sc >= FLOOR:
            checked.append((day, top, hit,
                            [p for p in players
                             if p.get("team_jp") == team]))

    out("| 日 | 最高の日本人選手 | 点 | 球団 | 見つかったハイライト |")
    out("|---|---|---:|---|---|")
    for day, name, sc, team, jp, _ in rows:
        out("| %s | %s | %d | %s | %s |" % (day, name, sc, team, jp))
    out()

    ids = [r[5] for r in rows if r[5]]
    st = stats(key, ids) if ids else {}
    out("| ハイライト | 再生 | コメント |")
    out("|---|---:|---:|")
    for day, name, sc, team, jp, vid in rows:
        if not vid:
            continue
        v, c = st.get(vid, (0, 0))
        out("| %s %s | %s | %s |" % (day, jp, format(v, ","), format(c, ",")))
    out()

    out("### コメントに名前が出ているか")
    out()
    out("| 試合 | 選手 | 読んだ | 名前あり | 割合 |")
    out("|---|---|---:|---:|---:|")
    for day, top, hit, same in checked[-4:]:
        cs = comments(key, hit["id"])
        if cs is None:
            out("| %s | %s | コメント無効 | | |" % (day, top.get("name")))
            continue
        names = [p.get("name_en", "") for p in same if p.get("name_en")]
        n = sum(1 for c in cs if mentions(c["t"], names))
        out("| %s %s | %s | %d | %d | %d%% |"
            % (day, hit["jp"], "/".join(surname(x) for x in names),
               len(cs), n, round(100 * n / max(1, len(cs)))))
        for c in sorted(cs, key=lambda x: -x["likes"]):
            if mentions(c["t"], names):
                out("| | 例 | %s | | |" % c["t"][:90].replace("|", " "))
                break
    out()
    out("FLOOR=%d 以上で、ハイライトも見つかった日: **%d / %d**"
        % (FLOOR, len(checked), len(rows)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
