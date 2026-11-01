"""Opusの項目別掛け合いを、問いだけ・保存原稿/実音声の45秒上限で使う。"""
from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
import os
import re

ZUNDA, METAN = 3, 2
LIMIT = 45.0
ASK_BY_HEAD = (
    ('決勝点', '決めたのは、だれなのだ？'),
    ('先制で決勝', '決めたのは、だれなのだ？'),
    ('本塁打', 'ホームランは出たのだ？'),
    ('先発', '先発はどうだったのだ？'),
    ('勝ち投手', '最後はだれが投げたのだ？'),
    ('日本人選手', '日本人選手はどうだったのだ？'),
    ('返信', '返事もついてるのだ？'),
    ('見出し', '現地の記事はどうなのだ？'),
    ('コメント', 'ファンはなんて言ってるのだ？'),
)
QUESTIONS = {q for _, q in ASK_BY_HEAD} | {'ほかの声もあるのだ？'}


def enabled(kind, day=None):
    import review_render_v3 as r3
    modes = {s.strip() for s in os.environ.get('COLLESPO_DUO', 'off').split(',')}
    if r3.LOOK != 'v4' or kind not in modes:
        return False
    if kind == 'voices':
        try:
            value=str(day)
            calendar=(datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=9))).date()
                      if 'T' in value else date.fromisoformat(value[:10]))
            return calendar.day % 2 == 0
        except ValueError:
            return False
    return kind == 'game'


def ask_for(head):
    return next((q for key, q in ASK_BY_HEAD if key in head), '')


def zunda_ok(text):
    return (5 <= len(text) <= 15 and text in QUESTIONS and text.endswith('？')
            and not re.search(r'[0-9０-９〇一二三四五六七八九十百千万]', text))


def estimate(segments):
    # Conservative drafting target; the final gate measures every WAV, never changes voice settings.
    return sum(len(s['text']) / 7.5 + .4 for s in segments)


def _answer(seg, text, screen, **meta):
    out = deepcopy(seg)
    out.update(text=text, speaker=METAN)
    out['meta'] = dict(out.get('meta') or {}, duo=True, screen=screen, who='四国めたん', **meta)
    return out


def game(segments, spec, items):
    plan = []
    for si, seg in enumerate(segments):
        meta = seg.get('meta') or {}
        if seg['kind'] == 'list':
            start = meta['start']
            for index in range(start, start + meta['count']):
                head, body = items[index]
                if head == '試合の結果':
                    continue  # the intro already states the result; no duplicate reading
                text = (spec.get('speech') or {}).get(head) or body.rstrip('。') + '。'
                text = re.sub(r'^' + re.escape(head) + r'[。｜、\s]+', '', text)
                answer = _answer(seg, text, f'item:{index}', start=index, count=1, head=head)
                priority = 100 if '決勝' in head else 80 if head == '本塁打' else 60 if head == '先発' else 20
                plan.append((answer, ask_for(head), priority))
        elif seg['kind'] == 'people':
            rows = spec.get(meta.get('group', 'japanese')) or []
            for index, row in enumerate(rows[:3]):
                text = row['name'] + ('が' + row['line'] if row.get('line') else '') + '。'
                answer = _answer(seg, text, f'people:{si}:{index}', row=index)
                plan.append((answer, ask_for('日本人選手'), 95))
        else:
            plan.append((_answer(seg, seg['text'], f'original:{si}'), '', 0))
    return _build(plan)


def voices(segments):
    plan = []
    for si, seg in enumerate(segments):
        rows = (seg.get('meta') or {}).get('quote_rows') or []
        quotes = [r for r in rows if r.get('read') and not r.get('fact')]
        if quotes:
            parent=None
            for ri,row in enumerate(quotes):
                prior=[dict(parent,read=False)] if row.get('reply') and parent else []
                if not row.get('reply'):parent=row
                head='返信' if row.get('reply') else 'コメント'
                question=ask_for(head) if not si else 'ほかの声もあるのだ？'
                text=row['said'].strip().rstrip('。！!、.')+'。'
                answer=_answer(seg,text,f'voice:{si}',quote_rows=prior+[dict(row,read=True,clip=True)])
                if row.get('reply'):answer['kind']='thread'
                priority=60 if row.get('reply') else 90
                plan.append((answer,question,priority))
        else:
            plan.append((_answer(seg,seg['text'],f'voice:{si}'),'',0))
    return _build(plan)


def _build(plan):
    candidates = [i for i, (_, q, _) in enumerate(plan) if q]
    if len(candidates) < 3:
        raise ValueError('掛け合いには問いに答える材料が3項目必要です')
    chosen = set(sorted(candidates, key=lambda i: (-plan[i][2], i))[:4])

    def make():
        result = []
        for i, (answer, question, _) in enumerate(plan):
            if i in chosen:
                ask = deepcopy(answer)
                ask.update(text=question, speaker=ZUNDA)
                ask['meta'].update(duo_ask=True, who='ずんだもん')
                ask['meta']['answer_text']=answer['text']
                result.append(ask)
            result.append(answer)
        return result

    result = make()
    # Remove whole optional fact/quote screens, not fragments or numeric claims.
    while estimate(result) > 36:
        optional = [i for i, (s, _, _) in enumerate(plan)
                    if s['kind'] not in ('intro', 'outro', 'next_line') and
                    (i not in chosen or len(chosen) > 3)]
        if not optional:
            break
        i = min(optional, key=lambda n: (plan[n][2], -n))
        chosen = {n - (n > i) for n in chosen if n != i}
        plan.pop(i)
        result = make()
    problems = check(result)
    if problems:
        raise ValueError('掛け合い原稿: ' + str(problems))
    return result


def check(segments, durations=None):
    asks = [s for s in segments if s.get('speaker') == ZUNDA]
    errors = []
    if not 3 <= len(asks) <= 4:
        errors.append('問いは3〜4回')
    if any(not zunda_ok(s['text']) for s in asks):
        errors.append('問いの定型/字数/数字なし')
    if any(a.get('speaker') == b.get('speaker') == ZUNDA for a,b in zip(segments, segments[1:])):
        errors.append('問いが連続')
    if not segments or segments[-1].get('speaker') != METAN:
        errors.append('締めはめたん')
    if (sum(durations) if durations is not None else estimate(segments)) > LIMIT:
        errors.append('45秒を超える（声の設定は変えず原稿を短く）')
    for i,s in enumerate(segments[:-1]):
        if s.get('speaker') == ZUNDA and s['meta']['screen'] != segments[i+1]['meta']['screen']:
            errors.append('問いと答えの画面が違う')
    return errors


def durations(segments):
    return [max(.1, float(s.get('duration') or len(s.get('text',''))/7.5)) for s in segments]


def credit(segments):
    return '音声: VOICEVOX:四国めたん・ずんだもん' if any(s.get('speaker') == ZUNDA for s in segments) else '音声: VOICEVOX:四国めたん'
