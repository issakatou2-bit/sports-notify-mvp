"""ファン素材の公開用表示。URLと媒体の情報は内部材料にだけ残す。"""
import copy
import re

LABEL = '海外ファンの声（匿名）'
MARKERS = re.compile(r'(?i)reddit|(?<!\w)/?[ru]/[\w-]+|@[\w\u0080-\uffff.-]+')
URL = re.compile(r'https?://(?:www\.)?(?:old\.)?reddit\.com/[^\s<>）)\]"\']*', re.I)


def reddit(row):
    return (row.get('kind') == 'reddit' or str(row.get('platform', '')).lower() == 'reddit'
            or bool(MARKERS.search(str(row.get('source', ''))))
            or bool(URL.search(str(row.get('url', '')))))


def safe(row):
    text = ' '.join(str(row.get(k) or '') for k in ('text', 'ja', 'original', 'title', 'caption_en', 'translation', 'said', 'who'))
    names = [str(row.get(k) or '') for k in ('author', 'author_name', 'username', 'displayName')]
    return not MARKERS.search(text) and not any(name and name in text for name in names)


def text(value):
    return MARKERS.sub(LABEL, URL.sub(LABEL, str(value)))


def source(row):
    return LABEL if reddit(row) else row.get('source', '')


def voices(value):
    """公開用コピー。内部の元URLを上書きしない。古い保存材料もここを通す。"""
    result = material(value)
    for key in ('voices', 'jp_praise'):
        result[key] = [dict(r, source=LABEL, url='', author='') if reddit(r) or reddit(value) else r
                       for r in result.get(key, []) if safe(r)]
    if reddit(value):
        result['source'] = LABEL
        result['source_url'] = ''
    return result


def description(value):
    # 公式チャンネル等の @handle は元のリンクを保つ。
    return re.sub(r'(?i)reddit|(?<!\w)/?r/[\w-]+', LABEL, URL.sub(LABEL, str(value)))


def material(value):
    result = copy.deepcopy(value)
    for key in ('voices','jp_praise'):
        rows = []
        for row in result.get(key,[]):
            if not safe(row):
                continue
            for replies in ('reply_ja','reply_details'):
                if isinstance(row.get(replies),list): row[replies] = [r for r in row[replies] if safe(r)]
            if reddit(row) or reddit(value):
                row['source'] = LABEL
                for name in ('author','author_name','username','displayName'):
                    row.pop(name,None)
            rows.append(row)
        result[key] = rows
    if reddit(value):
        result['source'] = LABEL
    return result
