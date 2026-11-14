"""試合前の招集28人と今季の数字。見本の経路は公開しない。公開の経路は --publish と upload_youtube の kind soccer_national_long だけ。"""
import argparse
import copy
from datetime import datetime, timedelta, time as dtime
import json
import os
from pathlib import Path

import soccer_national as n
import soccer_national_numbers as numbers

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'data/soccer_national_fixtures.json'
POSITIONS=('GK','DF','MF/FW')
PUBLISHED=ROOT/'data/published_videos.json'
RECORD_KIND='soccer_national_long'
TITLE_MAX=50


def previous_match(history,roster,game,as_of):
    """同じ招集期間（発表日〜この試合の前日）で、この試合より前に終わった代表戦のうち最新の1つ。無ければ None。"""
    start=n.instant(roster['announced_at']).astimezone(n.JST).date().isoformat()
    kick=n.instant(game['kickoff_jst']).astimezone(n.JST).date().isoformat()
    until=min(kick,(n.instant(as_of).astimezone(n.JST).date()+timedelta(days=1)).isoformat())
    rows=[r for r in history.get('matches',[]) if start<=r['date']<until]
    if not rows:return None
    r=max(rows,key=lambda r:r['date'])
    if type(r['gf']) is not int or type(r['ga']) is not int or min(r['gf'],r['ga'])<0:raise ValueError('前の試合の得失点が不正です')
    row=dict(date=r['date'],competition=r['competition'],opponent=r['opponent'],gf=r['gf'],ga=r['ga'])
    if r.get('scorers'):
        if not all(isinstance(x,str) and x for x in r['scorers']):raise ValueError('前の試合の得点者が不正です')
        row['scorers']=list(r['scorers'])
    return row


def material(key,as_of,sheet,publish=False):
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
    # 発表後の離脱（JFAの別の発表）は、その試合の回から外し、外したことを台本で言う（11/14 鎌田大地）。
    gone=withdrawals(roster,key)
    people=[n.squad_player(p) for p in roster['players'] if p['name_en'] not in gone]
    left=[dict(name=n.squad_player(p)['name'],**{k:gone[p['name_en']][k] for k in ('reason','announced_on','source_url')})
        for p in roster['players'] if p['name_en'] in gone]
    lookup={p['name']:p for p in sheet['players']}
    for p in people:p['season_numbers']=copy.deepcopy(lookup.get(p['name']))
    history=n.read(ROOT/'data/soccer_national_results.json')
    previous=copy.deepcopy(history.get('previous_meetings',{}).get(game['opponent'],[]))
    last=previous_match(history,roster,game,as_of)
    return dict(version=1,as_of=as_of,key=key,game=copy.deepcopy(game),source_url=fixtures['source_url'],
        season=roster['season'],players=people,numbers=kept_numbers(sheet,people),history=previous,
        history_sources=history['sources'],previous_match=last,withdrawn=left,called=len(roster['players']),planned_publish_at=planned.isoformat(),publication_enabled=bool(publish))


def withdrawals(roster,key):
    """{英語名: 離脱の記録}。JFAの発表・理由・日付が揃った物だけ。名簿にいない名前は止める。"""
    names={p['name_en'] for p in roster['players']};out={}
    for w in roster.get('withdrawals') or []:
        if w.get('match_key')!=key:continue
        if w.get('name_en') not in names:raise ValueError('離脱の選手が招集名簿にいません: '+str(w.get('name_en')))
        if not (w.get('reason') and w.get('announced_on') and str(w.get('source_url','')).startswith('https://www.jfa.jp/')):
            raise ValueError('離脱の発表（理由・日付・JFAの出典）が足りません')
        out[w['name_en']]=w
    return out


def kept_numbers(sheet,people):
    """離脱した選手の数字は、その回の集計・出典に入れない。"""
    out=copy.deepcopy(sheet);names={p['name'] for p in people}
    out['players']=[p for p in out['players'] if p['name'] in names]
    return out


def squad_words(data):
    """「招集28人」か、離脱があれば「離脱を除く27人」。"""
    if data.get('withdrawn'):return f"離脱を除く{len(data['players'])}人"
    return f"招集{len(data['players'])}人"


def title(data):
    last=data.get('previous_match')
    if last:
        text=last['opponent']+'戦の結果と '+data['game']['opponent']+'戦へ '+('代表' if data.get('withdrawn') else '招集')+str(len(data['players']))+'人の今季'
        if len(text)<=TITLE_MAX:return text
    return data['game']['opponent']+'戦へ '+('代表' if data.get('withdrawn') else '招集')+str(len(data['players']))+'人を今季の数字で'


