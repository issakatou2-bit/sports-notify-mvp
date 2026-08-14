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
    print()
    if any(r["ok"] for r in nba):
        print("[結論] NBAの一次情報はこの環境から取れます。実装に進めます。")
    elif mlb and mlb[0]["ok"]:
        print("[結論] MLBは取れてNBAだけ落ちています。回線の問題ではなく、"
              "NBA側がこのIPを弾いています。鍵の要るAPIを検討してください。")
    else:
        print("[結論] MLBも落ちているので、この環境自体が外に出られていません。"
              "判定材料になりません。")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n結果を書き出しました: {args.out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
