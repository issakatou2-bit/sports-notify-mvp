#!/usr/bin/env python3
"""PSの試合の話題を、試合が終わってすぐ出すための判定（ps_game_now.yml から呼ぶ）。

なぜ要るのか:
  10/5、本人「試合の話題を試合のすぐ後（お昼すぎ）に出す。可能ならそのほうがいい」。
  試合の話題（ps_game_story.py）は初日から970再生前後で、いちばん強い型だった。
  ところが出すのは夕方のシーズンまとめの枠（16:30〜23:30）で、試合が終わってから
  半日以上たっていた。PSの試合は日本時間の朝〜昼に終わる。

  --due     いま出してよい試合の話題のキー（空白区切り）。
            条件: まだ出していない・試合が終わって DELAY 分たった（MLB.comの
            総括記事やハイライトのコメントが出そろうのを待つ）・その日の本数の
            上限（シーズンまとめの枠と同じ数え方で4本）に余裕がある。
  --watch   まだ見張る理由があるか（終了コード 0 = ある）。
            終わっていない・これから始まるPSの試合がある、または出せる話題が残っている。

数え方はシーズンまとめの枠（next_asset.pick_season）と同じ。昼に出した本数は
夕方の枠の本数から引かれるので、1日の本数は今と変わらない。
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import next_asset  # noqa: E402

DELAY_MINUTES = 45      # 試合が終わってから待つ時間
DAILY_CAP = 4           # season_review.yml の既定（--season 4）と同じ
LOOKAHEAD_HOURS = 6     # これから始まる試合を待つ範囲
PS_TYPES = ("F", "D", "L", "W")


def _utc(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def load_topics(path: str) -> list:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8")).get("topics") or []
    except (OSError, ValueError):
        return []


def left_today(published_path: str, today=None) -> int:
    done = next_asset.posted_today(published_path, today=today, kinds={"season"}, count=True)
    return max(0, DAILY_CAP - int(done or 0))


def due(topics: list, published: set, now: datetime, left: int) -> list:
    """いま出してよいキー。日本人選手の試合を先に、その中では早く終わった順。"""
    ready = []
    for t in topics:
        key = t.get("key") or ""
        if not t.get("game") or not key or key in published:
            continue
        end = _utc(t.get("finished_at"))
        if end is None or now - end < timedelta(minutes=DELAY_MINUTES):
            continue
        ready.append((not t.get("jp_first"), end, key))
    ready.sort()
    return [k for _, _, k in ready][:left]


def waiting(topics: list, published: set, now: datetime) -> bool:
    """出していない話題で、待てば出せるもの（終わって DELAY 分たっていない）。"""
    for t in topics:
        end = _utc(t.get("finished_at"))
        if t.get("game") and t.get("key") not in published and end and \
                now - end < timedelta(minutes=DELAY_MINUTES):
            return True
    return False


def games_ahead(games: list, now: datetime) -> bool:
    """まだ終わっていない・これから始まるPSの試合（始まって12時間以内か、LOOKAHEAD 以内に始まる）。"""
    for g in games:
        if g.get("gameType") not in PS_TYPES:
            continue
        if (g.get("status") or {}).get("abstractGameState") == "Final":
            continue
        start = _utc(g.get("gameDate"))
        if start and now - timedelta(hours=12) <= start <= now + timedelta(hours=LOOKAHEAD_HOURS):
            return True
    return False


def schedule(now: datetime) -> list:
    import requests
    r = requests.get("https://statsapi.mlb.com/api/v1/schedule", timeout=30, params={
        "sportId": 1, "gameType": ",".join(PS_TYPES),
        "startDate": (now - timedelta(days=1)).date().isoformat(),
        "endDate": (now + timedelta(days=1)).date().isoformat()})
    r.raise_for_status()
    return [g for d in r.json().get("dates") or [] for g in d.get("games") or []]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--topics", default="data/ps_game_topics.json")
    ap.add_argument("--published", default="data/published_assets.json")
    ap.add_argument("--skip", default="",
                    help="出さないキーを1行ずつ書いたファイル（この起動で失敗したもの）")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    topics = load_topics(args.topics)
    published = next_asset.published(args.published)
    left = left_today(args.published)
    if args.due:
        skip = set()
        if args.skip:
            try:
                skip = {x.strip() for x in pathlib.Path(args.skip).read_text(
                    encoding="utf-8").splitlines() if x.strip()}
            except OSError:
                skip = set()
        print(" ".join(k for k in due(topics, published, now, left) if k not in skip))
        return 0
    if args.watch:
        if left <= 0:
            print("[info] きょうの本数の上限に達しました", file=sys.stderr)
            return 1
        if due(topics, published, now, left) or waiting(topics, published, now):
            return 0
        try:
            ahead = games_ahead(schedule(now), now)
        except Exception as e:                              # noqa: BLE001
            print(f"[warn] 日程を取れません({e})。見張りを続けます", file=sys.stderr)
            return 0
        if not ahead:
            print("[info] 見張るPSの試合がありません", file=sys.stderr)
        return 0 if ahead else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
