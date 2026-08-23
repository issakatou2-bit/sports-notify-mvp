#!/usr/bin/env python3
"""
新しい競技・新しい音声を足す前に、その材料が本当に取れるのかを確かめる。

手元(日本の回線)からはNBAのCDNが403を返す。地域や回線で弾かれている
可能性が高く、それだけでは「取れない」とは言えない。実際に動かすのは
GitHub Actionsのランナー(米国)なので、そこから叩いた結果で判断する。

    python3 scripts/probe_sources.py

判定を人の記憶や一般論ではなく、その場の応答で決めるためのもの。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# NBAの一次情報。認証なしで取れるものから順に並べる。
# balldontlie は無料枠だが鍵が要る(鍵なしなら401が返る = 生きている印)。
SOURCES = [
    ("NBA 今日のスコア",
     "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
     {"Referer": "https://www.nba.com/"}),
    ("NBA シーズン日程",
     "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
     {"Referer": "https://www.nba.com/"}),
    ("NBA 選手名鑑",
     "https://cdn.nba.com/static/json/staticData/lookupIndexes.json",
     {"Referer": "https://www.nba.com/"}),
    ("balldontlie(鍵が要る)",
     "https://api.balldontlie.io/v1/teams", {}),
    # 比較用。ここが通ってNBAだけ落ちるなら、回線ではなく先方の遮断。
    ("MLB(比較用・実績あり)",
     "https://statsapi.mlb.com/api/v1/teams?sportId=1", {}),
]


def probe(name: str, url: str, extra: dict) -> dict:
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
               "Accept-Language": "en-US,en;q=0.9", **extra}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            size = len(raw)
            head = ""
            try:
                data = json.loads(raw)
                head = ", ".join(list(data)[:5]) if isinstance(data, dict) else \
                    f"list {len(data)}件"
            except json.JSONDecodeError:
                head = "(JSONではない)"
            return {"name": name, "ok": True, "status": r.status,
                    "bytes": size, "keys": head}
    except urllib.error.HTTPError as e:
        return {"name": name, "ok": False, "status": e.code,
                "error": e.reason}
    except Exception as e:  # noqa: BLE001
        return {"name": name, "ok": False, "status": None,
                "error": f"{type(e).__name__}: {e}"}


def probe_soccer_detail() -> None:
    """football-data.org の無料枠で、試合の中身がどこまで取れるか。

    MLBと同じ形の枠(その日の日本人選手・貢献スコア・今日の1人)を
    サッカーへ広げられるかは、ここで決まる。
      得点者が取れる     → 「今日のゴール」が作れる
      出場記録が取れる   → 「今日の日本人選手」が作れる
      出場時間が取れる   → 貢献スコアの物差しが作れる

    取れないなら、別のデータ元を探すところから始める話になる。
    想像で構想を書いても、作り始めてから覆る。
    """
    import json as _j
    import os as _os
    import urllib.request as _u
    key = _os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        print("\n[soccer] FOOTBALL_DATA_API_KEY が無いため飛ばします")
        return
    url = ("https://api.football-data.org/v4/competitions/PL/matches"
           "?status=FINISHED&limit=1")
    try:
        req = _u.Request(url, headers={"X-Auth-Token": key,
                                       "User-Agent": "collespo/1.0"})
        d = _j.loads(_u.urlopen(req, timeout=25).read())
    except Exception as e:  # noqa: BLE001
        print(f"\n[soccer] 取れません: {type(e).__name__} {str(e)[:120]}")
        return
    ms = d.get("matches") or []
    if not ms:
        print("\n[soccer] 終了した試合が返りませんでした")
        return
    m = ms[0]
    body = _j.dumps(m, ensure_ascii=False)
    print("\n[soccer] football-data.org 無料枠で返る中身")
    print(f"  項目: {sorted(m)}")
    for label, key_ in (("得点者", "goals"), ("交代", "substitutions"),
                        ("先発", "lineup"), ("警告", "bookings"),
                        ("スタッツ", "statistics")):
        got = m.get(key_)
        n = len(got) if isinstance(got, list) else ("あり" if got else "なし")
        print(f"  {label:8s} {key_:14s} -> {n}")
    print(f"  レスポンス長: {len(body):,} バイト")
    print("  判定: 得点者が取れれば「今日のゴール」、"
          "出場記録が取れれば「今日の日本人選手」が作れます")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="結果のJSON出力先")
    args = ap.parse_args()

    print("一次情報が取れるかを、この環境から実際に叩いて確かめます\n")
    results = []
    for name, url, extra in SOURCES:
        r = probe(name, url, extra)
        results.append(r)
        if r["ok"]:
            print(f"  取れる    {name}")
            print(f"            HTTP {r['status']} / {r['bytes']:,} バイト "
                  f"/ 中身: {r['keys']}")
        else:
            print(f"  取れない  {name}")
            print(f"            HTTP {r['status']} {r.get('error', '')}")

    nba = [r for r in results if r["name"].startswith("NBA")]
    mlb = [r for r in results if r["name"].startswith("MLB")]
    reachable = any(r["ok"] for r in nba)
    if reachable:
        verdict = "NBAの一次情報はこの環境から取れます。実装に進めます。"
    elif mlb and mlb[0]["ok"]:
        verdict = ("MLBは取れてNBAだけ落ちています。回線の問題ではなく、"
                   "NBA側がこのIPを弾いています。鍵の要るAPIを検討してください。")
    else:
        verdict = ("MLBも落ちているので、この環境自体が外に出られていません。"
                   "判定材料になりません。")
    print(f"\n[結論] {verdict}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"reachable": reachable, "verdict": verdict,
                       "results": results}, f, ensure_ascii=False, indent=2)
        print(f"\n結果を書き出しました: {args.out}")

    # 実行ページに結論を出す。成果物を開かないと分からないのでは、
    # 確認のために毎回ダウンロードすることになる。
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## 一次情報の到達性\n\n**{verdict}**\n\n")
            f.write("| 取得先 | 結果 |\n|---|---|\n")
            for r in results:
                mark = "取れる" if r["ok"] else f"取れない (HTTP {r['status']})"
                f.write(f"| {r['name']} | {mark} |\n")

    # 終了コードにも結論を載せる。成功/失敗の色だけで判断できるようにする。
    # 取れない = 失敗 とみなすのは、ここが「取れるか確かめる」ためだけの
    # ワークフローで、取れないことが分かった時点で目的を果たしていないため。
    return 0 if reachable else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
