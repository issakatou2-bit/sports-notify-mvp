#!/usr/bin/env python3
"""
その日まだ出ていない枠と、それを作るワークフローを並べる。

なぜ要るのか:
  見張りは「出ていない」と報せるところで終わっていた。気づいた人が
  手で回す前提だったが、出先だと何時間も空く。8/29は6本全部が
  止まって、回収は夜になった。

  何が欠けていて、どれを回せばよいかは機械で分かる。
  分かるなら、自分で回してよい。

止め方:
  公開時刻から45分を過ぎた枠だけを見る(healthcheck と同じ猶予)。
  作っている最中のものを「無い」と言って回し直すと二重に出る。

  回し直しは1周だけ。GitHubは GITHUB_TOKEN で起動した実行から
  workflow_run を発火させないので、そこで自然に止まる。

出力: 標準出力に「ワークフローのファイル名」を1行ずつ。
      無ければ何も出さない。

使い方:
  python3 scripts/missing_kinds.py
"""

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import post_common  # noqa: E402

JST = timezone(timedelta(hours=9))

# 枠と、それを作るワークフロー。
#
# サッカーは日次の完走で連鎖するが、GITHUB_TOKEN で起動した実行は
# workflow_run を発火させない。だから明示的に並べる。
OWNER = {
    "morning": "morning_recap.yml",
    "morning_player": "morning_recap.yml",
    "morning_voices": "morning_recap.yml",
    "morning_press": "morning_recap.yml",
    "daily": "daily_notify.yml",
    "daily_soccer": "soccer_daily.yml",
}

# 公開時刻から何分待って「出ていない」と判断するか。
# healthcheck.PUBLISH_GRACE_MIN と揃える。
GRACE_MIN = 45


def missing(day: str = None, path: str = "data/published_videos.json") -> list:
    """まだ出ていない枠。公開時刻＋猶予を過ぎたものだけ。"""
    now = datetime.now(JST)
    day = day or now.strftime("%Y-%m-%d")
    judge_from = (now - timedelta(minutes=GRACE_MIN)).strftime("%H:%M")
    try:
        rec = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for kind, name, _, at in post_common.DAILY_LINEUP:
        if at > judge_from:
            continue                      # まだ出そろう時刻ではない
        if (rec.get(kind) or {}).get(day):
            continue                      # 出ている
        out.append((kind, name, at))
    return out


def main() -> int:
    rows = missing()
    if not rows:
        print("[info] 欠けている枠はありません", file=sys.stderr)
        return 0
    for kind, name, at in rows:
        print(f"[info] {at} {name} が出ていません", file=sys.stderr)
    # 同じワークフローを2回回さない
    seen = []
    for kind, _, _ in rows:
        wf = OWNER.get(kind)
        if wf and wf not in seen:
            seen.append(wf)
    for wf in seen:
        print(wf)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
