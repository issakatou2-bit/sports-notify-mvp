"""MLB公式RSSの試合総括見出し。本文は取得せず、元URLと公開日時を保存する。"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

RSS = "https://www.mlb.com/feeds/news/rss.xml"
RECAP = re.compile(r"^/news/([a-z-]+)-win-(alwc|nlwc|alds|nlds|alcs|nlcs|world-series)-game-([1-7])-(\d{4})$")


def utc(value):
    """ISO/RSSの時刻を同じ基準に。タイムゾーン不明は推測しない。"""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            dt = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def recap_identity(url):
    u = urlsplit(url or "")
    if u.scheme != "https" or u.netloc != "www.mlb.com":
        return None
    m = RECAP.fullmatch(u.path)
    return m.groups() if m else None


def parse(raw, now, limit=4):
    rows, seen = [], set()
    for item in ET.fromstring(raw).findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        at = utc(item.findtext("pubDate"))
        if not title or url in seen or not recap_identity(url) or not at:
            continue
        if not now - timedelta(hours=30) <= at <= now:
            continue
        seen.add(url)
        rows.append({"query": "PS試合総括", "title": title, "url": url,
                     "source": "MLB.com", "at": at.isoformat()})
    rows.sort(key=lambda h: h["at"], reverse=True)
    return rows[:limit]


def fetch(limit=4):
    import requests
    r = requests.get(RSS, headers={"User-Agent": "collespo/1.0 (+https://collespo.com)"}, timeout=20)
    r.raise_for_status()
    return parse(r.content, datetime.now(timezone.utc), limit)
