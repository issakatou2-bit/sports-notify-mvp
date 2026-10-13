"""公開台帳14日分の題を、現行series/press_namesの順で比較する。設定変更なし。"""
import argparse
from datetime import date,timedelta
import hashlib,json,re,sys,unicodedata
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import series,press_names

def identity_title(title,roster):
    # 保存済み題はpress_names適用後。名字から主役候補を復元するのはこの見本だけ。
    out=title
    for full,surname in sorted(press_names.SURNAME.items(),key=lambda kv:-len(kv[1])):
        if full not in roster or full in out:continue
        out=re.sub(re.escape(surname)+r'(?![一-龥ぁ-んァ-ヶ])',full,out)
        # 球団名に直結する新聞の書き方は別に拾う。
        teams='|'.join(map(re.escape,press_names._teams()))
        out=re.sub('('+teams+')'+re.escape(surname),r'\1'+full,out)
        out=re.sub(re.escape(surname)+'(?='+teams+')',full,out)
    return out

def compare(title,kind,roster):
    names=series.main_players(identity_title(title,roster),kind,roster)
    draft=press_names.press_title(series.series_title(title,names,kind)) if names and kind not in series.EVERGREEN_KINDS else title
    # 題が名字だけの場合、series側の名前除去にも復元した文を使う。
    if names and kind not in series.EVERGREEN_KINDS and draft!=title:
        draft=press_names.press_title(series.series_title(identity_title(title,roster),names,kind))
    width=sum(2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in draft)
    reason='主役なし/対象外' if not names else '紹介回は現行維持' if kind in series.EVERGREEN_KINDS else 'シリーズ案'
    return dict(current=title,proposal=draft,names=names,reason=reason,characters=len(draft),api_limit=len(draft)<=100,
                display_width=width,preview=draft[:36]+('…' if len(draft)>36 else ''),
                press='既存press_namesの球団表現を適用。シリーズの人名はフルネーム。')

def rows(videos,end,days=14):
    roster=series.load_roster();start=end-timedelta(days=days-1);out=[]
    for kind,entries in videos.items():
        if not isinstance(entries,dict):continue
        for day,entry in entries.items():
            try:at=date.fromisoformat(day)
            except ValueError:continue
            if start<=at<=end and isinstance(entry,dict) and entry.get('video_id') and entry.get('title'):
                out.append(dict(day=day,kind=kind,video_id=entry['video_id'],**compare(entry['title'],kind,roster)))
    return sorted(out,key=lambda r:(r['day'],r['kind'],r['video_id']))

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--end',type=date.fromisoformat,required=True)
    ap.add_argument('--videos',type=Path,default=Path('data/published_videos.json'));ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();raw=args.videos.read_bytes();out=rows(json.loads(raw),args.end)
    esc=lambda s:str(s).replace('|',r'\|').replace('\n',' ')
    lines=['# シリーズ題の見本（㉝）','',f"期間: {args.end-timedelta(days=13)}〜{args.end}。公開台帳保存分{len(out)}件。未記録の回は補わない。",'',
           f"出典: `{args.videos}`（SHA256 {hashlib.sha256(raw).hexdigest()}）。手元のmainから取得。本番の変数/投稿文は変更しない。",'',
           '現行のseries→press_namesの順を再現。保存題が名字になっている場合、この見本内だけ対応表から人名を復元して判定。',
           '予告/報道/ランキングはシリーズ対象外、人物紹介は「今日」を付けない。人名が特定できない回も現行のまま。',
           'シリーズの人名は現行仕様のフルネーム。「村上ホワイトソックス」等の新聞の球団表現は本文へ適用する。人名を名字へ統一するかは本人判断。','',
           '100文字以内はAPI上限の検査。ショート棚での省略は端末/書体/場所で違うため保証しない。先頭36文字を併記して、内容の見える位置を比べる。','',
           '|日付・枠|今の題|SERIES_TITLE=1の案|文字数/100|先頭36文字の見え方|扱い|','|---|---|---|---:|---|---|']
    lines += ['|'+'|'.join(map(esc,[r['day']+' '+r['kind'],r['current'],r['proposal'],str(r['characters'])+(' OK' if r['api_limit'] else ' 超過'),r['preview'],r['reason']]))+'|' for r in out]
    lines += ['',f"変更する案: {sum(r['current']!=r['proposal'] for r in out)}件。API100文字超過: {sum(not r['api_limit'] for r in out)}件。",'',
              '残り: 本人が題の自然さと実際のスマホ表示を見て採否を決定。保存台帳からの検査のみ。CI/公開画面は未確認。']
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text('\n'.join(lines)+'\n',encoding='utf8')
    args.out.with_suffix('.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f'rows={len(out)} changed={sum(r["current"]!=r["proposal"] for r in out)}')
if __name__=='__main__':main()
