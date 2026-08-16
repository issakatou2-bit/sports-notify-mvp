"""
過去のアーカイブ(archive/*.json)のうち、最終スコアがまだ記録されていない
試合について、結果を取得して埋める。MLBと欧州5大リーグの両方を見る。

なぜ後から埋める必要があるのか:
  生成(19時JST)の時点では、その日表示する試合はまだ始まってすらいない
  (アメリカ時間の夜=日本時間の朝方に行われるため)。そのため結果は、
  「翌日以降の生成タイミングで、過去分をさかのぼって埋める」しかない。
  このスクリプトは毎日の生成の中で走らせ、直近数日分のアーカイブを
  チェックして、終了済みなのにまだ結果が無い試合があれば埋める。

対象範囲:
  直近 BACKFILL_LOOKBACK_DAYS 日分のアーカイブファイルのみ(際限なく
  過去まで毎回問い合わせるとAPI呼び出しが際限なく増えるため)。

  長らくMLBだけを見ていた。そのためサッカーの試合には結果が一度も入らず、
  答え合わせにも週次の検算にも、サッカーは一切出てこなかった。
  データ源が違う(football-data.org)だけで、やることは同じなので足した。
  FOOTBALL_DATA_API_KEY が無い環境では、サッカーの分だけ静かに飛ばす。

使い方:
  python3 scripts/backfill_results.py --archive-dir archive
"""

import argparse
import json
import os
import pathlib
import sys

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
BACKFILL_LOOKBACK_DAYS = 5

# 5大リーグとCLの日本語名。アーカイブの league にはこの表記が入っている。
SOCCER_LEAGUES = {"プレミアリーグ", "ラ・リーガ", "セリエA",
                  "ブンデスリーガ", "リーグ・アン", "チャンピオンズリーグ"}


def fetch_final_score(game_id: str):
    """
    指定したgamePkの試合が終了していれば (home_score, away_score) を返す。
    未終了・取得失敗の場合はNoneを返す(呼び出し側はスキップして次回また試す)。
    """
    if not game_id:
        return None
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/schedule",
            params={"sportId": 1, "gamePk": game_id},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for date_entry in data.get("dates", []):
            for g in date_entry.get("games", []):
                if str(g.get("gamePk")) != str(game_id):
                    continue
                if g.get("status", {}).get("abstractGameCode") != "F":
                    return None
                home_score = g["teams"]["home"].get("score")
                away_score = g["teams"]["away"].get("score")
                if home_score is None or away_score is None:
                    return None
                return home_score, away_score
    except Exception as e:
        print(f"[warn] game_id={game_id} の結果取得に失敗しました: {e}", file=sys.stderr)
    return None


def fetch_soccer_final_score(game_id: str, api_key: str):
    """
    football-data.org から終了済みの試合のスコアを返す。

    延長・PKまで行った場合、fullTime は90分終了時ではなく延長後の値になる
    (APIの定義がそうなっている)。リーグ戦しか扱っていないので実際には
    起きないが、CLの決勝トーナメントを足すときはここを見直すこと。
    """
    if not (game_id and api_key):
        return None
    try:
        resp = requests.get(f"{FOOTBALL_DATA_BASE}/matches/{game_id}",
                            headers={"X-Auth-Token": api_key}, timeout=10)
        resp.raise_for_status()
        m = resp.json()
        if m.get("status") != "FINISHED":
            return None
        full = (m.get("score") or {}).get("fullTime") or {}
        home, away = full.get("home"), full.get("away")
        if home is None or away is None:
            return None
        return home, away
    except Exception as e:  # noqa: BLE001
        print(f"[warn] game_id={game_id} の結果取得に失敗しました: {e}",
              file=sys.stderr)
    return None


def decide_winner(home: int, away: int) -> str:
    """
    引き分けは "draw"。野球には無いが、サッカーでは3割前後を占める。
    表示側が home/away の2択で書かれていると、引き分けが負け扱いになる。
    """
    if home > away:
        return "home"
    if away > home:
        return "away"
    return "draw"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default="archive")
    args = parser.parse_args()

    archive_dir = pathlib.Path(args.archive_dir)
    if not archive_dir.exists():
        print(f"[warn] {archive_dir} が見つからないためスキップします")
        return

    football_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not football_key:
        print("[info] FOOTBALL_DATA_API_KEY未設定のため、サッカーは飛ばします")

    date_files = sorted(archive_dir.glob("????-??-??.json"), reverse=True)
    targets = date_files[:BACKFILL_LOOKBACK_DAYS]

    updated_files = 0
    updated_games = 0
    for path in targets:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] {path} の読み込みに失敗しました、スキップします: {e}", file=sys.stderr)
            continue

        changed = False
        for g in data.get("games", []):
            if g.get("final_score"):
                continue  # 既に埋め済み
            league = g.get("league")
            if league == "MLB":
                result = fetch_final_score(g.get("game_id"))
            elif league in SOCCER_LEAGUES:
                result = fetch_soccer_final_score(g.get("game_id"), football_key)
            else:
                continue
            if result is None:
                continue
            home_score, away_score = result
            g["final_score"] = {
                "home": home_score,
                "away": away_score,
                "winner": decide_winner(home_score, away_score),
            }
            changed = True
            updated_games += 1

        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            updated_files += 1

    print(f"[info] 結果補完: {updated_files}ファイル、{updated_games}試合を更新しました")


if __name__ == "__main__":
    main()
