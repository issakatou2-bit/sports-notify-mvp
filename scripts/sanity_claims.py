"""現在の名指しした所属・順位・勝点・シリーズ勝敗だけを三値照合する。"""
import re
import soccer_sanity_material as soccer


def _club_matches(claim, club):
    return claim in soccer.aliases(club)


def review(text, materials, why=None, context=None):
    if re.search(r'昨季|昨年|前季|ではない|ではなく|だった|でした|という説', text):
        return None
    values = dict(affiliation=[], rank=[], points=[], wins=[])
    full = context or text
    for source in materials or []:
        for series in source.get('series') or []:
            teams = series.get('teams') or []
            if len(teams) != 2:
                continue
            for team, other in (teams, teams[::-1]):
                name = team.get('name')
                if not name:
                    continue
                for sentence in text.split('。'):
                    # シリーズ名を明示した文だけ。個別試合の途中経過へ流用しない。
                    label = series.get('round_jp') or ''
                    if not label or not (label in sentence or (series.get('round') == 'W' and 'WS' in sentence)):
                        continue
                    for match in re.finditer(re.escape(name)+r'(?:が|は|、)?\s*(\d+)勝(\d+)敗', sentence):
                        expected = (team.get('wins'), other.get('wins'))
                        values['wins'].append(tuple(map(int, match.groups())) == expected
                                              if None not in expected else None)
        for comp in source.get('competitions') or []:
            rows = comp.get('jp') or []
            for row in rows:
                name, club = row.get('name'), row.get('club_jp')
                if not name or not club:
                    continue
                # 元の段落に対象の人物・クラブが一組だけある場合は部分引用も照合。
                aliases = soccer.aliases(club)
                mentioned = [r for r in rows if r.get('name') and r['name'] in full]
                if len(mentioned) == 1 and mentioned[0] != row:
                    continue
                own = name in text or any(a in text for a in aliases)
                if not own and not (len(mentioned) == 1 and mentioned[0] == row):
                    continue
                # 他の人物の順位を当てはめない。複数人の一段落は人物ごとに分ける。
                block = text
                if len(mentioned) > 1:
                    start = text.find(name)
                    if start < 0:
                        continue
                    ends = [text.find(r['name'], start+len(name)) for r in mentioned if r != row]
                    block = text[start:min([e for e in ends if e >= 0] or [len(text)])]
                elif name not in text:
                    starts = [text.find(a) for a in aliases if a in text]
                    if starts:
                        start = min(starts)
                        ends = [text.find(a, start+1) for r in rows if r != row
                                for a in soccer.aliases(r.get('club_jp') or '') if a]
                        block = text[start:min([e for e in ends if e >= 0] or [len(text)])]
                affiliation = re.search(re.escape(name)+r'(?:の|は)([^。、\n]+)',
                                        block if name in block else full)
                if affiliation:
                    claimed = re.sub(r'(?:所属(?:です|だ)?|の選手(?:です|だ)?|なのだ|なのです|よ|です|だ)$', '', affiliation[1]).strip()
                    if (_club_matches(claimed, club) or '所属' in affiliation[1]
                            or (name+'の' in affiliation[0]
                                and re.fullmatch(r'[ァ-ヴー・A-Za-z ]+', claimed)
                                and claimed not in ('チーム', 'クラブ', 'プレー'))):
                        values['affiliation'].append(_club_matches(claimed, club))
                ranks = list(re.finditer(r'(?<!\d)(\d+)位', block))
                for match in ranks if len(ranks) == 1 else []:
                    values['rank'].append(int(match[1]) == row.get('position') if row.get('position') is not None else None)
                total_block = re.sub(r'(?:まで|勝点差(?:は)?|勝ち点差(?:は)?)勝(?:ち)?点\d+', '', block)
                total_block = re.sub(r'差(?:が|は)?勝(?:ち)?点\d+|勝(?:ち)?点\d+差', '', total_block)
                for match in re.finditer(r'勝(?:ち)?点(\d+)', total_block):
                    values['points'].append(int(match[1]) == row.get('points') if row.get('points') is not None else None)
                for match in re.finditer(r'(チャンピオンズリーグ|CL|ヨーロッパリーグ|EL|降格)(?:圏内|圏)?(?:にいて、)?(?:。)?(?:圏内から)?(まで|から落ちるまで|落ちるまで)勝(?:ち)?点(\d+)', block):
                    label, direction, diff = match.groups()
                    label = {'チャンピオンズリーグ': 'CL', 'ヨーロッパリーグ': 'EL'}.get(label, label)
                    lines = [line for line in row.get('lines') or [] if (line.get('label') or '').startswith(label)]
                    values['points'].append(all(line.get('diff') == int(diff) and
                        line.get('side') == ('outside' if direction == 'まで' else 'inside') for line in lines) if lines else None)
                # 「圏内から落ちるまで」は直前のCL/ELを引き継ぐ。
                for match in re.finditer(r'(?<!から)(?:圏内から)?落ちるまで勝(?:ち)?点(\d+)', block):
                    labels = re.findall(r'チャンピオンズリーグ|CL|ヨーロッパリーグ|EL', block[:match.start()])
                    if labels:
                        label = {'チャンピオンズリーグ': 'CL', 'ヨーロッパリーグ': 'EL'}.get(labels[-1], labels[-1])
                        lines = [line for line in row.get('lines') or [] if (line.get('label') or '').startswith(label)]
                        values['points'].append(all(line.get('diff') == int(match[1]) and line.get('side') == 'inside'
                                                   for line in lines) if lines else None)
    if False in [v for group in values.values() for v in group]:
        return False
    targets = set()
    if why is not None:
        for pattern, target in ((r'所属|移籍|選手と.*クラブ|クラブ.*対応', 'affiliation'),
                                (r'順位|\d+位|首位', 'rank'),
                                (r'勝点|勝ち点|圏内|圏外', 'points'),
                                (r'勝敗|\d+勝|シリーズ|WS', 'wins')):
            if re.search(pattern, why):
                targets.add(target)
        if re.search(r'本塁打|安打|スコア|得点|日程|時刻|開催地', why):
            return None
    selected = [v for target in (targets or values) for v in values[target]]
    if targets and any(not values[t] for t in targets):
        return None
    return True if selected and all(v is True for v in selected) else None
