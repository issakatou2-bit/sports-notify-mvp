"""
選手の試合ログから「その日ならではの見どころ」を検出する。

なぜ試合ログを見るのか:
  順位表や季節通算成績からは「今どういう状態か」しか分からない。
  「移籍後初登板」「4試合連続安打中」のような、その日限りの文脈は
  1試合ずつの記録を並べて初めて見えてくる。
  しかもこれらは推測ではなく、試合ログから機械的に確認できる事実なので、
  「検証できるものだけを書く」という方針を崩さずに情報量を増やせる。

設計方針:
  - 毎日必ず何かを出すものではない。条件を満たしたときだけ返す
  - API呼び出しを抑えるため、AI要約の対象になる上位数試合に限って呼ぶ
  - 取得に失敗した場合は静かに何も返さない(本体の生成は止めない)
"""

import sys

try:
    import requests
except ImportError:  # ネットワーク無効環境でのimportエラーを避ける
    requests = None

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# 連続安打は、これ以上続いていたら言及に値するとみなす
MIN_HIT_STREAK = 4
# 移籍後の登板・出場は、これ以下なら「まだ日が浅い」として言及に値する
MAX_DEBUT_GAMES = 3


def _fetch_game_log(player_id: str, season: str, group: str) -> list:
    """今季の試合ログを、日付の古い順で返す。失敗時は空リスト。"""
    if not player_id or requests is None:
        return []
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={"stats": "gameLog", "group": group, "season": season},
            timeout=15,
        )
        resp.raise_for_status()
        splits = []
        for st in resp.json().get("stats", []):
            splits.extend(st.get("splits", []))
        splits.sort(key=lambda s: s.get("date", ""))
        return splits
    except Exception as e:
        print(f"[warn] 試合ログの取得に失敗(player_id={player_id}): {e}", file=sys.stderr)
        return []


def detect_hitting_notes(player_id: str, player_name: str, team_id: str, season: str) -> list:
    """打者向けの見どころを返す(該当が無ければ空リスト)"""
    notes = []
    log = _fetch_game_log(player_id, season, "hitting")
    if not log:
        return notes

    # --- 連続安打 ---
    streak = 0
    for split in reversed(log):
        stat = split.get("stat") or {}
        at_bats = int(stat.get("atBats") or 0)
        hits = int(stat.get("hits") or 0)
        if at_bats == 0:
            continue  # 出場していない試合は連続を切らない扱いにする
        if hits > 0:
            streak += 1
        else:
            break
    if streak >= MIN_HIT_STREAK:
        notes.append(f"{player_name}は{streak}試合連続安打中")

    # --- 移籍後の出場数 ---
    with_team = [s for s in log if str((s.get("team") or {}).get("id", "")) == team_id]
    if 0 < len(with_team) <= MAX_DEBUT_GAMES and len(with_team) < len(log):
        notes.append(f"{player_name}は移籍後{len(with_team)}試合目")
    elif not with_team and len(log) > 0:
        notes.append(f"{player_name}は移籍後まだ出場していない")

    return notes


def detect_pitching_notes(player_id: str, player_name: str, team_id: str, season: str) -> list:
    """先発投手向けの見どころを返す(該当が無ければ空リスト)"""
    notes = []
    log = _fetch_game_log(player_id, season, "pitching")
    if not log:
        return notes

    with_team = [s for s in log if str((s.get("team") or {}).get("id", "")) == team_id]
    if not with_team and len(log) > 0:
        notes.append(f"{player_name}は移籍後初登板")
    elif 0 < len(with_team) <= MAX_DEBUT_GAMES and len(with_team) < len(log):
        notes.append(f"{player_name}は移籍後{len(with_team) + 1}登板目")

    # --- 直近の好投が続いているか ---
    # 自責点1以下に抑えた登板が続いている場合のみ言及する
    quality = 0
    for split in reversed(with_team or log):
        stat = split.get("stat") or {}
        try:
            er = int(stat.get("earnedRuns") or 0)
            ip = float(stat.get("inningsPitched") or 0)
        except (TypeError, ValueError):
            break
        if ip >= 5.0 and er <= 1:
            quality += 1
        else:
            break
    if quality >= 3:
        notes.append(f"{player_name}は直近{quality}登板を自責1以下に抑えている")

    return notes