def result_word(row):
    return '勝利' if row['gf']>row['ga'] else '敗戦' if row['gf']<row['ga'] else '引き分け'


def highlighted(data):
    players=[p for p in data['players'] if numbers.metric(p)]
    return sorted(players,key=lambda p:(not numbers.rank(p)[0],-numbers.rank(p)[1],p['name']))[:3]


def history_line(row):
    day=datetime.fromisoformat(row['date'])
    result='勝利' if row['gf']>row['ga'] else '敗戦' if row['gf']<row['ga'] else '引き分け'
    return f"{day.year}年{day.month}月{day.day}日 {row['competition']} / 日本 {row['gf']}対{row['ga']} / {result}"


WEEKDAYS='月火水木金土日'


def player_numbers(p):
    """新しい見た目の札用。数字は数字のまま、未取得は None（ゼロにしない）。"""
    counts=(p.get('season_numbers') or {}).get('values',{})
    return dict(name=p['name'],club=p['club'],position=p['position'],first_call=bool(p.get('first_call')),
        appearances=counts.get('appearances'),goals=counts.get('goals') if p['position']!='GK' else None)


def match_numbers(row,opponent):
    day=datetime.fromisoformat(row['date'])
    result='勝利' if row['gf']>row['ga'] else '敗戦' if row['gf']<row['ga'] else '引き分け'
    return dict(date=f'{day.year}.{day.month}.{day.day}',competition=row['competition'],gf=row['gf'],ga=row['ga'],
        result=result,opponent=opponent)


