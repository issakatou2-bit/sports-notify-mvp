"""姓と頭文字が同じ名簿の別人を、短縮名だけで確定しない。通信なし。"""


def same_given_name(given, name_en):
    import notability_engine as ne
    parts = (name_en or '').split()
    if len(parts) < 2:
        return False
    actual = ne.normalize_club((given or '').rstrip('.'))
    wanted = ne.normalize_club(parts[0].rstrip('.'))
    if not actual or not wanted:
        return False
    if min(len(actual), len(wanted)) > 1:
        return actual == wanted
    if actual[0] != wanted[0]:
        return False
    # 当日の片側名簿には一方しかいなくても、既存の本人名簿全体で照合する。
    surname = ne.normalize_club(parts[-1])
    candidates = {ne.normalize_club(name_en)}
    for player in ne.JP_PLAYERS_SOCCER:
        name = (player.get('name_en') or '').split()
        if (len(name) > 1 and ne.normalize_club(name[-1]) == surname
                and ne.normalize_club(name[0]).startswith(wanted[0])):
            candidates.add(ne.normalize_club(player['name_en']))
    return len(candidates) == 1
