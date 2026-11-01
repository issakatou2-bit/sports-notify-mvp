#!/usr/bin/env python3
"""サッカーの試合が0件になる理由を確かめる（読むだけ）。

9/21から、19:00の処理が取るサッカーの試合が毎日0件（土日も）。
9/20までは20件前後取れていた。問い合わせは
  /competitions/{code}/matches?dateFrom=D&dateTo=D
で、同じ日を両端に置いている。APIの振る舞いが変わって終わりの日が
含まれなくなったのか、回数制限なのか、ここで分ける。

使い方（鍵はランナーにしか無い）:
  FOOTBALL_DATA_API_KEY=... python3 scripts/probe_soccer_dates.py
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.football-data.org/v4"


def get(path, key):
    req = urllib.request.Request(BASE + path, headers={"X-Auth-Token": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), {}


def main():
    key = os.environ.get("FOOTBALL_DATA_API_KEY") or ""
    if not key:
        print("鍵がありません")
        return 0
    for day, nxt in (("2026-09-26", "2026-09-27"), ("2026-09-20", "2026-09-21")):
        for label, q in (("同じ日", f"dateFrom={day}&dateTo={day}"),
                         ("翌日まで", f"dateFrom={day}&dateTo={nxt}")):
            st, h, d = get(f"/competitions/PL/matches?{q}", key)
            ms = d.get("matches") or []
            print(f"PL {day} {label}: HTTP {st} / {len(ms)}試合 / 残り"
                  f"{h.get('X-Requests-Available-Minute')} / "
                  f"{[m.get('utcDate') for m in ms][:3]}")
            if st != 200:
                print("   ", json.dumps(d)[:200])
            time.sleep(7)       # 1分10回を超えない
    st, h, d = get("/competitions/PL/matches?matchday=6", key)
    print("PL 第6節:", st, [(m.get("utcDate"), m.get("status"))
                          for m in (d.get("matches") or [])][:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
