#!/usr/bin/env python3
"""番記者の投稿を、球団ごとに10日ぶん貯める（PSの話題の引用用）。

local_reporters.json は直近30時間しか持たない。シリーズが決着した翌日の
投稿（GMの総括など）を、話題の回を作る日まで残しておく。
訳（jp）はlocal_reporters.py が付けたものをそのまま使う（ここで訳し直さない）。
"""

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

KEEP_DAYS = 10


def merge(store: list, posts: list, now: datetime) -> list:
    seen = {x.get("uri") for x in store}
    out = list(store) + [p for p in posts if p.get("uri") and p["uri"] not in seen]
    cut = (now - timedelta(days=KEEP_DAYS)).isoformat()
    return [x for x in out if (x.get("at") or "") >= cut[:19]]


def main() -> int:
    src = pathlib.Path("data/local_reporters.json")
    dst = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data/ps_quotes.json")
    try:
        posts = json.loads(src.read_text(encoding="utf-8")).get("posts") or []
    except (OSError, json.JSONDecodeError):
        posts = []
    try:
        store = json.loads(dst.read_text(encoding="utf-8")).get("posts") or []
    except (OSError, json.JSONDecodeError):
        store = []
    now = datetime.now(timezone.utc)
    keep = ("team", "author", "outlet", "handle", "text", "jp", "likes", "at", "uri")
    merged = merge(store, [{k: p.get(k) for k in keep} for p in posts], now)
    dst.write_text(json.dumps({"updated_at": now.isoformat(), "posts": merged},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 番記者の投稿 {len(merged)}件（新しく{len(merged) - len(store)}件）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
