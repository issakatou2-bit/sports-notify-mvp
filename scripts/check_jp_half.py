"""heavy_waitから実行する前半・後半の数字照合、27日模擬、軽い静止画。"""
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT)]
WORK = ROOT/'build/jp_half_check'
OUT = ROOT/'build_reports/jp_half_20261104'


def audit():
    import jp_stock as jp
    raw_path = ROOT.parents[0]/'codex/tmp/jp_logs_raw_20261104/raw.json'
    raw = json.loads(raw_path.read_text(encoding='utf8'))
    saved = jp.stock.read(ROOT/jp.SOURCE_PATH)
    baseline = jp.stock.read(ROOT/'scripts/fixtures/jp_half_legacy_20261104.json')
    audited = []
    for spec in jp.build()['topics']:
        if spec['stock_kind'] != 'half':
            continue
        pid, group = spec['player_ids'][0], spec['comparison_group']
        rows = raw[pid][group+'_gameLog']
        for i, first in enumerate((True, False)):
            selected = [r for r in rows if ('2026-03-01' <= r['date'] <= '2026-06-30' if first else
                                          '2026-07-01' <= r['date'] <= '2026-09-30')]
            total = Counter()
            for r in selected:
                total.update({k: v for k, v in r['stat'].items() if type(v) is int})
                matching = next(x for x in saved['players'][pid][group] if x['game_pk'] == r['game']['gamePk'])
                assert matching['date'] == r['date']
                assert all(value == r['stat'][key] for key, value in matching['stat'].items())
            if group == 'hitting':
                avg = (Decimal(total['hits'])/total['atBats']).quantize(Decimal('.001'), rounding=ROUND_HALF_UP)
                rate = str(avg).removeprefix('0')
                text = f"打率{rate}、{total['homeRuns']}本塁打、{total['rbi']}打点"
            else:
                outs = sum(int(r['stat']['inningsPitched'].split('.')[0])*3+int(r['stat']['inningsPitched'].split('.')[1]) for r in selected)
                era = (Decimal(total['earnedRuns'])*27/outs).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                rate = str(era)
                innings = f'{outs//3}回'+(f'{outs%3}/3' if outs%3 else '')
                text = f"防御率{rate}、{innings}、{total['strikeOuts']}奪三振"
            assert spec['items'][i][1] == text, (spec['key'], text, spec['items'])
            assert rate in spec['title']
        assert set(spec['game_ids']) == {str(r['game']['gamePk']) for r in rows}
        audited.append(dict(key=spec['key'], title=spec['title'], items=spec['items']))
    jp.write(WORK/'numeric_audit.json', dict(halves=audited, legacy_groups={k: len(v) for k, v in baseline.items()},
             raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest()))


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with patch.object(socket.socket, 'connect', side_effect=RuntimeError('通信禁止')):
        import jp_stock as jp
        jp.write(ROOT/'build/jp_stock_topics.json', jp.build())
        import check_jp_split as checks
        checks.WORK, checks.OUT = WORK, OUT
        audit()
        checks.run(kinds={'half'})
        from PIL import Image
        samples = sorted(OUT.glob('season_half_*_1.jpg'))
        if samples:
            contact = Image.new('RGB', (432*min(3, len(samples)), 768*((len(samples)+2)//3)), '#ddd')
            for index, sample in enumerate(samples):
                with Image.open(sample) as im:
                    contact.paste(im, ((index%3)*432, (index//3)*768))
            contact.save(OUT/'contact.jpg', quality=86)


if __name__ == '__main__':
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK/'check.log').open('w', encoding='utf8', buffering=1) as log:
        sys.stdout = sys.stderr = log
        main()
