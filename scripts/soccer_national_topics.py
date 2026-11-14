"""終了済み代表戦の保存材料だけから、条件を満たす話題を組み立てる。"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

import short_common
import soccer_national as national
from duo import ZUNDA, METAN

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / 'data/soccer_national_topics_published.json'
NAMES = ROOT / 'data/soccer_national_opponent_names.json'
RESULTS = ROOT / 'data/soccer_national_results.json'
REACTIONS = ROOT / 'data/soccer_national_reactions.json'
PROGRAM = 'soccer_national_topic'
VIDEO = 'collespo_national_topic.mp4'
LIMIT = 45
DEFAULT_EVENT = '401916337'


class Unavailable(ValueError):
    pass


def opponent_names():
    return national.read(NAMES)


def meetings_for(other):
    """確認一覧（data/soccer_national_results.json）にある、その相手との過去の対戦。"""
    return national.read(RESULTS).get('previous_meetings', {}).get(other, [])


def compact(summary):
    """固定材料と本番材料の共通形。写真・ロゴ・記事・コメントの名前を持たない。"""
    c = summary['header']['competitions'][0]
    return dict(header=dict(id=summary['header']['id'], competitions=[dict(
        id=c['id'], date=c['date'], status=c['status'], competitors=[dict(
            id=t['id'], score=t['score'], team={k:t['team'][k] for k in ('id', 'displayName', 'abbreviation')})
            for t in c['competitors']])]),
        boxscore=dict(teams=[dict(team=dict(id=t['team']['id']), statistics=[dict(name=s['name'], displayValue=s['displayValue'])
            for s in t['statistics'] if s['name'] in ('possessionPct','totalShots','shotsOnTarget','wonCorners','saves')])
            for t in summary['boxscore']['teams']]),
        rosters=[dict(team=dict(id=t['team']['id']), roster=[dict(athlete={k:r['athlete'][k] for k in ('id','displayName')},
            starter=r['starter'], position=r['position'], stats=[dict(name=s['name'],displayValue=s['displayValue'])
            for s in r.get('stats',[]) if s['name'] in ('saves','totalShots','shotsOnTarget')]) for r in t['roster']])
            for t in summary['rosters']],
        keyEvents=[{k:e[k] for k in ('id','type','text','clock','scoringPlay','team','participants','period','ownGoal','shootout') if k in e}
            for e in summary.get('keyEvents',[]) if e.get('scoringPlay') or e.get('type',{}).get('type') in ('substitution','red-card')],
        commentary=[{k:c[k] for k in ('text','time') if k in c} for c in summary.get('commentary',[])
            if 'Goal confirmed following VAR Review' in c.get('text','')])


class Material:
    def __init__(self, summary, names=None, meetings=None):
        self.raw = summary
        self.c = summary['header']['competitions'][0]
        if not self.c['status']['type'].get('completed'):
            raise Unavailable('終了が確認できない試合')
        teams = self.c['competitors']
        self.jp = next(t for t in teams if str(t['id']) == national.JAPAN)
        self.opp = next(t for t in teams if str(t['id']) != national.JAPAN)
        self.oid = str(self.opp['id'])
        self.other = national.team_name(self.opp['team']['displayName'])
        if not self.other or re.search('[A-Za-z]',self.other):
            raise Unavailable('相手国の日本語名が未登録')
        self.score = [int(self.jp['score']), int(self.opp['score'])]
        self.names = opponent_names() if names is None else names
        self.meetings = meetings_for(self.other) if meetings is None else meetings
        self.today = national.instant(self.c['date']).astimezone(national.JST).date().isoformat()
        self.goals = sorted([e for e in summary.get('keyEvents',[]) if e.get('scoringPlay') and not e.get('shootout')], key=lambda e:self.minute_number(e))
        if any(sum(str(e.get('team',{}).get('id')) == tid for e in self.goals) != value
               for tid,value in zip((national.JAPAN,self.oid), self.score)):
            raise Unavailable('得点イベントが最終スコアと一致しない')

    @staticmethod
    def minute(e):
        s = e['clock']['displayValue'].replace("'",'').replace('′','')
        if not re.fullmatch(r'\d+(?:\+\d+)?',s):
            raise Unavailable('得点・交代の分が不明')
        return s

    @classmethod
    def minute_number(cls,e):
        return sum(map(int,cls.minute(e).split('+')))

    def name(self, athlete, tid):
        english=athlete['displayName']
        if str(tid)==national.JAPAN:
            return national.player_name(english, True)
        if english not in self.names:
            raise Unavailable('相手選手名が未登録: '+english)
        row=self.names[english]
        if not row.get('name') or not re.fullmatch('[ァ-ヶー・]+',row.get('reading','')):
            raise Unavailable('相手選手の読みが未登録: '+english)
        return row['name']

    def short(self, athlete, tid):
        """題・問いで使う短い呼び名。表に short があるときだけ。"""
        full=self.name(athlete,tid)
        if str(tid)==national.JAPAN:return full
        row=self.names[athlete['displayName']]
        if not row.get('short'):return full
        if not re.fullmatch('[ァ-ヶー・]+',row.get('short_reading','')):raise Unavailable('相手選手の短い呼び名の読みが未登録')
        return row['short']

    def who(self,e,index=0):
        if e.get('ownGoal'):
            raise Unavailable('オウンゴールは選手の得点として紹介しない')
        return self.name(e['participants'][index]['athlete'],e['team']['id'])

    def roster(self,tid):
        return next(t['roster'] for t in self.raw['rosters'] if str(t['team']['id'])==str(tid))

    def player(self,e):
        ident=e['participants'][0]['athlete']['id']
        return next(r for r in self.roster(e['team']['id']) if r['athlete']['id']==ident)

    def stat(self,tid,key,player=None):
        rows=player['stats'] if player else next(t['statistics'] for t in self.raw['boxscore']['teams'] if str(t['team']['id'])==str(tid))
        value=next(s['displayValue'] for s in rows if s['name']==key)
        if not re.fullmatch(r'\d+(?:\.\d+)?',value):raise Unavailable('数字が未確認: '+key)
        return value

    def result(self):
        a,b=self.score
        return ('試合の結果はどうなったのだ？',f'日本と{self.other}の試合は、日本が{a}対{b}で'+('勝ちました。' if a>b else '敗れました。' if a<b else '引き分けました。'),
                '試合結果',[('日本 対 '+self.other,f'{a}-{b}')])


def percent(value):
    return str(int(float(value)+.5))


def team_numbers(m):
    if m.score[0]<=m.score[1]:raise Unavailable('日本の勝利ではない')
    pairs=[(key,m.stat(national.JAPAN,key),m.stat(m.oid,key)) for key in ('possessionPct','totalShots','shotsOnTarget','wonCorners')]
    if any(float(a)>=float(b) for _,a,b in pairs):raise Unavailable('日本が各数字で下回る条件を満たさない')
    ja,oa=percent(pairs[0][1]),percent(pairs[0][2])
    if int(ja)+int(oa)!=100:raise Unavailable('支配率の整数が合計100にならない')
    pairs[0]=('possessionPct',ja,oa)
    shown=[('ボール支配率',ja+'%',oa+'%'),('シュート',pairs[1][1]+'本',pairs[1][2]+'本'),
           ('枠内シュート',pairs[2][1]+'本',pairs[2][2]+'本'),('コーナーキック',pairs[3][1]+'本',pairs[3][2]+'本')]
    def compare(count):
        return dict(compare=dict(teams=['日本',m.other],rows=[list(r) for r in shown[:count]]))
    def rows(*indexes):
        return [(t,shown[i][1 if t=='日本' else 2]) for i in indexes for t in ('日本',m.other)]
    panels=[('ボール支配率は、どうだったのだ？',f'ボール支配率は、日本が{ja}パーセント、{m.other}が{oa}パーセントでした。','ボール支配率',
             rows(0),compare(1)),
            ('シュートの数は、どうだったのだ？',f'シュートは、日本が{pairs[1][1]}本、{m.other}が{pairs[1][2]}本。枠内シュートは、日本が{pairs[2][1]}本、{m.other}が{pairs[2][2]}本でした。',
             'シュートと枠内シュート',rows(1,2),compare(3)),
            ('コーナーキックは、どうだったのだ？',f'コーナーキックは、日本が{pairs[3][1]}本、{m.other}が{pairs[3][2]}本でした。','コーナーキック',
             rows(3),compare(4))]
    # 題で結果を言うので、結果を先に言い、数字で上回られていたことへつなぐ（Argon 11/15）。
    opening=(f'{m.other}戦は、どうなったのだ？',f'日本が{m.score[0]}対{m.score[1]}で勝ちました。ただ、試合の数字では{m.other}が上回っていました。',
             '試合結果',[('日本 対 '+m.other,f'{m.score[0]}-{m.score[1]}')])
    return f'日本{m.score[0]}-{m.score[1]}{m.other} 支配率{ja}% シュート{pairs[1][1]}本で勝利',[opening]+panels


def late_winner(m):
    if m.score[0]<=m.score[1]:raise Unavailable('日本の勝利ではない')
    # 最後にリードを得て、その後追いつかれていない得点だけが決勝点。
    scores={national.JAPAN:0,m.oid:0};decisive=None
    for e in m.goals:
        tid=str(e['team']['id']);scores[tid]+=1
        if scores[national.JAPAN]==scores[m.oid]:decisive=None
        elif tid==national.JAPAN and scores[national.JAPAN]==scores[m.oid]+1:decisive=e
    if not decisive:raise Unavailable('決勝点を確認できない')
    player=m.player(decisive)
    if player.get('starter') is not False:raise Unavailable('決勝点の選手が控えではない')
    ident=player['athlete']['id']
    sub=next((e for e in m.raw['keyEvents'] if e.get('type',{}).get('type')=='substitution'
        and str(e.get('team',{}).get('id'))==national.JAPAN and e.get('participants',[{}])[0].get('athlete',{}).get('id')==ident),None)
    if not sub or m.minute_number(sub)>m.minute_number(decisive):raise Unavailable('得点前の途中出場が未確認')
    name=m.who(decisive);minute=m.minute(decisive);entry=m.minute(sub);replaced=m.who(sub,1)
    rows=[('決勝点は、誰が決めたのだ？',f'日本の決勝点を決めたのは、{name}です。得点は{national.minute_words(minute)}でした。','決勝点',[(name,minute+'分')]),
          ('どのように出場したのだ？',f'{name}は先発ではなく、{national.minute_words(entry)}に{replaced}と交代で出場しました。','途中出場',[(name,entry+'分'),('交代した選手',replaced)])]
    confirmed=any('Goal confirmed following VAR Review' in c.get('text','') and
        (c.get('time',{}).get('displayValue')==decisive['clock']['displayValue']) and
        player['athlete']['displayName'] in c.get('text','') for c in m.raw.get('commentary',[]))
    if confirmed:rows.append(('得点の確認は、どうなったのだ？','この決勝点は、VARの確認を経て認められました。','得点の確認',[('VARの確認','得点を認定')]))
    return f'{name} 途中出場から{minute}分の決勝点',rows+[m.result()]


def opponent_star(m):
    groups={}
    for e in m.goals:
        if str(e['team']['id'])==m.oid and not e.get('ownGoal'):
            groups.setdefault(e['participants'][0]['athlete']['id'],[]).append(e)
    candidates=[g for g in groups.values() if len(g)>=2]
    if not candidates:raise Unavailable('相手に複数得点の選手がいない')
    goals=sorted(candidates,key=lambda g:(-len(g),g[0]['participants'][0]['athlete']['id']))[0]
    athlete=goals[0]['participants'][0]['athlete']
    name=m.who(goals[0]);short=m.short(athlete,m.oid);n=len(goals);minutes='・'.join(m.minute(e)+'分' for e in goals)
    spoken='・'.join(national.minute_words(m.minute(e)) for e in goals)
    shots=m.stat(m.oid,'totalShots',m.player(goals[0]));target=m.stat(m.oid,'shotsOnTarget',m.player(goals[0]))
    rows=[(f'{m.other}の得点者は、誰なのだ？',f'{m.other}の{name}が{n}得点。得点した時間は{spoken}でした。','相手の得点者',[(name,f'{n}得点'),('得点の時間',minutes)]),
          ('シュートは、何本だったのだ？',f'{name}のシュートは{shots}本。そのうち枠内シュートは{target}本でした。','シュートの数字',[('シュート',shots+'本'),('枠内シュート',target+'本')])]
    outside=all('outside the box' in e.get('text','') for e in goals)
    if outside:rows.append((f'{short}は、どこから決めたのだ？',f'{n}得点とも、ペナルティエリアの外からのシュートでした。','得点の位置',[('ペナルティエリアの外',f'{n}得点')]))
    assists=[m.who(e,1) for e in goals if 'Assisted by ' in e.get('text','') and len(e.get('participants',[]))>=2]
    if len(assists)==n and len(set(assists))==1:
        rows.append(('アシストしたのは、誰なのだ？',f'{n}点とも、{assists[0]}のアシストでした。','アシスト',[('全得点のアシスト',assists[0])]))
    return f'{short} {n}得点'+('とも箱の外から' if outside else ''),rows+[m.result()]


def keeper(m):
    keepers=[r for r in m.roster(national.JAPAN) if r['position'].get('abbreviation')=='G' and r.get('starter')]
    if len(keepers)!=1:raise Unavailable('日本の先発GKが未確認')
    p=keepers[0];name=m.name(p['athlete'],national.JAPAN);saves=m.stat(national.JAPAN,'saves',p)
    # GK交代があればチーム全体の数字を個人の数字と混同しない。
    if saves!=m.stat(national.JAPAN,'saves'):raise Unavailable('日本のGKとチームのセーブ数が異なる')
    opponents=[r for r in m.roster(m.oid) if r['position'].get('abbreviation')=='G' and r.get('starter')]
    if len(opponents)!=1:raise Unavailable('相手GKが未確認')
    other_saves=m.stat(m.oid,'saves',opponents[0])
    shots=m.stat(m.oid,'totalShots');target=m.stat(m.oid,'shotsOnTarget')
    rows=[('日本のゴールキーパーは、どうだったのだ？',f'日本のゴールキーパー、{name}のセーブ数は{saves}でした。','守護神の数字',[(name,saves+'セーブ')]),
          (f'{m.other}のシュートは、どうだったのだ？',f'{m.other}のシュートは{shots}本。そのうち枠内シュートは{target}本でした。日本が受けたシュートの数字です。','日本の被シュート',[('被シュート',shots+'本'),('被枠内シュート',target+'本')]),
          (f'{m.other}のゴールキーパーは、どうだったのだ？',f'{m.other}のゴールキーパーのセーブ数は{other_saves}。{name}は{saves}セーブでした。','両チームのGK',[('日本',saves+'セーブ'),(m.other,other_saves+'セーブ')])]
    win=m.score[0]>m.score[1]
    return f'{name} {saves}セーブ'+(f'で{m.other}に勝利' if win else f' {m.other}のシュート{shots}本'),rows+[m.result()]


FOOT={'left footed shot':'左足','right footed shot':'右足'}
PASS={'with a through ball':'スルーパス','with a cross':'クロス'}


def how(e):
    """ESPN の得点の文から、決めた足とアシストの形（分かる物だけ）。"""
    text=e.get('text','')
    return next((v for k,v in FOOT.items() if k in text),None),next((v for k,v in PASS.items() if k in text),None)


def goal_flow(m):
    """全得点の流れ（同じ選手の続けての得点はまとめる）と、画面の表。"""
    groups=[]
    for e in m.goals:
        if e.get('ownGoal'):raise Unavailable('オウンゴールは選手の得点として紹介しない')
        ident=e['participants'][0]['athlete']['id']
        if groups and groups[-1][0]==ident:groups[-1][1].append(e)
        else:groups.append((ident,[e]))
    return groups,[(m.minute(e)+'分 '+('日本' if str(e['team']['id'])==national.JAPAN else m.other),m.short(e['participants'][0]['athlete'],e['team']['id'])) for e in m.goals]


def early_goals(m):
    if m.score[0]<=m.score[1]:raise Unavailable('日本の勝利ではない')
    goals=[e for e in m.goals if str(e['team']['id'])==national.JAPAN and e.get('period',{}).get('number')==1]
    pair=next(((a,b) for a,b in zip(goals,goals[1:]) if 0<m.minute_number(b)-m.minute_number(a)<=5),None)
    if not pair:raise Unavailable('前半に5分以内の間隔の日本の2得点がない')
    a,b=pair;gap=m.minute_number(b)-m.minute_number(a);rows=[]
    for e,q,head,lead in ((a,'先制点は、どう決まったのだ？','前半の得点','前半'),(b,'続く得点は、どう決まったのだ？','前半の続く得点',f'{gap}分後の前半')):
        name=m.who(e);minute=m.minute(e)
        if 'Assisted by ' not in e.get('text','') or len(e.get('participants',[]))<2:raise Unavailable('アシストが未確認')
        assist=m.who(e,1);foot,kind=how(e)
        said=f'{lead}{national.minute_words(minute)}、{assist}の'+(kind or 'アシスト')+f'から、{name}が'+(f'{foot}で' if foot else '')+'決めました。'
        rows.append((q,said,head,[(name,minute+'分')]+([('シュート',foot)] if foot else [])+[('アシスト',assist+('の'+kind if kind else ''))]))
    # 2点のあとの流れも言う（「3-2」だけに飛ばさない。Argon 11/15）。
    groups,flow=goal_flow(m)
    later=[g for g in groups if m.minute_number(g[1][0])>m.minute_number(b)]
    if not later:raise Unavailable('その後の得点がない')
    tally={national.JAPAN:0,m.oid:0}
    for e in m.goals:
        if m.minute_number(e)<=m.minute_number(b):tally[str(e['team']['id'])]+=1
    parts=[]
    for _,es in later:
        for e in es:tally[str(e['team']['id'])]+=1
        team='' if str(es[0]['team']['id'])==national.JAPAN else f'{m.other}の'
        parts.append(f"{team}{m.who(es[0])}が{'と'.join(national.minute_words(m.minute(e)) for e in es)}に決めて{tally[national.JAPAN]}対{tally[m.oid]}")
    said='その後、'+'。'.join(parts)+'。日本が勝ちました。'
    rows.append(('試合は、そのあとどうなったのだ？',said,'全得点の流れ',flow))
    return f'{m.who(a)}と{m.who(b)} {gap}分間で2得点',rows


def day_words(row):
    year,month,day=row['date'].split('-')
    return f'{int(month)}月{int(day)}日'


def board(row,other):
    year,month,day=row['date'].split('-')
    # 両国名を書く（「1-2 ブラジル」だけではどちらの点か分からない。Argon 11/15）。
    return (f"{year}/{int(month)}/{int(day)} {row['competition']}"+((' '+row['stage']) if row.get('stage') else ''),f"日本 {row['gf']}-{row['ga']} {other}")


def rematch(m):
    if m.score[0]<=m.score[1]:raise Unavailable('日本の勝利ではない')
    before=sorted([r for r in m.meetings if r['date']<m.today],key=lambda r:r['date'],reverse=True)
    lost=next((r for r in before if r['competition']=='ワールドカップ' and r['result']=='loss' and r['gf']<r['ga']),None)
    if not lost:raise Unavailable('ワールドカップで敗れた対戦が確認一覧にない')
    stage=lost.get('stage','')
    now=dict(date=m.today,competition='親善試合',gf=m.score[0],ga=m.score[1])
    # 今回の勝ちから入り、対戦を新しい順に1行ずつ積む（Argon 11/15：結論を先に・一覧で）。
    rows=[(f'{m.other}戦は、どうなったのだ？',f'日本が{m.score[0]}対{m.score[1]}で勝ちました。ワールドカップで敗れた相手です。','対戦の記録',[board(now,m.other)]),
          ('ワールドカップでは、どうだったのだ？',f"{day_words(lost)}のワールドカップの{stage}で、日本は{lost['gf']}対{lost['ga']}で敗れました。",
            '対戦の記録',[board(now,m.other),board(lost,m.other)])]
    won=next((r for r in before if r['result']=='win' and r['gf']>r['ga'] and r['date']<lost['date']),None)
    if won:rows.append(('その前の対戦は、どうだったのだ？',f"{won['date'][:4]}年{int(won['date'][5:7])}月の{won['competition']}では、日本が{won['gf']}対{won['ga']}で勝っています。",
            '対戦の記録',[board(now,m.other),board(lost,m.other),board(won,m.other)]))
    return f'W杯で敗れた{m.other}に{m.score[0]}-{m.score[1]}で勝利',rows


def reaction_material(event):
    return (national.read(REACTIONS).get('events') or {}).get(str(event))


def reactions(m):
    """試合後の声。記事の鍵括弧の中の言葉だけを、発言者と媒体つきで言う。"""
    data=reaction_material(m.raw['header']['id'])
    if not data or not data.get('checked_on') or not data.get('quotes'):raise Unavailable('試合後の声の確認済み材料がない')
    rows=[]
    for q in data['quotes']:
        if not q.get('source_url','').startswith('https://') or not q.get('quote') or '「' in q['quote'] or '」' in q['quote']:
            raise Unavailable('発言の出典・中身が未確認: '+q.get('who',''))
        said=f"{q['lead']}は、「{q['quote']}」と話しました。"+(f"{q['via']}の報道です。" if q.get('via') else '')
        rows.append((q['ask'],said,q['head'],[(q['who']+'の発言','「'+q['quote']+'」'),('出典',q['source'])]))
    for f in data.get('facts',[]):
        if len(f.get('sources',[]))<2:raise Unavailable('2つの出典で確かめていない事実がある')
        rows.append((f['ask'],f['text'],f['head'],[tuple(r) for r in f['rows']]+([('出典',f['source_names'])] if f.get('source_names') else [])))
    return data['title'],rows


TOPICS={'team-numbers':team_numbers,'late-winner':late_winner,'opponent-star':opponent_star,'keeper':keeper,'early-goals':early_goals,'rematch':rematch,'reactions':reactions}


def narration(summary, topic, *, names=None, meetings=None):
    raw=compact(summary);m=Material(raw,names,meetings)
    title,panels=TOPICS[topic](m)
    segments=[]
    for i,(question,answer,head,rows,*extra) in enumerate(panels):
        meta=dict(duo=True,topic=topic,panel=i,head=head,rows=rows,**(extra[0] if extra else {}))
        segments += [dict(kind='list',text=question,speaker=ZUNDA,meta=dict(meta,duo_ask=True,who='ずんだもん')),
                     dict(kind='list',text=answer,speaker=METAN,meta=dict(meta,who='四国めたん'))]
    doc=dict(program=PROGRAM,date_jst=m.today,
        title=title+' #Shorts',topic=topic,event_id=str(raw['header']['id']),
        topic_key=str(raw['header']['id'])+':'+topic,source_url='https://www.espn.com/soccer/match/_/gameId/'+str(raw['header']['id']),
        segments=segments,topic_summary=raw,duration_budget=dict(limit=LIMIT,grace=0),
        sanity_materials=[dict(source='ESPN 保存材料',sport='soccer',facts=raw)])
    if topic=='rematch':
        doc['previous_meetings']=[copy.deepcopy(r) for r in m.meetings if r['date']<m.today]
        doc['meeting_sources']=national.read(RESULTS)['sources']
    if topic=='reactions':
        doc['reaction_material']=copy.deepcopy(reaction_material(raw['header']['id']))
        doc['sanity_materials'].append(dict(source='試合後の発言（確認済み）',sport='soccer',facts=doc['reaction_material']))
    return short_common.prepare(doc)


def estimate(doc):
    """原稿の文字数からの見積もり（実音声の測定ではない）。既存の掛け合いと同じ式。"""
    return sum(len(s['text'])/7.5+.4 if s['kind']!='outro' else short_common.OUTRO_SECONDS for s in doc['segments'])


def available(summary, names=None, meetings=None):
    made={};excluded={}
    for topic in TOPICS:
        try:made[topic]=narration(summary,topic,names=names,meetings=meetings)
        except (Unavailable,KeyError,ValueError,TypeError,StopIteration) as e:excluded[topic]=str(e) or '必要な欄がない'
    return made,excluded


def check(doc):
    if doc.get('program')!=PROGRAM:return []
    try:
        expected=narration(doc['topic_summary'],doc['topic'],meetings=doc.get('previous_meetings',[]))
        if json.loads(json.dumps(doc))!=json.loads(json.dumps(expected)):return ['代表の話題の原稿・数字・題が保存材料と一致しません']
        for s in doc['segments']:
            if s['kind']=='outro':continue
            if s['speaker']==ZUNDA and (not s['text'].endswith('？') or re.search('[0-9０-９〇一二三四五六七八九十百千万]',s['text'])):
                return ['ずんだもんは数字なしの問いだけです']
    except (ValueError,KeyError,TypeError,StopIteration):return ['代表の話題の条件・名前・材料が不一致です']
    return []


def speech_readings(doc):
    if check(doc):raise ValueError('話題の原稿が不一致')
    import name_reading_guard as guard
    readings={}
    text='\n'.join(s['text'] for s in doc['segments'])
    for t in doc['topic_summary']['rosters']:
        for r in t['roster']:
            english=r['athlete']['displayName']
            if str(t['team']['id'])==national.JAPAN:
                p=national.official_squad_player(english)
                if p and p['name'] in text:readings[p['name']]=('player',p['reading'])
            elif english in opponent_names():
                p=opponent_names()[english]
                if p['name'] in text:readings[p['name']]=('player',p['reading'])
                if p.get('short') and p['short'] in text:readings[p['short']]=('player',p['short_reading'])
    for name,(_,reading) in readings.items():
        existing=guard.player_data().get('readings',{}).get(name)
        if existing and existing!=reading:raise ValueError('既存の読みと不一致: '+name)
    return readings


def information(doc):
    if check(doc):raise ValueError('材料が不一致')
    answers=[(i,s) for i,s in enumerate(doc['segments']) if s['speaker']==METAN and s['kind']!='outro']
    if doc['topic']=='reactions':
        r=doc['reaction_material'];sources=[q['source_url'] for q in r['quotes']]+[' '.join(f['sources']) for f in r.get('facts',[])]
        return [dict(subject=s['meta']['head'],fact='試合後の発言・試合の最後の出来事',value=s['meta']['rows'],source=src,segments=[i])
                for (i,s),src in zip(answers,sources)]
    return [dict(subject=s['meta']['head'],fact='当該試合の数字・経過',value=s['meta']['rows'],source=doc['source_url'],segments=[i])
            for i,s in answers]


GLOSSARY={'枠内シュート':'枠内シュート：ゴールの枠の中に向かったシュート。','セーブ':'セーブ：GKが相手のシュートを防いだ記録。',
          'VAR':'VAR：映像による判定の確認。','コーナーキック':'コーナーキック：守る側が最後に触れたボールがゴールラインを出たときの攻撃側の再開。'}


def metadata(doc):
    if check(doc):raise ValueError('原稿が不一致')
    said='\n'.join(s['text'] for s in doc['segments'] if s['speaker']==METAN and s['kind']!='outro')
    terms=[v for k,v in GLOSSARY.items() if k in said]
    source='出典: ESPN 試合ページ\n'+doc['source_url']
    if doc['topic']=='rematch':
        source+='\n過去の対戦: 日本代表の試合の確認一覧\n'+'\n'.join(doc['meeting_sources'])
    if doc['topic']=='reactions':
        r=doc['reaction_material']
        source='出典:\n'+'\n'.join(f"{q['who']}（{q['where']}）: {q['source']}\n{q['source_url']}" for q in r['quotes'])
        urls=list(dict.fromkeys(u for f in r.get('facts',[]) for u in f['sources']))
        if urls:source+='\n試合の最後の退場:\n'+'\n'.join(urls)
        source+='\n試合の結果: ESPN 試合ページ\n'+doc['source_url']
    return dict(snippet=dict(title=doc['title'],description=said+('\n\n'+'\n'.join(terms) if terms else '')+'\n\n'+source+
        '\n音声: VOICEVOX:ずんだもん・四国めたん\n#サッカー日本代表 #Shorts',tags=['サッカー','日本代表','コレスポ'],categoryId='17',defaultLanguage='ja',defaultAudioLanguage='ja'))


def reservation(now, ledger):
    """当日12時/19時/21時の空き。過去の枠への即時投稿や翌日への自動送りをしない。"""
    local=now.astimezone(national.JST)
    for hour in (12,19,21):
        at=local.replace(hour=hour,minute=0,second=0,microsecond=0)
        if at>local+timedelta(minutes=5) and not any(r.get('publish_at')==at.isoformat() for r in ledger.values()):return at
    raise ValueError('当日の予約枠がありません。翌日に手で実行してください')


def validate_upload(args, now=None):
    doc=national.read(args.narration)
    if check(doc) or doc['topic_summary']!=national.read(args.games):raise ValueError('原稿と材料が不一致')
    if __import__('os').getenv('COLLESPO_NATIONAL_TOPIC_PUBLISH')!='true':raise ValueError('話題の公開は手動指定が必要です')
    if doc['topic']=='rematch' and doc['previous_meetings']!=[r for r in meetings_for(Material(doc['topic_summary']).other) if r['date']<doc['date_jst']]:
        raise ValueError('過去の対戦が確認一覧と一致しません')
    if doc['topic']=='reactions' and doc.get('reaction_material')!=reaction_material(doc['event_id']):
        raise ValueError('試合後の声が確認済みの材料と一致しません')
    ledger=national.read(LEDGER)
    if doc['topic_key'] in ledger:raise ValueError('同じ試合の同じ話題は予約・投稿済みです')
    if not args.publish_at:raise ValueError('未来の予約時刻が必要です')
    at=national.instant(args.publish_at);now=now or datetime.now(timezone.utc)
    if at<=now:raise ValueError('未来の予約時刻が必要です')
    import short_content
    report=short_content.validate_upload(args.video)
    if report['actual_seconds']>LIMIT:raise ValueError(f'話題ショートは{LIMIT}秒までです')
    # 無音の見本は公開させない。実音声の記録（voice_manifest）が要る。
    if not (Path(args.narration).parent/'audio/voice_manifest.json').exists() and not (Path(args.video).parent/'voice_manifest.json').exists():
        raise ValueError('実音声の記録がありません')


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--summary',type=Path);ap.add_argument('--topic',choices=list(TOPICS));ap.add_argument('--list',action='store_true')
    ap.add_argument('--event',help='ESPN の event id（本番は実行時に summary を取る。既定 401916337）')
    ap.add_argument('--out',type=Path,default=ROOT/'build/soccer_national_topics')
    ap.add_argument('--reservation',action='store_true')
    args=ap.parse_args(argv)
    if args.reservation:
        print(reservation(datetime.now(timezone.utc),national.read(LEDGER)).isoformat());return
    if args.summary:summary=national.read(args.summary)
    else:
        import requests
        response=requests.get(national.API+'summary',params={'event':args.event or DEFAULT_EVENT},timeout=30);response.raise_for_status();summary=response.json()
    made,excluded=available(summary)
    national.save(args.out/'topics.json',dict(available={k:round(estimate(v),1) for k,v in made.items()},excluded=excluded))
    if args.list:print(json.dumps(dict(available={k:round(estimate(v),1) for k,v in made.items()},excluded=excluded),ensure_ascii=False));return
    if not args.topic:ap.error('--topic または --list が必要です')
    if args.topic not in made:raise ValueError(excluded[args.topic])
    doc=made[args.topic];national.save(args.out/'narration.json',doc);national.save(args.out/'material.json',doc['topic_summary'])


if __name__=='__main__':main()
