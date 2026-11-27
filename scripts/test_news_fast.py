
"""保存済みの実報道と、時刻・取引・公開を固定したニュース経路の検査。"""
from datetime import datetime, timedelta
from pathlib import Path
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import mlb_news_fast as mlb
import news_fast_topic as topic
import news_fast_watch as watch
import soccer_national_topics as shared
import soccer_news_fast as soccer
import topic_dialogue

NOW = datetime.fromisoformat('2026-11-25T15:05:00+09:00')
FIXTURES = Path(__file__).parent / 'fixtures/marketwatch_1125'
FEEDS = [('MLBTR', FIXTURES / 'mlbtr.xml'), ('ESPN', FIXTURES / 'espn_mlb.xml')]


def no_transactions(*_):
    return {'transactions': []}


@pytest.fixture(scope='module')
def replay():
    rows, failures, success = watch.mlb_candidates(FEEDS, dict(first_seen={}), NOW, no_transactions)
    assert not failures and success == 3
    return {row['key'].split('-')[2]: row for row in rows}


def test_saved_reporting_counts_its_original_sources(replay):
    sato, taira = replay['teruaki'], replay['kaima']
    assert {r['origin'] for r in sato['detail']['reports']} == {'ESPN'}
    assert sato['material'] is None
    assert '独立した2報道' in sato['reason']
    assert {r['origin'] for r in taira['detail']['reports']} == {'ESPN', 'New York Post'}
    assert taira['material']['hook']['big'] == '8000'
    assert '3年目の後' in taira['material']['items'][0]['text']
    assert '正式発表はまだ' in taira['material']['items'][0]['text']
    assert taira['material']['items'][-1]['source_names'] == 'NPB公式'


def test_same_reporter_syndicated_under_two_outlets_does_not_count(replay):
    a, b = replay['kaima']['detail']['reports']
    assert not mlb.distinct_origins([a, dict(b, reporter=a['reporter'])])


@pytest.mark.parametrize('update', [
    dict(team_en='Chicago Cubs'),
    dict(terms=dict(years=4, amount=8000.0)),
    dict(terms=dict(years=5, amount=7500.0)),
])
def test_mismatched_destination_years_or_total_is_held(replay, update):
    a, b = replay['kaima']['detail']['reports']
    assert mlb.decide([a, dict(b, **update)], None) == (None, '球団・年数・総額が食い違う')


def test_two_outlets_without_three_matching_fields_are_held(replay):
    a, b = replay['kaima']['detail']['reports']
    assert mlb.decide([a, dict(b, terms=None)], None)[0] is None
    assert mlb.decide([a, dict(b, team_en='')], None)[0] is None


def test_official_signing_does_not_require_two_reports():
    record = dict(id=32, date='2026-11-25', typeCode='SFA', toTeam={'id': 112},
                  person={'id': 10, 'fullName': 'Teruaki Sato'},
                  description='Chicago Cubs signed free agent 3B Teruaki Sato.')
    def get(route, params):
        return {'transactions': [record]} if route == '/transactions' else {}
    rows, failures, _ = watch.mlb_candidates([], dict(first_seen={}), NOW, get)
    assert not failures
    result, = rows
    doc = topic.narration('mlb', result['key'], result['material'])
    assert result['key'].endswith('-official')
    assert 'MLBの取引記録' in doc['segments'][1]['text']
    assert '総額' not in doc['segments'][1]['text']
    assert not shared.check(doc)
    assert list(mlb.official_records([dict(record, typeCode='ASG')], mlb.API, {}, set())) == []
    assert list(mlb.official_records([dict(record, description=record['description']+' To a minor league contract.')],
                                     mlb.API, {}, set())) == []


def test_missing_pronunciation_stays_as_issue():
    with patch.object(mlb, 'player_reading', return_value=''):
        rows, _, _ = watch.mlb_candidates(FEEDS, dict(first_seen={}), NOW, no_transactions)
    taira = next(r for r in rows if 'kaima' in r['key'])
    assert taira['material'] is None
    notices, queue = watch.delivery('mlb', [taira], dict(noticed={}), {}, {}, NOW, 'true')
    assert notices[0]['title'].startswith('確認待ち')
    assert '読み' in notices[0]['reason']
    assert queue == []


