"""保存した公式応答を通信なしで再生。stars未提供時は日本人だけの下限を測る。"""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import offseason_news as n


def replay(folder):
    jp, table = n.names()
    result = {'note': '大型の判定に必要な当季成績と前年賞は未提供。stars空の日本人のみが確定下限。動画尺の合格本数とは別。', 'transactions': {}, 'awards': {}}
    for file, start, end in [('transactions_2025off.json', date(2025,10,29), date(2025,12,31)),
                              ('transactions_20261025_30.json', date(2026,10,25), date(2026,10,30))]:
        payload = json.loads((folder/file).read_text(encoding='utf-8'))
        rows = n.transaction_rows(payload, start, end, jp, table, set())
        seen, batches = set(), []
        day = start
        while day <= end:
            current = n.transaction_rows(payload, day-timedelta(days=6), day, jp, table, set())
            spec = n.topic('transactions', [r for r in current if r['event_id'] not in seen], day, day.year)
            if spec and len(spec['items']) >= 3:
                batches.append({'day':str(day),'events':[r['event_id'] for r in spec['offseason']['events']]})
                seen.update(batches[-1]['events'])
            day += timedelta(days=1)
        result['transactions'][file] = {'input_count':len(payload['transactions']),
            'types':dict(Counter(r['typeCode'] for r in payload['transactions'])),
            'japanese_material_count':len(rows), 'japanese_materials':[{'date':r['raw']['date'],'body':r['body'],'id':r['raw']['id']} for r in rows],
            'seven_day_batches_at_least_three':batches, 'batch_count':len(batches)}
    for file in sorted(folder.glob('aw_*.json')):
        ident = file.stem[3:]
        payload = json.loads(file.read_text(encoding='utf-8'))
        missing = [r['player']['nameFirstLast'] for r in payload['awards'] if not table.get(r['player']['nameFirstLast'])]
        rows = n.award_rows({ident:payload},2025,jp,table)
        topics = n.award_topics(rows,date(2025,11,6),2025)
        result['awards'][ident] = {'input_count':len(payload['awards']), 'registered_rows':len(rows),
            'missing_names':missing,'production_batches':[len(t['items']) for t in topics]}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(replay(args.input),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
