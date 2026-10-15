"""長編のその試合の値を照合。今季成績/現在のPS情勢と混ぜない。通信不要。"""
import re
import unicodedata

NO_SCORE = re.compile(r'無得点|(?:得点|点)(?:に|には|は|も|が)?(?:結びつ(?:いて)?|つなが(?:って)?|繋が(?:って)?|して)?(?:い)?(?:ない|なかった|ゼロ|なし|0)|ホームを踏(?:んでいない|まなかった)')
POST = re.compile(r'試合(?:の)?(?:あと|後)|終了後|試合を終えて|現在|いま|今は|これで|となった|になった')
FUTURE = re.compile(r'次(?:の|は|戦)|これから')
PRE = re.compile(r'試合(?:の)?(?:前|開始)|開始前|始まる前|で始ま')
PAST_EVENT = re.compile(r'その試合|この試合|先制|押し出し|決着戦|最終戦|負けたら終わり|の試合|から始ま')


def material(m, mode):
    if mode == 'numbers':
        from press_names import SURNAME
        out=[]
        for p in m.get('players', []):
            row=p.get('_row') or p
            stats=(row.get('batting') or {}) if row.get('type') == 'two_way' else row
            stats = p.get('game_facts') or stats
            name=p.get('name') or row.get('name')
            out.append(dict({k:stats.get(k) for k in ('runs','hits','rbi')},name=name,
                            type='batter' if row.get('type') == 'two_way' else row.get('type'),
                            aliases=[SURNAME[name]] if name in SURNAME else []))
        early = []
        race = m.get('race') or {}
        if race.get('date') and race.get('date') == m.get('date'):
            for s in race.get('series') or []:
                played, need = s.get('played'), s.get('need')
                if (not s.get('over') and type(played) is int and type(need) is int
                        and 0 < played < need and len(s.get('teams') or []) == 2):
                    early.append({'name': s.get('round_jp'), 'played': played, 'need': need,
                                  'names': [n for team in s['teams']
                                            for n in [team.get('name'), *(team.get('players') or []),
                                                      *(SURNAME.get(p) for p in team.get('players') or [])] if n]})
        return {'players': out, 'early_series': early}
    result = m.get('top', {}).get('result') or {}
    return {'players': result.get('batting_facts') or [], 'series': result.get('series') or {},
            'teams': [result.get('home_jp'), result.get('away_jp')]}


def _aliases(row):
    return [n for n in [row.get('name'), row.get('name_en'), *(row.get('aliases') or [])] if n]


def early_series_errors(dialogue, evidence):
    """最短の決着試合数未満なら、既に終えた試合は敗退決定戦ではない。

    同日材料の明示されたシリーズだけ。将来の条件、否定、疑問は止めない。
    球団/人物の名前が書かれた一文だけ照合し、話題の主語を推測しない。
    """
    bad = []
    rows = evidence.get('early_series') or []
    for i, seg in enumerate(dialogue.get('segments') or [], 1):
        for sentence in (seg.get('text') or '').split('。'):
            if (re.search(r'明日|次(?:の|は|戦)|これから|ではな|じゃな|でな', sentence)
                    or sentence.rstrip().endswith(('?', '？'))):
                continue
            if not re.search(r'負け(?:たら|れば)(?:終わり|敗退)(?:の|となる|になる)?(?:試合|一戦)で', sentence):
                continue
            for series in rows:
                if any(name in sentence for name in series['names']):
                    bad.append(f'{i}行目: 終了した試合を敗退決定戦としていますが、'
                               f'{series["name"]}は{series["played"]}試合終了・決着は最短{series["need"]}試合です')
    return list(dict.fromkeys(bad))