def dialogue(data):
    panels={};segments=[]
    chapters=[dict(id='positions',title='ポジション別の今季成績'),dict(id='focus',title='数字で注目する選手'),
              dict(id='history',title='過去の対戦'),dict(id='kickoff',title='試合日時')]
    last=data.get('previous_match')
    if last:chapters.insert(0,dict(id='previous',title='前の試合'));chapters.insert(0,dict(id='opening',title='冒頭'))
    first_chapter='opening' if last else 'positions'
    fixture=data['numbers'].get('fixture',False)
    def card(key,heading,rows,chapter,atomic=(),v2=None):
        if fixture:heading='【検証用・数値は架空】 '+heading
        panels[key]=dict(type='soccer_weekly',heading=heading,rows=rows,atomic=list(atomic))
        if v2:panels[key]['v2']=dict(v2,fixture=fixture)
        return key,chapter
    def say(speaker,text,ref):
        segments.append(dict(kind='talk',speaker=speaker,text=text,panel=ref[0],chapter=ref[1],
            meta=dict(who='めたん' if speaker==2 else 'ずんだもん')))
    count=len(data['players']);known=len(data['numbers']['players'])
    day=n.instant(data['as_of']).astimezone(n.JST)
    opening=card('opening',title(data),[f'{squad_words(data)} / 数値確認 {known}人','所属リーグごとの今季成績',
        f'取得日 {day.year}/{day.month}/{day.day}','未取得の数値は「未確認」。ゼロとして数えません。'],first_chapter,
        v2=dict(layout='opening',lead=data['game']['opponent']+'戦へ向けて',count=count,
            facts=[['内訳','　'.join(f"{pos} {sum(p['position']==pos for p in data['players'])}人" for pos in POSITIONS)],
                ['今季の数値を確認',f'{known}人'],['取得日',f'{day.year}.{day.month}.{day.day}']],
            note='数値は所属リーグの今季集計。未取得は「未確認」で、ゼロとして数えません。'))
    leaders=highlighted(data)
    # 11/14 本人「ずんだもんの疑問にめたんが答える形」：ずんだもんは問い、数字と事実はめたんが答える。
    say(3,f"{data['game']['opponent']}戦へ、どんな選手が呼ばれたのだ？",opening)
    if leaders:
        first=leaders[0];metric=numbers.metric(first)
        say(2,f"{first['name']}は、今季{metric[1]}{metric[2]}です。",opening)
    order='前の試合の結果、ポジションごとの今季成績' if last else 'ポジションごとの今季成績'
    if data.get('withdrawn'):
        say(2,f"{data['game']['opponent']}戦へ向けた招集{data['called']}人のうち、離脱を除く{count}人です。{order}、注目の選手、過去の対戦、試合日時の順に見ていきます。",opening)
        say(3,'離脱したのは、誰なのだ？',opening)
        for w in data['withdrawn']:
            d=datetime.fromisoformat(w['announced_on'])
            say(2,f"{w['name']}です。{d.month}月{d.day}日のJFAの発表で、理由は{w['reason']}です。",opening)
    else:
        say(2,f"{data['game']['opponent']}戦へ向けた招集{count}人です。{order}、注目の選手、過去の対戦、試合日時の順に見ていきます。",opening)
    say(3,'数字はカップ戦も合わせた合計なのだ？',opening)
    say(2,f"ここで使うのは所属リーグの今季集計だけです。取得日は{day.month}月{day.day}日。確認できたのは{known}人で、未確認はゼロとして数えません。",opening)
    if last:
        when=datetime.fromisoformat(last['date']);word=result_word(last);who=last['opponent']
        rows=[f"{when.month}月{when.day}日 {last['competition']}",f"日本 {last['gf']}対{last['ga']} {who} / {word}"]
        if last.get('scorers'):rows.append('得点者 '+'・'.join(last['scorers']))
        ref=card('previous',f'前の試合 {who}戦',rows,'previous',
            v2=dict(layout='matches',title=f'前の試合 {who}戦',matches=[match_numbers(last,who)],empty=''))
        say(3,f'前の{who}戦は、どうだったのだ？',ref)
        ending='日本の勝ち' if last['gf']>last['ga'] else '日本の負け' if last['gf']<last['ga'] else '引き分け'
        text=f"{when.month}月{when.day}日、日本は{who}と{last['competition']}で対戦し、{last['gf']}対{last['ga']}で{ending}でした。"
        if last.get('scorers'):text+='得点者は'+'、'.join(last['scorers'])+'です。'
        say(2,text,ref)
    for position in POSITIONS:
        group=[p for p in data['players'] if p['position']==position]
        for offset in range(0,len(group),3):
            people=group[offset:offset+3]
            rows=[p['name']+' / '+p['club']+'\n'+(numbers.stat_line(p) or '今季の数値は未確認') for p in people]
            ref=card(f'position_{position.replace("/", "_")}_{offset}',f'{position} / {offset+1}〜{offset+len(people)}人目',rows,'positions',
                     [v for p in people for v in (p['name'],p['club'])],
                     v2=dict(layout='roster',title=f'{position}　全{len(group)}人',players=[player_numbers(p) for p in group],
                         focus=[p['name'] for p in people],enter=offset==0))
            if offset==0:
                say(3,f'{position}は、誰が呼ばれたのだ？',ref)
                say(2,f'{position}は{len(group)}人です。',ref)
                if position=='GK':say(2,'ゴールキーパーはリーグ戦の出場数を見ます。ここから先の札は、発表されたポジションと名簿の順です。',ref)
                elif position=='DF':say(2,'続いてディフェンダーです。所属の異なる選手も、確認できたリーグ戦の出場と得点を並べます。',ref)
                else:say(2,'発表ではミッドフィルダーとフォワードが一つの区分です。役割をこちらで分けず、この区分のまま紹介します。',ref)
            if offset:say(3,f'{position}は、ほかに誰がいるのだ？',ref)
            for index,p in enumerate(people):
                line=numbers.stat_line(p)
                text=p['name']+'は'+(line+'です。' if line else p['club']+'からです。')
                if p.get('first_call'):text+='初めての招集です。'
                say(2,text,ref)
    focus=card('focus_intro','数字で注目する選手',[p['name']+' / '+numbers.stat_line(p) for p in leaders] or ['数値を確認できた選手はいません。'],'focus',
        v2=dict(layout='players',title='数字で注目する選手',players=[player_numbers(p) for p in leaders],empty='数値を確認できた選手はいません。'))
    say(3,'数字で目立つのは、誰なのだ？',focus)
    say(2,'得点が記録された選手を先に、その次に出場数を見ます。異なるリーグの数字なので、単純な実力の順位にはしません。',focus)
    for i,p in enumerate(leaders):
        row=p['season_numbers']
        ref=card('focus_'+str(i),p['name'],[p['club'],row['season']+' / '+row['league_label'],numbers.stat_line(p),
            '取得日 '+day.strftime('%Y/%m/%d')],'focus',[p['name'],p['club']],
            v2=dict(layout='player',player=dict(player_numbers(p),league=row['season']+'　'+row['league_label']),
                note=f'リーグ戦だけの数字　取得日 {day.year}.{day.month}.{day.day}'))
        say(3,p['name']+'は、どんな数字なのだ？',ref)
        say(2,p['club']+'所属。'+numbers.stat_line(p)+'です。'+('ゴールキーパーなので、ここでは出場数だけを使っています。' if p['position']=='GK' else 'リーグ戦だけを切り出した数字です。'),ref)
    if len(leaders)<3:say(2,'数値を確認できた選手が3人に満たないため、残りを推測で補うことはしません。',focus)
    ref=card('history',data['game']['opponent']+'との過去の対戦',[history_line(r) for r in data['history']] or ['確認できる対戦結果はありません。'],'history',
        v2=dict(layout='matches',title=data['game']['opponent']+'との過去の対戦',
            matches=[match_numbers(r,data['game']['opponent']) for r in data['history']],empty='確認できる対戦結果はありません。'))
    say(3,data['game']['opponent']+'とは、これまでどうだったのだ？',ref)
    say(2,'確認できる過去の対戦を振り返ります。',ref)
    for row in data['history']:say(2,history_line(row).replace(' / ','、')+'でした。',ref)
    if not data['history']:say(2,'過去の対戦結果を確認できないため、数字は出しません。',ref)
    game=data['game'];kick=n.instant(game['kickoff_jst']).astimezone(n.JST)
    when=f'{kick.month}月{kick.day}日 {kick.hour}時{kick.minute:02d}分（日本時間）'
    ref=card('kickoff','日本 対 '+game['opponent'],[when,'会場 '+game['venue'],'招集名簿・試合日時：JFA発表'],'kickoff',
        v2=dict(layout='kickoff',opponent=game['opponent'],date=f'{kick.month}.{kick.day}',time=f'{kick.hour}:{kick.minute:02d}',
            weekday=WEEKDAYS[kick.weekday()]+'曜',facts=[['会場',game['venue']],['出典','JFA発表（招集名簿・試合日時）']]))
    say(3,'試合は、いつなのだ？',ref)
    say(2,f"日本対{game['opponent']}は、{kick.month}月{kick.day}日、日本時間の{kick.hour}時{kick.minute}分開始です。会場は{game['venue']}です。",ref)
    say(2,'今季の数字と所属を見たうえで、代表でどんな組み合わせになるか。試合を楽しみに待ちましょう。',ref)
    return dict(program='soccer_national_long',kind='soccer_national_long',label=game['key'],title=title(data),top=title(data),
        panels=panels,chapters=chapters,segments=segments,national_long_material=copy.deepcopy(data))


