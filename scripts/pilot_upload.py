"""観戦の見取り図を非公開で投稿。専用台帳と所有者照合で重複・誤公開を防ぐ。"""
import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

from pilot_series import CATALOG, episode_key, load_episode, write_json

CHANNEL_ID = "UCpZ_j8X8uOex5VvKwwTJj3Q"
REPOSITORY = "issakatou2-bit/sports-notify-mvp"
STATE_BRANCH = "codex/pilot-series-state"
STATE_FILE = "pilot_uploads.json"


def github(path, method="GET", body=None):
    token = os.environ.get("GITHUB_TOKEN")
    if not token or os.environ.get("GITHUB_REPOSITORY", REPOSITORY) != REPOSITORY:
        raise RuntimeError("専用台帳を書き込むGitHubの権限を確認してください")
    req = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + path,
                                 method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json", "User-Agent": "collespo-pilot"})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            data = response.read()
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as error:
        # 応答本文やリクエストヘッダはログに出さない。
        if error.code == 404:
            return None
        raise RuntimeError(f"台帳APIの操作が失敗しました（HTTP {error.code}）") from None


def load_state():
    if github("/git/ref/heads/" + STATE_BRANCH) is None:
        head = github("/git/ref/heads/main")
        github("/git/refs", "POST", {"ref": "refs/heads/" + STATE_BRANCH, "sha": head["object"]["sha"]})
    row = github("/contents/" + STATE_FILE + "?ref=" + STATE_BRANCH)
    if row is None:
        return {"schema_version": 1, "entries": {}}, None
    data = json.loads(base64.b64decode(row["content"]))
    if data.get("schema_version") != 1 or not isinstance(data.get("entries"), dict):
        raise ValueError("投稿台帳の形式を確認してください")
    return data, row["sha"]


def record(key, entry):
    data, sha = load_state()
    data["entries"][key] = entry
    body = {"message": "pilot: record private upload state", "branch": STATE_BRANCH,
            "content": base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode()).decode()}
    if sha:
        body["sha"] = sha
    result = github("/contents/" + STATE_FILE, "PUT", body)
    if not result:
        raise RuntimeError("投稿台帳を保存できませんでした。追加投稿しません")


def youtube_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    values = [os.environ.get(key) for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")]
    if not all(values):
        raise RuntimeError("YouTubeの認証情報が設定されていません")
    credentials = Credentials(None, refresh_token=values[2], client_id=values[0], client_secret=values[1],
                              token_uri="https://oauth2.googleapis.com/token")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def owned_videos(yt):
    channels = yt.channels().list(part="id,contentDetails", mine=True).execute().get("items", [])
    if len(channels) != 1 or channels[0]["id"] != CHANNEL_ID:
        raise RuntimeError("コレスポの所有チャンネルと一致しません")
    playlist = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    for _ in range(100):
        page = yt.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50,
                                      pageToken=token).execute()
        ids.extend(x["contentDetails"]["videoId"] for x in page.get("items", []))
        token = page.get("nextPageToken")
        if not token:
            break
    if token:
        raise RuntimeError("全件を照合できませんでした。追加投稿しません")
    found = {}
    for offset in range(0, len(ids), 50):
        items = yt.videos().list(part="snippet,status,processingDetails", id=",".join(ids[offset:offset + 50])).execute()
        for item in items.get("items", []):
            marker = re.search(r"\[COLLESPO-PILOT:([a-z0-9-]+)\]", item.get("snippet", {}).get("description", ""))
            if marker:
                key = marker[1]
                if key in found:
                    raise RuntimeError("同じ回が複数あります。自動で追加しません")
                found[key] = item
    return found


def require_private(item):
    if item.get("snippet", {}).get("channelId") != CHANNEL_ID:
        raise RuntimeError("動画の所有者が一致しません")
    if item.get("status", {}).get("privacyStatus") != "private":
        raise RuntimeError("非公開ではないため、この試作処理では操作しません")
    if item.get("status", {}).get("uploadStatus") in {"failed", "rejected", "deleted"}:
        raise RuntimeError("YouTube側で動画の処理が失敗しています")


def select_episode(candidates, state, found):
    for data in candidates:
        key = episode_key(data)
        old, existing = state.get("entries", {}).get(key), found.get(key)
        if existing:
            require_private(existing)
        if old and old.get("status") == "confirmed":
            if not existing or existing["id"] != old["video_id"]:
                raise RuntimeError("以前の投稿が照合できません。再投稿は保留します")
            continue
        if old and not existing:
            raise RuntimeError("前回の投稿結果が不明です。動画を照合してから再開してください")
        return data, existing["id"] if existing else None
    return None, None


def output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(f"{key}={value}\n")


def prepare(episode, out, render_only=False):
    if episode != "auto" and not re.fullmatch(r"[a-z0-9-]+", episode):
        raise ValueError("企画IDが不正です")
    paths = sorted(CATALOG.glob("*.json")) if episode == "auto" else [CATALOG / (episode + ".json")]
    candidates = [load_episode(path) for path in paths]
    if render_only:
        data, existing = (candidates[0] if candidates else None), None
    else:
        state, _ = load_state()
        data, existing = select_episode(candidates, state, owned_videos(youtube_client()))
    out.mkdir(parents=True, exist_ok=True)
    plan = {"should_build": data is not None, "privacy": "private", "existing_id": existing}
    if data:
        plan.update(episode_id=data["id"], episode_key=episode_key(data))
        write_json(out / "episode.json", data)
        output("episode", data["id"])
    write_json(out / "plan.json", plan)
    output("build", "true" if data else "false")
    print("非公開の試作を生成します" if data else "未投稿の確認済み原稿はありません。追加生成・投稿はしません")


