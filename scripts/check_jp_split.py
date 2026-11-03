"""保存資料だけで11月末までの実選択と静止画を検査。実績は書かない。"""
from contextlib import redirect_stdout, redirect_stderr, ExitStack
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT)]
os.environ.update(COLLESPO_SHORT_LOOK='v4', COLLESPO_SOLO_HOST='metan',
                  COLLESPO_HOST_SPLIT='', COLLESPO_UI_VOICE_STOCK='',
                  COLLESPO_CAPTION_BREAKS='bunsetsu', COLLESPO_MOTION='on', COLLESPO_HOOK_AB='')
OUT = ROOT/'build_reports/jp_split_20261104'
WORK = ROOT/'build/jp_split_check'


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def run():
    # APIや共有の声へ接続するコードの混入も停止する。
    with patch.object(socket.socket, 'connect', side_effect=RuntimeError('通信禁止')):
        import jp_stock as jp
        import jp_assets
        import next_asset as picker
        import generate_asset_video as g
        import player_publications as pp
        import offseason_market
        import short_content
        import sanity_material
        import review_render_v3 as r3
        import v3_rules
        import name_reading_guard
        import synthesize_narration as synth
        doc = jp.build()
        # workflowと同じ2つの保存済み日本人候補を合流。その他は本番の保存候補を維持。
        topics = dict(g.LIST_TOPICS)
        topics.update({t['key']: t for t in jp_assets.build()['topics']+doc['topics']})
        g.LIST_TOPICS = topics
        initial = copy.deepcopy(pp.load())
        ledgers = copy.deepcopy(initial)
        original_datetime = dt.datetime
        class Frozen(original_datetime):
            at = original_datetime.fromisoformat('2026-11-04T18:30:00+09:00')
            @classmethod
            def now(cls, tz=None):
                return cls.at.astimezone(tz) if tz else cls.at.replace(tzinfo=None)
        ledger = WORK/'simulated_assets.json'
        days, calls = [], []
        previous = set()
        errors = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(pp, 'load', side_effect=lambda **kwargs: ledgers))
            stack.enter_context(patch('ui_voice_stock.prioritize', side_effect=lambda rows: rows))
            for module in (dt, picker, jp, pp, offseason_market):
                stack.enter_context(patch.object(module, 'datetime', Frozen))
            for offset in range(27):
                day = dt.date(2026, 11, 4)+dt.timedelta(days=offset)
                picked = []
                players = set()
                for hour in ('18:30', '22:00'):
                    Frozen.at = original_datetime.fromisoformat(f'{day}T{hour}:00+09:00')
                    write(ledger, ledgers[1])
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        picker.pick_season(SimpleNamespace(published=str(ledger), season=2))
                    keys = stdout.getvalue().split()
                    calls.append(dict(at=Frozen.at.isoformat(), keys=keys, diagnostics=stderr.getvalue()))
                    for key in keys:
                        spec = topics[key]
                        ids = jp_assets.ids(key, spec)
                        if ids & (players | previous):
                            errors.append(dict(day=str(day), key=key, duplicate_players=sorted(ids & (players | previous))))
                        if key in picked:
                            errors.append(dict(day=str(day), duplicate_key=key))
                        players |= ids
                        picked.append(key)
                        row = dict(title=spec['title'], player_ids=sorted(ids), published_at=Frozen.at.isoformat())
                        ledgers[0].setdefault('asset', {})[key] = row
                        ledgers[1].setdefault('assets', {})[key] = row
                assert len(picked) == len({picker.season_kind(k) for k in picked})
                days.append(dict(day=str(day), keys=picked, titles=[topics[k]['title'] for k in picked],
                                 count=len(picked), reason='' if len(picked) == 2 else '保存候補の残数・当日前日の選手回避・同日型制限で2本に不足'))
                previous = players
        write(WORK/'simulation.json', dict(days=days, calls=calls, duplicate_errors=errors,
                                         initial_ledger_counts=[len(initial[0].get('asset', {})), len(initial[1].get('assets', {}))]))
        assert not errors, errors
        checks = []
        for spec in doc['topics']:
            narration = g.build_narration(spec['key'])
            material_errors = sanity_material.check(narration, sanity_material.grounding([narration]))
            name_reading_guard.validate_dialogue(narration)
            units = short_content.information(narration, spec)
            checks.append(dict(key=spec['key'], information=len(units), sanity=material_errors))
            assert len(units) >= 3 and not material_errors, checks[-1]
        write(WORK/'checks.json', checks)
        # 完成MP4とは区別した、制作器の本文・表紙の全場面見本。
        desired = ['season_win_2026_660271_hitting', 'season_win_2026_673548_hitting',
                   'season_home_2026_673540_pitching', 'season_win_2026_808967_pitching']
        desired += [t['key'] for t in doc['topics'] if t['stock_kind'] == 'daynight']
        layouts = []
        for key in desired:
            spec = topics[key]
            narration = g.build_narration(key)
            write(WORK/key/'narration.json', narration)
            write(WORK/key/'material.json', spec)
            for index, seg in enumerate(narration['segments']):
                seg['speaker'] = 2
                r3.set_program_clock(index*8)
                r3.set_caption(seg['text'] if seg['kind'] != 'outro' else '', 8, 40, speaker=2)
                im = g.render_v3(3, seg['kind'], seg['meta'], spec, key, seg, 8)
                errs = v3_rules.check_layout(im)
                layouts.append(dict(key=key, segment=index, errors=errs))
                im.thumbnail((432, 768))
                im.convert('RGB').save(OUT/f'{key}_{index}.jpg', quality=82)
        write(WORK/'layout.json', layouts)
        assert not any(x['errors'] for x in layouts), layouts
        print('在庫', len(doc['topics']), '選出', sum(x['count'] for x in days), '不足日', sum(x['count'] != 2 for x in days))


if __name__ == '__main__':
    run()
