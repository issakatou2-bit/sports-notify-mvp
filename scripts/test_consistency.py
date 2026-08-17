"""
同じことを2か所で決めていないか、実際の値で突き合わせる。

なぜ要るのか:
  ここで見つかった不具合は、どれも「壊れている」のではなく
  「2か所が別々のことを言っている」形だった。片方だけ直して、
  もう片方が古いまま残る。動かしても例外は出ないので気づけない。

  実例:
    ・読み上げは players[0]、画面は pick_top() で別の選手を指していた
    ・「今夜/明日」を各所が自前で決め、同じ試合の呼び方が食い違った
    ・サッカーの理由は league の日本語名、判定はコードで比較していた
    ・サイトは games.json だけを読むのに、MLBしか渡していなかった
    ・公開している計算式と、実装の係数が別々に書かれていた

  どれも「1つの問いに答えが2つある」状態。ここではその形を探す。
"""

import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {label}: {got}"
          + ("" if ok else f" (期待 {want})"))


# --- 冒頭で挙げる選手が、読み上げと画面で同じか -----------------------------
print("--- 冒頭の選手 ---")
import generate_morning_short as ms  # noqa: E402
import morning_recap as mr  # noqa: E402

recap = ROOT / "data" / "morning_recap.json"
if recap.exists():
    d = json.loads(recap.read_text(encoding="utf-8"))
    players = ms.sort_players(d.get("players") or [])
    if players:
        narration = ms.build_narration({**d, "players": players}, "players")
        spoken = narration["segments"][0]["text"]
        check("読み上げの冒頭に、一覧1位の名前が入っている",
              players[0]["name"] in spoken, True)
# 選び方が2つ残っていないか
check("選手を選ぶ関数が1つだけ", hasattr(ms, "pick_top"), False)


# --- 「今夜/明日」を決める場所が1つか ---------------------------------------
print("\n--- 日付の呼び方 ---")
import post_common as pc  # noqa: E402

srcs = list((ROOT / "scripts").glob("*.py")) + [ROOT / "notability_engine.py"]
own = [f.name for f in srcs
       if f.name not in ("post_common.py", "test_consistency.py")
       and re.search(r'def (when_label|today_or_tomorrow_label)\b',
                     f.read_text(encoding="utf-8", errors="replace"))]
check("post_common 以外に同名の関数が無い", own, [])
check("競技で境目が違うことが1か所で決まっている",
      hasattr(pc, "_late_night_until"), True)


# --- 公開している計算式と、実装の係数が一致しているか -----------------------
print("\n--- 計算式の公開 ---")
# 数字を2か所に書かず、ページが実装から読むようになっているか。
# 手で書くと、片方を変えたときにもう片方が古いまま残る。
page = (ROOT / "scripts" / "generate_score_page.py").read_text(encoding="utf-8")
check("ページが土台を実装から読んでいる", "{mr.BATTER_BASE}" in page, True)
check("ページが倍率を実装から読んでいる", "{mr.BATTER_SCALE}" in page, True)
check("土台の数字がページに直接書かれていない",
      re.search(r"スコア = \d+ \+ 素点", page) is None, True)


# --- サイトが読むファイルに、両方の競技が入るか -----------------------------
print("\n--- サイトへ渡すデータ ---")
index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
reads = set(re.findall(r"fetch\('([\w./]+)'", index))
check("サイトが読むのは games.json だけ", "games.json" in reads, True)
wf = (ROOT / ".github" / "workflows" / "daily_notify.yml").read_text(encoding="utf-8")
check("その games.json に両方の競技を入れている",
      "merge_games.py" in wf, True)
check("MLBだけをコピーしていない",
      "cp notable_games.json public/games.json" in wf, False)


# --- 動画・タイトル・説明文が同じ材料を見ているか ---------------------------
print("\n--- 「今日の1人」 ---")
import player_screens as ps  # noqa: E402
import upload_youtube as uy  # noqa: E402

prof_path = ROOT / "data" / "player_profile.json"
if prof_path.exists():
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    title = uy.build_metadata("notable_games.json", "8月18日", "morning",
                              morning_mode="player")["snippet"]["title"]
    check("タイトルの選手が、材料の選手と同じ", prof["name"] in title, True)
    body = uy.build_metadata("notable_games.json", "8月18日", "morning",
                             morning_mode="player")["snippet"]["description"]
    line = ps.stat_line(prof, prof.get("career") or {})
    check("説明文の通算が、画面と同じ書き方", line and line in body, True)


# --- 動画の区分名が、再生リスト・健康診断と揃っているか ---------------------
print("\n--- 区分名 ---")
import healthcheck as hc  # noqa: E402
import playlists as pl  # noqa: E402

expected = {k for k, _, _, _ in hc.EXPECTED_DAILY + hc.OPTIONAL_DAILY}
have = set(pl.PLAYLISTS)
check("健康診断が見る区分に、再生リストが全部ある",
      sorted(expected - have), [])


print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
