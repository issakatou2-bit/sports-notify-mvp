"""保存材料の話題に合わせて掛け合いを組み立てる共通部品。"""
import re
from zlib import crc32

from duo import METAN, ZUNDA


NUMBER = re.compile(r'\d|[〇零一二三四五六七八九十百千万億兆]+(?=[年月日時分秒点本位試回勝敗件倍割厘]|人(?:だ|よ|の|で|と|が|は|[。！、？]|$))')
VAGUE_ENDING = ('注目したい', '気になる', '待ちたい', '楽しみ')


def pick(key, *options):
    """#442 と同様、同じ材料と選択肢は毎回同じ台詞にする。"""
    return options[crc32(f'{key}:{options[0]}'.encode()) % len(options)]


def receive(text, reaction):
    """材料に既にある応答語は取り除き、場面に合う受けに差し替える。"""
    return reaction + '。' + re.sub(r'^(?:はい|ええ|そうね|そうなの)[。､、]\s*', '', text, count=1)


def ending_segments(segments, ending):
    """最後の画面を保ち、数え直しのまとめを新しい事実として登録しない。"""
    pair = segments[-2:]
    return segments + [dict(s, text=text, meta=dict(s['meta'], dialogue_ending=True))
                       for s, text in zip(pair, ending)]


def problems(segments):
    lines = [s['text'] for s in segments if s['speaker'] == ZUNDA and s['kind'] != 'outro']
    errors = []
    if not lines or not lines[0].endswith('！'):
        errors.append('最初のずんだもんの台詞が感嘆で終わっていません')
    if all(text.endswith('？') for text in lines):
        errors.append('ずんだもんの台詞が問いだけになっています')
    if any(NUMBER.search(text) for text in lines):
        errors.append('ずんだもんの台詞に数字が入っています')
    tail = [s for s in segments if s['kind'] != 'outro'][-2:]
    if [s['speaker'] for s in tail] != [ZUNDA, METAN] or tail[0]['text'].endswith('？'):
        errors.append('締めが感想とまとめになっていません')
    if (any(any(word in s['text'] for word in VAGUE_ENDING) for s in tail)
            and not any(NUMBER.search(s['text']) for s in tail)):
        errors.append('締めが中身のない感想だけになっています')
    middle = lines[:-1]
    if sum('も気になる' in text and 'のだ' in text for text in middle) >= 2:
        errors.append('ずんだもんの「も気になるのだ」が2回以上あります')
    return errors


def require(segments):
    errors = problems(segments)
    if errors:
        raise ValueError('、'.join(errors))


def material_number(data):
    """材料の items の big か rows から、画面に出ている数字を1つ拾う。"""
    for item in data.get('items') or []:
        big = item.get('big') or {}
        value, unit = str(big.get('value') or ''), str(big.get('unit') or '')
        if re.fullmatch(r'\d[\d億万]*(?:\.\d+)?', value):
            quantity = value + unit.removesuffix('（約）').removesuffix('の後')
            if quantity in item.get('text', '') or value in item.get('text', ''):
                return quantity
    for item in data.get('items') or []:
        for _, value in item.get('rows') or []:
            text = str(value)
            if re.search(r'\d', text) and re.fullmatch(r'\d[\d億万]*(?:\.\d+)?[^0-9]*', text) and text in item.get('text', ''):
                return text
    return None


def material_ending(data, *, kind=None, subject=None):
    """material['ending'] を優先し、無ければ出来事と画面の数字で締める。"""
    if data.get('ending'):
        reaction, summary = data['ending']
        return reaction, summary
    info = data.get('news') or {}
    report = info.get('report') or {}
    if subject is None:
        if kind == 'mlb':
            subject = info.get('name') or (data.get('hook') or {}).get('score', '')
        else:
            subject = (report.get('players') or [None])[0] or (info.get('context') or {}).get('team') or ''
    number = material_number(data)
    if number:
        summary = f'そうね。まずは{number}、この数字を押さえておきましょう。'
    elif kind == 'mlb' and not info.get('official'):
        summary = 'そうね。いま分かっているのは、合意が報じられたことまでよ。'
    else:
        summary = f'そうね。{subject}の続報が入ったら、また数字で確かめるわ。'
    if kind == 'mlb':
        if info.get('official'):
            reaction = f'{subject}の新しいプレーが、いよいよ見えてくるのだ！'
        else:
            reaction = f'{subject}の行き先が、いよいよ見えてきたのだ！'
    elif kind == 'analysis':
        reaction = f'{subject}の動きが、ここまで見えてきたのだ！'
    elif report.get('kind') in ('監督就任', '監督退任'):
        team = (info.get('context') or {}).get('team') or subject
        reaction = f'{team}は監督を代えて立て直しに出たのだ！'
    else:
        reaction = f'{subject}のニュースが、はっきりしてきたのだ！'
    return reaction, summary


def market_opening(data, key):
    # 市場の比べのように、決まった型が合わない回は材料に書いた台詞を使う（検査は problems のまま）。
    if data.get('opening'):
        return data['opening']
    name = data['hook']['score']
    if data.get('large_contract'):
        return pick(key, 'また大型契約なのだ！', f'{name}の大型契約にびっくりなのだ！',
                    '移籍市場が大きく動いたのだ！')
    return pick(key, f'{name}の移籍話が動いたのだ！', f'{name}の行き先が気になるのだ！',
                f'{name}の契約のニュースが来たのだ！')


def market_ending(data):
    if data.get('ending'):
        reaction, summary = data['ending']
        return reaction, summary
    entry = data.get('large_contract')
    if entry:
        return ('年数と総額を並べると見え方が変わるのだ。',
                'ええ。年平均も契約の大きさを見る目安になるわ。')
    return ('契約の中身まで聞くと見え方が変わるのだ。',
            f'そうね。{data["hook"]["score"]}の契約は、いまのところ合意が報じられた段階よ。')
