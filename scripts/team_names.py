"""翻訳後の球団名を共通の日本語表記へ揃える。選手名は扱わない。"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import MLB_TEAM_NAME_EN, MLB_TEAM_NAME_JP  # noqa: E402


def _aliases() -> dict[str, str]:
    names = {}
    for team_id, full_name in MLB_TEAM_NAME_EN.items():
        words = full_name.split()
        # Red Sox / White Sox / Blue Jays は2語で球団名になる。
        nickname = " ".join(words[-2:]) if words[-1] in ("Sox", "Jays") else words[-1]
        for alias in (full_name, nickname):
            names[alias.lower()] = MLB_TEAM_NAME_JP[team_id]
    return names


_NAMES = _aliases()
# 長い正式名を先に拾う。日本語の助詞との境界も拾い、英単語の一部は替えない。
_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(re.escape(name) for name in sorted(_NAMES, key=len, reverse=True))
    + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def team_names_jp(text: str) -> str:
    """正式名・球団の呼び名だけを置換し、既存の日本語はそのまま返す。"""
    return _PATTERN.sub(lambda match: _NAMES[match.group().lower()], text)