def validate_document(doc):
    data=doc['national_long_material']
    rebuilt=material(data['key'],data['as_of'],data['numbers'],publish=bool(data.get('publication_enabled')))
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


def description(doc,chapters=None):
    """概要欄。何の回か・章の時刻・出典・取得日・音声のクレジット。数字は材料の値だけ。"""
    data=doc['national_long_material'];day=n.instant(data['as_of']).astimezone(n.JST)
    kick=n.instant(data['game']['kickoff_jst']).astimezone(n.JST)
    lines=[title(data),f"日本代表 対 {data['game']['opponent']}（{kick.month}月{kick.day}日 {kick.hour}時{kick.minute:02d}分 日本時間）の試合前に、{squad_words(data)}の所属リーグでの今季成績を確認する回です。",'']
    for w in data.get('withdrawn') or []:
        d=datetime.fromisoformat(w['announced_on'])
        lines.insert(2,f"離脱：{w['name']}（{w['reason']}、{d.month}月{d.day}日 JFA発表）")
    if chapters:lines+=list(chapters)+['']
    last=data.get('previous_match')
    if last:
        when=datetime.fromisoformat(last['date'])
        lines.append(f"前の試合：{when.month}月{when.day}日 {last['competition']} 日本 {last['gf']}対{last['ga']} {last['opponent']}（{result_word(last)}）"+('　得点者：'+'、'.join(last['scorers']) if last.get('scorers') else ''))
    lines+=['今季のリーグ戦のみ。取得日 '+f'{day.year}年{day.month}月{day.day}日',
        '未確認の数字はゼロとして扱いません。図は発表されたポジションの名簿順で、先発やフォーメーションの予想ではありません。',
        'MF/FWはJFAの一括発表です。過去の対戦は保存済みの結果のみです。','','出典：',
        'JFA発表（招集名簿・試合日時）：'+data['source_url']]+['JFA発表（離脱）：'+w['source_url'] for w in data.get('withdrawn') or []]
    lines+=[p['source'] for p in data['numbers']['players']]+data['history_sources']
    lines+=['','音声：VOICEVOX 四国めたん / ずんだもん','#日本代表 #サッカー日本代表']
    return chr(10).join(_dedupe(lines))


