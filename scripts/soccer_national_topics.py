"""終了済み代表戦の保存材料だけから、条件を満たす話題を組み立てる。"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
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
FOLLOWUPS = ROOT / 'data/soccer_national_followups.json'
PROGRAM = 'soccer_national_topic'
MLB_PROGRAM = 'mlb_market_topic'
MLB_LEDGER = ROOT / 'data/mlb_market_topics_published.json'
MLB_FOLLOWUPS = ROOT / 'data/mlb_market_followups.json'
MLB_TEAMS = {'sato-cubs': '112', 'taira-bluejays': '141'}
PROGRAMS = (PROGRAM, MLB_PROGRAM)
VIDEO = 'collespo_national_topic.mp4'
LIMIT = 45
# MLB の掛け合いは契約・成績・比べを並べる型なので上限90秒（11/25 本人「まかせます」）。
# 上限であって目安ではない。原稿は短い方がよい（短い回の方が見られた割合が高い：DECISIONS 参照）。
MLB_LIMIT = 90
OPENING_SECONDS = 3.0
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
        return ('試合の結果はどうなったのだ？',f'日本と{self.other}の試合は、日本が{a}対{b}で'+('勝ったわ。' if a>b else '敗れたわ。' if a<b else '引き分けたわ。'),
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
    panels=[('ボール支配率は、どうだったのだ？',f'ボール支配率は、日本が{ja}パーセント、{m.other}が{oa}パーセントだったわ。','ボール支配率',
             rows(0),compare(1)),
            ('シュートの数は、どうだったのだ？',f'シュートは、日本が{pairs[1][1]}本、{m.other}が{pairs[1][2]}本。枠内シュートは、日本が{pairs[2][1]}本、{m.other}が{pairs[2][2]}本だったわ。',
             'シュートと枠内シュート',rows(1,2),compare(3)),
            ('コーナーキックは、どうだったのだ？',f'コーナーキックは、日本が{pairs[3][1]}本、{m.other}が{pairs[3][2]}本だったわ。','コーナーキック',
             rows(3),compare(4))]
    # 解説：数字で下回っても勝てた理由を、枠内シュートと得点の比で言う（本人 11/15「解説的な視点」）。
    on_j,on_o=int(pairs[2][1]),int(pairs[2][2]);g,h=m.score
    if 0<on_j and 0<on_o and g<=on_j and h<=on_o and g*on_o>h*on_j:
        panels[-1]=('なぜ、シュートが少なくても勝てたのだ？',
            f'枠内に飛んだシュートのうち、日本は{on_j}本で{g}点、{m.other}は{on_o}本で{h}点だったわ。少ない好機を、日本が確実に決めた試合なのよ。',
            '枠内シュートと得点',[('日本',f'枠内{on_j}本で{g}点'),(m.other,f'枠内{on_o}本で{h}点')],
            dict(compare=dict(teams=['日本',m.other],rows=[list(r) for r in shown[:3]]+[['得点',f'{g}点',f'{h}点']])))
    # 題で結果を言うので、結果を先に言い、数字で上回られていたことへつなぐ（Argon 11/15）。
    opening=(f'{m.other}戦は、どうなったのだ？',f'日本が{m.score[0]}対{m.score[1]}で勝ったわ。ただ、試合の数字では{m.other}が上回っていたわ。',
             '試合結果',[('日本 対 '+m.other,f'{m.score[0]}-{m.score[1]}')])
    m.hook=dict(subject=f'シュート{pairs[1][1]}本で',big=str(g),unit='得点',note=f'{m.other}は{pairs[1][2]}本で{h}得点')
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
    gap=m.minute_number(decisive)-m.minute_number(sub)
    rows=[('決勝点は、誰が決めたのだ？',f'日本の決勝点を決めたのは、{name}よ。得点は{national.minute_words(minute)}だったわ。','決勝点',[(name,minute+'分')]),
          ('どのように出場したのだ？',f'{name}は先発ではなく、{national.minute_words(entry)}に{replaced}と交代で出場したわ。'+(f'出場してから{gap}分で決めた決勝点なのよ。' if gap>0 else ''),
           '途中出場',[(name,entry+'分'),('交代した選手',replaced)]+([('出場から得点まで',f'{gap}分')] if gap>0 else []))]
    confirmed=any('Goal confirmed following VAR Review' in c.get('text','') and
        (c.get('time',{}).get('displayValue')==decisive['clock']['displayValue']) and
        player['athlete']['displayName'] in c.get('text','') for c in m.raw.get('commentary',[]))
    if confirmed:rows.append(('得点の確認は、どうなったのだ？','この決勝点は、VARの確認を経て認められたわ。','得点の確認',[('VARの確認','得点を認定')]))
    m.hook=dict(subject=f'{name} 途中出場から',big=minute,unit='分',note='決勝点'+(f'（出場から{gap}分）' if gap>0 else ''))
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
    team=m.stat(m.oid,'totalShots');alone=n==m.score[1]
    rows=[(f'{m.other}の得点者は、誰なのだ？',f'{m.other}の{name}が{n}得点。得点した時間は{spoken}だったわ。'+(f'{m.other}の得点は、すべて{short}よ。' if alone else ''),
           '相手の得点者',[(name,f'{n}得点'),('得点の時間',minutes)]+([(f'{m.other}の得点',f'{n}点すべて')] if alone else [])),
          ('シュートは、何本だったのだ？',f'{name}のシュートは{shots}本。そのうち枠内シュートは{target}本だったわ。'+(f'チーム全体のシュート{team}本のうち、{shots}本を打っているわ。' if int(team)>int(shots) else ''),
           'シュートの数字',[('シュート',shots+'本'),('枠内シュート',target+'本')]+([('チームのシュート',team+'本')] if int(team)>int(shots) else []))]
    outside=all('outside the box' in e.get('text','') for e in goals)
    if outside:rows.append((f'{short}は、どこから決めたのだ？',f'{n}得点とも、ペナルティエリアの外からのシュートだったわ。','得点の位置',[('ペナルティエリアの外',f'{n}得点')]))
    assists=[m.who(e,1) for e in goals if 'Assisted by ' in e.get('text','') and len(e.get('participants',[]))>=2]
    if len(assists)==n and len(set(assists))==1:
        rows.append(('アシストしたのは、誰なのだ？',f'{n}点とも、{assists[0]}のアシストだったわ。','アシスト',[('全得点のアシスト',assists[0])]))
    m.hook=dict(subject=f'{m.other}の{short}',big=str(n),unit='得点',note=('すべてペナルティエリアの外から' if outside else f'{m.other}の得点はすべて{short}' if alone else ''))
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
    rows=[('日本のゴールキーパーは、どうだったのだ？',f'日本のゴールキーパー、{name}のセーブ数は{saves}だったわ。','守護神の数字',[(name,saves+'セーブ')]),
          ((f'{m.other}のシュートを、どれだけ止めたのだ？',f'{m.other}のシュートは{shots}本、枠内は{target}本。{name}はそのうち{saves}本を止め、決められたのは{m.score[1]}本だったわ。',
            '枠内シュートとセーブ',[('被シュート',shots+'本'),('被枠内シュート',target+'本'),('止めた数',f'{target}本中{saves}本')])
           if int(saves)+m.score[1]==int(target) else
           (f'{m.other}のシュートは、どうだったのだ？',f'{m.other}のシュートは{shots}本。そのうち枠内シュートは{target}本だったわ。日本が受けたシュートの数字なのよ。','日本の被シュート',[('被シュート',shots+'本'),('被枠内シュート',target+'本')])),
          (f'{m.other}のゴールキーパーは、どうだったのだ？',f'{m.other}のゴールキーパーのセーブ数は{other_saves}。{name}は{saves}セーブだったわ。','両チームのGK',[('日本',saves+'セーブ'),(m.other,other_saves+'セーブ')])]
    win=m.score[0]>m.score[1]
    m.hook=dict(subject=f'GK {name}',big=saves,unit='セーブ',note=f'枠内{target}本のうち{saves}本を止めた' if int(saves)+m.score[1]==int(target) else f'{m.other}のシュート{shots}本')
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
        said=f'{lead}{national.minute_words(minute)}、{assist}の'+(kind or 'アシスト')+f'から、{name}が'+(f'{foot}で' if foot else '')+'決めたわ。'
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
    said='その後、'+'。'.join(parts)+'。日本が勝ったわ。'
    rows.append(('試合は、そのあとどうなったのだ？',said,'全得点の流れ',flow))
    m.hook=dict(subject=f'{m.who(a)}と{m.who(b)}',big=str(gap),unit='分間で2得点',note=f'前半{m.minute(a)}分から')
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
    rows=[(f'{m.other}戦は、どうなったのだ？',f'日本が{m.score[0]}対{m.score[1]}で勝ったわ。ワールドカップで敗れた相手なのよ。','対戦の記録',[board(now,m.other)]),
          ('ワールドカップでは、どうだったのだ？',f"{day_words(lost)}のワールドカップの{stage}で、日本は{lost['gf']}対{lost['ga']}で敗れたわ。",
            '対戦の記録',[board(now,m.other),board(lost,m.other)])]
    won=next((r for r in before if r['result']=='win' and r['gf']>r['ga'] and r['date']<lost['date']),None)
    if won:rows.append(('その前の対戦は、どうだったのだ？',f"{won['date'][:4]}年{int(won['date'][5:7])}月の{won['competition']}では、日本が{won['gf']}対{won['ga']}で勝っているわ。",
            '対戦の記録',[board(now,m.other),board(lost,m.other),board(won,m.other)]))
    m.hook=dict(subject=f'W杯で敗れた{m.other}に',big=f'{m.score[0]}-{m.score[1]}',unit='で勝利',note=f"{day_words(lost)}のW杯{stage}は{lost['gf']}-{lost['ga']}で敗戦")
    return f'W杯で敗れた{m.other}に{m.score[0]}-{m.score[1]}で勝利',rows


def is_reactions(topic):
    """試合後の声の話題。'reactions' と、同じ試合の別の組 'reactions-<名前>'（例 相手国の報道）。"""
    return topic=='reactions' or str(topic).startswith('reactions-')


def reaction_material(event, topic='reactions'):
    event=(national.read(REACTIONS).get('events') or {}).get(str(event))
    if not event or topic=='reactions':return event
    return (event.get('sets') or {}).get(topic[len('reactions-'):])


def reaction_topics(event):
    event=(national.read(REACTIONS).get('events') or {}).get(str(event)) or {}
    return ['reactions-'+name for name in event.get('sets') or {}]


def is_followup(topic):
    """「そういえば〇〇はどこに？」の話題 'followup-<名前>'。本人 11/15。試合の材料ではなく確認済みの事実の組から作る。"""
    return str(topic).startswith('followup-')


def followup_material(event, topic):
    return ((national.read(FOLLOWUPS).get('events') or {}).get(str(event)) or {}).get(topic[len('followup-'):])


def followup_topics(event):
    return ['followup-'+name for name in (national.read(FOLLOWUPS).get('events') or {}).get(str(event)) or {}]


HOOK_KEYS=('score','result','subject','big','unit','note')


def followup(topic, event):
    """その後の話題。各段は2つ以上の出典（https）で確かめた事実だけ。冒頭の大きな字も材料から。"""
    return followup_panels(followup_material(event,topic))


def mlb_big_in_text(big, text):
    value, unit = str(big['value']), big['unit']
    if not re.fullmatch(r'\d+(?:\.\d+)?|\d+億\d+', value):
        return False
    quantity = value + unit.removesuffix('（約）').removesuffix('の後')
    if re.search(r'(?<![\d.億万])' + re.escape(quantity) + r'(?![\d.])', text):
        return True
    if unit == '万ドル' and '.' in value:
        dollars = Decimal(value) * 10000
        if dollars != dollars.to_integral_value():
            return False
        dollars = int(dollars)
        alternative = f'{dollars // 10000}万{dollars % 10000:04d}ドル'
        return re.search(r'(?<![\d.億万])' + alternative, text) is not None
    return False


def followup_panels(data, *, mlb=False):
    if not data or not data.get('checked_on') or not data.get('items'):raise Unavailable('その後の話題の確認済み材料がない')
    if set(data.get('hook') or {})!=set(HOOK_KEYS):raise Unavailable('その後の話題の冒頭の材料が足りない')
    rows=[]
    for f in data['items']:
        sources = [url for url in f.get('sources', []) if url.startswith('https://')]
        minimum = 1 if data.get('large_contract', {}).get('state') == '契約を発表' and not rows else 2
        if len(set(sources) if mlb else sources) < minimum:
            raise Unavailable('2つの出典で確かめていない事実がある: '+f.get('head',''))
        extra=dict(followup_sources=f['sources'])
        # 答えの画面の要の数字（Argon 11/15「どの数字が主役か分かりにくい」）。数字は本文と同じ材料から。
        if f.get('big'):
            big=f['big']
            if set(big)!={'label','value','unit'} or not (
                mlb_big_in_text(big, f['text']) if mlb
                else str(big['value']).isdigit() and str(big['value']) in f['text']
            ):
                raise Unavailable('要の数字が本文に無い: '+f.get('head',''))
            extra['big']=dict(big)
        rows.append((f['ask'],f['text'],f['head'],[tuple(r) for r in f['rows']]+[('出典',f['source_names'])],extra))
    return data['title'],rows,dict(data['hook'])


def topic_reaction(event, topic):
    """各話題の最後に足す反応（記事の発言）。本人 11/15「事実だけでなく反応・解説も」。"""
    if is_reactions(topic) or is_followup(topic):return None
    event=(national.read(REACTIONS).get('events') or {}).get(str(event)) or {}
    return (event.get('topic_reactions') or {}).get(topic)


def quote_groups(quotes):
    groups=[]
    for q in quotes:
        if not q.get('source_url','').startswith('https://') or not q.get('quote') or '「' in q['quote'] or '」' in q['quote']:
            raise Unavailable('発言の出典・中身が未確認: '+q.get('who',''))
        # 続けて同じ問いの発言は1つの問いにまとめる（毎回「〇〇は何と話したのだ？」で単調。Argon 11/15）。
        if groups and groups[-1][0]['ask']==q['ask']:groups[-1].append(q)
        else:groups.append([q])
    return groups


def quote_panel(qs):
    # 記事・見出しの文は「書き」、会見・取材の言葉は「話し」（書いた物を「話した」と言わない）。
    past={'話し':'話したわ。','書き':'書いたわ。','述べ':'述べたわ。','語り':'語ったわ。'}
    said=''.join(f"{q['lead']}は、「{q['quote']}」と"+((q.get('verb') or '話し')+'、' if i<len(qs)-1 else past[q.get('verb') or '話し']) for i,q in enumerate(qs))+''.join(f"{q['via']}の報道なのよ。" for q in qs if q.get('via'))
    # 新聞・分析記事は「の発言」でなく label（Argon 11/15「見出しの発言」は不自然）
    panel=[(q.get('label') or q['who']+'の発言','「'+q['quote']+'」') for q in qs]+[('出典','・'.join(dict.fromkeys(q['source'] for q in qs)))]
    return said,panel


def reactions(m, topic='reactions'):
    """試合後の声。記事の鍵括弧の中の言葉だけを、発言者と媒体つきで言う。"""
    data=reaction_material(m.raw['header']['id'],topic)
    if not data or not data.get('checked_on') or not data.get('quotes'):raise Unavailable('試合後の声の確認済み材料がない')
    groups=quote_groups(data['quotes'])
    rows=[]
    a,b=m.score
    for i,qs in enumerate(groups):
        said,panel=quote_panel(qs)
        if i==0:
            # 最初に何の試合の声かを出す（Argon 11/15：結果が画面に無い）。
            # 相手国の反応の組は相手の側から言う（「日本に2対3で敗れた試合の後」）。
            if topic=='reactions':said=f"{m.other}に{a}対{b}で"+('勝った' if a>b else '敗れた' if a<b else '引き分けた')+'試合の後、'+said
            else:said=f"日本に{b}対{a}で"+('勝った' if b>a else '敗れた' if b<a else '引き分けた')+'試合の後、'+said
            panel=[('試合結果',f'日本 {a}-{b} {m.other}')]+panel
        rows.append((qs[0]['ask'],said,qs[0]['head'],panel))
    for f in data.get('facts',[]):
        if len(f.get('sources',[]))<2:raise Unavailable('2つの出典で確かめていない事実がある')
        rows.append((f['ask'],f['text'],f['head'],[tuple(r) for r in f['rows']]+([('出典',f['source_names'])] if f.get('source_names') else [])))
    return data['title'],rows


TOPICS={'team-numbers':team_numbers,'late-winner':late_winner,'opponent-star':opponent_star,'keeper':keeper,'early-goals':early_goals,'rematch':rematch,'reactions':reactions}


def core_panel(segments):
    """冒頭と同じ大きな数字の答えを優先し、なければ最初の大きな数字を選ぶ。"""
    hook = segments[0]['meta'].get('hook')
    fallback = same_value = None
    for seg in segments:
        meta = seg['meta']
        big = meta.get('big')
        if seg['speaker'] != METAN or not big:
            continue
        if fallback is None:
            fallback = meta['panel']
        if hook and str(big['value']) == str(hook['big']):
            # 「2点」と「2本で2点」のように数字だけ同じ札があるので、単位まで合う札を先に選ぶ。
            if str(big.get('unit', '')) == str(hook.get('unit', '')):
                return meta['panel']
            if same_value is None:
                same_value = meta['panel']
    return fallback if same_value is None else same_value


def narration(summary, topic, *, names=None, meetings=None):
    raw=compact(summary);m=Material(raw,names,meetings)
    hook=None
    if is_reactions(topic):title,panels=reactions(m,topic)
    elif is_followup(topic):title,panels,hook=followup(topic,raw['header']['id'])
    else:title,panels=TOPICS[topic](m)
    added=topic_reaction(raw['header']['id'],topic)
    if added:
        if not added.get('checked_on') or not added.get('quotes'):raise Unavailable('話題の反応の確認済み材料がない')
        # 結果は題で言っているので、反応を足すときは最後の「試合結果」の段と入れ替える（45秒に収める）。
        if panels and panels[-1][2]=='試合結果':panels=list(panels)[:-1]
        for qs in quote_groups(added['quotes']):
            said,panel=quote_panel(qs)
            panels=list(panels)+[(qs[0]['ask'],said,qs[0]['head'],panel,dict(quote=True,reaction_urls=[q['source_url'] for q in qs]))]
    if not hook and getattr(m,'hook',None):
        hook=m.hook;a,b=m.score
        hook=dict(hook,result=('勝利' if a>b else '敗戦' if a<b else '引き分け'),score=f'日本 {a}-{b} {m.other}')
    doc=dict(program=PROGRAM,date_jst=m.today,
        title=title+' #Shorts',topic=topic,event_id=str(raw['header']['id']),
        topic_key=str(raw['header']['id'])+':'+topic,source_url='https://www.espn.com/soccer/match/_/gameId/'+str(raw['header']['id']),
        segments=dialogue_segments(topic,panels,hook),topic_summary=raw,duration_budget=dict(limit=LIMIT,grace=0),
        sanity_materials=[dict(source='ESPN 保存材料',sport='soccer',facts=raw)])
    if topic=='rematch':
        doc['previous_meetings']=[copy.deepcopy(r) for r in m.meetings if r['date']<m.today]
        doc['meeting_sources']=national.read(RESULTS)['sources']
    if added:
        doc['topic_reaction']=copy.deepcopy(added)
        doc['sanity_materials'].append(dict(source='話題の反応（確認済み）',sport='soccer',facts=doc['topic_reaction']))
    if is_followup(topic):
        doc['followup_material']=copy.deepcopy(followup_material(raw['header']['id'],topic))
        doc['sanity_materials'].append(dict(source='その後の事実（確認済み）',sport='soccer',facts=doc['followup_material']))
    if is_reactions(topic):
        doc['reaction_material']=copy.deepcopy(reaction_material(raw['header']['id'],topic))
        doc['sanity_materials'].append(dict(source='試合後の発言（確認済み）',sport='soccer',facts=doc['reaction_material']))
    return tone_gate(short_common.prepare(doc))


def tone_gate(doc):
    """めたんの語尾が1つでも「です・ます」系なら原稿を作らない（revise 後の最終確認）。"""
    import metan_tone
    bad=[f'{i}番目「{e}」' for i,e in metan_tone.check(doc['segments'])]
    if bad:raise ValueError('めたんの口調が決まりと違います: '+'、'.join(bad))
    return doc


def dialogue_segments(topic, panels, hook, *, ending=None):
    segments=[]
    for i,(question,answer,head,rows,*extra) in enumerate(panels):
        meta=dict(duo=True,topic=topic,panel=i,head=head,rows=rows,**(extra[0] if extra else {}))
        ask=dict(meta,duo_ask=True,who='ずんだもん')
        if i==0 and hook:ask['hook']=hook
        segments += [dict(kind='list',text=question,speaker=ZUNDA,meta=ask),
                     dict(kind='list',text=answer,speaker=METAN,meta=dict(meta,who='四国めたん'))]
    if ending:
        import topic_dialogue
        segments = topic_dialogue.ending_segments(segments, ending)
        topic_dialogue.require(segments)
    return segments


MARKET_TRANSITIONS = {
    '鈴木誠也との比べ': '同じカブスの鈴木誠也と比べると、年平均はどうなのだ？',
    '2026年の成績': '契約の話を聞くと、移籍前のプレーも気になるのだ。',
    'NPBから移った2人の1年目': 'メジャーに渡った打者の数字も見ておきたいのだ。',
    '守る位置': '移籍先では、どこを守る見込みなのだ？',
    '契約を途中でやめる権利': '総額に加えて、契約の途中にも注目なのだ。',
    '西武への譲渡金': '送り出した西武にも、譲渡金が入るのだ？',
    '岡本和真と同じ球団': '岡本和真もいるチームなのだ！',
}


def market_panels(data, key):
    import topic_dialogue
    _, facts, _ = followup_panels(data, mlb=True)
    panels = []
    for i, (ask, answer, head, rows, meta) in enumerate(facts):
        if i == 0:
            line = topic_dialogue.market_opening(data, key)
        else:
            line = MARKET_TRANSITIONS.get(head, ask)
        # 比較や成績の台詞には、直前のひと言を受ける短い言葉を置く。
        response = ('ええ', 'そうね', 'そうなの', 'ええ', 'そうね')[i % 5]
        if i == 1 and data.get('large_contract'):
            response = 'そうね'
        panels.append((line, topic_dialogue.receive(answer, response), head, rows, meta))
    return panels


def mlb_narration(topic):
    event = topic.removeprefix('followup-')
    if not is_followup(topic):
        raise Unavailable('MLB移籍の話題は followup-<名前> で指定してください')
    team_id = MLB_TEAMS.get(event)
    if team_id:
        data = national.read(MLB_FOLLOWUPS)['events'][event]
    else:
        import market_watch
        from notability_engine import MLB_TEAM_NAME_EN
        entries = national.read(market_watch.LARGE_CONTRACTS).get('events', {})
        if event not in entries:
            raise Unavailable('大型契約の段2材料がありません')
        entry = entries[event]
        data = market_watch.large_followup(entry)
        team_id = next((str(i) for i, name in MLB_TEAM_NAME_EN.items()
                        if name == entry['reports'][0]['team_en']), None)
    import topic_dialogue
    title, _, hook = followup_panels(data, mlb=True)
    panels = market_panels(data, topic)
    if hook['score'] not in data['readings'] or not mlb_big_in_text(
        dict(value=hook['big'], unit=hook['unit']), panels[0][1]
    ):
        raise Unavailable('冒頭の選手名の読みか要の数字が材料にありません')
    return tone_gate(short_common.prepare(dict(
        program=MLB_PROGRAM, date_jst=data['checked_on'], title=title+' #Shorts',
        topic=topic, event_id=event, topic_key=topic,
        segments=dialogue_segments(topic, panels, hook, ending=topic_dialogue.market_ending(data)),
        followup_material=data, team_id=team_id, screen_title='MLB',
        duration_budget=dict(limit=MLB_LIMIT,grace=0), baseball_average_voice=True,
        sanity_materials=[dict(source='MLB移籍報道（確認済み）',sport='mlb',facts=data)],
    )))


def estimate(doc):
    """原稿の文字数からの見積もり（実音声の測定ではない）。既存の掛け合いと同じ式。"""
    return sum(len(s['text'])/7.5+.4 if s['kind']!='outro' else short_common.OUTRO_SECONDS for s in doc['segments'])


def available(summary, names=None, meetings=None):
    made={};excluded={}
    for topic in list(TOPICS)+reaction_topics(summary['header']['id'])+followup_topics(summary['header']['id']):
        try:made[topic]=narration(summary,topic,names=names,meetings=meetings)
        except (Unavailable,KeyError,ValueError,TypeError,StopIteration) as e:excluded[topic]=str(e) or '必要な欄がない'
    return made,excluded


def check(doc):
    if doc.get('program') not in PROGRAMS:return []
    if 'news_material' in doc:
        try:
            import news_fast_topic
            sport = 'mlb' if doc['program'] == MLB_PROGRAM else 'soccer'
            expected = news_fast_topic.narration(sport, doc['topic'], doc['news_material'])
            if doc_as_json(expected) == doc_as_json(doc):
                return []
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        return ['ニュースの台本・数字・題が保存材料と一致しません']
    if doc['program']==MLB_PROGRAM:
        try:
            if doc_as_json(mlb_narration(doc['topic'])) == doc_as_json(doc):
                return []
        except (ValueError, KeyError, TypeError):
            pass
        return ['MLB移籍の原稿が確認済みの材料と一致しません']
    try:
        expected=narration(doc['topic_summary'],doc['topic'],meetings=doc.get('previous_meetings',[]))
        if doc_as_json(doc)!=doc_as_json(expected):return ['代表の話題の原稿・数字・題が保存材料と一致しません']
        for s in doc['segments']:
            if s['kind']=='outro':continue
            if s['speaker']==ZUNDA and (not s['text'].endswith('？') or re.search('[0-9０-９〇一二三四五六七八九十百千万]',s['text'])):
                return ['ずんだもんは数字なしの問いだけです']
    except (ValueError,KeyError,TypeError,StopIteration):return ['代表の話題の条件・名前・材料が不一致です']
    return []


def doc_as_json(doc):
    return json.loads(json.dumps(doc))


def speech_readings(doc):
    if check(doc):raise ValueError('話題の原稿が不一致')
    import name_reading_guard as guard
    readings={}
    text='\n'.join(s['text'] for s in doc['segments'])
    if 'news_material' in doc:
        readings.update({name: ('player', reading) for name, reading in doc['news_material']['readings'].items()
                         if name in text})
    for t in doc.get('topic_summary',{}).get('rosters',[]):
        for r in t['roster']:
            english=r['athlete']['displayName']
            if str(t['team']['id'])==national.JAPAN:
                p=national.official_squad_player(english)
                if p and p['name'] in text:readings[p['name']]=('player',p['reading'])
            elif english in opponent_names():
                p=opponent_names()[english]
                if p['name'] in text:readings[p['name']]=('player',p['reading'])
                if p.get('short') and p['short'] in text:readings[p['short']]=('player',p['short_reading'])
    if is_followup(doc['topic']):
        # 試合に出ていない選手の読みは材料に書く（例 塩貝健人＝シオガイケント、JFA の名簿の表記）。
        for name,reading in (doc['followup_material'].get('readings') or {}).items():
            if name in text:readings[name]=('player',reading)
    for name,(_,reading) in readings.items():
        existing=guard.player_data().get('readings',{}).get(name)
        if existing and existing!=reading:raise ValueError('既存の読みと不一致: '+name)
    return readings


def information(doc):
    if check(doc):raise ValueError('材料が不一致')
    answers=[(i,s) for i,s in enumerate(doc['segments']) if s['speaker']==METAN and s['kind']!='outro' and not s['meta'].get('dialogue_ending')]
    if 'news_material' in doc:
        return [dict(subject=s['meta']['head'], fact='ニュースで確認した事実', value=s['meta']['rows'],
                     source=' '.join(s['meta']['followup_sources']), segments=[i]) for i, s in answers]
    if doc.get('followup_material', {}).get('large_contract'):
        first, comparison = answers
        return [dict(subject=first[1]['meta']['head'], fact='報じられた契約', value=first[1]['meta']['rows'],
                     source=' '.join(first[1]['meta']['followup_sources']), segments=[first[0]])] + [
                dict(subject=name, fact='比較する契約', value=value,
                     source=' '.join(comparison[1]['meta']['followup_sources']), segments=[comparison[0]])
                for name, value in doc['followup_material']['items'][1]['comparison_rows']]
    if is_followup(doc['topic']):
        return [dict(subject=s['meta']['head'],fact='確認済みの事実（その後）',value=s['meta']['rows']+([('要の数字',s['meta']['big']['label']+' '+str(s['meta']['big']['value'])+s['meta']['big']['unit'])] if s['meta'].get('big') else []),source=' '.join(s['meta']['followup_sources']),segments=[i])
                for i,s in answers]
    if is_reactions(doc['topic']):
        r=doc['reaction_material'];sources=[q['source_url'] for q in r['quotes']]+[' '.join(f['sources']) for f in r.get('facts',[])]
        return [dict(subject=s['meta']['head'],fact='試合後の発言・試合の最後の出来事',value=s['meta']['rows'],source=src,segments=[i])
                for (i,s),src in zip(answers,sources)]
    return [dict(subject=s['meta']['head'],fact='記事の発言' if s['meta'].get('reaction_urls') else '当該試合の数字・経過',value=s['meta']['rows'],
                 source=' '.join(s['meta']['reaction_urls']) if s['meta'].get('reaction_urls') else doc['source_url'],segments=[i])
            for i,s in answers]


GLOSSARY={'枠内シュート':'枠内シュート：ゴールの枠の中に向かったシュート。','セーブ':'セーブ：GKが相手のシュートを防いだ記録。',
          'VAR':'VAR：映像による判定の確認。','コーナーキック':'コーナーキック：守る側が最後に触れたボールがゴールラインを出たときの攻撃側の再開。'}


def metadata(doc):
    if check(doc):raise ValueError('原稿が不一致')
    if 'news_material' in doc:
        return __import__('news_fast_topic').metadata(doc)
    said='\n'.join(s['text'] for s in doc['segments'] if s['speaker']==METAN and s['kind']!='outro')
    terms=[v for k,v in GLOSSARY.items() if k in said]
    source='出典: ESPN 試合ページ\n'+doc.get('source_url','')
    if doc['topic']=='rematch':
        source+='\n過去の対戦: 日本代表の試合の確認一覧\n'+'\n'.join(doc['meeting_sources'])
    if doc.get('topic_reaction'):
        source+='\n反応:\n'+'\n'.join(f"{q['who']}（{q['where']}）: {q['source']}\n{q['source_url']}" for q in doc['topic_reaction']['quotes'])
    if is_reactions(doc['topic']):
        r=doc['reaction_material']
        # 同じ発言を載せた別の記事（also）も説明欄に並べる（画面の出典は1行に収めるため主な媒体だけ）。
        source='出典:\n'+'\n'.join(f"{q['who']}（{q['where']}）: {q['source']}\n"+'\n'.join([q['source_url']]+q.get('also',[])) for q in r['quotes'])
        urls=list(dict.fromkeys(u for f in r.get('facts',[]) for u in f['sources']))
        if urls:source+='\n試合の最後の退場:\n'+'\n'.join(urls)
        source+='\n試合の結果: ESPN 試合ページ\n'+doc['source_url']
    if is_followup(doc['topic']):
        source='出典:\n'+'\n'.join(f"{f['head']}: {f['source_names']}\n"+'\n'.join(f['sources']) for f in doc['followup_material']['items'])
    tags=['サッカー','日本代表','コレスポ']
    hashtags='#サッカー日本代表 #Shorts'
    if doc['program']==MLB_PROGRAM:
        tags=['MLB','メジャーリーグ','移籍',doc['followup_material']['hook']['score']]
        hashtags=' '.join('#'+tag for tag in tags)+' #Shorts'
    return dict(snippet=dict(title=doc['title'],description=said+('\n\n'+'\n'.join(terms) if terms else '')+'\n\n'+source+
        '\n\n役に立ったら高評価・チャンネル登録をお願いします。\n音声: VOICEVOX:ずんだもん・四国めたん\n'+hashtags,tags=tags,categoryId='17',defaultLanguage='ja',defaultAudioLanguage='ja'))


def reservation(now, ledger):
    """当日12時/19時/21時の空き。過去の枠への即時投稿や翌日への自動送りをしない。"""
    local=now.astimezone(national.JST)
    for hour in (12,19,21):
        at=local.replace(hour=hour,minute=0,second=0,microsecond=0)
        if at>local+timedelta(minutes=5) and not any(r.get('publish_at')==at.isoformat() for r in ledger.values()):return at
    raise ValueError('当日の予約枠がありません。翌日に手で実行してください')


def validate_upload(args, now=None):
    doc=national.read(args.narration)
    kind=getattr(args,'kind',PROGRAM)
    mlb=kind==MLB_PROGRAM
    news = doc.get('news_material')
    material_key = 'news_material' if news else 'followup_material' if mlb else 'topic_summary'
    if doc.get('program')!=kind or check(doc) or doc[material_key]!=national.read(args.games):
        raise ValueError('原稿と材料が不一致')
    if mlb and args.sport!='mlb':raise ValueError('MLB移籍の公開には --sport mlb が必要です')
    flag='COLLESPO_MLB_MARKET_TOPIC_PUBLISH' if mlb else 'COLLESPO_NATIONAL_TOPIC_PUBLISH'
    if news:
        import news_fast_watch
        sport = 'mlb' if mlb else 'soccer'
        if args.sport != sport or not news_fast_watch.may_publish(sport, news, os.getenv(news_fast_watch.FLAG[sport], '')):
            raise ValueError('ニュースの公開は指定変数が true の場合だけです')
    elif os.getenv(flag) != 'true':
        raise ValueError('話題の公開は手動指定が必要です')
    if not mlb and not news:
        if doc['topic']=='rematch' and doc['previous_meetings']!=[r for r in meetings_for(Material(doc['topic_summary']).other) if r['date']<doc['date_jst']]:
            raise ValueError('過去の対戦が確認一覧と一致しません')
        if is_reactions(doc['topic']) and doc.get('reaction_material')!=reaction_material(doc['event_id'],doc['topic']):
            raise ValueError('試合後の声が確認済みの材料と一致しません')
        if doc.get('topic_reaction')!=topic_reaction(doc['event_id'],doc['topic']):
            raise ValueError('話題の反応が確認済みの材料と一致しません')
    ledger=national.read(MLB_LEDGER if mlb else LEDGER)
    # 誤りの回を hold_video で非公開にして作り直す時だけ、旧動画のIDを COLLESPO_TOPIC_REPLACES で渡せば通す（11/25 サトテル・平良の差し替えが止まった）。
    replaces=os.getenv('COLLESPO_TOPIC_REPLACES','').strip()
    if doc['topic_key'] in ledger and not (replaces and ledger[doc['topic_key']].get('video_id')==replaces):
        raise ValueError('同じ試合の同じ話題は予約・投稿済みです（差し替えは旧動画のIDを replaces に）')
    if not args.publish_at:raise ValueError('未来の予約時刻が必要です')
    at=national.instant(args.publish_at);now=now or datetime.now(timezone.utc)
    if at<=now:raise ValueError('未来の予約時刻が必要です')
    if mlb and news:
        import mlb_news_fast
        reason = mlb_news_fast.publication_block(news, doc['topic_key'], ledger, at)
        if reason:
            raise ValueError(reason)
    elif mlb:
        day = at.astimezone(national.JST).date()
        occupied = [key for key, row in ledger.items()
                    if key != doc['topic_key'] and row.get('publish_at')
                    and national.instant(row['publish_at']).astimezone(national.JST).date() == day]
        if len(occupied) >= 3:
            raise ValueError('MLB移籍のショートは日本時間で1日3本までです')
    import short_content
    report=short_content.validate_upload(args.video)
    limit=MLB_LIMIT if mlb else LIMIT
    if report['actual_seconds']>limit:raise ValueError(f'話題ショートは{limit}秒までです')
    # 無音の見本は公開させない。実音声の記録（voice_manifest）が要る。
    if not (Path(args.narration).parent/'audio/voice_manifest.json').exists() and not (Path(args.video).parent/'voice_manifest.json').exists():
        raise ValueError('実音声の記録がありません')


def record_published(doc, vid, publish_at):
    path=MLB_LEDGER if doc['program']==MLB_PROGRAM else LEDGER
    ledger=national.read(path)
    before=ledger.get(doc['topic_key'])
    ledger[doc['topic_key']]=dict(video_id=vid,
        publish_at=national.instant(publish_at).astimezone(national.JST).isoformat(),title=doc['title'])
    if before:ledger[doc['topic_key']]['replaced']=before.get('replaced',[])+[before.get('video_id')]
    if doc['program'] == MLB_PROGRAM and doc.get('news_material'):
        info = doc['news_material']['news']
        ledger[doc['topic_key']].update(news_player=info['name'], news_first_seen=info['first_seen'],
                                         news_official=info['official'], news_report_times=info['report_times'],
                                         news_reserved_at=datetime.now(national.JST).isoformat())
    national.save(path,ledger)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--summary',type=Path);ap.add_argument('--topic',help='話題（TOPICS の名前、reactions-<組>、followup-<名前>）');ap.add_argument('--list',action='store_true')
    ap.add_argument('--event',help='ESPN の event id（本番は実行時に summary を取る。既定 401916337）')
    ap.add_argument('--sport',choices=('soccer','mlb'),default='soccer')
    ap.add_argument('--out',type=Path)
    ap.add_argument('--news-material', type=Path)
    ap.add_argument('--reservation',action='store_true')
    args=ap.parse_args(argv)
    if args.news_material:
        if not args.out or not args.topic:
            ap.error('ニュースは --topic と --out が必要です')
        import news_fast_topic
        material = national.read(args.news_material)
        doc = news_fast_topic.narration(args.sport, args.topic, material)
        national.save(args.out/'narration.json', doc)
        national.save(args.out/'material.json', material)
        (args.out/'description.txt').write_text(metadata(doc)['snippet']['description'], encoding='utf-8')
        return
    if args.sport=='mlb':
        if not args.topic or args.summary or args.event or args.list or args.reservation:
            ap.error('MLB移籍は --topic followup-<名前> を指定してください')
        out=args.out or ROOT/'build/mlb_market_topics'
        doc=mlb_narration(args.topic)
        national.save(out/'narration.json',doc)
        national.save(out/'material.json',doc['followup_material'])
        return
    args.out=args.out or ROOT/'build/soccer_national_topics'
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
