"""斜めカット型の吹き出しの b と c を、回の種類で使い分ける表（Opus-33・作業280、10/14）。

本人（10/14）：「斜めカット型は b（クリーム地＋話し手の色の帯）と c（斜め×ガラス）を併用。
選べない、どっちもいい」。

- 数字・成績が中心の回は b、話題・反応の回は c。
- 変わるのは COLLESPO_BUBBLE=slant のときだけ（ほかの吹き出しのときは None を返し、何も変えない）。
- COLLESPO_SLANT_VARIANT を指定したときは、その型で全部そろえる（今までと同じ動き）。
- **入れ替えるときは、下の表 VARIANT_BY_EPISODE の "b" と "c" を書き換えるだけ。**
"""
from __future__ import annotations

import os
from contextvars import ContextVar

CURRENT_EPISODE = ContextVar('collespo_episode', default=None)


def set_episode(kind, morning_mode=None, sport='mlb', longform_mode=None):
    """描く側の回を渡す。環境変数やワークフローの設定は変更しない。"""
    CURRENT_EPISODE.set(episode_key(kind, morning_mode, sport, longform_mode))

# 回の種類 → 斜めカット型の種類（"b" または "c"）。ここ1か所だけ。
VARIANT_BY_EPISODE = {
    # --- 数字・成績が中心の回 → b（クリーム地＋話し手の色の帯）---
    "morning_players": "b",     # 17時の日本人選手の成績
    "ranking": "b",             # ランキング
    "morning_postseason": "b",  # 順位争い・進出争い（MLB）
    "soccer_race": "b",         # 順位争い（欧州サッカー）
    "soccer_result": "b",       # サッカーの結果
    "soccer_week": "b",         # 欧州の日本人選手の週末（結果）
    "daily": "b",               # 予告（今夜・明日の注目試合。MLB）
    "soccer_daily": "b",        # 予告（欧州サッカーの注目試合）
    "soccer_preview": "b",      # 予告（欧州サッカーの開幕ガイドなど）
    "ps_odds": "b",             # ポストシーズンの情勢
    "verdict": "b",             # 注目した試合、どうなった？（答え合わせ）
    "weekly": "b",              # 1週間のまとめ
    # --- 話題・反応の回 → c（斜め×ガラス）---
    "morning_voices": "c",      # コメント欄
    "reddit": "c",              # Reddit の反応
    "morning_press": "c",       # 現地の報道
    "morning_local": "c",       # 現地でいちばん名前が挙がったチーム（現地の話題）
    "morning_player": "c",      # 選手の話題（今日の1人）
    "jp_reaction": "c",         # 日本の反応
    "longform": "c",            # 長編（コメント欄・反応の長編）
    "longform_numbers": "c",    # 長編（数字の長編）。指示書どおり長編は c。b にしたいときはここを "b" に
}

# 表に無い回（新しい回など）のときの型。
DEFAULT_VARIANT = "b"

# mainの実際の制作器・kind名。仮名の表も互換性のため保持する。
VARIANT_BY_EPISODE.update(soccer_results='b',soccer_now='b',ps_preview='b',ps_situation='b',
                          reddit_reaction='c',japan_reacts='c',player_story='c',soccer_voices='c')

VARIANTS = ("b", "c")


def episode_key(kind: str, morning_mode: str | None = None, sport: str = "mlb",
                longform_mode: str | None = None) -> str:
    """upload_youtube などの引数（kind・morning_mode・sport・longform_mode）を、上の表の名前にする。"""
    kind = (kind or "").strip()
    if kind == "morning":
        if morning_mode in ('soccer_race','soccer_week'):
            return morning_mode
        return f"morning_{morning_mode or 'players'}"
    if kind == "daily" and sport == "soccer":
        return "soccer_daily"
    if kind == "longform" and longform_mode == "numbers":
        return "longform_numbers"
    return kind


def slant_variant(episode: str | None = None, env=None) -> str | None:
    """この回の斜めカット型（"b" か "c"）。斜めカット型でないときは None（何も変えない）。

    episode を渡さないときは、変数 COLLESPO_EPISODE（ワークフローでその回の名前を入れる）を見る。
    """
    env = os.environ if env is None else env
    if (env.get("COLLESPO_BUBBLE") or "").strip() != "slant":
        return None
    forced = (env.get("COLLESPO_SLANT_VARIANT") or "").strip()
    if forced:
        return forced                     # 指定があれば、全部その型（今までの動き）
    name = (episode if episode is not None else env.get("COLLESPO_EPISODE") or (CURRENT_EPISODE.get() if env is os.environ else None) or "").strip()
    return VARIANT_BY_EPISODE.get(name, DEFAULT_VARIANT)
