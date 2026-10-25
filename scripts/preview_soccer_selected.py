"""同じ保存材料・場面・字幕の今／新。音声/API/動画エンコードなし。"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import preview_soccer_readability as old


def saved_cases():
    """保存当時の計画も固定。浅いcheckoutでも履歴取得や通信なしで検査できる。"""
    import soccer_slots_v4 as slots
    import soccer_results_render as result
    cases=old.read('scripts/fixtures/soccer-readable/saved-cases.json')
    for case in cases:
        if case.get('plan'):
            case['plan'].update(data=case['data'],clubs=case['clubs'],narration=case['narration'])
            case['draw']=lambda t,seg,p=case['plan']:slots.frame(t,seg,p)
        else:
            case['draw']=lambda t,seg,d=case['data'],c=case['clubs']:result.frame(t,seg,d,c)
    return cases


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=old.ROOT/'build/soccer-selected-20261025')
    args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.update(COLLESPO_SOCCER_LOOK='v5',COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_BADGE='B',
                      COLLESPO_BUBBLE='slant',COLLESPO_MOTION='on',COLLESPO_DUO='off',COLLESPO_SOLO_HOST='metan')
    import soccer_readable as new
    cases=saved_cases();rows=[];reports=[]
    labels=dict(results='欧州の結果',preview='注目試合の予告',race='順位争い',week='日本人の週末',goal='ゴール速報')
    samples=[]
    for case in cases:
        segs=case['narration']['segments']
        kind='preview' if case['key']=='preview' else 'jp_roster' if case['key']=='week' else None
        seg=next(s for s in segs if kind is None or s['kind']==kind)
        samples.append((case['key'],labels[case['key']],case,seg,3))
        if case['key']=='week':samples.append(('week-page2','日本人の週末 2画面目',case,seg,9))
        if case['key']=='goal':
            detail=next(s for s in segs if s['kind']=='result')
            samples.append(('goals-assists','得点者・時間・アシスト',case,detail,3))
            samples.append(('goals-assists-page2','得点・アシスト 2画面目',case,detail,9))
    for key,label,case,seg,t in samples:
        os.environ['COLLESPO_SOCCER_LOOK']='v5';old.caption(seg)
        before=old.render_current(case,seg)
        os.environ['COLLESPO_SOCCER_LOOK']='v6';old.caption(seg)
        if case.get('plan'):after=__import__('soccer_slots_v4').frame(t,seg,case['plan'])
        else:after=__import__('soccer_results_render').frame(t,seg,case['data'],case['clubs'])
        if not after.info.get('soccer_readable'):raise ValueError('新配置の入口に接続していません: '+key)
        before.save(out/(key+'-current.png'));after.save(out/(key+'-new.png'))
        errors=new.check_frame(after,case['clubs'])
        report=dict(key=key,source=case['source'],revision=case['revision'],segment=seg,
                    page=after.info.get('readable_page',0),errors=errors,
                    entries=after.info['v3_layout'],portraits=after.info.get('duo_layer'),
                    source_material_sha256=hashlib.sha256(json.dumps(case['data'],sort_keys=True).encode()).hexdigest())
        reports.append(report)
        items=[(before,'保存材料・同じ場面・同じ字幕'),(after,'整列一覧／一組の大きなスコア')]
        rows.append((label+'\n'+case['day'],items))
        old.sheet([(label,items)],out/(key+'-comparison.png'),['今','新'],cell=540)
    old.sheet(rows,out/'03-current-new.png',['今','新'],cell=360)
    old.save(out/'measurements.json',dict(version='v6',settings='COLLESPO_SOCCER_LOOK=v6',
        production_switch_changed=False,publication=False,source_note='保存当時の材料。現在の試合情報ではありません。',
        timing='静止再描画。各場面内3秒、週末2画面目は9秒。実音声・実尺未検証。',cases=reports))
    errors=[dict(key=r['key'],errors=r['errors']) for r in reports if r['errors']]
    old.save(out/'validation.json',dict(checked=len(reports),errors=errors))
    print(json.dumps(dict(out=str(out),checked=len(reports),errors=errors),ensure_ascii=False))
    return bool(errors)


if __name__=='__main__':raise SystemExit(main())
