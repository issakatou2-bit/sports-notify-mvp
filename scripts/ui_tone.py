"""雨衣ソロだけの口調。引用・数字・名前・札には手を加えない。"""
import copy
import re

# 本人10/13指定（apsc-video/docs/キャラの口調.md の雨衣節）。
GUIDANCE = ('雨衣はやわらかい敬語（です・ますね・しましょう）。一人称は原則使わない。'
            '事実・数字・選手名と引用はそのまま。感情や問いを新しく足さない。')

# 長い語尾から選ぶ。文末だけを対象とし、一般の活用を推測しない。
ENDINGS = (
    ('だったのよ', 'でした'), ('だったわね', 'でしたね'), ('だったわ', 'でした'),
    ('なのかしら', 'でしょうか'), ('なのよ', 'です'), ('なのね', 'ですね'),
    ('しているわね', 'していますね'), ('しているのよ', 'しています'),
    ('しましょうね', 'しましょう'), ('だわね', 'ですね'), ('だわ', 'です'),
    ('だよ', 'です'), ('だね', 'ですね'),
    ('ですよ', 'です'), ('ますよ', 'ますね'), ('ですねえ', 'ですね'),
    ('かしら', 'でしょうか'), ('見ていくわね', '見ていきましょう'),
    ('注目してね', '注目しましょう'), ('見てみよう', '見てみましょう'),
)
PHRASES = {'今日の勝利貢献順位です。': '今日の勝利貢献順位を見ていきましょう。',
           'また見に来てくださいね。': 'また見に来てください。'}
QUOTES = re.compile(r'(「[^」]*」|『[^』]*』|“[^”]*”)')


def text(source):
    def prose(value):
        for before, after in PHRASES.items():
            value = value.replace(before, after)
        def sentence(match):
            body, mark = match.group(1), match.group(2)
            for before, after in ENDINGS:
                if body.endswith(before):
                    return body[:-len(before)] + after + mark
            if body.endswith('だ'):
                return body[:-1] + 'です' + mark
            return body + mark
        return re.sub(r'([^。！？!?]+)([。！？!?]|$)', sentence, value)
    return ''.join(chunk if i % 2 else prose(chunk)
                   for i, chunk in enumerate(QUOTES.split(source)))


def narration(source, default_speaker=2):
    import solo_host
    if solo_host.for_segments(source.get('segments', []), default_speaker) != 'ui':
        return source
    result = copy.deepcopy(source)
    for seg in result['segments']:
        seg['text'] = text(seg.get('text', ''))
        # 数字だけを並べる成績札も敬体で読む。引用は対象外。
        if seg.get('kind') in ('hero', 'list') and seg['text'].endswith('。'):
            body = seg['text'][:-1]
            if not body.endswith(('です', 'ます', 'でした', 'ました', 'ね', '」', '』')):
                seg['text'] = body + 'です。'
        if (seg.get('meta') or {}).get('who') == '四国めたん':
            seg['meta']['who'] = '雨衣'
    return result
