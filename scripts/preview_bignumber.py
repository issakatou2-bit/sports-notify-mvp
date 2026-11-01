"""保存済み成績を、その日付の試作としてだけ描く。投稿処理は持たない。"""
import argparse
import json
import pathlib
import sys
from datetime import date
from unittest.mock import patch

import bignumber_render as bn
import generate_morning_short as gms
import recap_freshness


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", default="scripts/fixtures/bignumber/recap_history/2026-09-25.json")
    ap.add_argument("--narration-out")
    ap.add_argument("--audio-dir", default="build/preview-audio")
    ap.add_argument('--narration',help='声つき試作の録音に使った保存原稿')
    ap.add_argument('--next-schedule',help='次情報用の保存した公式日程')
    args = ap.parse_args()
    data = json.loads(pathlib.Path(args.material).read_text(encoding="utf-8"))
    edition = date.fromisoformat(data["date_jst"])
    # この試作スクリプトだけで時点を固定。本番の鮮度検査は変更しない。
    bn._no_network()
    argv = ["generate_morning_short", "--mode", "players", "--recap", args.material,
            "--voices", "scripts/fixtures/bignumber/empty.json",
            "--talk", "scripts/fixtures/bignumber/empty.json",
            "--audio-dir", args.audio_dir, "--require-audio", "--out", "build/preview"]
    if args.narration_out:
        argv += ["--narration-out", args.narration_out]
    if args.narration:argv += ['--narration',args.narration]
    if args.next_schedule:
        argv += ['--next-schedule',args.next_schedule,'--publish-at',data['date_jst']+'T17:00:00+09:00']
    # 現在の履歴から「ここ7日」を混ぜない。週次場面は専用の固定検査で確認する。
    with patch.object(recap_freshness, "current_day", return_value=edition), \
         patch.object(gms, "week_line", return_value=("", [])), patch.object(sys, "argv", argv):
        return gms.main()


if __name__ == "__main__":
    raise SystemExit(main())