def review(dialogue):
    evidence = dialogue.get('game_material') or {}
    # numbersの旧保存台本もrunsが存在する場合だけ参照する。未知を0にしない。
    if not evidence and dialogue.get('mode') == 'numbers':
        evidence = dialogue.get('material') or {}
    players = [p for p in evidence.get('players', []) if p.get('type') in ('batter','two-way','two_way')]
    series = evidence.get('series') or {}
    bad, warnings, omit, recent, active = early_series_errors(dialogue, evidence), [], set(), [], None
    panels = dialogue.get('panels') or {}
    timeline, pending_pairs = '', []
    for i, seg in enumerate(dialogue.get('segments') or [], 1):
        text = unicodedata.normalize('NFKC', seg.get('text') or '')
        # 季節/別試合の数字を、この試合の値と突き合わせない。
        current = []
        other_series_context = False
        for sentence in text.split('。'):
            other_round = any(n in sentence and n not in series.get('name','')
                              for n in ('ワイルドカード','地区シリーズ','リーグ優勝決定','ワールドシリーズ'))
            if other_round:
                other_series_context = True
            elif series.get('name') and series['name'] in sentence:
                other_series_context = False
            # 「LADはリーグ優勝決定シリーズへ。10月12日に第1戦」は同じ話題。
            # 句点で割った後半を、別カードの地区シリーズ第4戦と比べない。
            if other_series_context or re.search(r'今季|通算|昨季|昨年|前回|前の試合', sentence):
                warnings.append(f'{i}行目: 別の期間/シリーズの文は当該試合と照合しません')
            else:
                current.append(sentence)
        text = '。'.join(current)
        if not text.strip('。'):
            recent, timeline, pending_pairs = [], '', []
            continue
        if seg.get('panel') and seg['panel'] != active:
            recent, timeline, pending_pairs = [], '', []
        active = seg.get('panel') or active
        mentioned = [p for p in players if any(n in text for n in _aliases(p))]
        if mentioned:
            recent = mentioned
        elif active and (panels.get(active) or {}).get('name'):
            owner = panels[active]['name']
            recent = [p for p in players if owner in _aliases(p)]
        targets = mentioned or recent
        score_claim = re.sub(r'無得点(?:(?:では|とは|というわけでは)ない|(?:で|に)(?:終わら|抑えられ)(?:ない|なかった))', '', text)
        if NO_SCORE.search(score_claim) and not text.rstrip().endswith(('?', '？')):
            for p in targets:
                if (any(n and n in text for n in evidence.get('teams', []))
                        or re.search(r'チーム|相手|両軍|試合全体', text)):
                    warnings.append(f'{i}行目: 無得点の主語を特定できないため停止しません')
                elif p not in mentioned:
                    omit.add(i)
                    warnings.append(f'{i}行目: 無得点を打者へ接続する根拠が曖昧なのでその行だけ除外')
                elif p.get('runs') is None:
                    omit.add(i)
                    warnings.append(f"{i}行目: {p['name']}の得点が未取得なので断定行だけ除外")
                elif p.get('runs') != 0:
                    bad.append(f"{i}行目: {p['name']}を無得点としていますが、この試合の得点は{p['runs']}")
        for p in mentioned:
            # 名指しした打者自身の得点。別の打者へ飛ばない短い範囲だけを照合。
            for name in _aliases(p):
                # 他の打者への読点を越えて数字を割り当てない。
                for match in re.finditer(re.escape(name)+r'[^。、]{0,18}?(\d+)得点', text):
                    if p.get('runs') is None:
                        omit.add(i)
                        warnings.append(f"{i}行目: {p['name']}の得点が未取得なので断定行だけ除外")
                    elif int(match[1]) != p['runs']:
                        bad.append(f"{i}行目: {p['name']}の得点がこの試合の材料と不一致")
        if not series.get('game_number'):
            continue
        for sentence in re.split(r'[。\n]', text):
            if not sentence:
                continue
            future, post, pre = bool(FUTURE.search(sentence)), bool(POST.search(sentence)), bool(PRE.search(sentence))
            if future or post or pre:
                timeline = 'after' if (future or post) and not pre else 'before'
            for match in re.finditer(r'第([0-9]+)戦', sentence):
                prefix = sentence[max(0,match.start()-10):match.start()]
                next_game = bool(FUTURE.search(prefix))
                expected = series.get('next_game_number') if next_game else series['game_number']
                if expected is not None and int(match[1]) != expected:
                    bad.append(f'{i}行目: 第{match[1]}戦が試合の材料（第{expected}戦）と不一致')
            state = timeline or ('before' if PAST_EVENT.search(sentence) else '')
            # 見えている現在の情勢を過去のプレーへ接続したらbeforeで照合。
            if PAST_EVENT.search(sentence) and not (post or future):
                state = 'before'
            records = series.get(state+'_by_team') or {}
            if state == 'before' and pending_pairs and records:
                possible = {(r['wins'],r['losses']) for r in records.values()}
                if any(pair not in possible for pair in pending_pairs):
                    bad.append(f'{i}行目: 直前のシリーズ勝敗を試合前のプレーへ接続しています')
                pending_pairs = []
            for match in re.finditer(r'(\d+)勝(\d+)敗', sentence):
                pair = (int(match[1]), int(match[2]))
                if not state:
                    pending_pairs.append(pair)
                elif not records:
                    omit.add(i)
                    warnings.append(f'{i}行目: {state}のシリーズ勝敗が未取得なので断定行だけ除外')
                prefix = sentence[:match.start()]
                named = [n for n in records if n and n in prefix]
                if named:
                    name = max(named, key=lambda n:prefix.rfind(n))
                    expected = records[name]
                    # 「相手を2勝1敗で下す」の勝敗は主語側。ここでは判定しない。
                    after_name = prefix[prefix.rfind(name)+len(name):]
                    if re.match(r'(?:を|に|との|相手に)', after_name):
                        continue
                    possible = {(expected['wins'], expected['losses'])}
                else:
                    possible = {(r['wins'],r['losses']) for r in records.values()}
                if possible and pair not in possible:
                    bad.append(f'{i}行目: {match[0]}は{state}のシリーズ勝敗と不一致')
            decision_claim = re.sub(r'(?:決着戦|最終戦|負けたら終わり)(?:では|とは|で)ない', '', sentence)
            if not (post or future) and re.search(r'決着戦|最終戦|負けたら終わり', decision_claim):
                before = series.get('before_by_team') or {}
                named = [n for n in before if n and n in sentence]
                total = series.get('games_in_series') or 0
                if re.search(r'負けたら終わり', sentence) and len(named) == 1 and total:
                    eliminated_if_loss = before[named[0]]['losses'] == total//2
                else:
                    eliminated_if_loss = series.get('is_decider')
                if eliminated_if_loss is False:
                    bad.append(f'{i}行目: 第{series["game_number"]}戦を決着戦として語っています')
    return {'errors': list(dict.fromkeys(bad)), 'warnings': list(dict.fromkeys(warnings)), 'omit': sorted(omit)}


