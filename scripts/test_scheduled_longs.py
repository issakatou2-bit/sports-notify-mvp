"""保存済み応答による在庫・市場・週間長編の通し試験。"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import asset_policy
import generated_topics
import market_watch as market
import metan_tone
import phase2_shorts as shorts
import scheduled_longs as long
import season_stock
import season_topics
import short_content
import soccer_national_topics
import topic_dialogue
from test_market_watch import FIXTURES, NOW


CUP_DAY = date(2026, 11, 26)
MARKET_DAY = date(2026, 11, 28)
CUP_MATCHES = Path(__file__).parent / 'fixtures/scheduled_longs_1126.json'


def assert_flow(doc):
    segments = doc['segments']
    assert not topic_dialogue.problems(segments)
    assert not list(metan_tone.check(segments))
    zunda = [s['text'] for s in segments if s['speaker'] == 3]
    assert zunda[0].endswith('！') and not zunda[-1].endswith('？')
    assert not any(topic_dialogue.NUMBER.search(line) for line in zunda)
    assert not any(a.endswith('？') and b.endswith('？') for a, b in zip(zunda, zunda[1:]))



def test_season_stock_from_saved_data():
    saved = long.load(long.ROOT / season_stock.INSIGHT_PATH)['topics']
    assert saved == season_topics.saved_insights()
    assert len(saved) >= 20
    assert len(saved) == len({p['key'] for p in saved})
    for row in saved:
        key = row['key']
        assert generated_topics.get(key) == row
        assert asset_policy.selectable(key, row)
        doc = shorts.season_narration(key)
        assert not shorts.check(doc)
        assert_flow(doc)
        assert doc == shorts.season_narration(key)
        assert len(short_content.information(doc)) >= short_content.MIN_INFORMATION
    dunn = next(row for row in saved if row['key'].endswith('rare_dunn'))
    assert all(s in dunn['insight']['answer'] for s in ('58.4%', '267人', '1位', '56.7%'))


def test_ordinary_game_has_no_insight():
    games = [dict(date=f'2026-04-{i:02d}', stat=dict(hits=1, plateAppearances=4))
             for i in range(1, 25)]
    rows = dict(season='2026', game_type='R', players={'100': dict(jp='選手', hitting=games)})
    assert season_stock.player_insights(rows) == []


def test_large_deal_requires_confirmation_or_matching_amount():
    feeds = [('MLBTR', FIXTURES / 'mlbtr.xml'), ('ESPN', FIXTURES / 'espn_mlb.xml')]
    result = market.run(feeds, {'version': 1, 'stories': {}}, NOW)
    key = 'freddy-peralta-baltimore-orioles-deal'
    entry = result['large_stage2'][key]
    assert entry == long.load(market.LARGE_CONTRACTS)['events'][key]
    reports = [dict(r, kind='合意') for r in entry['reports']]
    assert len(reports) == 2
    assert list(market.confirmed_large(reports[:1])) == []
    assert list(dict(market.confirmed_large(reports))) == [key]
    bad = [r | {'contract': r['contract'] | {'amount': 13000}} for r in reports[1:]]
    assert list(market.confirmed_large(reports[:1] + bad)) == []
    assert list(market.confirmed_large([next(r for r in entry['reports'] if r['kind'] == '正式')]))
    doc = soccer_national_topics.mlb_narration('followup-' + key)
    assert not soccer_national_topics.check(doc) and not list(metan_tone.check(doc['segments']))
    items = doc['followup_material']['items']
    assert '5年総額1億2500万ドル' in items[0]['text']
    assert_flow(doc)
    assert len(items) == 2
    comparison = items[1]['text']
    assert '佐藤輝明は6年総額1億2000万ドル' in comparison
    assert '平良海馬は5年総額8000万ドル' in comparison
    assert '年平均にすると、フレディ・ペラルタは約2500万ドル' in comparison
    assert len(short_content.information(doc)) == 3
    assert market.saved_contract_total('6年 総額1億2000万ドル') == (6, Decimal(12000))
    assert market.annual_average(5, 2) == Decimal(3)
    assert market.annual_average(4.99, 2) == Decimal(2)


def test_long_skips_empty_weeks_and_runs_from_saved_sources():
    for data in (long.cup_material(CUP_DAY, []), long.market_material(MARKET_DAY, {}, {}, {})):
        assert not data['can_make'] and data['reason']
    material = long.cup_material(CUP_DAY, long.load(CUP_MATCHES))
    assert material['can_make'] and len(material['rows']) == 3
    assert not long.cup_material(CUP_DAY + timedelta(days=7), material['rows'])['can_make']
    ledger = {key: dict(video_id=key, privacy='public')
              for key in ('followup-sato-cubs', 'followup-taira-bluejays')}
    data = long.market_material(MARKET_DAY, long.load(market.LARGE_CONTRACTS)['events'], ledger, {})
    assert {r['key'] for r in data['rows']} >= {'followup-sato-cubs', 'followup-taira-bluejays'}
    for pack in (material, data):
        doc = long.dialogue(pack)
        long.validate_document(doc)
        assert_flow(doc)
        assert doc == long.dialogue(pack)
        doc['segments'][0]['text'] += '9試合'
        try:
            long.validate_document(doc)
        except ValueError:
            pass
        else:
            raise AssertionError('材料と違う台本が通りました')


def test_highlight_answer_and_related_list(tmp_path):
    cup = long.cup_material(CUP_DAY, long.load(CUP_MATCHES))
    highlight, = long.highlights(cup)
    doc = long.highlight_narration(cup, highlight['key'], 'longFixture')
    lines = [s['text'] for s in doc['segments']]
    assert lines[-1] == 'ほかは長編で。'
    assert all('長編で' not in line for line in lines[:-1])
    assert any('3本' in line and '7本' in line and '2対1' in line for line in lines[:-1])
    assert not shorts.check(doc)
    assert_flow(doc)
    assert doc == long.highlight_narration(cup, highlight['key'], 'longFixture')
    doc['segments'][1]['text'] = '答えは長編で。'
    assert shorts.check(doc)
    now = datetime(2026, 11, 27, 10, tzinfo=long.JST)
    stamp = '2026-11-26T20:30:00+09:00'
    ledger = {'soccer_goal_short': {'2026-11-26:401915377': {
        'video_id': '_vrMkLaqMws', 'title': '上田綺世がゴール', 'privacy': 'public'}}}
    ledger[long.CUP] = {cup['key']: dict(video_id='longFixture', title='欧州カップ長編', publish_at=stamp)}
    ledger[long.HIGHLIGHT] = {doc['topic_key']: dict(video_id='highlight00', title='誘導ショート')}
    receipts = {long.CUP: {cup['key']: dict(video_id='longFixture', material=cup)}}
    path = long.write_related(tmp_path, ledger, receipts, now)
    assert path.name == 'related_videos_20261127.md'
    summary = path.read_text(encoding='utf-8')
    assert 'highlight00' in summary and '_vrMkLaqMws' in summary and 'longFixture' in summary
    assert not long.related_rows(ledger, receipts, now - timedelta(days=1))
    ledger[long.CUP][cup['key']]['held'] = True
    assert not long.related_rows(ledger, receipts, now)



def test_next_asset_selects_two_distinct_players(tmp_path):
    from contextlib import redirect_stdout
    from io import StringIO
    from types import SimpleNamespace
    from unittest.mock import patch

    import generate_asset_video as gav
    import next_asset
    import player_publications

    stock = {row['key']: row for row in season_topics.saved_insights()}
    ledgers = ({'asset': {}}, {'assets': {}})
    out = StringIO()
    with patch.dict(gav.LIST_TOPICS, stock, clear=True), \
            patch.object(player_publications, 'load', return_value=ledgers), redirect_stdout(out):
        assert next_asset.pick_season(SimpleNamespace(published=str(tmp_path/'assets.json'), season=2)) == 0
    picks = out.getvalue().split()
    assert len(picks) == 2
    assert len({stock[key]['player_id'] for key in picks}) == 2


if __name__ == '__main__':
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('build/test_scheduled_longs')
    root.mkdir(exist_ok=True, parents=True)
    test_season_stock_from_saved_data()
    test_ordinary_game_has_no_insight()
    test_large_deal_requires_confirmation_or_matching_amount()
    test_long_skips_empty_weeks_and_runs_from_saved_sources()
    test_highlight_answer_and_related_list(root)
    test_next_asset_selects_two_distinct_players(root)
    print('6件すべて通過')