def test_repeated_observation_waits_until_second_source_and_keeps_first_seen():
    state = dict(first_seen={})
    first, _, _ = watch.mlb_candidates(FEEDS[:1], state, NOW, no_transactions)
    assert all(not row['material'] for row in first)
    second, _, _ = watch.mlb_candidates(FEEDS[1:], state, NOW+timedelta(minutes=15), no_transactions)
    taira = next(r for r in second if 'kaima' in r['key'])
    assert taira['material']['news']['first_seen'] == NOW.isoformat()


def test_limit_is_three_reservations_in_japan_including_legacy(replay):
    material = replay['kaima']['material']
    day = datetime.fromisoformat('2026-11-24T15:01:00+00:00')
    ledger = {str(i): {'publish_at': day.isoformat()} for i in range(2)}
    assert not mlb.publication_block(material, 'topic', ledger, NOW)
    ledger['3'] = {'publish_at': day.isoformat()}
    assert '1日3本' in mlb.publication_block(material, 'topic', ledger, NOW)
    assert not mlb.publication_block(material, 'topic', ledger, NOW+timedelta(days=1))


def test_second_short_only_for_a_later_official_entry(replay):
    material = replay['kaima']['material']
    key = replay['kaima']['key']
    row = dict(news_player='平良海馬', news_first_seen=NOW.isoformat(), news_official=False,
               publish_at=(NOW + timedelta(minutes=21)).isoformat())
    ledger = {key: row}
    assert mlb.publication_block(material, key, ledger, NOW)
    assert mlb.publication_block(material, 'another-report', ledger, NOW)
    info = dict(material['news'], official=True, official_day='2026-11-26',
                official_first_seen=(NOW + timedelta(days=1)).isoformat())
    official = dict(material, news=info)
    assert not mlb.publication_block(official, 'official', ledger, NOW+timedelta(days=1))
    assert mlb.publication_block(dict(official, news=dict(info, official_day='2026-11-23')),
                                 'official', ledger, NOW)
    ledger['official'] = dict(row, news_official=True)
    assert mlb.publication_block(official, 'official-2', ledger, NOW+timedelta(days=1))


@pytest.mark.parametrize('flag', ['', 'false', 'TRUE'])
def test_preview_is_the_default_even_if_legacy_flag_is_true(replay, flag):
    row = replay['kaima']
    state = dict(noticed={})
    _, queue = watch.delivery('mlb', [row], state, {}, {}, NOW, flag)
    assert len(queue) == 1 and queue[0]['publish'] is False
    assert watch.delivery('mlb', [row], state, {row['key']: 'preview'}, {}, NOW, flag) == ([], [])
    doc = topic.narration('mlb', row['key'], row['material'])
    with patch.object(shared.national, 'read', side_effect=[doc, row['material']]), patch.dict(
            os.environ, COLLESPO_MARKET_AUTO_PUBLISH=flag, COLLESPO_MLB_MARKET_TOPIC_PUBLISH='true'):
        with pytest.raises(ValueError, match='指定変数'):
            shared.validate_upload(SimpleNamespace(kind=shared.MLB_PROGRAM, sport='mlb', narration='n', games='g'))


def test_time_summary_counts_at_most_sixty_minutes():
    ledger = {str(i): dict(news_first_seen=NOW.isoformat(), publish_at=(NOW+timedelta(minutes=i)).isoformat())
              for i in (21, 60, 61)}
    ledger['manual'] = {'publish_at': NOW.isoformat()}
    assert mlb.latency(ledger) == dict(reserved=3, within_one_hour=2, fraction=2/3)


def espn(headline, description, *, id=41, team='Brighton & Hove Albion'):
    return dict(id=id, headline=headline, description=description, published='2026-11-26T15:00:00Z',
                links={'web': {'href': f'https://www.espn.com/soccer/story/_/id/{id}/news'}},
                categories=[dict(type='team', teamId=331, team=dict(description=team))])


