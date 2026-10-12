"""使った見出しと同じ記事URLだけを出典へ。URL/媒体名を推測しない。"""
import urllib.parse


def safe_url(value):
    if not isinstance(value,str):return ''
    value=value.strip()
    if len(value)>2048 or any(ord(c)<33 or ord(c)==127 for c in value):return ''
    try:
        parsed=urllib.parse.urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            return ''
        return value
    except ValueError:
        return ''


def references(narration, budget=1500):
    """選択済みの原稿metadataだけ。前回のRSSや見出し一覧を取り直さない。"""
    lines,seen,used=[],set(),0
    for segment in narration.get('segments') or []:
        for entry in (segment.get('meta') or {}).get('source_headlines') or []:
            url=safe_url(entry.get('url'))
            if not url or url in seen:continue
            source=' '.join(str(entry.get('source') or '現地報道').split())[:60]
            title=' '.join(str(entry.get('title') or entry.get('jp') or '').split())[:100]
            pair=[f'・{source}：{title}',url]
            size=sum(map(len,pair))+2
            if used+size>budget:
                print('[info] 概要欄の長さを守るため、長い記事リンクを省略')
                continue
            lines+=pair;seen.add(url);used+=size
    return ['','紹介した記事の出典']+lines if lines else []
