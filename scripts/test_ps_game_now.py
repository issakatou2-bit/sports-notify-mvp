#!/usr/bin/env python3
"""PSの試合の話題を試合のすぐ後に出す判定（ps_game_now.py）と、見張りのシェル（ps_game_now.yml）。

APIもYouTubeも使わない。シェルは偽の python / git / bash で流す。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ps_game_now as gn  # noqa: E402

NOW = datetime(2026, 10, 6, 3, 0, tzinfo=timezone.utc)   # 日本時間 12:00


def topic(key, ended_min_ago, jp=True):
    return {"key": key, "game": True, "jp_first": jp,
            "finished_at": (NOW - timedelta(minutes=ended_min_ago)).isoformat()}


class Due(unittest.TestCase):
    def test_waits_until_the_game_has_settled(self):
        self.assertEqual(gn.due([topic("season_game_1", 30)], set(), NOW, 4), [])
        self.assertEqual(gn.due([topic("season_game_1", 50)], set(), NOW, 4), ["season_game_1"])

    def test_already_published_is_not_due(self):
        self.assertEqual(gn.due([topic("season_game_1", 90)], {"season_game_1"}, NOW, 4), [])

    def test_japanese_games_first_then_earliest(self):
        rows = [topic("season_game_3", 60, jp=False), topic("season_game_2", 60),
                topic("season_game_1", 200)]
        self.assertEqual(gn.due(rows, set(), NOW, 4),
                         ["season_game_1", "season_game_2", "season_game_3"])

    def test_daily_cap_is_shared_with_the_evening_slot(self):
        rows = [topic("season_game_1", 90), topic("season_game_2", 80)]
        self.assertEqual(gn.due(rows, set(), NOW, 1), ["season_game_1"])
        self.assertEqual(gn.due(rows, set(), NOW, 0), [])

    def test_unknown_end_time_is_not_due(self):
        self.assertEqual(gn.due([{"key": "season_game_1", "game": True}], set(), NOW, 4), [])

    def test_series_story_is_not_this_slot(self):
        self.assertEqual(gn.due([{"key": "season_story_x", "story": True,
                                  "finished_at": NOW.isoformat()}], set(), NOW, 4), [])


class Watch(unittest.TestCase):
    def test_waiting_for_a_just_finished_game(self):
        self.assertTrue(gn.waiting([topic("season_game_1", 10)], set(), NOW))
        self.assertFalse(gn.waiting([topic("season_game_1", 10)], {"season_game_1"}, NOW))

    def test_games_ahead(self):
        live = {"gameType": "D", "status": {"abstractGameState": "Live"},
                "gameDate": (NOW - timedelta(hours=2)).isoformat()}
        later = {"gameType": "D", "status": {"abstractGameState": "Preview"},
                 "gameDate": (NOW + timedelta(hours=3)).isoformat()}
        tomorrow = {"gameType": "D", "status": {"abstractGameState": "Preview"},
                    "gameDate": (NOW + timedelta(hours=20)).isoformat()}
        final = {"gameType": "D", "status": {"abstractGameState": "Final"},
                 "gameDate": (NOW - timedelta(hours=4)).isoformat()}
        regular = {"gameType": "R", "status": {"abstractGameState": "Live"},
                   "gameDate": NOW.isoformat()}
        self.assertTrue(gn.games_ahead([live], NOW))
        self.assertTrue(gn.games_ahead([later], NOW))
        self.assertFalse(gn.games_ahead([tomorrow, final, regular], NOW))

    def test_left_today_counts_the_season_kind(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "pub.json"
            today = datetime.now(timezone(timedelta(hours=9)))
            path.write_text(json.dumps({"assets": {
                "season_game_1": {"published_at": today.isoformat()},
                "legend_1": {"published_at": today.isoformat()}}}), encoding="utf-8")
            self.assertEqual(gn.left_today(str(path)), gn.DAILY_CAP - 1)


BASH = shutil.which("bash")
if os.name == "nt":
    candidate = pathlib.Path("C:/Program Files/Git/bin/bash.exe")
    BASH = str(candidate) if candidate.exists() else None


@unittest.skipUnless(BASH, "bash is needed to exercise the runner shell")
class WatchLoop(unittest.TestCase):
    """ps_game_now.yml の見張りのシェルを、偽のコマンドで流す。"""

    def run_loop(self, build_fails=False, watch_rounds=1):
        import yaml
        wf = yaml.safe_load((HERE.parent / ".github/workflows/ps_game_now.yml")
                            .read_text(encoding="utf-8"))
        step = next(s for s in wf["jobs"]["watch"]["steps"] if s.get("name") == "Watch and publish")
        fake = '''
python() {
  case "$*" in
    *"ps_game_now.py --due"*)
      if grep -qx season_game_1 "$STATE/done" 2>/dev/null || grep -qx season_game_1 build/failed.txt 2>/dev/null; then echo ""; else echo "season_game_1"; fi ;;
    *"ps_game_now.py --watch"*)
      n=$(cat "$STATE/watch" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$STATE/watch"
      [ "$n" -lt "$ROUNDS" ] ;;
    *"upload_youtube.py"*)
      echo "CALL:upload"; [ "$FAIL" != 1 ] && echo season_game_1 > "$STATE/done"; [ "$FAIL" != 1 ] ;;
    *"local_voices.py"*|*"mlb_buzz.py"*|*"local_reporters.py"*) echo "CALL:refresh" ;;
    *) return 0 ;;
  esac
}
git() { return 0; }
bash() { echo "CALL:bash $1"; return 0; }
sleep() { return 0; }
'''
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "UNTIL_UTC": "23:59", "RUN_ID": "1", "STATE": d.replace("\\", "/"),
                   "FAIL": "1" if build_fails else "0", "ROUNDS": str(watch_rounds + 1),
                   "GITHUB_STEP_SUMMARY": os.path.join(d, "summary").replace("\\", "/")}
            return subprocess.run([BASH, "--noprofile", "--norc"], input=fake + step["run"],
                                  text=True, encoding="utf-8", capture_output=True,
                                  cwd=d, env=env)

    def test_publishes_once_then_stops_when_nothing_left(self):
        r = self.run_loop(watch_rounds=2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("CALL:upload"), 1)
        self.assertIn("CALL:bash scripts/commit_data.sh", r.stdout)

    def test_failed_topic_is_not_retried_and_does_not_refresh_again(self):
        r = self.run_loop(build_fails=True, watch_rounds=3)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("CALL:upload"), 1)
        # 取り直し（翻訳の費用がかかる）は、出せる話題があった1回目だけ
        self.assertEqual(r.stdout.count("CALL:refresh"), 3)


if __name__ == "__main__":
    unittest.main(argv=["test_ps_game_now"])
