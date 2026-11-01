"""公開する題の表記。音声・画面・材料の球団名には適用しない。"""
import re

import club_display_names
import press_names

# NPB現行12球団の呼び名（https://npb.jp/teams/、2026-10-23確認）。
# MLBの一覧との積集合を試験し、対象の追加漏れを検出する。
NPB_NICKNAMES = frozenset((
    'タイガース', 'ベイスターズ', 'ジャイアンツ', 'ドラゴンズ', 'カープ', 'スワローズ',
    'ホークス', 'ファイターズ', 'バファローズ', 'ゴールデンイーグルス', 'ライオンズ', 'マリーンズ',
))
TEAM_CITIES = {'タイガース': 'デトロイト', 'ジャイアンツ': 'サンフランシスコ'}


def team_city_text(text: str) -> str:
    """単独の呼び名の初出だけ補足する。対戦カードと既存の街名は保つ。"""
    text = str(text or '')
    teams = '|'.join(map(re.escape, press_names.ne.MLB_TEAM_NAME_JP.values()))
    abbreviations = '|'.join(map(re.escape, press_names.ne.MLB_TEAM_ABBR.values()))
    # 相手側が街名付き、または英略称のカードでも表記を保つ。
    team = rf'(?:[ァ-ヶー・]+[・\s]*)?(?:{teams})|(?:{abbreviations})'
    team = rf'(?:{team})'
    # カードだけを除外する。同じ題の別の場所にある単独名は補足する。
    card = rf'{team}(?:\s*(?:vs\.?|対|×|/|－|–|—|-)\s*{team})+'
    protected = [m.span() for m in re.finditer(card, text, re.IGNORECASE)]
    for name, city in TEAM_CITIES.items():
        seen = False
        pattern = rf'{city}[・\s]*{name}|(?:阪神|読売)[・\s]*{name}|{name}'
        def replace(match):
            nonlocal seen
            if any(a <= match.start() < b for a, b in protected):
                return match.group()
            if match.group() != name:
                if match.group().startswith(city):
                    seen = True
                return match.group()
            if seen:
                return name
            seen = True
            return city + '・' + name
        # 置換でずれた位置を次の球団のカード判定へ持ち越さない。
        text = re.sub(pattern, replace, text)
        protected = [m.span() for m in re.finditer(card, text, re.IGNORECASE)]
    return text


def public_title(text: str, *, soccer: bool = False) -> str:
    """題の共通入口。街名追加後に既存の省略・100字制限を適用する。"""
    # 選手＋球団の既存の言い方は、街名を挟む前に整える。
    title = press_names.press_title(str(text or ''))
    title = title if soccer else team_city_text(title)
    title = press_names.press_title(title)
    title = club_display_names.display_text(title)
    return club_display_names.youtube_title(title) if soccer else title[:100]


def description_head(text: str) -> str:
    head, sep, rest = text.partition('\n')
    return team_city_text(head) + sep + rest
