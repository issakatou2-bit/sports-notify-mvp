"""Shared Japanese phrase wrapping/pages. Offline, fixed BudouX model.

BudouX parsing algorithm: Copyright 2021 Google LLC, Apache-2.0.
Adapted to text-only parsing; adds sports quantities and Japanese kinsoku.
See vendor/budoux-LICENSE.txt and vendor/budoux-NOTICE.txt.
"""
import functools
import json
import os
from pathlib import Path
import re

UNITS = r'被本塁打|被四球|被安打|本塁打|奪三振|自責点|アシスト|ホールド|イニング|セーブ|投球回|投球数|打数|打席|安打|三振|四球|死球|打点|得点|失点|勝点|試合|連勝|連敗|盗塁|打者|アウト|万人|時間|キロ|メートル|回|分|秒|時|月|日|年|歳|位|勝|敗|戦|人|球|本|点|番|対|号|円|万|億|%|％'
NUMBER = re.compile(r'(?:\d+(?:[.,:]\d+)*|\.\d+)(?:回\d+分の\d+|分の\d+|(?:'+UNITS+r'))?(?:\d+(?:[.,:]\d+)*(?:'+UNITS+r'))*')
WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
CONNECTOR = re.compile(r'[一-龥]+(?:によると|について|に対して|として|のため)')
NO_HEAD = '、。，．：:!?！？）」』】〉》ー％%'
NO_END = '（「『【〈《('


def enabled():
    return os.environ.get('COLLESPO_BUBBLE') in ('slant','glass') or os.environ.get('COLLESPO_CAPTION_BREAKS')=='bunsetsu'


@functools.lru_cache(maxsize=1)
def model():
    data = json.loads(Path(__file__).with_name('vendor').joinpath('budoux-ja.json').read_text(encoding='utf-8'))
    return data,-sum(sum(g.values()) for g in data.values())*.5


@functools.lru_cache(maxsize=4096)
def phrases(text):
    text = str(text)
    if not text:return ()
    data,base = model()
    blocked = set()
    for regex in (NUMBER,WORD,CONNECTOR):
        for m in regex.finditer(text):blocked.update(range(m.start()+1,m.end()))
    breaks = [0]
    features = [('UW1',-3,1),('UW2',-2,1),('UW3',-1,1),('UW4',0,1),('UW5',1,1),('UW6',2,1),
                ('BW1',-2,2),('BW2',-1,2),('BW3',0,2),('TW1',-3,3),('TW2',-2,3),('TW3',-1,3),('TW4',0,3)]
    for i in range(1,len(text)):
        if i in blocked or text[i] in NO_HEAD or text[i-1] in NO_END:continue
        score = base
        for key,offset,length in features:
            start = i+offset
            if start>=0 and start+length<=len(text):score += data.get(key,{}).get(text[start:start+length],0)
        if score>0 or text[i-1] in '。！？!?、\n　 ':breaks.append(i)
    breaks.append(len(text))
    return tuple(text[a:b] for a,b in zip(breaks,breaks[1:]))


def pages(text, limit=38, fits=None, *, splitter=phrases, min_clause=0):
    """Prefer full stop, then comma, then phrase; never discard or split an atom."""
    atoms = splitter(str(text));out=[];at=0
    if fits is None:fits=lambda value:len(value)<=limit
    while at<len(atoms):
        options=[];value=''
        for end in range(at,len(atoms)):
            value+=atoms[end]
            if not fits(value):break
            stripped=value.rstrip()
            priority=3 if stripped.endswith(tuple('。！？!?')) else 2 if stripped.endswith('、') and len(stripped)>=min_clause else 1
            options.append((priority,end+1,value))
        if not options:
            # Indivisible quantity/phrase. Drawing must shrink or explicitly fail.
            out.append(atoms[at]);at+=1;continue
        _,at,value=max(options,key=lambda item:(item[0],item[1]))
        out.append(value)
    return out


def wrap(text, measure, width, *, splitter=phrases):
    rows=[];cur=''
    for atom in splitter(str(text)):
        if '\n' in atom:
            for i,part in enumerate(atom.split('\n')):
                if i:
                    rows.append(cur);cur=''
                if part:
                    if measure(cur+part)>width and cur:rows.append(cur);cur=''
                    if measure(part)>width:raise ValueError('文節が幅に収まりません')
                    cur+=part
            continue
        if measure(cur+atom)>width and cur:rows.append(cur);cur=''
        if measure(atom)>width:raise ValueError('文節が幅に収まりません')
        cur+=atom
    if cur:rows.append(cur)
    return rows


def runs(text):
    out=[];at=0
    for m in re.finditer(r'\d+(?:[.,:]\d+)*|\.\d+',text):
        if m.start()>at:out.append((text[at:m.start()],False))
        out.append((m.group(),True));at=m.end()
    if at<len(text):out.append((text[at:],False))
    return out


def violations(text, chunks, *, splitter=phrases):
    normalized=text.replace('\n','')
    chunks=[s.replace('\n','') for s in chunks]
    if ''.join(chunks)!=normalized:return ['全文の欠落/重複']
    allowed=set();at=0
    for atom in splitter(text):at+=len(atom.replace('\n',''));allowed.add(at)
    at=0;errors=[]
    for chunk in chunks[:-1]:
        at+=len(chunk)
        if at not in allowed:errors.append('文節の途中: '+str(at))
        if any(m.start()<at<m.end() for m in NUMBER.finditer(normalized)):errors.append('数字/単位の途中: '+str(at))
    return errors
