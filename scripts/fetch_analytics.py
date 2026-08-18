#!/usr/bin/env python3
"""
公開した動画が、実際どう見られたかを取ってくる。

なぜ要るのか:
  維持率も再生数も、これまで人が Studio の画面から書き写していた。
  毎回の作業になるうえ、変化に気づくのが見に行った時だけになる。

  数字が自動で残れば、「1枚目を変えた翌日に維持率が動いたか」を
  こちらが機械的に比べられる。改善したつもりのものが効いていないことに、
  その日のうちに気づける。

  Studioの画面と同じ値を、YouTube Analytics API から引く。

必要な権限:
  https://www.googleapis.com/auth/yt-analytics.readonly

  いまの認証(youtube.upload と youtube)には入っていない。
  追加したトークンを取り直す必要がある。手順は README にある。
  権限が無い場合は静かに飛ばす(他の処理を止めない)。

何を取るか:
  動画ごとに、再生数・平均視聴率・平均視聴秒数・高評価・登録者の増減。
  日付ごとに data/analytics.json へ積む。上書きせず足す。

出力: data/analytics.json

使い方:
  python3 scripts/fetch_analytics.py --days 28
"""

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("[warn] Google APIライブラリが無いためスキップします")
    sys.exit(0)

TOKEN_URI = "https://oauth2.googleapis.com/token"
JST = timezone(timedelta(hours=9))

# 取る指標。Studioの画面に出ているものと同じ。
METRICS = ("views,estimatedMinutesWatched,averageViewDuration,"
           "averageViewPercentage,likes,subscribersGained")


def client(service: str, version: str):
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return None
    # scopes は渡さない(渡すと invalid_scope になる。他と同じ)
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=cid, client_secret=secret)
    return build(service, version, credentials=creds, cache_discovery=False)


def load(path: str) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--out", default="data/analytics.json")
    args = ap.parse_args()

    yta = client("youtubeAnalytics", "v2")
    if yta is None:
        return 0

    end = datetime.now(JST).date()
    start = end - timedelta(days=args.days)
    try:
        res = yta.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(), endDate=end.isoformat(),
            metrics=METRICS, dimensions="video",
            sort="-views", maxResults=50,
        ).execute()
    except HttpError as e:
        if e.resp.status in (401, 403):
            # 403は2つの理由で返る。取り違えると、直っているトークンを
            # 何度も取り直すことになる(実際そうなった)ので、書き分ける。
            body = (getattr(e, "content", b"") or b"").decode("utf-8", "replace")
            if "accessNotConfigured" in body or "has not been used in project" in body:
                print("[info] Google Cloud で YouTube Analytics API が"
                      "有効になっていません。トークンは正しいので、"
                      "コンソールで有効にすれば通ります:")
                print("       https://console.cloud.google.com/apis/library/"
                      "youtubeanalytics.googleapis.com")
            else:
                print("[info] 分析の権限がありません。"
                      "yt-analytics.readonly を足したトークンが要ります "
                      "(README の手順を参照)")
            return 0
        print(f"[warn] 取得に失敗しました: {e}", file=sys.stderr)
        return 0

    cols = [h["name"] for h in res.get("columnHeaders", [])]
    rows = []
    for row in res.get("rows", []):
        rows.append(dict(zip(cols, row)))
    if not rows:
        print("[info] 対象の動画がありません")
        return 0

    # 題名を添える。IDだけでは、どの枠の数字か読めない。
    titles = {}
    yt = client("youtube", "v3")
    if yt:
        ids = [r["video"] for r in rows][:50]
        try:
            v = yt.videos().list(part="snippet,contentDetails",
                                 id=",".join(ids)).execute()
            for it in v.get("items", []):
                titles[it["id"]] = it["snippet"]["title"]
        except HttpError:
            pass

    store = load(args.out)
    today = end.isoformat()
    store.setdefault("days", {})[today] = {
        "range": [start.isoformat(), end.isoformat()],
        "videos": [{**r, "title": titles.get(r.get("video"), "")}
                   for r in rows],
    }
    # 積み上げるが、際限なく増やさない。90日あれば季節の比較もできる。
    days = sorted(store["days"])[-90:]
    store["days"] = {d: store["days"][d] for d in days}

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, ensure_ascii=False, indent=2),
                 encoding="utf-8")

    print(f"[info] {len(rows)}本ぶんを取りました ({start} 〜 {end})")
    print(f"\n{'維持率':>7s} {'再生':>6s} {'秒':>4s}  題名")
    for r in rows[:12]:
        print(f"{r.get('averageViewPercentage', 0):6.1f}% "
              f"{int(r.get('views', 0)):6d} "
              f"{int(r.get('averageViewDuration', 0)):4d}  "
              f"{titles.get(r.get('video'), r.get('video'))[:46]}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["## 動画ごとの数字", "",
                 "| 維持率 | 再生 | 平均秒 | 題名 |", "|---|---|---|---|"]
        for r in rows[:15]:
            lines.append(
                f"| {r.get('averageViewPercentage', 0):.1f}% "
                f"| {int(r.get('views', 0))} "
                f"| {int(r.get('averageViewDuration', 0))} "
                f"| {titles.get(r.get('video'), '')[:44]} |")
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
