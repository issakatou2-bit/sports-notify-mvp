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

    # NBAが取れないことは異常ではなく結果。赤くすると、
    # 他の確認を足したときに毎回赤が出て、意味が薄れる。
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
    # 「取れない」も結果なので、それだけで赤くしない。
    # 赤が常態になると、本当に壊れた日の赤が埋もれる。
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
