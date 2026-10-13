"""公開台帳からサイトの動画表示と構造化データを作る（外部通信なし）。"""
import html
import json
import pathlib
import re

from video_visibility import is_public


def load_published_videos(path="data/published_videos.json"):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def published_entries(ledger):
    """日付キーの公開動画のみ。同じ日・同じIDの再掲は1本にまとめる。"""
    seen = set()
    rows = []
    for kind, records in ledger.items():
        if not isinstance(records, dict):
            continue
        for date, entry in records.items():
            if (re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and is_public(entry)
                    and isinstance(entry["video_id"], str)
                    and re.fullmatch(r"[A-Za-z0-9_-]+", entry["video_id"])):
                rows.append((date, kind, entry))
    for date, kind, entry in sorted(rows, key=lambda row: row[0], reverse=True):
        key = (date, entry["video_id"])
        if key not in seen:
            seen.add(key)
            yield date, kind, entry


def player_videos(name, ledger):
    # 球団に所属しているだけでは本人の動画とみなさない。
    related = {}
    for _, _, entry in published_entries(ledger):
        if (name in str(entry.get("title") or "")
                or name in str(entry.get("description") or "")
                or name in (entry.get("players") or [])
                or name == entry.get("player_name")):
            related.setdefault(entry["video_id"], entry)
    return list(related.values())


def embed_url(entry):
    return "https://www.youtube-nocookie.com/embed/" + entry["video_id"]


def video_jsonld(entries):
    objects = []
    for entry in entries:
        obj = {"@context": "https://schema.org", "@type": "VideoObject",
               "embedUrl": embed_url(entry)}
        # published_atは台帳のアップロード記録。予約公開日時とは分ける。
        for target, sources in {
            "name": ("name", "title"), "description": ("description",),
            "thumbnailUrl": ("thumbnailUrl", "thumbnail_url"),
            "uploadDate": ("uploadDate", "published_at"),
            "contentUrl": ("contentUrl", "content_url"),
        }.items():
            for source in sources:
                if entry.get(source):
                    obj[target] = entry[source]
                    break
        # YouTube視聴ページのurlは動画ファイルのcontentUrlではない。
        objects.append(obj)
    if not objects:
        return ""
    return ('<script type="application/ld+json">'
            + json.dumps(objects, ensure_ascii=False).replace("<", "\\u003c")
            + '</script>')


VIDEO_STYLE = """
  .published-videos { display: grid; gap: 1rem; margin: 1.2rem 0 1.8rem; }
  .published-video { margin: 0; min-width: 0; }
  .published-video iframe { width: 100%; aspect-ratio: 16 / 9; border: 0;
    border-radius: 8px; display: block; }
  .published-video figcaption { font-size: .85rem; margin-top: .4rem; }
"""


def render_videos(entries):
    if not entries:
        return ""
    parts = ['<section aria-label="公開済みの関連動画" class="published-videos">']
    for entry in entries:
        title = html.escape(entry.get("title") or "YouTube動画")
        watch = "https://www.youtube.com/watch?v=" + entry["video_id"]
        parts.append(f'<figure class="published-video"><iframe src="{embed_url(entry)}" '
                     f'title="{title}" loading="lazy" width="560" height="315" '
                     'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>'
                     f'<figcaption><a href="{watch}" target="_blank" rel="noopener">'
                     f'{title} — YouTubeで見る</a></figcaption></figure>')
    parts.append('</section>')
    return "\n".join(parts)
