#!/usr/bin/env python3
"""出たかどうかの確認が、日をまたいだ実行で嘘をつかないか。

なぜ検査が要るのか:
  9/13の19時の枠が、GitHubのscheduleの遅れでJST 00:30に走った。
  動画は9/13の日付で作られて投稿されたのに、確認はJST 00:42に
  「9/14のdailyはあるか」と探して、無いので赤くした。
  **その回は9本すべて出ていた。**

  日次・サッカー・見張りの3つが同時に赤くなり、実行ページ上は
  障害が起きたように見えた。**出ているのに出ていないと言うのは、
  出ていないのに出ていると言うのと同じくらい困る。**

  かといって前日をいつでも見ると、今日1本も出ていない日を
  緑にしてしまう。時間の幅で切る。
"""

import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def run(record: dict, kind: str = "daily", allow_missing=False) -> int:
    """実際にスクリプトを起動して、終了コードを見る。"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        path = f.name
    cmd = [sys.executable, str(HERE / "verify_published.py"),
           "--kind", kind, "--record", path]
    if allow_missing:
        cmd.append("--allow-missing")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    pathlib.Path(path).unlink(missing_ok=True)
    return r.returncode


def rec(day_offset: int, hours_ago: float, kind: str = "daily") -> dict:
    """その日の記録を1件だけ持つ台帳を作る。"""
    now = datetime.now(JST)
    day = (now + timedelta(days=day_offset)).strftime("%Y-%m-%d")
    at = (now - timedelta(hours=hours_ago)).astimezone(timezone.utc)
    return {kind: {day: {"video_id": "abc123", "title": "検査",
                         "published_at": at.isoformat()}}}


print("--- 今日の記録があれば緑 ---")
check("今日出した", run(rec(0, 1.0)), 0)

print()
print("--- 記録が無ければ赤 ---")
check("1本も出ていない", run({}), 1)
check("別の区分しかない", run(rec(0, 1.0, kind="morning")), 1)
check("--allow-missing なら赤くしない", run({}, allow_missing=True), 0)

print()
print("--- 日をまたいだ実行 ---")
# **9/13の19時の枠がJST 0時台に走った日の形。**
# 前日の日付で記録されているが、出したのはついさっき。
check("前日の記録でも、1時間前に出していれば緑", run(rec(-1, 1.0)), 0)
check("4時間前でも緑", run(rec(-1, 4.0)), 0)
# **これ以上広げない。**前日の朝に出したものまで拾うと、
# 今日1本も出ていない日を緑にしてしまう。
check("6時間前は赤（前日の分として扱わない）", run(rec(-1, 6.0)), 1)
check("前日の朝に出したもの（20時間前）は赤", run(rec(-1, 20.0)), 1)

print()
print("--- 壊れた記録でも落ちない ---")
check("時刻が読めない",
      run({"daily": {(datetime.now(JST) - timedelta(days=1))
                     .strftime("%Y-%m-%d"):
                     {"video_id": "x", "published_at": "こわれている"}}}), 1)
check("時刻が無い",
      run({"daily": {(datetime.now(JST) - timedelta(days=1))
                     .strftime("%Y-%m-%d"): {"video_id": "x"}}}), 1)
check("動画IDが無い",
      run({"daily": {datetime.now(JST).strftime("%Y-%m-%d"):
                     {"title": "IDなし"}}}), 1)

print()
print("--- 幅は定数で持つ ---")
sys.path.insert(0, str(HERE))
import verify_published as vp  # noqa: E402
check("RECENT_HOURS がある", isinstance(vp.RECENT_HOURS, (int, float)), True)
check("5時間", vp.RECENT_HOURS, 5)

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
