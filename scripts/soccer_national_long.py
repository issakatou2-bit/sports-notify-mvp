"""試合前の招集28人と今季の数字。取得・見本だけ。公開機能は持たない。"""
import argparse
import copy
from datetime import datetime, timedelta
import os
from pathlib import Path

import soccer_national as n
import soccer_national_numbers as numbers

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'data/soccer_national_fixtures.json'
POSITIONS=('GK','DF','MF/FW')


def material(key,as_of,sheet):
    roster=n.read(ROOT/'data/soccer_national_squad.json')
    n.squad_source(roster)
    # 同じ公式名簿・確定した読み・重複検査を短編と共用する。
    validated=n.squad(roster,{},as_of,0)
    if not validated:raise ValueError('対象期間の招集名簿がありません')
    numbers.validate(sheet,roster,as_of)
    fixtures=n.read(FIXTURES)
    if fixtures['source_url']!=roster['source_url']:raise ValueError('試合日時のJFA出典が違います')
    game=next((g for g in fixtures['matches'] if g['key']==key),None)
    if not game:raise ValueError('確認済みの相手を指定してください')
    kickoff=n.instant(game['kickoff_jst'])
    if n.instant(as_of)>=kickoff:raise ValueError('試合前の長編だけを作ります')
    planned=(kickoff-timedelta(days=1)).replace(hour=20,minute=0,second=0,microsecond=0)
    people=[n.squad_player(p) for p in roster['players']]
    lookup={p['name']:p for p in sheet['players']}
    for p in people:p['season_numbers']=copy.deepcopy(lookup.get(p['name']))
    history=n.read(ROOT/'data/soccer_national_results.json')
    previous=copy.deepcopy(history.get('previous_meetings',{}).get(game['opponent'],[]))
    return dict(version=1,as_of=as_of,key=key,game=copy.deepcopy(game),source_url=fixtures['source_url'],
        season=roster['season'],players=people,numbers=copy.deepcopy(sheet),history=previous,
        history_sources=history['sources'],planned_publish_at=planned.isoformat(),publication_enabled=False)


def title(data):
    return data['game']['opponent']+'戦へ 招集'+str(len(data['players']))+'人を今季の数字で'


def highlighted(data):
    players=[p for p in data['players'] if numbers.metric(p)]
    return sorted(players,key=lambda p:(not numbers.rank(p)[0],-numbers.rank(p)[1],p['name']))[:3]


def history_line(row):
    day=datetime.fromisoformat(row['date'])
    result='勝利' if row['gf']>row['ga'] else '敗戦' if row['gf']<row['ga'] else '引き分け'
    return f"{day.year}年{day.month}月{day.day}日 {row['competition']} / 日本 {row['gf']}対{row['ga']} / {result}"


