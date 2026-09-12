"""公開記録の動画IDを優先し、題名だけで不明な動画を用語集に入れない。"""

KIND_ALIASES = {"morning_postseason": "postseason", "verdict": "weekly"}

# 記録が残っていない動画だけに使う。競技・番組が明示された題に限定する。
TITLE_RULES = [
    ("postseason", ("ポストシーズン",)),
    ("morning_voices", ("現地のファンは何と言ったか",)),
    ("longform", ("【海外の反応】", "公式コメント欄を読み解く",
                  "公式動画のコメントを読む")),
    ("morning_player", ("今日の1人",)),
    ("morning_press", ("現地メディアは何と言っている", "番記者の投稿と現地の見出し")),
    ("morning_local", ("現地で最も注目された試合", "現地での注目度",
                       "現地で最も見られた試合")),
    ("morning", ("勝利貢献スコア", "日本人選手の成績")),
    ("weekly", ("週間ダイジェスト", "1週間を振り返", "今週の注目試合",
                "答え合わせ")),
    ("daily_soccer", ("の注目試合【サッカー】", "注目試合｜サッカー",
                      "今夜の注目試合")),
    ("daily", ("の注目試合【MLB】", "明日の注目試合")),
]


def classify(title: str) -> str | None:
    for kind, needles in TITLE_RULES:
        if any(needle in title for needle in needles):
            return kind
    return None


def recorded_kinds(published: dict, assets: dict, supported) -> dict:
    """別の種類へ重複記録されたIDはNoneにして、自動判断を保留する。"""
    candidates = {}
    records = list(published.items())
    records.append(("asset", assets.get("assets", {})))
    for kind, entries in records:
        kind = KIND_ALIASES.get(kind, kind)
        if kind not in supported or not isinstance(entries, dict):
            continue
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            video_id = entry.get("video_id")
            if isinstance(video_id, str) and video_id:
                candidates.setdefault(video_id, set()).add(kind)
    return {video_id: next(iter(kinds)) if len(kinds) == 1 else None
            for video_id, kinds in candidates.items()}


def kind_for_video(video_id: str, title: str, recorded: dict) -> str | None:
    # タイトルの変更やA/Bテストで番組の種類が変わることはない。
    if video_id in recorded:
        return recorded[video_id]
    return classify(title)
