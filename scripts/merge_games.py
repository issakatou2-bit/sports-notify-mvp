#!/usr/bin/env python3
"""
サイトが読む1ファイルに、競技をまとめる。

なぜ要るのか:
  web/index.html は games.json だけを読み、MLBタブとサッカータブを
  中身の league で振り分ける。ところがサイト組み立てが
  notable_games.json(MLBのみ)をそのまま置いていたため、
  サッカータブには何も入らず「シーズンオフのため試合がありません」と
  毎日表示されていた。開幕しているのに。

  プッシュもRSSも動画も、どれも両方のファイルを受け取っている。
  サイトだけが片方しか渡されていなかった。

出力: public/games.json

使い方:
  python3 scripts/merge_games.py --input notable_games.json \
      --input data/soccer_games.json --out public/games.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", action="append", default=None,
                    help="まとめる元のファイル。複数回指定できる")
    ap.add_argument("--out", default="public/games.json")
    args = ap.parse_args()

    games, status = [], {}
    for path in (args.input or ["notable_games.json"]):
        p = pathlib.Path(path)
        if not p.exists():
            print(f"[info] {path} が無いため飛ばします")
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] {path} を読めませんでした: {e}", file=sys.stderr)
            continue
        got = d.get("games") or []
        games.extend(got)
        # AIの実行状況は足し合わせる(片方だけ失敗した日が分かるように)
        for k, v in (d.get("ai_status") or {}).items():
            if isinstance(v, (int, float)):
                status[k] = status.get(k, 0) + v
        print(f"[info] {path}: {len(got)}試合")

    # 注目度の高い順。同点なら開始時刻順。振り分けは league で行うので、
    # ここで競技ごとに分けたりはしない。
    games.sort(key=lambda g: (-(g.get("score") or 0),
                              g.get("start_time_jst") or "99/99 99:99"))

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games,
        "ai_status": status,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    by = Counter(g.get("league") for g in games)
    print(f"[info] 合計{len(games)}試合 {dict(by)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
