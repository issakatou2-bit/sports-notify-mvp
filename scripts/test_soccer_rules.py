"""
サッカーの採点を、取得側が実際に作るのと同じ形の入力で検証する。

なぜこのテストが要るのか:
  サッカー用のルールを入れたとき、Game.league に競技会コード("PD")を
  渡すテストを書いて通していた。しかし fetch_soccer_games_and_standings は
  日本語のリーグ名("ラ・リーガ")を入れる。判定はコードとしか
  突き合わせていなかったので、ルールは本番で1つも発火せず、
  開幕日の全試合が0点になっていた。テストは緑のままだった。

  ここでは取得側と同じ値を入れる。合わせるべきは仕様書ではなく、
  実際にデータへ入っている値。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import notability_engine as ne  # noqa: E402
from notability_engine import Game, Standing  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {label}: {got}" + ("" if ok else f" (期待 {want})"))


def make(league, home, away, i=0):
    """取得側と同じ形。league には日本語のリーグ名が入る。"""
    return Game(game_id=f"g{i}", league=league,
                home_team_id=f"h{i}", away_team_id=f"a{i}",
                home_team_name=home, away_team_name=away,
                start_time_utc="2026-08-22T19:00:00Z")


# --- 競技の判定 -------------------------------------------------------------
print("--- リーグの見分け(コードと日本語名の両方) ---")
for lg in ("PD", "ラ・リーガ", "PL", "プレミアリーグ", "CL", "チャンピオンズリーグ"):
    check(f"{lg} はサッカー", ne.is_soccer(make(lg, "A", "B")), True)
check("MLB はサッカーでない", ne.is_soccer(make("MLB", "A", "B")), False)

# --- 実際のリーグ名でルールが発火するか -------------------------------------
print("\n--- 日本語のリーグ名で採点する ---")
CASES = [
    ("ラ・リーガ", "FC Barcelona", "Real Madrid CF", True, "エル・クラシコ"),
    ("セリエA", "AC Milan", "FC Internazionale Milano", True, "ミラノ・ダービー"),
    ("プレミアリーグ", "Liverpool FC", "Brighton & Hove Albion FC", True, "日本人選手"),
    ("ラ・リーガ", "Deportivo Alavés", "Getafe CF", False, "中位同士"),
]
for league, home, away, want_notable, note in CASES:
    out = ne.build_output([make(league, home, away)], {}, {})
    g = out["games"][0]
    check(f"{note}: {g['matchup']}", bool(g.get("is_notable")), want_notable)
    if g.get("is_notable"):
        for r in g.get("reasons") or []:
            print(f"      {r.get('text')}")

# --- 表記が日本語になるか ---------------------------------------------------
print("\n--- クラブ名の表記 ---")
out = ne.build_output([make("ラ・リーガ", "FC Barcelona", "Real Madrid CF")], {}, {})
check("matchup が日本語", out["games"][0]["matchup"], "バルセロナ vs レアル・マドリード")
# 区切りの "vs" は残してよい。クラブ名の側に英字が残っていないかを見る。
check("クラブ名に英字が残っていない",
      any(c.isascii() and c.isalpha() for c in
          out["games"][0]["home_team_name"] + out["games"][0]["away_team_name"]),
      False)

# --- 今季の順位が付いている時期 ---------------------------------------------
print("\n--- 順位表がある場合 ---")
st = {"h0": Standing(team_id="h0", division_rank=1, games_back=0.0,
                     win_streak=0, points_back=0.0),
      "a0": Standing(team_id="a0", division_rank=2, games_back=0.3,
                     win_streak=0, points_back=1.0)}
out = ne.build_output([make("プレミアリーグ", "Arsenal FC", "Manchester City FC")],
                      st, {})
g = out["games"][0]
check("上位対決が注目になる", bool(g.get("is_notable")), True)
texts = " / ".join(r.get("text", "") for r in g.get("reasons") or [])
check("勝ち点差で語る(ゲーム差と書かない)", "ゲーム差" in texts, False)
print(f"      {texts}")

# --- MLBが壊れていないか ----------------------------------------------------
print("\n--- MLB側に影響が無いこと ---")
mlb = Game(game_id="m", league="MLB", home_team_id="119", away_team_id="135",
           home_team_name="ドジャース", away_team_name="パドレス",
           start_time_utc="2026-08-22T02:10:00Z")
out = ne.build_output([mlb], {}, {"119": ["大谷翔平", "山本由伸"]})
g = out["games"][0]
check("日本人選手の所属が理由になる",
      any(r.get("tag") == "jp_team" for r in g.get("reasons") or []), True)
check("表記は変えない", g["matchup"], "ドジャース vs パドレス")

print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
