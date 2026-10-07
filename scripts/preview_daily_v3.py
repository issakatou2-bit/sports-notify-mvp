"""保存材料で日次の外観だけを確認。投稿、材料更新、有料モデルの呼出なし。"""
import argparse
from datetime import date
import json
from pathlib import Path
import sys
from unittest.mock import patch

import generate_morning_short as g
import recap_freshness


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["voices"], default="voices")
    ap.add_argument("--narration-out")
    ap.add_argument("--audio-dir", default="build/preview-audio")
    args = ap.parse_args()
    material = "scripts/fixtures/comment/local_voices-preview.json"
    d = json.loads(Path(material).read_text(encoding="utf-8"))
    edition = date.fromisoformat(d["updated_at"][:10])
    argv = ["generate_morning_short", "--mode", args.mode, "--recap", "scripts/fixtures/bignumber/empty.json",
            "--voices", material, "--buzz", "scripts/fixtures/bignumber/empty.json",
            "--talk", "scripts/fixtures/bignumber/empty.json", "--reporters", "scripts/fixtures/bignumber/empty.json",
            "--audio-dir", args.audio_dir, "--require-audio", "--out", "build/preview"]
    if args.narration_out:
        argv += ["--narration-out", args.narration_out]
    # 本番の鮮度判定は保持。この非公開試作の時点だけ固定。
    with patch.object(recap_freshness, "current_day", return_value=edition), \
         patch.object(g.local_voices, "load", return_value=d), patch.object(sys, "argv", argv):
        return g.main()


if __name__ == "__main__":
    raise SystemExit(main())
