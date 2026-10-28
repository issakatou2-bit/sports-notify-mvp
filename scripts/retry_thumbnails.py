"""前日16時以降の完了実行から画像を回収する。書込み前の保存物で日内重複を防ぐ。"""
import argparse
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from thumbnail_pending import VIDEO_ID

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("時刻には時差が必要です")
    return result


def gh_json(endpoint, key):
    result = subprocess.run(["gh", "api", "--paginate", "--slurp", endpoint],
                            check=True, capture_output=True)
    return [item for page in json.loads(result.stdout) for item in page[key]]


def collect(repository, directory, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(JST)
    reset = now.replace(hour=16, minute=0, second=0, microsecond=0)
    # 手動実行も枠が戻るまで待つ。朝の誤実行でその日の印を消費しない。
    if now < reset:
        print("[info] 16時より前なので付け直しません")
        return []
    start = reset - timedelta(days=1)
    base = f"repos/{repository}/actions"
    marker = f"thumbnail-retry-{now.date().isoformat()}"
    if gh_json(f"{base}/artifacts?name={marker}&per_page=100", "artifacts"):
        print("[info] 本日の付け直しは着手済みです")
        return []
    # updated_at（完了時刻）で絞る。作成日時だけで切ると長い投稿実行が抜ける。
    runs = gh_json(f"{base}/runs?status=completed&branch=main&per_page=100"
                   f"&created=%3E%3D{(start - timedelta(days=1)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                   "workflow_runs")
    entries = {}
    for run in runs:
        if (run.get("head_branch") != "main"
                or run.get("event") not in {"schedule", "workflow_dispatch", "push", "workflow_run"}
                or run.get("head_repository", {}).get("full_name") != repository
                or run.get("status") != "completed"
                or not start <= stamp(run["updated_at"]) <= now):
            continue
        artifacts = gh_json(f"{base}/runs/{int(run['id'])}/artifacts?per_page=100", "artifacts")
        for artifact in artifacts:
            if artifact["name"] != "thumbnail-pending" or artifact.get("expired"):
                continue
            result = subprocess.run(
                ["gh", "api", f"{base}/artifacts/{int(artifact['id'])}/zip"],
                check=True, capture_output=True)
            # 展開せず、検証したIDのPNGとmanifestだけを読む。
            with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
                pending = json.loads(archive.read("pending.json"))
                for item in pending:
                    vid = item["video_id"]
                    failed = stamp(item["failed_at"])
                    if not VIDEO_ID.fullmatch(vid):
                        raise ValueError("保存物の動画IDが不正です")
                    if not start <= failed <= now or now - failed >= timedelta(hours=24):
                        print(f"[info] 期限外の画像を見送ります: {vid}")
                        continue
                    if vid in entries and stamp(entries[vid]["failed_at"]) >= failed:
                        continue
                    image = directory / f"{vid}.png"
                    image.write_bytes(archive.read(f"{vid}.png"))
                    entries[vid] = dict(item, image=str(image.resolve()))
    return list(entries.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--directory", type=Path, default=Path("build/thumbnail_retry"))
    args = parser.parse_args()
    directory = args.directory
    manifest = directory / "selected.json"
    if args.apply:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        # 回収後に長く待った場合も24時間の期限を守る。
        now = datetime.now(timezone.utc)
        pairs = [f"{item['video_id']}={item['image']}" for item in entries
                 if timedelta(0) <= now - stamp(item['failed_at']) < timedelta(hours=24)]
        if not pairs:
            return 0
        return subprocess.run([sys.executable, str(ROOT / "scripts/reset_thumbnail.py"),
                               "--write", "--quota-warning", *pairs], check=False).returncode
    directory.mkdir(parents=True, exist_ok=True)
    entries = collect(os.environ["GITHUB_REPOSITORY"], directory)
    manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    day = datetime.now(JST).date().isoformat()
    if entries:
        (directory / "attempt.json").write_text(
            json.dumps(dict(day=day, video_ids=[item["video_id"] for item in entries])),
            encoding="utf-8")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"pending={'true' if entries else 'false'}\nday={day}\n")
    print(f"[info] 付け直し対象 {len(entries)}本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
