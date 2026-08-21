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


# 崖と呼ぶ落ち込み。この幅より急に減った区間を「切られた場所」とする。
#
# 隣り合う2点の差で見ると見つからない。曲線は100点あるので、
# 1点は動画の1%(1秒未満)しかなく、6秒で6割落ちていても
# 1点あたりでは15%ずつにしか見えない。人はそんな刻みで
# 動画を切らない。区間で見る。
CLIFF_DROP = 0.30
CLIFF_WINDOW = 5   # 何点ぶんを1つの区間として見るか(動画の5%)

# 曲線を取る本数。1本1リクエストなので、再生数の多いものから。
CURVE_TOP = 5


def retention_curve(yta, video_id: str, start, end) -> list:
    """
    その動画の、どこまで見られたか。[(位置0-1, 残っている割合), ...]

    平均維持率だけでは、なだらかに減ったのか1か所で切られたのかが
    分からない。実測では同じ枠の2本が、片方は6秒地点で6割落ち、
    もう片方は最後まで3割を保っていた。平均が19%と50%という差より、
    直すべき場所が違うことの方が大事になる。
    """
    try:
        r = yta.reports().query(
            ids="channel==MINE", startDate=start.isoformat(),
            endDate=end.isoformat(), metrics="audienceWatchRatio",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}").execute()
    except HttpError:
        return []
    return [(row[0], row[1]) for row in (r.get("rows") or [])]


def find_cliff(curve: list) -> tuple:
    """いちばん急に落ちた区間の終わりと、その落ち幅。無ければ (None, 最大幅)。"""
    worst, drop_at = 0.0, None
    for i in range(CLIFF_WINDOW, len(curve)):
        drop = curve[i - CLIFF_WINDOW][1] - curve[i][1]
        if drop > worst:
            worst, drop_at = drop, curve[i][0]
    return (drop_at, worst) if worst >= CLIFF_DROP else (None, worst)


def half_at(curve: list):
    """
    見ていた人が半分になる位置。0〜1。最後まで半分を保てば None。

    崖より先にこれを見る。崖が無くても、5%の時点で半分になっていれば
    そこが問題で、60%まで半分が残っていれば形としては良い。
    ループ再生で最初が1.0を超えるので、開始点を基準に測る。
    """
    if not curve:
        return None
    base = max(v for _, v in curve[:3]) or 1.0
    for pos, v in curve:
        if v <= base * 0.5:
            return pos
    return None


