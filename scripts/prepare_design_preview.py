"""試作限定の表紙再検査と、声なし成果物の成功扱いを防ぐ。投稿はしない。"""
import argparse
import json
import pathlib

import ps_v3_cover


def prepare(path):
    p = pathlib.Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = json.loads(pathlib.Path("data/postseason.json").read_text(encoding="utf-8")).get("series", [])
    for topic in data.get("topics", []):
        if topic.get("game") or topic.get("odds"):
            ps_v3_cover.apply(topic, rows)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return next((t["key"] for t in data.get("topics", []) if t.get("style") == "v3"), "")


def require_voice(manifest):
    data = json.loads(pathlib.Path(manifest).read_text(encoding="utf-8"))
    segs = data.get("segments", [])
    if not segs or any(not s.get("file") or s.get("duration", 0) <= 0 for s in segs):
        raise ValueError("声付き試作に必要な音声が不足しています")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--material")
    ap.add_argument("--manifest")
    args = ap.parse_args()
    if args.manifest:
        require_voice(args.manifest)
    else:
        print(prepare(args.material))
