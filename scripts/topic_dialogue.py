"""保存材料の話題に合わせて掛け合いを組み立てる共通部品。"""
import re
from zlib import crc32

from duo import METAN, ZUNDA


NUMBER = re.compile(r'\d|[〇零一二三四五六七八九十百千万億兆]+(?=[年月日時分秒点本位試回勝敗件倍割厘]|人(?:だ|よ|の|で|と|が|は|[。！、？]|$))')


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
    return errors


def require(segments):
    errors = problems(segments)
    if errors:
        raise ValueError('、'.join(errors))


def market_opening(data, key):
    name = data['hook']['score']
    if data.get('large_contract'):
        return pick(key, 'また大型契約なのだ！', f'{name}の大型契約にびっくりなのだ！',
                    '移籍市場が大きく動いたのだ！')
    return pick(key, f'{name}の移籍話が動いたのだ！', f'{name}の行き先が気になるのだ！',
                f'{name}の契約のニュースが来たのだ！')


def market_ending(data):
    entry = data.get('large_contract')
    if entry:
        return ('年数と総額を並べると見え方が変わるのだ。',
                'ええ。年平均も契約の大きさを見る目安になるわ。')
    return ('契約の中身まで聞くと見え方が変わるのだ。',
            f'そうね。{data["hook"]["score"]}の契約は、いまのところ合意が報じられた段階よ。')