def _report(why: str) -> None:
    """取れなかった理由を実行ページに出す。

    このステップは continue-on-error なので、落ちても回は緑で終わる。
    理由はログの奥にしか残らず、実際 data/analytics.json は8/19で
    止まったまま2日気づかれなかった。何をすれば直るのかまで書く。
    """
    s = os.environ.get("GITHUB_STEP_SUMMARY")
    if not s:
        return
    with open(s, "a", encoding="utf-8") as f:
        f.write("\n## アナリティクスが取れませんでした\n\n")
        f.write("- %s\n" % why)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--out", default="data/analytics.json")
    ap.add_argument("--curves", action="store_true", default=True,
                    help="再生数上位の離脱曲線も取る")
    ap.add_argument("--no-curves", dest="curves", action="store_false")
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
            # 上位50本だけを取っていたので、本数が50を超えてから
            # 中央値も「再生10回未満が何本あるか」も測れなくなっていた。
            # 見えていないのは必ず下位——つまり、いちばん知りたい側。
            sort="-views", maxResults=200,
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
                _report("Google Cloud で YouTube Analytics API が"
                        "有効になっていません。"
                        "console.cloud.google.com/apis/library/"
                        "youtubeanalytics.googleapis.com で有効にしてください")
            else:
                print("[info] 分析の権限がありません。"
                      "yt-analytics.readonly を足したトークンが要ります "
                      "(README の手順を参照)")
                _report("トークンに yt-analytics.readonly が入っていません。"
                        "`python scripts/youtube_auth.py` で取り直して、"
                        "YOUTUBE_REFRESH_TOKEN を入れ替えてください")
            return 0
        print(f"[warn] 取得に失敗しました: {e}", file=sys.stderr)
        _report("取得に失敗しました: %s" % str(e)[:200])
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
        # videos.list は1回50件まで。上限を200に上げたので、
        # 50で切ると51本目から題名が空になる——そして空になるのは
        # 再生数の少ない側、つまり調べたい側から先に消える。
        ids = [r["video"] for r in rows]
        for i in range(0, len(ids), 50):
            try:
                v = yt.videos().list(part="snippet,contentDetails",
                                     id=",".join(ids[i:i + 50])).execute()
                for it in v.get("items", []):
                    titles[it["id"]] = it["snippet"]["title"]
            except HttpError:
                pass

    # 再生数の多いものだけ、曲線も取る。1本1リクエストなので全部は取らない。
    curves = {}
    if args.curves:
        for r in rows[:CURVE_TOP]:
            c = retention_curve(yta, r["video"], start, end)
            if c:
                curves[r["video"]] = c

    store = load(args.out)
    today = end.isoformat()
    store.setdefault("days", {})[today] = {
        "range": [start.isoformat(), end.isoformat()],
        "videos": [{**r, "title": titles.get(r.get("video"), ""),
                    **({"curve": curves[r["video"]]}
                       if r.get("video") in curves else {})}
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

    # 取れたことを実行ページに書く。
    #
    # このステップは continue-on-error なので、落ちても回は緑になる。
    # そのぶん、取れていないことに誰も気づけない。実際 data/analytics.json
    # は8/19の1回きりで、2日ぶん静かに欠けていた。数字を見ようとした
    # ときに初めて分かるのでは遅い。
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## アナリティクス\n\n")
            f.write(f"- {end} の分を {len(rows)}本ぶん取りました\n")
            f.write(f"- 残っている日: {', '.join(sorted(store['days'])[-5:])}\n")
    print(f"\n{'維持率':>7s} {'再生':>6s} {'秒':>4s}  題名")
    for r in rows[:12]:
        print(f"{r.get('averageViewPercentage', 0):6.1f}% "
              f"{int(r.get('views', 0)):6d} "
              f"{int(r.get('averageViewDuration', 0)):4d}  "
              f"{titles.get(r.get('video'), r.get('video'))[:46]}")

    if curves:
        print("\n--- どこで切られたか ---")
        for r in rows[:CURVE_TOP]:
            c = curves.get(r.get("video"))
            if not c:
                continue
            at, drop = find_cliff(c)
            h = half_at(c)
            name = titles.get(r.get("video"), "")[:38]
            hs = f"半減 {h * 100:3.0f}%地点" if h is not None else "半減せず   "
            cs = (f"/ 崖 {at * 100:3.0f}%地点で{drop * 100:.0f}%減"
                  if at is not None else f"/ 崖なし(最大{drop * 100:.0f}%)")
            print(f"  {hs} {cs}  {name}")

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
        if curves:
            lines += ["", "### どこで切られたか", "",
                      "平均だけでは、なだらかに減ったのか1か所で切られたのか"
                      "が分かりません。半分が離れる位置が遅いほど良い形です。",
                      "",
                      "| 半分が離れる位置 | 崖 | 題名 |", "|---|---|---|"]
            for r in rows[:CURVE_TOP]:
                c = curves.get(r.get("video"))
                if not c:
                    continue
                at, drop = find_cliff(c)
                h = half_at(c)
                name = titles.get(r.get("video"), "")[:40]
                hs = f"{h * 100:.0f}%地点" if h is not None else "最後まで半分以上"
                cs = (f"{at * 100:.0f}%地点で{drop * 100:.0f}%減"
                      if at is not None else "なし")
                lines.append(f"| {hs} | {cs} | {name} |")
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
