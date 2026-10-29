"""記事の公開日を保存し、対象日の2日前までの材料だけを採用する。通信なし。"""
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit


def publication_day(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()
    except ValueError:
        try:
            return parsedate_to_datetime(str(value)).date()
        except (TypeError, ValueError, OverflowError):
            return None


def url_days(url):
    path = urlsplit(url or '').path
    days = []
    for match in re.finditer(r'(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)', path):
        try:
            days.append(date(*map(int, match.groups())).isoformat())
        except ValueError:
            continue
    return days


class PublicationHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dates = []
        self.canonical = ''
        self.ld = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = (attrs.get('property') or attrs.get('name') or attrs.get('itemprop') or '').lower()
        if tag == 'meta' and key in {'article:published_time', 'datepublished', 'pubdate', 'date', 'parsely-pub-date'}:
            self.dates.append(attrs.get('content', ''))
        if tag == 'time' and attrs.get('datetime'):
            # 更新日時を公開日に代用しない。
            if key != 'datemodified' and not re.search(r'updat|modif', attrs.get('class', ''), re.I):
                self.dates.append(attrs['datetime'])
        if tag == 'link' and attrs.get('rel', '').lower() == 'canonical':
            self.canonical = attrs.get('href', '')
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.ld, self.parts = True, []

    def handle_data(self, data):
        if self.ld:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag != 'script' or not self.ld:
            return
        self.ld = False
        def walk(obj):
            if isinstance(obj, dict):
                if obj.get('datePublished'):
                    self.dates.append(obj['datePublished'])
                for key in ('@graph', 'mainEntity'):
                    walk(obj.get(key))
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)
        try:
            walk(json.loads(''.join(self.parts)))
        except (ValueError, TypeError):
            pass


def dated_article(row, html='', resolved_url=''):
    """RSS・記事・URLそれぞれの根拠を保持。再配信日より古い原記事を優先。"""
    result = dict(row)
    evidence = list(row.get('publication_evidence') or [])
    for key in ('at', 'published_at', 'published', 'published_date'):
        day = publication_day(row.get(key))
        if day:
            evidence.append(dict(source=key, date=day.isoformat()))
    parser = PublicationHTML()
    parser.feed(html or '')
    for value in parser.dates:
        day = publication_day(value)
        if day:
            evidence.append(dict(source='article', date=day.isoformat()))
    for url in (row.get('url'), resolved_url, parser.canonical):
        for day in url_days(url):
            evidence.append(dict(source='url', date=day))
    evidence = [dict(source=source, date=day) for source, day in sorted({
        (e['source'], e['date']) for e in evidence if publication_day(e.get('date'))})]
    result['publication_evidence'] = evidence
    result['published_date'] = min((e['date'] for e in evidence), default=None)
    return result


def fresh_articles(rows, target_date=None, corroborating=()):
    target = publication_day(target_date) or datetime.now(timezone.utc).date()
    earliest = target - timedelta(days=2)
    dated = [dated_article(row) for row in rows]
    known = [dated_article(row) for row in corroborating] + dated
    def fresh(row):
        day = publication_day(row.get('published_date'))
        return day is not None and earliest <= day <= target
    def title(row):
        return re.sub(r'\W+', '', row.get('title') or row.get('text') or '').casefold()
    def origin(row):
        host = (urlsplit(row.get('url') or '').hostname or '').removeprefix('www.')
        return (host if host and host != 'news.google.com' else
                row.get('source') or row.get('outlet') or '').casefold()
    kept = []
    for row in dated:
        if fresh(row):
            kept.append(row)
        elif not row.get('published_date'):
            # 姓や話題が同じだけでは裏付けにならない。同じ内容を別媒体が日付付きで報じた場合。
            refs = [other for other in known if fresh(other) and title(row)
                    and title(row) == title(other) and origin(row) and origin(other)
                    and origin(row) != origin(other)]
            if refs:
                row['corroborated_by'] = [dict(url=r.get('url', ''), source=origin(r),
                                             date=r['published_date']) for r in refs]
                kept.append(row)
            elif any(earliest <= publication_day(ref.get('date')) <= target
                     for ref in row.get('corroborated_by') or []
                     if publication_day(ref.get('date')) and ref.get('source')
                     and ref['source'] != origin(row)):
                kept.append(row)
    return kept


def fresh_material(material, target_date=None):
    result = dict(material)
    result['headlines'] = fresh_articles(material.get('headlines') or [], target_date)
    result['headline_pool'] = fresh_articles(material.get('headline_pool') or [], target_date,
                                           corroborating=result['headlines'])
    result['posts'] = fresh_articles(material.get('posts') or [], target_date)
    return result
