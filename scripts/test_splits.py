#!/usr/bin/env python3
"""移籍した選手の成績を、二重に数えていないか。

なぜ検査が要るのか:
  9/7の長編で「ルイス・ガルシア56本、ベン・ライス36本」と出た。
  実際は28本で、**合計の行と球団ごとの行を両方足していた**。
  176打点は歴代最多に迫る数字で、それが台本にも題にも入っていた。

  同じ形の読み方が5つのファイルにあった。足しているところと、
  「最初の1行」を採っているところ。後者は**たまたま合計が先頭に
  来ているから合っているだけ**で、APIが順番を変えたら静かにずれる。

  ここでは、実際のAPIが返す形をそのまま作って確かめる。
  外部には出ない。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import generate_dialogue  # noqa: E402
import mlb_splits  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


# 2026-09-08 に実際に返ってきた形。
MOVED = [
    {"numTeams": 2, "season": "2026",
     "stat": {"homeRuns": 28, "rbi": 88, "atBats": 461, "hits": 131}},
    {"team": {"name": "Washington Nationals"}, "season": "2026",
     "stat": {"homeRuns": 23, "rbi": 76, "atBats": 357, "hits": 101}},
    {"team": {"name": "New York Yankees"}, "season": "2026",
     "stat": {"homeRuns": 5, "rbi": 12, "atBats": 104, "hits": 30}},
]
STAYED = [
    {"team": {"name": "New York Yankees"}, "season": "2026",
     "stat": {"homeRuns": 36, "rbi": 88, "atBats": 401, "hits": 104}},
]

print("--- 合計の行を選ぶ ---")
check("移籍した選手は合計だけ", len(mlb_splits.prefer_total(MOVED)), 1)
check("移籍した選手の本塁打", mlb_splits.season_stat(MOVED).get("homeRuns"), 28)
check("移籍した選手の打点", mlb_splits.season_stat(MOVED).get("rbi"), 88)
check("移籍していない選手はそのまま",
      mlb_splits.season_stat(STAYED).get("homeRuns"), 36)
check("空でも落ちない", mlb_splits.season_stat([]), {})
check("Noneでも落ちない", mlb_splits.season_stat(None), {})

# 試合ログのように合計の行が無い並びは、素通りする。
GAMELOG = [{"date": "2026-09-01", "stat": {"hits": 2}},
           {"date": "2026-09-02", "stat": {"hits": 1}}]
check("試合ログは減らさない", len(mlb_splits.prefer_total(GAMELOG)), 2)

print(chr(10) + "--- 足し算のほう（長編の選手一覧） ---")
t = generate_dialogue._add(MOVED, generate_dialogue.HIT_KEYS)
check("足しても56本にならない", t.get("homeRuns"), 28)
check("打点も176にならない", t.get("rbi"), 88)
check("打数も足し過ぎない", t.get("atBats"), 461)
t2 = generate_dialogue._add(STAYED, generate_dialogue.HIT_KEYS)
check("移籍していない選手はそのまま", t2.get("homeRuns"), 36)

# 打率も、足した材料から出し直しているので正しくなる。
line = generate_dialogue._hit_line(t)
check("打率が.284になる（131安打 / 461打数）", "打率.284" in line, True)

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
