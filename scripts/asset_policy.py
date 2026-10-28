"""資産動画の題材停止。生成器・公開済み分類は残し、再開時はこの集合を変更する。"""

# 本人決定 2026-10-26。成績が上がっても自動復帰させない。
PAUSED_KINDS = frozenset({"venue", "season_team", "team"})
PAUSE_NOTE = "球場・球団まとめは10/26の本人判断で新規制作を停止。本数の補充はしません。"


def paused(topic):
    topic = (topic or "").removeprefix("asset:")
    kind = ("season_team" if topic == "season_team" or topic.startswith("season_team_")
            else "venue" if topic == "mlb_venue" else topic.split("_")[0])
    return kind in PAUSED_KINDS


def topic_catalog():
    """監視用の材料一覧。描画・音声・投稿の依存を読み込まない。"""
    import ast
    from pathlib import Path
    import generated_topics
    source = Path(__file__).with_name('generate_asset_video.py')
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    definition = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'LIST_TOPICS' for t in n.targets))
    topics = ast.literal_eval(definition.value)
    # 手書き定義を優先する生成器と同じ合流順。
    return {**generated_topics.all_topics(), **topics}


if __name__ == "__main__":
    import sys
    # ワークフローの明示指定にも同じ選択条件を適用する。
    print(" ".join(t for arg in sys.argv[1:] for t in arg.split() if not paused(t)))
