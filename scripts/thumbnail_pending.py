"""使用枠切れの画像だけを、投稿実行の保存物へ引き渡す。"""
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil


VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def quota_exceeded(error):
    from googleapiclient.errors import HttpError
    if not isinstance(error, HttpError) or error.resp.status != 403:
        return False
    try:
        errors = json.loads(error.content).get("error", {}).get("errors", [])
        return any(item.get("reason") == "quotaExceeded" for item in errors)
    except (ValueError, TypeError, AttributeError):
        return False


def remember(error, image, video_id, kind, title,
             directory="build/thumbnail_pending", now=None):
    if not quota_exceeded(error):
        return False
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("動画IDの形式が不正です")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "pending.json"
    entries = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    shutil.copyfile(image, directory / f"{video_id}.png")
    entries = [item for item in entries if item["video_id"] != video_id]
    entries.append(dict(video_id=video_id, kind=kind, title=title,
                        failed_at=(now or datetime.now(timezone.utc)).isoformat()))
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(manifest)
    return True
