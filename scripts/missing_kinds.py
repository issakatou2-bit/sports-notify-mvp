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

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import post_common  # noqa: E402
from publication_clock import publication_due, target_day  # noqa: E402

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


def missing(day: str = None, path: str = "data/published_videos.json", now=None) -> list:
    """まだ出ていない枠。公開時刻＋猶予を過ぎたものだけ。"""
    now = now or datetime.now(JST)
    day = day or target_day(now)
    try:
        rec = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for kind, name, _, at in post_common.DAILY_LINEUP:
        if not publication_due(day, at, now, GRACE_MIN):
            continue                      # まだ出そろう時刻ではない
        if (rec.get(kind) or {}).get(day):
            continue                      # 出ている
        import morning_topics
        if morning_topics.skip_reason(kind, day):
            continue                      # 新しい題材が無いことを制作側で確認済み
        if kind=='daily_soccer':
            import soccer_preview_assessment
            try:material=json.loads(pathlib.Path('data/soccer_games.json').read_text(encoding='utf8'))
            except (OSError,ValueError):material={}
            if soccer_preview_assessment.assessment(material,day)[0]=='skip':continue
        out.append((kind, name, at))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date', type=lambda value: datetime.fromisoformat(value).date().isoformat(),
                    help='見張りと同じ対象日（既定は正午前まで前日）')
    args = ap.parse_args()
    rows = missing(day=args.date)
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