def check(dialogue):
    """停止できるのは、取得した値との確認済みの矛盾だけ。"""
    return review(dialogue)['errors']


def prepare(dialogue, log=print):
    """欠測からの断定だけ行を除外。疑いと確認済みの矛盾を分けて記録。"""
    import copy
    result = copy.deepcopy(dialogue)
    inspected = review(result)
    import backstage_guard
    for i,seg in enumerate(result.get('segments') or [],1):
        text=seg.get('text') or ''
        if backstage_guard.violations(text):
            inspected['omit'].append(i)
            inspected['warnings'].append(f'{i}行目: 楽屋表現の行だけ除外')
        elif result.get('mode') == 'numbers' and backstage_guard.violations(text,scope='numbers'):
            inspected['warnings'].append(f'{i}行目: 不明という表現だけでは制作事情/事実矛盾と決めず停止しません')
    for warning in inspected['warnings']:
        log('::warning::'+warning)
    if inspected['omit']:
        drop = set(inspected['omit'])
        result['segments'] = [s for i,s in enumerate(result.get('segments') or [],1) if i not in drop]
        if not any(s.get('kind') not in ('intro','outro') for s in result['segments']):
            evidence=result.get('game_material') or {}
            texts=[]
            for player in evidence.get('players') or []:
                if player.get('type') not in ('batter','two_way','two-way') or not player.get('name'):
                    continue
                for key,unit in (('hits','安打'),('runs','得点'),('rbi','打点')):
                    value=player.get(key)
                    if isinstance(value,int) and not isinstance(value,bool) and value >= 0:
                        texts.append(f"{player['name']}は{value}{unit}です。")
            series=evidence.get('series') or {}
            if series.get('game_number'):
                texts.append(f"この試合は{series.get('name') or ''}第{series['game_number']}戦でした。")
            if texts:
                safe=[{'kind':'line','text':t,'panel':None,'speaker':2,'meta':{'who':'めたん'}} for t in texts
                      if not backstage_guard.violations(t)]
                intro=[s for s in result['segments'] if s.get('kind')=='intro']
                outro=[s for s in result['segments'] if s.get('kind')=='outro']
                result['segments']=intro+safe+outro
                log('::warning::断定行の除外後は取得済みの試合の値だけで続行します')
    result['fact_review'] = inspected
    # 除外済みの文を理由に回全体を失わず、実際に出す原稿を再照合する。
    remaining=review(result)['errors']
    result['fact_review']['remaining_errors']=remaining
    return result, remaining
