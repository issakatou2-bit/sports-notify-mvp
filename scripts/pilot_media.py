"""確認済みの実写素材だけを取得し、原本・出典・日付を動画へ結び付ける。"""
import hashlib
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "content/media/catalog.json"
LICENSES = {f"CC BY {version}": f"https://creativecommons.org/licenses/by/{version}/"
            for version in ("2.0", "3.0", "4.0")}
HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org"}


def valid_download_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username
            or parsed.password or parsed.port or not parsed.path.startswith("/wikipedia/commons/")
            or parsed.query or parsed.fragment):
        raise ValueError("素材の取得先が承認された配布元ではありません")
    return url


def validate_asset(asset):
    if asset.get("status") != "approved" or not re.fullmatch(r"[a-z0-9-]+", asset.get("id", "")):
        raise ValueError("目視・出典確認済みの素材が必要です")
    if asset.get("license") not in LICENSES or asset.get("license_url", "").rstrip("/") != LICENSES[asset["license"]].rstrip("/"):
        raise ValueError("対応する商用利用・改変可能なライセンスではありません")
    for key in ("title", "author", "captured_at", "label", "changes", "context_note", "review_note"):
        if not isinstance(asset.get(key), str) or not asset[key].strip():
            raise ValueError("素材の出典・撮影時点・変更表示が不足しています: " + key)
    page = urllib.parse.urlsplit(asset.get("source_page", ""))
    if page.scheme != "https" or page.hostname != "commons.wikimedia.org" or not page.path.startswith("/wiki/File:"):
        raise ValueError("素材の個別出典ページが必要です")
    date.fromisoformat(asset["checked_on"])
    if asset["captured_at"] != "unknown":
        date.fromisoformat(asset["captured_at"][:10])
    if not re.fullmatch(r"[0-9a-f]{64}", asset.get("sha256", "")):
        raise ValueError("確認した素材のハッシュが必要です")
    limit = {"image": 10_000_000, "video": 50_000_000}.get(asset.get("kind"), 0)
    if not isinstance(asset.get("bytes"), int) or not 1 <= asset["bytes"] <= limit:
        raise ValueError("素材の種類・容量が範囲外です")
    if asset["kind"] == "video":
        clip = asset.get("clip", {})
        if (not isinstance(clip.get("start"), int) or not 0 <= clip["start"] <= 3600
                or not isinstance(clip.get("duration"), int) or not 1 <= clip["duration"] <= 15
                or clip.get("audio") != "muted"):
            raise ValueError("確認済みの消音した映像区間が必要です")
    valid_download_url(asset["source_url"])


def catalog():
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("素材台帳の版が不正です")
    result = {}
    for asset in raw["assets"]:
        validate_asset(asset)
        if asset["id"] in result:
            raise ValueError("素材IDが重複しています")
        result[asset["id"]] = asset
    return result


def assets_for(data):
    ids = data.get("media_ids", [])
    if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("使用素材IDが不正・重複しています")
    if not ids:
        return []
    approved = catalog()
    if any(aid not in approved for aid in ids):
        raise ValueError("未確認の素材は動画へ入れられません")
    return [approved[aid] for aid in ids]


def cache_dir():
    return pathlib.Path(os.environ.get("PILOT_MEDIA_CACHE", str(ROOT / "build/licensed-media")))


def file_path(asset):
    # 台帳の自由記述ファイル名をパスとして使わない。
    return cache_dir() / (asset["id"] + (".jpg" if asset["kind"] == "image" else ".webm"))


def verify_file(path, asset):
    if path.stat().st_size != asset["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
        raise ValueError("確認した原本と素材が一致しません: " + asset["id"])


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        valid_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_asset(asset):
    validate_asset(asset)
    path = file_path(asset)
    if path.exists():
        verify_file(path, asset)
        return path
    opener = urllib.request.build_opener(CheckedRedirect())
    request = urllib.request.Request(asset["source_url"], headers={
        "User-Agent": "CollespoMedia/1.0 (https://collespo.com/about.html)"})
    with opener.open(request, timeout=50) as response:
        valid_download_url(response.geturl())
        raw = response.read(asset["bytes"] + 1)
    if len(raw) != asset["bytes"] or hashlib.sha256(raw).hexdigest() != asset["sha256"]:
        raise ValueError("配布元の素材が確認済みの版と違います: " + asset["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".download")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return path


def prepare(data, out=None):
    assets = assets_for(data)
    for asset in assets:
        fetch_asset(asset)
    if out is not None and assets:
        out = pathlib.Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "media-sources.json").write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "media-credits.txt").write_text(credits(data), encoding="utf-8")
    return assets


def credits(data):
    blocks = []
    for asset in assets_for(data):
        blocks.append("\n".join([asset["title"] + " — " + asset["author"],
            asset["license"] + " " + asset["license_url"], asset["source_page"],
            "撮影時点: " + asset["captured_at"], "変更: " + asset["changes"]]))
    return "\n\n".join(blocks)
