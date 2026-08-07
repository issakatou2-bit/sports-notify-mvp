"""
選手の所属チームの変化を日々の差分から検知し、
「APIで裏が取れたものだけ」をニュースとして出力する。

なぜ差分だけでは足りないのか:
  差分から分かるのは「所属が変わった」という事実のみで、
  それがトレードなのか、ウェーバーなのか、FAなのかは区別できない。
  また、マイナー昇降格・故障者リスト入り・APIの一時的な不整合でも、
  名簿上は同じように「消えた/現れた」ように見えてしまう。
  そのため、差分はあくまで「候補」として扱い、
  別のエンドポイントで裏を取れたものだけを公開する設計にしている。

検証(ファクトチェック)の内容:
  1. /people/{id} で現在の所属チームを問い合わせ、差分の結果と一致するか確認する
     (一致しなければ、APIの一時的な不整合とみなして破棄)
  2. 「移籍後まだ出場していない」と書く場合は、今季の試合ログを取得し、
     新チームでの出場が実際に0であることを確認する
  検証に落ちた候補は、一切出力しない。

表現について:
  移籍の理由(トレード/ウェーバー/FA)はAPIから判別できないため、
  「トレードで」のような踏み込んだ表現は使わず、
  「◯◯へ移籍」という、どの経路でも事実として正しい表現に留める。

入出力:
  data/roster_snapshot.json … 前回の所属一覧(比較用、リポジトリにコミットする)
  public/news.json          … その日の検証済みニュース(毎日上書き、非コミット)
  data/news_log.json        … 検証済みニュースの履歴(日付つきで蓄積、コミットする)
                              週次まとめ動画の「今週の動き」がこれを読む

使い方:
  python3 scripts/detect_roster_changes.py \
      --snapshot data/roster_snapshot.json --out public/news.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# 1回の実行で検証にかけるAPI呼び出しの上限。
# 開幕直後やトレード期限直後は変化が大量に出るため、上限を設けないと
# API呼び出しが数百回に膨れ上がる。
MAX_VERIFY_CALLS = 40

# ニュースとして出す最大件数
MAX_NEWS = 3


def fetch_current_rosters(season: str) -> dict:
    """
    今シーズンのMLB選手一覧を取得し、{player_id: {...}} を返す。
    notability_engine.py と同じ /sports/1/players を使う。
    """
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/sports/1/players",
            params={"season": season},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] 選手一覧の取得に失敗しました: {e}", file=sys.stderr)
        return {}

    out = {}
    for p in resp.json().get("people", []):
        pid = str(p.get("id", ""))
        team = p.get("currentTeam") or {}
        if not pid:
            continue
        out[pid] = {
            "name": p.get("fullName", ""),
            "team_id": str(team.get("id", "")),
            "team_name": team.get("name", ""),
            "pos": (p.get("primaryPosition") or {}).get("abbreviation", ""),
        }
    return out


def verify_current_team(player_id: str, expected_team_id: str) -> bool:
    """
    選手の現所属チームを個別に問い合わせ、差分の結果と一致するか確認する。
    一致しない場合はAPIの一時的な不整合の可能性があるため、falseを返す。
    """
    try:
        resp = requests.get(f"{MLB_API_BASE}/people/{player_id}", timeout=10)
        resp.raise_for_status()
        people = resp.json().get("people", [])
        if not people:
            return False
        actual = str((people[0].get("currentTeam") or {}).get("id", ""))
        return actual == expected_team_id
    except Exception as e:
        print(f"[warn] 所属確認に失敗(player_id={player_id}): {e}", file=sys.stderr)
        return False


def count_games_with_team(player_id: str, team_id: str, season: str, group: str) -> int:
    """
    今季の試合ログから、指定チームでの出場数を数える。
    「移籍後まだ出場していない」と書く根拠に使う。
    取得できなかった場合は -1 を返す(呼び出し側で『検証できなかった』扱いにする)。
    """
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={
                "stats": "gameLog",
                "group": group,
                "season": season,
            },
            timeout=15,
        )
        resp.raise_for_status()
        count = 0
        for st in resp.json().get("stats", []):
            for split in st.get("splits", []):
                if str((split.get("team") or {}).get("id", "")) == team_id:
                    count += 1
        return count
    except Exception as e:
        print(f"[warn] 試合ログの取得に失敗(player_id={player_id}): {e}", file=sys.stderr)
        return -1


def build_candidates(prev: dict, current: dict) -> list:
    """
    前回と今回の所属を比較し、ニュース候補を作る。
    ここではまだ検証していない「候補」であることに注意。
    """
    candidates = []
    for pid, now in current.items():
        before = prev.get(pid)
        if not before:
            continue  # 新規登場は昇格・初登録など理由が多様なため、今は扱わない
        if not now.get("team_id") or not before.get("team_id"):
            continue
        if now["team_id"] != before["team_id"]:
            candidates.append(
                {
                    "player_id": pid,
                    "name": now["name"],
                    "pos": now.get("pos", ""),
                    "from_team": before.get("team_name", ""),
                    "to_team": now.get("team_name", ""),
                    "to_team_id": now["team_id"],
                }
            )
    return candidates


def score_candidate(c: dict, jp_names: set) -> int:
    """
    ニュースの注目度を決める。試合のスコアリングと同じ考え方で、
    「日本の読者にとっての注目度」を基準にする。
    """
    score = 1
    if c["name"] in jp_names:
        score += 5  # 日本人選手が絡む移籍は最優先
    if c.get("pos") in ("P", "SP"):
        score += 1  # 投手は先発予定と結びつきやすい
    return score


# ニュースの履歴を残す日数。週次まとめ(7日)に余裕を持たせた長さ。
# 際限なく貯めると差分コミットが重くなるだけなので、ここで打ち切る。
NEWS_LOG_DAYS = 60


def append_news_log(log_path: pathlib.Path, verified: list) -> None:
    """
    検証を通ったニュースを、日付つきで履歴ファイルへ積む。

    なぜ履歴が要るのか:
      public/news.json は「その日の検知結果」で毎日上書きされ、しかも
      public/ はリポジトリにコミットされない。そのため週次のまとめ動画からは
      過去の動きを一切参照できず、「今週の動き」の枠が常に空になっていた。
      data/ は日次ワークフローがコミットしているので、ここに積めば
      週次側から1週間分をまとめて読める。

    同じ移籍が複数日に渡って検知された場合は、最初に出た日付だけを残す。
    """
    entries = []
    if log_path.exists():
        try:
            entries = json.loads(log_path.read_text(encoding="utf-8")).get("entries", [])
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] ニュース履歴を読めませんでした(作り直します): {e}", file=sys.stderr)

    known = {e.get("text") for e in entries}
    today = datetime.now(timezone.utc).date()
    added = 0
    for item in verified:
        if item.get("text") in known:
            continue
        entries.append({
            "date": today.isoformat(),
            "text": item["text"],
            "name": item.get("name"),
            "player_id": item.get("player_id"),
        })
        known.add(item.get("text"))
        added += 1

    cutoff = (today - timedelta(days=NEWS_LOG_DAYS)).isoformat()
    entries = [e for e in entries if (e.get("date") or "") >= cutoff]
    entries.sort(key=lambda e: e.get("date") or "")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[info] ニュース履歴に{added}件追加しました"
          f"(保持{len(entries)}件 / 直近{NEWS_LOG_DAYS}日)-> {log_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default="data/roster_snapshot.json")
    parser.add_argument("--out", default="public/news.json")
    parser.add_argument(
        "--log",
        default="data/news_log.json",
        help="検証を通ったニュースを日付つきで積む履歴ファイル(週次まとめが読む)",
    )
    parser.add_argument("--season", default=None)
    parser.add_argument(
        "--jp-names",
        default="",
        help="日本人選手の英語名をカンマ区切りで(スコア加点用、省略可)",
    )
    args = parser.parse_args()

    season = args.season or str(datetime.now(timezone.utc).year)
    jp_names = {n.strip() for n in args.jp_names.split(",") if n.strip()}

    current = fetch_current_rosters(season)
    if not current:
        print("[warn] 選手一覧が取得できなかったため、今回は何もしません")
        return

    snap_path = pathlib.Path(args.snapshot)
    prev = {}
    if snap_path.exists():
        try:
            with open(snap_path, "r", encoding="utf-8") as f:
                prev = json.load(f).get("players", {})
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] 前回のスナップショットを読めませんでした: {e}", file=sys.stderr)

    # 次回の比較用に、今回の状態を必ず保存する(ニュースが出せたかに関わらず)
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(
            {"updated_at": datetime.now(timezone.utc).isoformat(), "players": current},
            f,
            ensure_ascii=False,
        )

    if not prev:
        print("[info] 前回の記録が無いため、今回は比較をスキップしました(次回から検知できます)")
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"updated_at": None, "news": []}, f, ensure_ascii=False)
        return

    candidates = build_candidates(prev, current)
    print(f"[info] 所属変更の候補: {len(candidates)}件")

    candidates.sort(key=lambda c: -score_candidate(c, jp_names))

    verified = []
    calls = 0
    for c in candidates:
        if len(verified) >= MAX_NEWS or calls >= MAX_VERIFY_CALLS:
            break

        # 検証1: 本当にそのチームに所属しているか
        calls += 1
        if not verify_current_team(c["player_id"], c["to_team_id"]):
            print(f"[info] 検証に落ちたため除外: {c['name']}(所属確認が取れず)")
            continue

        item = {
            "player_id": c["player_id"],
            "name": c["name"],
            "from_team": c["from_team"],
            "to_team": c["to_team"],
            # 移籍の経路(トレード/ウェーバー/FA)はAPIから判別できないため、
            # どの経路でも事実として正しい表現に留める
            "text": f"{c['name']}が{c['from_team']}から{c['to_team']}へ移籍",
        }

        # 検証2: 新チームでまだ出場していないか(書ける場合のみ付記する)
        group = "pitching" if c.get("pos") in ("P", "SP", "RP") else "hitting"
        calls += 1
        played = count_games_with_team(c["player_id"], c["to_team_id"], season, group)
        if played == 0:
            item["text"] += "。新チームでの出場はこれから"
            item["debut_pending"] = True
        elif played > 0:
            item["debut_pending"] = False

        verified.append(item)

    print(f"[info] 検証を通過: {len(verified)}件(API呼び出し{calls}回)")

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "news": verified,
            },
            f,
            ensure_ascii=False,
        )
    print(f"[info] ニュースを出力しました -> {out_path}")

    append_news_log(pathlib.Path(args.log), verified)


if __name__ == "__main__":
    main()
