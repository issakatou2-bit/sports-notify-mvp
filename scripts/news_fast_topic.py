
"""ニュース材料を既存の掛け合いショートへ渡す。"""
import re

import market_watch as common
import soccer_national_topics as shared
import short_common
import topic_dialogue


def narration(sport, topic, material):
    if not re.fullmatch(r'news-(?:mlb-[a-z0-9-]+|espn-[0-9]+)', topic):
        raise ValueError('ニュースの題材IDが不正です')
    mlb = sport == 'mlb'
    if mlb != topic.startswith('news-mlb-'):
        raise ValueError('競技とニュースの題材IDが一致しません')
    news = material['news']
    if mlb:
        name = news['name']
        if not material['readings'].get(name):
            raise ValueError('選手名の読みがありません')
        if not news['official'] and len(set(material['items'][0]['sources'])) < 2:
            raise ValueError('独立した契約報道の出典が足りません')
        if news['official'] and not news['transaction_id']:
            raise ValueError('MLBの取引記録IDがありません')
        first = f'{name}の移籍話が動いたのだ！'
        closing = ('これからのプレーが楽しみなのだ。', 'そうね。新しい球団でのプレーに注目したいわ。')
        if not news['official']:
            closing = ('正式発表を待ちたいのだ。', 'そうね。いま分かっているのは、合意が報じられたことまでよ。')
        hook = material['hook'] if material['hook']['big'] else None
        options = dict(team_id=news.get('team_id'), baseball_average_voice=True)
    else:
        first = material['opening']
        closing = ('ここからの試合も気になるのだ。', 'そうね。次の試合でチームの動きに注目したいわ。')
        hook = None
        from soccer_slots_v4 import clubs_for
        options = dict(clubs=clubs_for([news['context']['team']]))
    panels = []
    for i, item in enumerate(material['items']):
        sources = [common.source_ok(url) for url in item['sources']]
        if not sources or not item['source_names']:
            raise ValueError('ニュースの札に出典がありません')
        extra = dict(followup_sources=sources, sub='ニュース')
        if item.get('big'):
            if not shared.mlb_big_in_text(item['big'], item['text']):
                raise ValueError('契約の数字が台詞にありません')
            extra['big'] = item['big']
        response = ('ええ', 'そうね', 'そうなの')[i % 3]
        panels.append((first if i == 0 else item['ask'], topic_dialogue.receive(item['text'], response),
                       item['head'], [tuple(row) for row in item['rows']], extra))
    label = 'MLB' if mlb else '欧州サッカー'
    program = shared.MLB_PROGRAM if mlb else shared.PROGRAM
    return shared.tone_gate(short_common.prepare(dict(
        program=program, topic=topic, topic_key=topic, event_id=topic, title=material['title'] + ' #Shorts',
        date_jst=material['checked_on'], screen_title=label, source_url=material['items'][0]['sources'][0],
        news_material=material, segments=shared.dialogue_segments(topic, panels, hook, ending=closing),
        duration_budget=dict(limit=shared.MLB_LIMIT if mlb else shared.LIMIT, grace=0),
        sanity_materials=[dict(source=label + 'のニュース資料', sport=sport, facts=material)],
        **options)))


def metadata(doc):
    from duo import METAN
    material = doc['news_material']
    said = '\n'.join(s['text'] for s in doc['segments'] if s['speaker'] == METAN and s['kind'] != 'outro')
    sources = '\n'.join(item['source_names'] + '\n' + '\n'.join(item['sources']) for item in material['items'])
    tags = ['MLB', '移籍'] if doc['program'] == shared.MLB_PROGRAM else ['欧州サッカー', 'サッカー']
    description = (said + '\n\n出典:\n' + sources +
                   '\n\n音声: VOICEVOX:ずんだもん・四国めたん\n' + ' '.join('#' + s for s in tags) + ' #Shorts')
    return dict(snippet=dict(title=doc['title'], description=description, tags=tags, categoryId='17',
                             defaultLanguage='ja', defaultAudioLanguage='ja'))
