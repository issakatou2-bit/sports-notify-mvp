"""gitに残る実取得材料へ点数を当てる。架空の日程を補わない。"""
import argparse
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import soccer_selection as selection


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--end',type=date.fromisoformat,required=True);ap.add_argument('--days',type=int,default=30);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();start=args.end-timedelta(days=args.days-1);seen={}
    refs=subprocess.check_output(['git','log','--format=%H','--','data/soccer_games.json'],cwd=selection.ROOT,text=True).splitlines()
    for ref in refs:
        raw=subprocess.check_output(['git','show',ref+':data/soccer_games.json'],cwd=selection.ROOT)
        data=json.loads(raw);at=selection.interest.timestamp(data.get('generated_at'))
        if not at:continue
        day=at.astimezone(selection.JST).date()
        if not start<=day<=args.end:continue
        if day.isoformat() in seen:continue
        # 過去の所属を現在の名簿で補完しない。保存された所属フラグだけを利用。
        for g in data.get('games',[]):g.setdefault('jp_by_side',{'home':[],'away':[]})
        picked=selection.select(data,now=at,availability={})
        game_rows=[dict(id=str(g['game_id']),home=g.get('home_team_name'),away=g.get('away_team_name'),rating=g.get('preview_rating'),selected=g['is_notable']) for g in picked['games']]
        seen[day.isoformat()]=dict(commit=ref,material_sha256=hashlib.sha256(raw).hexdigest(),fixtures=len(data['games']),**picked['preview_selection'],games=game_rows)
    rows=sorted(seen.values(),key=lambda r:r['day']);cfg=selection.policy()
    lines=['# 保存日程による選定数（㉝）','',f'対象: {start}〜{args.end}。保存されている実取得日だけ。開催なしの日と保存なしの日を混ぜない。',
           f"初期値: {cfg['threshold']}点以上、最大{cfg['max_games']}試合。リーグ10点だけ/所属15点だけでは選ばず、ダービー・順位争い・大きなクラブ等の裏づけが加わるカードを選ぶ。CL決勝トーナメントは大会の材料があると45点。",'',
           '上限3はこれまでの尺を保つ編集上の初期値。再生効果を実証した値ではない。本人が下の結果と題材を見て調整する。',
           '現在の名簿や現在のFPL数字を過去の日へ足していない。保存分に当時の選手集計が無ければ期待選手の点は付かない。','',
           '|日付|保存試合数|選んだ数|選んだ試合・点数|見送り/未確認の理由|材料commit|','|---|---:|---:|---|---|---|']
    for r in rows:
        cards=' / '.join(f"{g['home']}対{g['away']} {g['rating']['score']}点" for g in r['games'] if g['selected'])
        lines.append(f"|{r['day']}|{r['fixtures']}|{r['count']}|{cards}|{r['reason']}|{r['commit'][:8]}|")
    lines+=['',f'保存実取得日 {len(rows)}日。選定0件 {sum(r["count"]==0 for r in rows)}日。',
            'EL/国内杯は従来の保存材料に無いため、この表だけで新しい大会の選定数を実測したと扱わない。']
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text('\n'.join(lines)+'\n',encoding='utf8')
    args.out.with_suffix('.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f'days={len(rows)} zero={sum(r["count"]==0 for r in rows)}')
if __name__=='__main__':main()
