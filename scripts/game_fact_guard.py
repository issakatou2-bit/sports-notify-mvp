"""長編のその試合の値を照合。今季成績/現在のPS情勢と混ぜない。通信不要。"""
import re
import unicodedata

NO_SCORE = re.compile(r'無得点|(?:得点|点)(?:に|には|は|も|が)?(?:結びつ(?:いて)?|つなが(?:って)?|繋が(?:って)?|して)?(?:い)?(?:ない|なかった|ゼロ|なし|0)|ホームを踏(?:んでいない|まなかった)')
POST = re.compile(r'試合(?:の)?(?:あと|後)|終了後|試合を終えて|現在|いま|今は|これで|となった|になった')
FUTURE = re.compile(r'次(?:の|は|戦)|これから|予定|迎える|控える')
PRE = re.compile(r'試合(?:の)?(?:前|開始)|開始前|始まる前|で始ま')
PAST_EVENT = re.compile(r'その試合|この試合|先制|押し出し|決着戦|最終戦|負けたら終わり|の試合|から始ま')


def material(m, mode):
    if mode == 'numbers':
        from press_names import SURNAME
        out=[]
        for p in m.get('players', []):
            row=p.get('_row') or p
            stats=(row.get('batting') or {}) if row.get('type') == 'two_way' else row
            name=p.get('name') or row.get('name')
            out.append(dict({k:stats.get(k) for k in ('runs','hits','rbi')},name=name,
                            type='batter' if row.get('type') == 'two_way' else row.get('type'),
                            aliases=[SURNAME[name]] if name in SURNAME else []))
        return {'players': out}
    result = m.get('top', {}).get('result') or {}
    return {'players': result.get('batting_facts') or [], 'series': result.get('series') or {},
            'teams': [result.get('home_jp'), result.get('away_jp')]}


def _aliases(row):
    return [n for n in [row.get('name'), row.get('name_en'), *(row.get('aliases') or [])] if n]


def check(dialogue):
    evidence = dialogue.get('game_material') or {}
    # numbersの旧保存台本もrunsが存在する場合だけ参照する。未知を0にしない。
    if not evidence and dialogue.get('mode') == 'numbers':
        evidence = dialogue.get('material') or {}
    players = [p for p in evidence.get('players', []) if p.get('type') in ('batter','two-way','two_way')]
    series = evidence.get('series') or {}
    bad, recent, active = [], [], None
    panels = dialogue.get('panels') or {}
    timeline, pending_pairs = '', []
    for i, seg in enumerate(dialogue.get('segments') or [], 1):
        text = unicodedata.normalize('NFKC', seg.get('text') or '')
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
        score_claim = re.sub(r'無得点(?:では|とは|というわけでは)ない', '', text)
        if NO_SCORE.search(score_claim) and not text.rstrip().endswith(('?', '？')):
            for p in targets:
                if p.get('runs') != 0:
                    value = '未取得' if p.get('runs') is None else str(p['runs'])
                    bad.append(f"{i}行目: {p['name']}を無得点としていますが、この試合の得点は{value}")
        for p in mentioned:
            # 名指しした打者自身の得点。別の打者へ飛ばない短い範囲だけを照合。
            for name in _aliases(p):
                for match in re.finditer(re.escape(name)+r'[^。]{0,18}?(\d+)得点', text):
                    if p.get('runs') is None or int(match[1]) != p['runs']:
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
                next_game = bool(FUTURE.search(prefix)) or future
                expected = series.get('next_game_number') if next_game else series['game_number']
                if expected is not None and int(match[1]) != expected:
                    bad.append(f'{i}行目: 第{match[1]}戦が試合の材料（第{expected}戦）と不一致')
            state = timeline or ('before' if PAST_EVENT.search(sentence) or active == 'score' else '')
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
                    bad.append(f'{i}行目: {state}のシリーズ勝敗が未取得なのに{match[0]}と断定')
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
            if not (post or future) and re.search(r'決着戦|最終戦|負けたら終わり', sentence):
                before = series.get('before_by_team') or {}
                named = [n for n in before if n and n in sentence]
                total = series.get('games_in_series') or 0
                if re.search(r'負けたら終わり', sentence) and len(named) == 1 and total:
                    eliminated_if_loss = before[named[0]]['losses'] == total//2
                else:
                    eliminated_if_loss = series.get('is_decider')
                if eliminated_if_loss is False:
                    bad.append(f'{i}行目: 第{series["game_number"]}戦を決着戦として語っています')
    return list(dict.fromkeys(bad))