def dialogue(data):
    panels={};segments=[]
    chapters=[dict(id='positions',title='ポジション別の今季成績'),dict(id='focus',title='数字で注目する選手'),
              dict(id='history',title='過去の対戦'),dict(id='kickoff',title='試合日時')]
    fixture=data['numbers'].get('fixture',False)
    def card(key,heading,rows,chapter,atomic=()):
        if fixture:heading='【検証用・数値は架空】 '+heading
        panels[key]=dict(type='soccer_weekly',heading=heading,rows=rows,atomic=list(atomic))
        return key,chapter
    def say(speaker,text,ref):
        segments.append(dict(kind='talk',speaker=speaker,text=text,panel=ref[0],chapter=ref[1],
            meta=dict(who='めたん' if speaker==2 else 'ずんだもん')))
    count=len(data['players']);known=len(data['numbers']['players'])
    day=n.instant(data['as_of']).astimezone(n.JST)
    opening=card('opening',title(data),[f'招集{count}人 / 数値確認 {known}人','所属リーグごとの今季成績',
        f'取得日 {day.year}/{day.month}/{day.day}','未取得の数値は「未確認」。ゼロとして数えません。'],'positions')
    leaders=highlighted(data)
    if leaders:
        first=leaders[0];metric=numbers.metric(first)
        say(3,f"{first['name']}、今季{metric[1]}{metric[2]}なのだ。",opening)
    else:say(3,f"{data['game']['opponent']}戦へ、招集{count}人を見るのだ。",opening)
    say(2,f"{data['game']['opponent']}戦へ向けた招集{count}人です。ポジションごとの今季成績、注目の選手、過去の対戦、試合日時の順に見ていきます。",opening)
    say(3,'数字はカップ戦も合わせた合計なのだ？',opening)
    say(2,f"ここで使うのは所属リーグの今季集計だけです。取得日は{day.month}月{day.day}日。確認できたのは{known}人で、未確認はゼロとして数えません。",opening)
    for position in POSITIONS:
        group=[p for p in data['players'] if p['position']==position]
        for offset in range(0,len(group),3):
            people=group[offset:offset+3]
            rows=[p['name']+' / '+p['club']+'\n'+(numbers.stat_line(p) or '今季の数値は未確認') for p in people]
            ref=card(f'position_{position.replace("/", "_")}_{offset}',f'{position} / {offset+1}〜{offset+len(people)}人目',rows,'positions',
                     [v for p in people for v in (p['name'],p['club'])])
            if offset==0:
                say(3,f'{position}は{len(group)}人なのだ。',ref)
                if position=='GK':say(2,'ゴールキーパーはリーグ戦の出場数を見ます。ここから先の札は、発表されたポジションと名簿の順です。',ref)
                elif position=='DF':say(2,'続いてディフェンダーです。所属の異なる選手も、確認できたリーグ戦の出場と得点を並べます。',ref)
                else:say(2,'発表ではミッドフィルダーとフォワードが一つの区分です。役割をこちらで分けず、この区分のまま紹介します。',ref)
            for index,p in enumerate(people):
                line=numbers.stat_line(p)
                text=p['name']+'は'+(line+'です。' if line else p['club']+'からです。')
                if p.get('first_call'):text+='初めての招集です。'
                say(2 if index%2==0 else 3,text.replace('です。','なのだ。') if index%2 else text,ref)
    focus=card('focus_intro','数字で注目する選手',[p['name']+' / '+numbers.stat_line(p) for p in leaders] or ['数値を確認できた選手はいません。'],'focus')
    say(3,'ここからは数字を確認できた選手に注目するのだ。',focus)
    say(2,'得点が記録された選手を先に、その次に出場数を見ます。異なるリーグの数字なので、単純な実力の順位にはしません。',focus)
    for i,p in enumerate(leaders):
        row=p['season_numbers']
        ref=card('focus_'+str(i),p['name'],[p['club'],row['season']+' / '+row['league_label'],numbers.stat_line(p),
            '取得日 '+day.strftime('%Y/%m/%d')],'focus',[p['name'],p['club']])
        say(3,p['name']+'に注目なのだ。',ref)
        say(2,p['club']+'所属。'+numbers.stat_line(p)+'です。'+('ゴールキーパーなので、ここでは出場数だけを使っています。' if p['position']=='GK' else 'リーグ戦だけを切り出した数字です。'),ref)
    if len(leaders)<3:say(2,'数値を確認できた選手が3人に満たないため、残りを推測で補うことはしません。',focus)
    ref=card('history',data['game']['opponent']+'との過去の対戦',[history_line(r) for r in data['history']] or ['確認できる対戦結果はありません。'],'history')
    say(3,data['game']['opponent']+'とは、これまでどうだったのだ？',ref)
    say(2,'確認できる過去の対戦を振り返ります。',ref)
    for row in data['history']:say(2,history_line(row).replace(' / ','、')+'でした。',ref)
    if not data['history']:say(2,'過去の対戦結果を確認できないため、数字は出しません。',ref)
    game=data['game'];kick=n.instant(game['kickoff_jst']).astimezone(n.JST)
    when=f'{kick.month}月{kick.day}日 {kick.hour}時{kick.minute:02d}分（日本時間）'
    ref=card('kickoff','日本 対 '+game['opponent'],[when,'会場 '+game['venue'],'招集名簿・試合日時：JFA発表'],'kickoff')
    say(3,'最後に試合の日時なのだ。',ref)
    say(2,f"日本対{game['opponent']}は、{kick.month}月{kick.day}日、日本時間の{kick.hour}時{kick.minute}分開始です。会場は{game['venue']}です。",ref)
    say(2,'今季の数字と所属を見たうえで、代表でどんな組み合わせになるか。試合を楽しみに待ちましょう。',ref)
    return dict(program='soccer_national_long',kind='soccer_national_long',label=game['key'],title=title(data),top=title(data),
        panels=panels,chapters=chapters,segments=segments,national_long_material=copy.deepcopy(data))


