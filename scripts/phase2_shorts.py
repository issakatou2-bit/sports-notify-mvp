"""保存成績と長編の要所を既存の掛け合いに渡す。"""
import short_common
import soccer_national_topics as topics
import topic_dialogue
from duo import METAN


SEASON = 'mlb_season_insight'
HIGHLIGHT = 'long_highlight'


def dialogue(program, key, title, day, label, credit, panels, *, ending, **material):
    return topics.tone_gate(short_common.prepare(dict(
        program=program, topic=key, topic_key=key, title=title, label=label,
        date_jst=day, screen_title=label, credit=credit,
        segments=topics.dialogue_segments(key, panels, None, ending=ending),
        duration_budget=dict(limit=45, grace=0), **material)))


def season_narration(key):
    import generated_topics
    spec = generated_topics.get(key)
    fact = spec['insight']
    rows = fact['rows']
    answer, sep, detail = fact['answer'].partition('。')
    name = spec['jp']
    if key.endswith(('_rare_dunn', '_rare_whip')):
        first, rank = answer.split('で、', 1)
        answer = first + 'だったわ'
        detail = rank + '。' + detail
    if key.endswith('_rare_dunn'):
        options = (f'{name}、とんでもない数字なのだ！', f'{name}の打席、数字で見るとすごいのだ！')
        turn = 'アダム・ダン本人と比べるとどうなのだ？'
        ending = ('打席ごとの結果が、数字に出ているのだ。',
                  'そうなの。アダム・ダン本人の最高まで上回ったのよ。')
        # 画面では順位と母数を先に見せ、長い説明は読み上げで補う。
        gate, rank_text = rows[1][1].split('以上', 1)
        population, rank = rank_text.split('の中で')
        rows = [rows[0], [f'順位（{gate}以上）', f'{population}中{rank}'], rows[2]]
    elif key.endswith('_rare_whip'):
        options = (f'{name}、走者を出さない投球が光るのだ！', f'{name}は走者の少なさが際立つのだ！')
        turn = '防御率とは違って、走者に注目する数字なのだ。'
        ending = ('投球の見え方が変わるのだ。',
                  'そうなの。山本由伸は走者の少なさでもトップクラスだったわ。')
    elif '_rare_' in key:
        options = (f'{name}の打席に目を引く数字があるのだ！', f'{name}の打席を数字で見ると面白いのだ！')
        turn = '打席の中身に注目なのだ。'
        ending = ('打席の印象が変わったのだ。', 'ええ。この割合でも上位に入ったのよ。')
    elif 'hr_month' in key or 'hr_streak' in key:
        options = (f'{name}の本塁打が続いた時期が気になるのだ！', f'{name}の本塁打、時期で見ると面白いのだ！')
        turn = '打った時期を並べると勢いが分かるのだ。'
        ending = ('試合を並べて見ると面白いのだ。', 'ええ。本塁打が出た時期に注目したわ。')
    else:
        options = (f'{name}の今季、目を引く試合があるのだ！', f'{name}の際立った試合を振り返りたいのだ！')
        turn = 'その試合が、今季のほかの試合とどれだけ違うのだ？'
        ending = ('シーズンの中でも印象に残るのだ。',
                  'そうなの。今季の試合を並べると、その数字が目立つわ。')
    panels = [(topic_dialogue.pick(key, *options), topic_dialogue.receive(answer + sep, 'ええ'),
               name + 'の今季', rows[:1]),
              (turn, topic_dialogue.receive(detail, 'そうね'), '数字で比べる', rows[1:])]
    return dialogue(SEASON, key, spec['title'], '2026-09-30', 'MLB',
                    'MLB Stats API', panels, ending=ending, source_url=fact['source'],
                    baseball_average_voice=True,
                    sanity_materials=[dict(source='MLB Stats API', sport='mlb', facts=spec)])


def season_metadata(doc):
    said = '\n'.join(s['text'] for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro')
    return dict(snippet=dict(title=doc['title'], description=(
        said + '\n\n出典: MLB Stats API\n' + doc['source_url'] +
        '\n音声: VOICEVOX:ずんだもん・四国めたん\n#MLB #Shorts'),
        categoryId='17', tags=['MLB', 'メジャーリーグ'], defaultLanguage='ja', defaultAudioLanguage='ja'))


def information(doc):
    return [dict(subject=s['meta']['head'], fact=label, value=value,
                 source=doc['source_url'], segments=[i])
            for i, s in enumerate(doc['segments'])
            if s['speaker'] == METAN and s['kind'] != 'outro' and not s['meta'].get('dialogue_ending')
            for label, value in s['meta']['rows']]


def check(doc):
    try:
        if doc['program'] == SEASON:
            expected = season_narration(doc['topic'])
        elif doc['program'] == HIGHLIGHT:
            expected = __import__('scheduled_longs').highlight_narration(
                doc['long_material'], doc['highlight_key'], doc['long_video_id'])
        else:
            return []
        if topics.doc_as_json(expected) == topics.doc_as_json(doc):
            return []
    except (KeyError, ValueError, TypeError, StopIteration):
        pass
    return ['掛け合いの数字・題が保存材料と一致しません']