def _dedupe(lines):
    """出典URLの重複だけ除く。空行と章の並びは残す。"""
    seen=set();out=[]
    for line in lines:
        if line.startswith('http') or line.startswith('JFA発表'):
            if line in seen:continue
            seen.add(line)
        out.append(line)
    return out


def metadata(doc,timeline_path=None):
    validate_document(doc);data=doc['national_long_material']
    chapters=[]
    if timeline_path:
        import soccer_weekly_long
        chapters=soccer_weekly_long.rendered_chapters(doc,timeline_path)
    return dict(snippet=dict(title=title(data),description=description(doc,chapters),categoryId='17',
        tags=['日本代表','サッカー日本代表',data['game']['opponent'],'招集メンバー'],defaultLanguage='ja',defaultAudioLanguage='ja'),
        planned_publish_at=data['planned_publish_at'],publication_enabled=bool(data.get('publication_enabled')))


def published(key,path=PUBLISHED):
    try:rows=json.loads(Path(path).read_text(encoding='utf8')).get(RECORD_KIND) or {}
    except (OSError,json.JSONDecodeError):return False
    return bool(rows.get(key,{}).get('video_id'))


def due(now=None,fixtures=None,record=PUBLISHED):
    """JSTのきょうが、未公開のどれかの試合の前日なら、その試合の key。違えば None。"""
    now=(now or datetime.now(n.JST)).astimezone(n.JST)
    fixtures=fixtures or n.read(FIXTURES)
    for game in fixtures['matches']:
        kick=n.instant(game['kickoff_jst']).astimezone(n.JST)
        if now.date()==kick.date()-timedelta(days=1) and now<kick and not published(game['key'],record):
            return game['key']
    return None


def validate_upload(args,now=None):
    """公開の最終関門。前日の20:00に間に合う時だけ通す。"""
    now=(now or datetime.now(n.JST)).astimezone(n.JST)
    doc=n.read(args.narration);validate_document(doc)
    data=n.read(args.games)
    if data!=doc['national_long_material']:raise ValueError('投稿用の材料と台本が一致しません')
    if not data.get('publication_enabled'):raise ValueError('公開の経路で作った材料ではありません')
    if data['numbers'].get('fixture'):raise ValueError('検証用の架空数値は公開しません')
    if args.force:raise ValueError('代表の長編は試合のkeyでの二重投稿を許可しません')
    if args.video_date!=data['key']:raise ValueError('記録する試合のkeyが材料と一致しません')
    planned=n.instant(data['planned_publish_at']).astimezone(n.JST)
    if planned.hour!=20 or planned.minute!=0:raise ValueError('公開予定が前日20:00ではありません')
    if args.publish_at!='20:00':raise ValueError('公開時刻は20:00だけ指定できます')
    if now.date()!=planned.date():raise ValueError('投稿は試合前日の当日に限ります')
    if now>=planned-timedelta(minutes=10):raise ValueError('前日20:00の予約に間に合わないため投稿しません')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--opponent',choices=('brazil','paraguay'))
    ap.add_argument('--due',action='store_true',help='きょうが未公開の試合の前日なら、GITHUB_OUTPUTへ due と opponent を書いて終わる')
    ap.add_argument('--publish',action='store_true',help='公開の経路。見本では付けない')
    ap.add_argument('--as-of',default=None)
    ap.add_argument('--fixture',type=Path)
    ap.add_argument('--out',type=Path,default=ROOT/'build/national_long')
    args=ap.parse_args()
    if args.due:
        key=due();lines=[f'due={"true" if key else "false"}',f'opponent={key or ""}']
        print(chr(10).join(lines))
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf8') as out:out.write(chr(10).join(lines)+chr(10))
        return
    if not args.opponent:raise ValueError('--opponent か --due が必要です')
    as_of=args.as_of or datetime.now(n.JST).isoformat()
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
    if args.publish and (args.fixture or sheet.get('fixture')):raise ValueError('公開の経路で検証用データは使えません')
    data=material(args.opponent,as_of,sheet,publish=args.publish)
    doc=dialogue(data);validate_document(doc)
    import name_reading_guard
    name_reading_guard.validate_dialogue(doc)
    for filename,value in (('numbers.json',sheet),('material.json',data),('dialogue.json',doc),('metadata.json',metadata(doc))):n.save(args.out/filename,value)
    print(title(data)+' / 予定 '+data['planned_publish_at']+(' / 公開の経路' if args.publish else ' / 見本のみ'))


if __name__=='__main__':main()
