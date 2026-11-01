"""公開向けの定型文だけをWS終了後に切り替える。欠測時は原文を保つ。"""
import argparse
from pathlib import Path

import post_common


# 意味が時期と食い違う部分だけ。過去回の題・日付・試合記録には適用しない。
REPLACEMENTS = {
    'ポストシーズンへの距離': 'MLBのシーズン成績',
    '地区順位とワイルドカード争いを確かめる': '地区順位とワイルドカード順位を振り返る',
    'MLBの順位争いを見る': 'MLBのシーズン成績を見る',
    '先発は誰か。順位争いはどう動くか。': 'MLBのシーズン成績と、欧州サッカーの注目カード。',
    '注目試合の見どころを毎日更新。': '試合のある日に見どころを更新。',
    '日本人選手の活躍や注目試合を短い動画で。じっくり見たい日は、ずんだもんとめたんの解説も。':
        'シーズンの振り返りや欧州サッカーを短い動画で。これまでの解説もご覧いただけます。',
    '「今日の注目試合」を、なぜ注目なのかの理由つきで毎日19時にお届けします。先発投手や順位争い、選手の記録から、その一戦を見る理由が分かります。':
        '注目試合を、試合のある日に理由つきでお届けします。MLBのシーズン成績や選手の記録も振り返れます。',
    'なぜ注目なのかの理由つきで毎日19時にお届けします。': '試合のある日に、なぜ注目なのかの理由つきでお届けします。',
    '理由つきで毎日19時に。': '試合のある日に理由つきで。',
    '毎日決まった時刻に配信するサービスです。': '試合のある日に決まった時刻に配信するサービスです。',
    'MLB公式データで現在の順位を確認': 'MLB公式データでシーズンの順位を確認',
    '順位表（最新）': '順位表（シーズン成績）',
    'の最新順位表。': 'の順位表（シーズン成績）。',
    'ワイルドカード争い': 'ワイルドカード順位',
    '地区首位を除いた公式順位です。線は3位の区切りで、進出確定ではありません。':
        'レギュラーシーズンの地区首位を除いた公式順位です。線は3位の区切りです。',
    '背景色のある行は現在の地区首位。優勝確定を意味しません。':
        '背景色のある行はレギュラーシーズンの地区首位です。',
    '次の注目試合を読む': '過去の注目試合を読む',
    '現在地が分かったら、次の対戦へ。': 'シーズンの対戦と結果を振り返る。',
    'MLBの注目試合を毎日19時に｜コレスポの使い方': 'MLBの記録と注目試合｜コレスポの使い方',
    '毎日19時に届きます': '試合のある日に届きます',
    '毎日19時にお届けするサービスです。': '試合のある日に19時にお届けするサービスです。',
    '毎日19時の通知': '試合のある日19時の通知',
    '毎日午後七時に、その日の注目試合を': '試合のある日、午後七時に、その日の注目試合を',
    '毎日19時 更新': '試合のある日に更新',
    'MLBと欧州サッカーの注目試合を、理由つきで毎日': 'MLBの振り返りと欧州サッカーをお届け',
    'コレスポでは毎日、この観点から注目試合を選んでいます。': 'コレスポでは試合のある日に、この観点から注目試合を選んでいます。',
    '毎日15試合前後あるので、': 'レギュラーシーズン中は1日15試合前後あるので、',
    'ほぼ毎日どこかで試合が行われています': 'レギュラーシーズン中はほぼ毎日どこかで試合が行われています',
}


def replace_text(text):
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def seasonal(text, ps=None, today=None):
    return replace_text(text) if post_common.mlb_offseason(ps, today) else text


def guide(spec, ps=None, today=None):
    """紹介回だけのコピーを作る。材料・定義そのものは書き換えない。"""
    if not post_common.mlb_offseason(ps, today):
        return spec
    def walk(value):
        if isinstance(value, str):
            return replace_text(value)
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(walk(item) for item in value)
        return value
    return walk(spec)


def render_site(root, ps=None, today=None):
    """生成が済んだ公開用コピーだけを変更する。通常期はバイトも書き戻さない。"""
    if not post_common.mlb_offseason(ps, today):
        return []
    changed = []
    for name in ('index.html', 'terms.html', 'football-competitions.html', 'standings.html'):
        path = Path(root) / name
        if not path.exists():
            continue
        original = path.read_bytes()
        text = replace_text(original.decode('utf-8'))
        if name == 'standings.html':
            text = text.replace('href="./#today">過去の注目試合', 'href="archive/">過去の注目試合')
        result = text.encode('utf-8')
        if result != original:
            path.write_bytes(result)
            changed.append(name)
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', default='public')
    args = parser.parse_args()
    print('オフ文言の切替: ' + ', '.join(render_site(args.site)))