def validate_document(doc):
    data=doc['national_long_material']
    rebuilt=material(data['key'],data['as_of'],data['numbers'])
    if data!=rebuilt:raise ValueError('長編の材料が公式名簿・数字・保存済みの対戦結果と一致しません')
    expected=dialogue(rebuilt)
    for key in ('program','kind','label','title','top','panels','chapters','segments'):
        if doc.get(key)!=expected[key]:raise ValueError('長編の確定台本と不一致: '+key)


def speech_readings(doc):
    validate_document(doc)
    clubs=n.read(ROOT/'data/soccer_national_club_readings.json')
    readings={p['name']:('player',p['reading']) for p in doc['national_long_material']['players']}
    readings.update({p['club']:('club',clubs[p['club']]) for p in doc['national_long_material']['players']})
    return readings


def metadata(doc):
    validate_document(doc);data=doc['national_long_material']
    lines=[title(data),'今季のリーグ戦のみ。取得日 '+data['as_of'],
        '未確認の数字はゼロとして扱いません。図は発表されたポジションの名簿順で、先発やフォーメーションの予想ではありません。',
        'MF/FWはJFAの一括発表です。過去の対戦は保存済みの結果のみです。',data['source_url']]
    lines += [p['source'] for p in data['numbers']['players']]+data['history_sources']
    return dict(snippet=dict(title=title(data),description='\n'.join(dict.fromkeys(lines))+'\n音声：VOICEVOX 四国めたん / ずんだもん',categoryId='17'),
        planned_publish_at=data['planned_publish_at'],publication_enabled=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--opponent',required=True,choices=('brazil','paraguay'))
    ap.add_argument('--as-of',default=None)
    ap.add_argument('--fixture',type=Path)
    ap.add_argument('--out',type=Path,default=ROOT/'build/national_long')
    args=ap.parse_args();as_of=args.as_of or datetime.now(n.JST).isoformat()
    roster=n.read(ROOT/'data/soccer_national_squad.json')
    fetcher=None
    if args.fixture:
        if os.environ.get('COLLESPO_SAMPLE_ONLY')!='true':raise ValueError('fixtureはsample_onlyだけで使用します')
        responses=n.read(args.fixture)['responses']
        def fixture_fetch(url):
            if url not in responses:raise OSError('fixtureにない取得は行いません')
            return copy.deepcopy(responses[url])
        fetcher=fixture_fetch
    sheet=numbers.collect(roster,as_of,args.out/'raw',fetch=fetcher,fixture=bool(args.fixture))
    data=material(args.opponent,as_of,sheet);doc=dialogue(data);validate_document(doc)
    import name_reading_guard
    name_reading_guard.validate_dialogue(doc)
    for filename,value in (('numbers.json',sheet),('material.json',data),('dialogue.json',doc),('metadata.json',metadata(doc))):n.save(args.out/filename,value)
    print(title(data)+' / 予定 '+data['planned_publish_at']+' / 公開機能なし')


if __name__=='__main__':main()
