#!/usr/bin/env python3
"""MLBの日本人選手名簿が、いまの登録と合っているか。

なぜ要るのか:
  `JP_PLAYERS_MLB` も手で書いた名簿で、自動では更新されない。
  サッカーの名簿が16人抜けていたのと同じ形の穴が、こちらにもある。

  9/9に調べたところ、**Rikuu Nishida（ホワイトソックス）が
  名簿に無かった。**12試合29打数7安打で出場している。
  名簿に無い選手は、成績ランキングにも題にも一度も出ない。

  MLBは移籍期限が7月末、開幕が3月末。**その前後で人が動く。**
  シーズン中の昇格・降格もある。

何をするか:
  MLB公式の `sports/1/players` から、出身国が日本の選手を引いて
  手元の名簿と突き合わせる。**直しはしない。**差分を出すだけ。

  ヌートバー（母が日本人、出身はアメリカ）のように、出身国では
  引けない選手がいる。名簿にあってAPIに無い、という向きの差分は
  **それだけで間違いとは言えない**ので、そう書いて出す。
"""

import json
import pathlib
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import mlb_splits  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
SEASON = "2026"


def main() -> int:
    from notability_engine import JP_PLAYERS_MLB

    try:
        with urllib.request.urlopen(
                f"{API}/sports/1/players?season={SEASON}", timeout=60) as r:
            people = json.loads(r.read()).get("people") or []
    except Exception as e:                       # noqa: BLE001
        print(f"[info] 名簿を引けません: {type(e).__name__}")
        return 0
    if not people:
        print("[info] 選手が1人も返りませんでした")
        return 0

    jp = {p.get("fullName") or "": p for p in people
          if (p.get("birthCountry") or "") == "Japan"}
    mine = {p["name_en"]: p for p in JP_PLAYERS_MLB}
    print(f"[info] {SEASON}年の登録 {len(people)}人 / 出身が日本 {len(jp)}人")
    print(f"[info] 手元の名簿 {len(mine)}人")
    print()

    add = [n for n in jp if n not in mine]
    if add:
        print("--- 名簿に無い（足す候補） ---")
        for n in sorted(add):
            p = jp[n]
            pid = p.get("id")
            line = ""
            try:
                with urllib.request.urlopen(
                        f"{API}/people/{pid}/stats?stats=season"
                        f"&season={SEASON}&group=hitting", timeout=20) as r:
                    for st in json.loads(r.read()).get("stats", []):
                        # 移籍した選手は合計と球団ごとの行が両方返る。
                        s = mlb_splits.season_stat(st.get("splits"))
                        if s:
                            line = (f"{s.get('gamesPlayed')}試合 "
                                    f"{s.get('atBats')}打数 "
                                    f"{s.get('hits')}安打 "
                                    f"{s.get('homeRuns')}本")
                            break
            except Exception:                    # noqa: BLE001
                pass
            pos = (p.get("primaryPosition") or {}).get("abbreviation") or ""
            print(f"  ★{n} ({pos}) id={pid} {line}")
    else:
        print("--- 名簿に無い選手: なし ---")

    print()
    gone = [n for n in mine if n not in jp]
    if gone:
        print("--- APIに見当たらない ---")
        print("  ※ 出身国が日本でない選手（ヌートバーなど）は、ここに必ず出る。")
        print("  ※ 登録抹消・マイナー降格でも出る。**それだけでは間違いではない。**")
        for n in sorted(gone):
            print(f"   {n} / 名簿では {mine[n].get('name_jp')}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
