"""ホームは構造データで一回だけ決定。提示順・matchup・文章から推測しない。"""
import functools
import json
import pathlib
import re


@functools.lru_cache(maxsize=1)
def alias_groups():
    root = pathlib.Path(__file__).resolve().parent.parent / 'data'
    groups = json.loads((root/'soccer_venue_aliases.json').read_text(encoding='utf-8'))['clubs']
    colors = json.loads((root/'club_colors.json').read_text(encoding='utf-8'))
    for league in colors['leagues'].values():
        for club in league['clubs']:
            groups.append([club[k] for k in ('team_en', 'name_jp', 'abbr') if club.get(k)])
    return groups


def aliases(name):
    names = {name} if name else set()
    # 既存クラブ表の正式名・日本語名・略称を同じ集合へ。順序はホームを決めない。
    changed = True
    while changed:
        changed = False
        for group in alias_groups():
            if any(x.casefold() in {n.casefold() for n in names} for x in group):
                before = len(names)
                names.update(group)
                changed = changed or len(names) != before
    return names


def roles(game):
    return {'home': game.get('home_team_name') or '',
            'away': game.get('away_team_name') or '',
            'neutral': bool(game.get('neutral_site') or game.get('neutralSite'))}


def instruction(game):
    sides = roles(game)
    if not sides['home'] or not sides['away']:
        return 'ホーム/アウェーは不明。迎える・訪れる・本拠地・敵地と書かないこと。\n\n'
    if sides['neutral']:
        return f"登録上のホームは{sides['home']}、アウェーは{sides['away']}。中立地なので本拠地・敵地・迎えると書かないこと。\n\n"
    return (f"ホーム（本拠地）は{sides['home']}、アウェー（訪問側）は{sides['away']}。"
            f"迎える・本拠地は{sides['home']}、敵地・訪れるは{sides['away']}にだけ使うこと。\n\n")


def check(text, game):
    sides = roles(game)
    # 新監督/新シーズンを迎えることは会場の主張ではない。
    club_names = {n for group in alias_groups() for n in group}
    club_pattern = r'(?<![A-Za-z])(?:'+'|'.join(re.escape(n) for n in sorted(club_names,key=len,reverse=True))+r')(?![A-Za-z])'
    venue_claim = bool(re.search(r'本拠地|敵地|ホーム(?:で|に|の|へ)',text or '')
                       or re.search(club_pattern+r'を(?:ホームに)?迎え(?!られ)',text or ''))
    if not sides['home'] or not sides['away']:
        return ['会場不明なのに会場表現を使用'] if venue_claim else []
    if sides['neutral']:
        return ['中立地なのに本拠地/敵地と表現'] if venue_claim else []
    def named(name):
        # OLなどが別の英単語の一部に一致しない。
        return r'(?<![A-Za-z])(?:'+'|'.join(re.escape(n) for n in sorted(aliases(name), key=len, reverse=True))+r')(?![A-Za-z])'
    home, away = named(sides['home']), named(sides['away'])
    errors = []
    for sentence in re.split(r'[。\n]', text or ''):
        # 相手が直前の主語になっている「ランスが敵地リヨンに…」も止める。
        home_claim = (re.search(r'ホームで|本拠地で',sentence)
                      or re.search(home+r'(?:を|と)[^。]{0,12}迎え(?!られ)',sentence))
        if home_claim:
            for claim in re.finditer(away+r'(?:が|は|のホームで|の本拠地で|、ホームで|、本拠地で)'
                                     r'(?P<between>[^。]{0,60}?)(?P<venue>迎え(?!られ)|ホームで|本拠地で)', sentence):
                # 「フロジノーネがナポリ本拠地で対戦」は訪問側の正しい説明。
                # 主語だけでホームを割り当てず、明記された所在地の持ち主を見る。
                at_home = (claim['venue'] != '迎え'
                           and re.search(home+r'(?:の)?$', claim['between']))
                if not at_home:
                    errors.append(f"アウェーの{sides['away']}をホームとして表現")
        if re.search(home+r'(?:が|は)[^。]{0,35}?敵地(?:の)?'+away+r'(?:を|と)[^。]{0,12}迎え(?!られ)', sentence):
            errors.append(f"ホームの{sides['home']}が敵地の相手を迎えると表現")
        if re.search(r'(?:両チーム|両クラブ|両強豪|両者)(?:が|は)[^。]{0,20}敵地で[^。]{0,8}(?:対戦|激突)', sentence):
            errors.append('双方が敵地で対戦すると表現')
        if re.search(home+r'(?:が|は|、)[^。]{0,60}?(?:敵地(?:で|へ|に)|訪れ)', sentence):
            errors.append(f"ホームの{sides['home']}を敵地側として表現")
        if re.search(r'(?:ホーム|本拠地)(?:の|で戦う|で対戦する)'+away, sentence):
            errors.append('アウェーを本拠地側と表現')
        if re.search(r'敵地(?:の)?'+home+r'(?:が|は)', sentence):
            errors.append('ホームを敵地側と表現')
    return list(dict.fromkeys(errors))
