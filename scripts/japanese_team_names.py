"""同じ球団の日本人選手を画面・音声で短く紹介する。題/説明は元の名簿を使う。"""

# 同姓でも入力の名前を落とさず、未知の名前を推測して切らない。
PROMINENCE = ('大谷翔平', '山本由伸', '佐々木朗希')


def surnames():
    return {'大谷翔平': '大谷', '山本由伸': '山本', '佐々木朗希': '佐々木',
            '鈴木誠也': '鈴木', '今永昇太': '今永', '菊池雄星': '菊池',
            '松井裕樹': '松井', 'ダルビッシュ有': 'ダルビッシュ', '吉田正尚': '吉田',
            '千賀滉大': '千賀', '藤浪晋太郎': '藤浪', '前田健太': '前田',
            '菅野智之': '菅野', '上沢直之': '上沢', '小笠原慎之介': '小笠原',
            '村上宗隆': '村上', '岡本和真': '岡本', '今井達也': '今井',
            'ヌートバー': 'ヌートバー', '西田陸浮': '西田'}


def team_names(players, team=''):
    """2人以上なら名字を読点で連結。1人はこれまでのフルネームを保つ。"""
    names = list(dict.fromkeys(p for p in players if p))
    order = {name: i for i, name in enumerate(PROMINENCE)}
    names.sort(key=lambda n: order.get(n, len(order)))
    text = '、'.join(surnames().get(n, n) for n in names) if len(names) >= 2 else ''.join(names)
    return (text + 'の' if text else '') + team if team else text
