#!/usr/bin/env python3
"""サッカーの日本人選手名簿が、いまの所属と合っているか。

なぜ要るのか:
  `JP_PLAYERS_SOCCER` は**手で書いた25人の名簿**で、自動では
  更新されない。定義のコメントにこう書いてある。

    2026年8月4日に外部の一覧記事と突き合わせて更新。
    欧州の移籍市場は9月2日早朝(日本時間)まで開いているため、
    **閉幕後にもう一度確認すること。**

  移籍市場は9月2日に閉じた。名簿は8月11日を最後に触られていない。
  つまり**8月の移籍が反映されていない可能性がある。**

  所属が違えば、「◯◯のいるクラブの試合」という題も、画面も、
  読み上げも、その日ぜんぶ間違う。**題は日本人選手名で作っていて、
  それがこの番組でいちばん効いている材料**なので、ここが古いのは痛い。

何をするか:
  football-data.org から各リーグのチームと選手を引いて、
  日本国籍の選手を拾い、手元の名簿と突き合わせる。
  **直しはしない。**差分を出すだけ。名簿はコードなので、
  人が見てから直す。

  無料枠で選手まで取れるかは、叩いてみないと分からない。
  取れなければ、そう出して終わる（それも知りたいことのうち）。
"""

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

BASE = "https://api.football-data.org/v4"
# 名簿にあるリーグ。football-data.org のコード。
LEAGUES = {"PL": "プレミアリーグ", "PD": "ラ・リーガ", "SA": "セリエA",
           "BL1": "ブンデスリーガ", "FL1": "リーグ・アン",
           "ELC": "イングランド2部", "BL2": "ドイツ2部"}


def _get(path: str, token: str):
    req = urllib.request.Request(BASE + path,
                                 headers={"X-Auth-Token": token})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def main() -> int:
    token = os.environ.get("FOOTBALL_DATA_API_KEY") or ""
    if not token:
        print("[info] FOOTBALL_DATA_API_KEY がありません")
        return 0
    from notability_engine import JP_PLAYERS_SOCCER

    mine = {p["name_en"]: p for p in JP_PLAYERS_SOCCER}
    found = {}
    reachable = 0
    for code, jp_name in LEAGUES.items():
        try:
            d = _get(f"/competitions/{code}/teams", token)
        except urllib.error.HTTPError as e:
            print(f"[info] {jp_name}({code}): 取れません HTTP {e.code}")
            continue
        except Exception as e:                   # noqa: BLE001
            print(f"[info] {jp_name}({code}): {type(e).__name__}")
            continue
        reachable += 1
        teams = d.get("teams") or []
        squads = sum(len(t.get("squad") or []) for t in teams)
        print(f"[info] {jp_name}({code}): {len(teams)}クラブ / "
              f"選手 {squads}人")
        for t in teams:
            for pl in (t.get("squad") or []):
                if (pl.get("nationality") or "") != "Japan":
                    continue
                found[pl.get("name") or ""] = {
                    "team_en": t.get("name") or "",
                    "league": code,
                    "position": pl.get("position") or "",
                }
        time.sleep(6)                # 無料枠は10回/分

    print()
    if not reachable:
        print("**どのリーグも引けませんでした。**無料枠の範囲外の可能性。")
        print("名簿は手で確かめるしかありません。")
        return 0
    if not found:
        print("**選手の一覧が返っていません。**"
              "無料枠では squad が空のようです。")
        print("名簿は手で確かめるしかありません。")
        return 0

    print("--- APIが返した日本国籍の選手 ---")
    for name in sorted(found):
        row = found[name]
        have = mine.get(name)
        if not have:
            print(f"  ★名簿に無い: {name} / {row['team_en']} ({row['league']})")
        elif row["team_en"] != have["team_en"]:
            print(f"  ★所属が違う: {name} / 名簿「{have['team_en']}」"
                  f" → いま「{row['team_en']}」")
        else:
            print(f"   一致: {name} / {row['team_en']}")
    print()
    gone = [n for n in mine if n not in found]
    if gone:
        print("--- APIに見当たらない（移籍・離脱の可能性） ---")
        for n in gone:
            print(f"  ★{n} / 名簿では {mine[n]['team_en']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