def test_soccer_detects_a_player_manager_and_large_transfer_and_skips_speculation():
    now = datetime.fromisoformat('2026-11-27T09:00:00+09:00')
    names = soccer.names(watch.load_data)
    record = soccer.article_record(espn('Kaoru Mitoma ruled out', 'Kaoru Mitoma has a hamstring injury.'),
                                   'eng.1', names, now)
    assert record['kind'] == 'けが' and record['player_en'] == 'Kaoru Mitoma'
    transfer = soccer.article_record(espn('Brighton sign player in £52m transfer', 'Club announcement.'),
                                     'eng.1', names, now)
    assert transfer['kind'] == '大型移籍'
    assert soccer.article_record(espn('Brighton could sack manager', ''), 'eng.1', names, now) is None
    record = soccer.article_record(espn('Brighton appoint new manager', 'The club confirmed the appointment.'),
                                   'eng.1', names, now)
    assert record['kind'] == '監督就任' and record['confirmed']
    ctx = soccer.context(record, watch.load_data)
    assert ctx['position'] == 2 and ctx['points'] == 22
    material = soccer.material(record, ctx)
    assert not watch.may_publish('soccer', material, 'false')
    assert watch.may_publish('soccer', material, 'true')
    doc = topic.narration('soccer', record['key'], material)
    assert '勝点22' in doc['segments'][3]['text'] and not shared.check(doc)
    with patch.object(shared.national, 'read', side_effect=[doc, material]), patch.dict(
            os.environ, COLLESPO_SOCCER_NEWS_PUBLISH='', COLLESPO_NATIONAL_TOPIC_PUBLISH='true'):
        with pytest.raises(ValueError, match='指定変数'):
            shared.validate_upload(SimpleNamespace(kind=shared.PROGRAM, sport='soccer', narration='n', games='g'))


def test_closing_uses_the_event_and_a_number_on_the_screen(replay):
    cases = [row for row in replay.values() if row['material']]
    assert cases
    for row in cases:
        doc = topic.narration('mlb', row['key'], row['material'])
        zunda, metan = [s['text'] for s in doc['segments'][-3:-1]]
        assert zunda.endswith('！') and not any(ch.isdigit() for ch in zunda)
        assert any(ch.isdigit() for ch in metan)
        assert topic_dialogue.problems(doc['segments']) == []
    record = dict(id=32, date='2026-11-25', typeCode='SFA', toTeam={'id': 112},
                  person={'id': 10, 'fullName': 'Teruaki Sato'},
                  description='Chicago Cubs signed free agent 3B Teruaki Sato.')
    def get(route, params):
        return {'transactions': [record]} if route == '/transactions' else {}
    rows, _, _ = watch.mlb_candidates([], dict(first_seen={}), NOW, get)
    doc = topic.narration('mlb', rows[0]['key'], rows[0]['material'])
    zunda, metan = [s['text'] for s in doc['segments'][-3:-1]]
    assert zunda.endswith('！') and not any(ch.isdigit() for ch in zunda)
    assert any(ch.isdigit() for ch in metan)
    assert topic_dialogue.problems(doc['segments']) == []
    now = datetime.fromisoformat('2026-11-27T09:00:00+09:00')
    names = soccer.names(watch.load_data)
    record = soccer.article_record(espn('Brighton appoint new manager', 'The club confirmed the appointment.'),
                                   'eng.1', names, now)
    material = soccer.material(record, soccer.context(record, watch.load_data))
    doc = topic.narration('soccer', record['key'], material)
    zunda, metan = [s['text'] for s in doc['segments'][-3:-1]]
    assert '監督を代えて立て直し' in zunda and not any(ch.isdigit() for ch in zunda)
    assert any(ch.isdigit() for ch in metan)
    assert topic_dialogue.problems(doc['segments']) == []


def test_january_transfer_window_tag_is_based_on_the_news_date():
    row = espn('Brighton sign player in £52m transfer', '')
    row['published'] = '2027-01-01T00:01:00Z'
    assert soccer.article_record(row, 'eng.1', {}, soccer.instant('2027-01-01T00:10:00Z'))['january']