def metadata(data, timeline):
    chapters, last = [], -100
    for segment in timeline["segments"]:
        start = int(segment["start"])
        if (not chapters or segment["chapter"] != chapters[-1][1]) and start - last >= 10 and timeline["duration"] - start >= 10:
            chapters.append((start, segment["chapter"]))
            last = start
    desc = data["summary"] + "\n\n" + data["source_note"]
    desc += "\n\n" + data.get("guide_label", "観戦ガイド") + "：" + data["guide_url"] + "\n\n"
    if len(chapters) >= 3:
        desc += "\n".join(f"{s // 60:02}:{s % 60:02} {label}" for s, label in chapters) + "\n\n"
    desc += "出典（確認日 " + data["reviewed_on"] + "）\n"
    desc += "\n".join(s["label"] + "\n" + s["url"] for s in data["sources"])
    desc += "\n\n音声：VOICEVOX:四国めたん\n図・構成：コレスポ\n非公開で品質を確認する試作です。"
    if data.get("media_ids"):
        import pilot_media
        desc += "\n\n写真の出典・利用条件\n" + pilot_media.credits(data)
    desc += "\n[COLLESPO-PILOT:" + episode_key(data) + "]"
    if len(desc.encode()) > 5000:
        raise ValueError("概要欄が長すぎます")
    return {"snippet": {"title": data["title"], "description": desc, "categoryId": "17",
                         "defaultLanguage": "ja", "defaultAudioLanguage": "ja",
                         "tags": ["コレスポ", "観戦の見取り図"] + data.get("tags", ["サッカー", "チャンピオンズリーグ"])},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}


def upload(out, yt=None):
    from googleapiclient.http import MediaFileUpload
    data = load_episode(out / "episode.json")
    key = episode_key(data)
    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    quality = json.loads((out / "quality.json").read_text(encoding="utf-8"))
    video = out / "episode.mp4"
    if not quality.get("passed") or timeline["episode_key"] != key or quality["episode_key"] != key:
        raise ValueError("検証済みの原稿・音声・映像が一致しません")
    if hashlib.sha256(video.read_bytes()).hexdigest() != quality["video_sha256"]:
        raise ValueError("検査後に動画が変わっています")
    cover = out / ("thumbnail.jpg" if (out / "thumbnail.jpg").is_file() else "thumbnail.png")
    if cover.stat().st_size > 2_000_000:
        raise ValueError("表紙画像を2MB以下に調整してください")
    body = metadata(data, timeline)
    yt = yt or youtube_client()
    found = owned_videos(yt)
    state, _ = load_state()
    old = state["entries"].get(key)
    existing = found.get(key)
    if existing:
        require_private(existing)
        video_id = existing["id"]
    else:
        if old:
            raise RuntimeError("前回の投稿が照合できません。追加投稿しません")
        # 通信が途切れたときも、次回が盲目的に2本目を作らないための記録。
        record(key, {"status": "pending", "run_id": os.environ.get("GITHUB_RUN_ID", "local")})
        request = yt.videos().insert(part="snippet,status", body=body, notifySubscribers=False,
                                     media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True))
        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=2)
        video_id = response["id"]
    record(key, {"status": "uploaded", "video_id": video_id, "run_id": os.environ.get("GITHUB_RUN_ID", "local")})
    write_json(out / "upload-receipt.json", {"episode_key": key, "video_id": video_id, "privacy": "private", "status": "processing"})
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(cover), mimetype="image/jpeg" if cover.suffix == ".jpg" else "image/png")).execute()
    for attempt in range(16):
        items = yt.videos().list(part="snippet,status,processingDetails", id=video_id).execute().get("items", [])
        if len(items) != 1:
            raise RuntimeError("投稿した動画を照合できません")
        item = items[0]
        require_private(item)
        if item["status"].get("uploadStatus") == "processed" or item.get("processingDetails", {}).get("processingStatus") == "succeeded":
            receipt = {"episode_key": key, "video_id": video_id, "privacy": "private", "status": "confirmed",
                       "url": "https://www.youtube.com/watch?v=" + video_id,
                       "studio_url": "https://studio.youtube.com/video/" + video_id + "/edit"}
            record(key, {"status": "confirmed", "video_id": video_id})
            write_json(out / "upload-receipt.json", receipt)
            print(json.dumps(receipt, ensure_ascii=False))
            return receipt
        print(f"YouTubeで処理中（{attempt + 1}/16）。非公開を確認済み", flush=True)
        time.sleep(15)
    raise RuntimeError("動画は非公開で受領されていますが、処理完了は未確認です。再投稿せず照合してください")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "upload"])
    parser.add_argument("--episode", default="auto")
    parser.add_argument("--out", default="build/pilot")
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.episode, pathlib.Path(args.out), args.render_only)
    else:
        upload(pathlib.Path(args.out))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except Exception as error:
        # SDK例外のURLや認証情報は出さない。制御した説明だけを残す。
        message = str(error) if type(error) in {ValueError, RuntimeError} else type(error).__name__
        print("[error] " + message, file=sys.stderr)
        raise SystemExit(1)
