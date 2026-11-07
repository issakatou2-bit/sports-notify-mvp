"""人が書いたMLB用語の材料。自動選定せず、指定した語だけ制作する。"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path=None):
    rows = json.loads(Path(path or ROOT / 'data/mlb_terms.json').read_text(encoding='utf-8'))['terms']
    out = {}
    for row in rows:
        spec = deepcopy(row)
        if not spec['key'].startswith('mlb_term_') or spec['key'] in out:
            raise ValueError('用語のkeyが不正または重複')
        for line in spec['lines']:
            if line['who'] not in ('zundamon', 'metan') or not line['text']:
                raise ValueError('用語の話者または台詞が不正')
            if 'card' in line and (line['who'] != 'metan' or type(line['card']) is not int
                                   or not 0 <= line['card'] < len(spec['cards'])):
                raise ValueError('用語の札番号または話者が不正')
        spec.update(mlb_term=True, manual_only=True, style='v3', label=spec['term'],
                    heading=spec['term'], kind_label='MLB用語', data_credit=spec['source_label'],
                    source=spec['source_label'] + ' ' + spec['source_url'],
                    items=[(c['head'], c['body']) for c in spec['cards']], longform_url='')
        out[spec['key']] = spec
    return out


def metadata(spec, published=None):
    """関連語は公開済み台帳のURLだけ。予約・非公開・保留は載せない。"""
    if published is None:
        path = ROOT / 'data/published_assets.json'
        published = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    lead = ['MLB用語：' + spec['term'], '',
            '出典：' + spec['source_label'] + ' ' + spec['source_url']]
    published = published.get('assets', published)
    terms = load()
    for key in spec['related']:
        row = published.get(key) or {}
        if row.get('privacy') != 'public' or row.get('hold_video') or row.get('held'):
            continue
        stamp = row.get('publish_at') or row.get('published_at')
        try:
            when = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            if when.tzinfo is None or when > datetime.now(timezone.utc):
                continue
        except (ValueError, TypeError):
            continue
        url = row.get('url')
        if isinstance(url, str) and url.startswith(('https://youtu.be/', 'https://www.youtube.com/watch?')) and key in terms:
            lead.append('あわせて：' + terms[key]['term'] + ' ' + url)
    if spec.get('longform_url'):
        lead.append(spec['longform_url'])
    return dict(title=spec['title'], lead=lead, tags=['MLB', 'MLB用語', spec['term'], 'コレスポ'])

