"""v4の編集単位。概要は字幕だけ、コメントと返信は一つの画面。"""
import copy
import re
from itertools import permutations
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def quote_groups(segments):
    result=[];pending=''
    for seg in segments:
        if seg['kind']=='outro':
            if pending and result:result[-1]['text']+=pending;pending=''
            result.append(copy.deepcopy(seg));continue
        active=[v for v in seg.get('meta',{}).get('quote_rows',[]) if v.get('read') and not v.get('fact')]
        if not active:
            # 概要の音声は保持。既存の札の上で読むため、独立場面を作らない。
            if result:result[-1]['text']+=seg['text']
            else:pending+=seg['text']
            continue
        row=active[-1]
        if row.get('reply') and result and result[-1]['kind']!='outro':
            result[-1]['text']+=seg['text']
            result[-1]['meta']['quote_rows'].append(dict(row,clip=False))
        else:
            out=copy.deepcopy(seg);out['text']=pending+seg['text'];pending=''
            out['meta']['quote_rows']=[dict(row,clip=False)]
            result.append(out)
    if pending:
        # 引用が無い回でも情報の音声を捨てない（札は描かない）。
        out=copy.deepcopy(segments[0]);out['text']=pending
        out['meta']['quote_rows']=[dict(said=pending,fact=True,read=True,clip=True)]
        result.insert(0,out)
    if ''.join(s['text'] for s in result)!=''.join(s['text'] for s in segments):
        raise ValueError('v4のまとめで読み上げ順が変わりました')
    return result


class ClubMentions:
    """同じ球団の選手付き呼称は動画内で一度。単独の選手名・成績は変えない。"""
    def __init__(self, teams):
        self.seen=set();self.phrases={}
        for team in teams:
            name=team.get('name','');players=team.get('players') or []
            if name and players:
                self.phrases[name]=sorted({'・'.join(group)+'の'+name
                    for n in range(1,min(3,len(players))+1) for group in permutations(players[:3],n)},key=len,reverse=True)

    def text(self,value):
        value=str(value)
        alternatives={phrase:name for name,phrases in self.phrases.items() for phrase in phrases}
        if not alternatives:return value
        def replace(m):
            name=alternatives[m.group()]
            if name in self.seen:return name
            self.seen.add(name);return m.group()
        return re.sub('|'.join(re.escape(p) for p in sorted(alternatives,key=len,reverse=True)),replace,value)


def affiliations(texts):
    """材料に実際にある「選手の球団」だけを拾う。所属を推測しない。"""
    import notability_engine as ne
    players='|'.join(re.escape(p['name_jp']) for p in ne.JP_PLAYERS_MLB)
    clubs='|'.join(re.escape(n) for n in sorted(ne.MLB_TEAM_NAME_JP.values(),key=len,reverse=True))
    found={}
    pattern=re.compile(r'((?:'+players+r')(?:・(?:'+players+r')){0,2})の('+clubs+r')')
    for value in texts:
        for m in pattern.finditer(str(value)):
            group=found.setdefault(m[2],[])
            for name in m[1].split('・'):
                if name not in group:group.append(name)
    return [dict(name=name,players=players) for name,players in found.items()]


def asset_display(spec,intro_speech=''):
    """毎フレーム独立した派生材料。状態をフレーム間へ持ち越さない。"""
    values=[spec.get('hook',''),*(str(v) for v in (spec.get('v3') or {}).values()),
            *(body for _,body in spec.get('items',[])),*(spec.get('speech') or {}).values()]
    teams=affiliations(values)
    if not teams:return spec
    out=copy.deepcopy(spec);tracker=ClubMentions(teams);v=out.get('v3') or {}
    for key in ('who','sub','tag'):
        if key in v:v[key]=tracker.text(v[key])
    for chip in v.get('chips',[]):
        chip['label']=tracker.text(chip.get('label',''))
    out['items']=[(head,tracker.text(body)) for head,body in out.get('items',[])]
    for row in out.get('japanese') or []:
        if 'line' in row:row['line']=tracker.text(row['line'])
    spoken=ClubMentions(teams);spoken.text(intro_speech)
    original_speech=spec.get('speech') or {};out['speech']={}
    for head,body in spec.get('items',[]):
        clean=spoken.text(original_speech.get(head) or f'{head.replace("｜","、")}。{body}。')
        if head in original_speech:out['speech'][head]=clean
    return out
