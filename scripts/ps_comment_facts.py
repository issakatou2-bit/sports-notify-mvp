"""PSコメントの得点主張を保存した当該試合と照合する。通信・AI判定なし。"""
import copy
import re
import unicodedata


def from_feed(feed):
    from ps_game_story import inning_score
    return inning_score(feed) or {}


def review(text, score):
    """確認済みの矛盾と、判定できない得点主張を分ける。"""
    text = unicodedata.normalize('NFKC', text or '')
    errors, unknown = [], False
    teams = [(side, score.get(side) or {}) for side in ('away', 'home')]
    totals = [t.get('total') for _, t in teams]
    scoring = bool(re.search(r'得点|点差|点を|点だけ|点返|点が入|大量|猛攻|ビッグイニング|満塁弾|満塁本塁打|[\d零〇一二三四五六七八九十百]+点|\d+対\d+', text))
    if not scoring:
        return errors, unknown
    # 否定・願望・別時点を、当該試合の肯定的な事実主張と誤認しない。
    # コメント候補では未解釈として外すが、確定矛盾とは扱わない。
    if re.search(r'ではな|じゃな|わけでは|してい?な|せず|できな|取れな|返せな|'
                 r'次(?:は|戦|の試合)|ほしい|欲しい|だったら|昨年|昨季|前の試合', text):
        return errors, True
    if any(not isinstance(n, int) for n in totals):
        return errors, True
    named = [(side, t) for side, t in teams if t.get('name') and t['name'] in text]
    covered = []
    if len(named) == 1:
        side, team = named[0]
        end = bool(re.search(r'最後|最終回|9回|九回', text))
        inning = re.search(r'(\d+)回', text)
        last = (score.get('innings') or [{}])[-1].get('num')
        target = int(inning[1]) if inning else (9 if '九回' in text else last if end else None)
        runs = team['total']
        if end and target is None:
            runs = None
        if target:
            row = next((r for r in score.get('innings') or [] if r.get('num') == target), {})
            runs = row.get(side)
        # 「大量」の厳密な閾値は定めず、0/1点との矛盾だけ確定する。
        if re.search(r'大量得点|大量点|ビッグイニング', text):
            if runs is not None and runs <= 1:
                errors.append(f"{team['name']}の得点は{runs}点で大量得点と矛盾")
            elif runs is None:
                unknown = True
        claims = list(re.finditer(r'(\d+)\s*(?:得点|点(?:だけ)?(?:を)?(?:返|取|奪|挙|あげ|入|獲得)|点を記録)', text))
        for match in claims:
            covered.append(match.span())
            if runs is None:
                unknown = True
            elif int(match[1]) > runs or (int(match[1]) != runs and re.search(r'だけ|のみ|合計|全得点', text)):
                errors.append(f"{team['name']}の得点主張{match[1]}点が材料{runs}点と矛盾")
            elif int(match[1]) < runs:
                # 途中の1得点を、球団の全得点と勝手に同一視しない。
                unknown = True
        if re.search(r'満塁弾|満塁本塁打', text) and runs is not None and runs < 4:
            errors.append(f"{team['name']}の得点が4点未満で満塁本塁打と矛盾")
        if not claims and not re.search(r'大量得点|大量点|ビッグイニング', text):
            unknown = True
    else:
        unknown = True
    # 最後の得点で縮めた差は、得点前・得点後を各回の経過から確認する。
    for match in re.finditer(r'(?:点差(?:が|は|を)?\s*(\d+)点|(\d+)点差)', text):
        covered.append(match.span())
        gap = int(match[1] or match[2])
        if re.search(r'最後|最終|終了|9回|九回', text):
            if gap != abs(totals[0] - totals[1]):
                errors.append(f'最後の点差{gap}点が最終スコアと矛盾')
            if re.search(r'縮ま|縮め', text) and len(named) == 1:
                side = named[0][0]
                rows = score.get('innings') or []
                if not rows or not isinstance(rows[-1].get(side), int):
                    unknown = True
                elif rows[-1][side] == 0:
                    errors.append('最終回に得点がなく点差を縮めた主張と矛盾')
        else:
            unknown = True
    for match in re.finditer(r'(\d+)対(\d+)', text):
        if len(named) != 2:
            unknown = True
            continue
        ordered = sorted(named, key=lambda x: text.index(x[1]['name']))
        if tuple(map(int, match.groups())) != tuple(t['total'] for _, t in ordered):
            errors.append('コメントの最終スコアが材料と矛盾')
    # 一つ照合できても、別の未解釈の点数を同時に通さない。
    if any(not any(start <= m.start() and m.end() <= end for start, end in covered)
           for m in re.finditer(r'\d+\s*(?:得点|点)', text)):
        unknown = True
    return list(dict.fromkeys(errors)), unknown


def acceptable(original, translated, score):
    errors, unknown = review(translated, score)
    if errors or unknown:
        return False
    # 得点を述べる原文が訳で消えた場合も使わない。皮肉を推測で補完しない。
    if re.search(r'\b(?:scored?|runs?|lead|deficit)\b', original or '', re.I):
        if not re.search(r'得点|点差|\d+点|\d+対\d+', translated or ''):
            return False
        # 単数 a/one run を「大量」「複数点」へ変えない。
        if re.search(r'\b(?:a|one|1)\s+(?:big\s+)?run\b', original or '', re.I):
            if re.search(r'大量|複数', translated or '') or any(
                    int(m[1]) != 1 for m in re.finditer(r'(\d+)点(?:を|だけ)?(?:返|取|奪|挙|入)', translated or '')):
                return False
    return True


def attach(document, topic):
    """使ったtopicだけを添付。再点検でも得点経過・先発・決勝点を失わない。"""
    import sanity_sources
    score = (topic.get('game_v4') or {}).get('score') or {}
    if not topic.get('game'):
        return document
    day = (topic.get('game_date') or '')[:10]
    # game_dateはUTC。試合日をJSTへ変換する。
    if topic.get('game_date'):
        from datetime import datetime
        from sanity_material import JST
        day = datetime.fromisoformat(topic['game_date'].replace('Z', '+00:00')).astimezone(JST).date().isoformat()
    game = dict(game_pk=topic.get('game_pk'), date_jst=day,
        home_team_name=(score.get('home') or {}).get('name'),
        away_team_name=(score.get('away') or {}).get('name'),
        final_score={s: (score.get(s) or {}).get('total') for s in ('away', 'home')},
        ps_score=copy.deepcopy(score), decisive=copy.deepcopy((topic.get('game_v4') or {}).get('decisive')),
        items=[list(row) for row in topic.get('items') or [] if row[0] in
               ('試合の結果', '先発', '決勝点', '先制で決勝の一打', '投手', '勝ち投手')])
    document['sanity_date_jst'] = day
    document['sanity_materials'] = sanity_sources.capture(document) + [dict(
        source='generation.ps_game_topic', source_url=f"https://statsapi.mlb.com/api/v1.1/game/{topic.get('game_pk')}/feed/live",
        date_jst=day, retrieved_at=topic.get('retrieved_at'), finished_at=topic.get('finished_at'), games=[game])]
    return document


def check(document, materials):
    errors = []
    for source in materials or []:
        for game in source.get('games') or []:
            score = game.get('ps_score')
            if not score:
                continue
            for i, segment in enumerate(document.get('segments') or [], 1):
                for sentence in re.split(r'[。！？\n]', segment.get('text') or ''):
                    found, _ = review(sentence, score)
                    errors.extend(f'行{i}: {e}' for e in found)
    return list(dict.fromkeys(errors))
