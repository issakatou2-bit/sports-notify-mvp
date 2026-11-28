"""資産動画の題材停止。生成器・公開済み分類は残し、再開時はこの集合を変更する。"""

# 本人決定 2026-10-26。成績が上がっても自動復帰させない。
PAUSED_KINDS = frozenset({"venue", "season_team", "team"})
PAUSE_NOTE = "球場・球団まとめは10/26の本人判断で新規制作を停止。本数の補充はしません。"


# 11/28 本人「終わったシーズンの動画まだ上げてるの？」。オフに出した今季の数字の回のうち、
# 1試合だけの記録・連続記録・対戦相手・連勝は 54〜202 再生（11/3〜11/27、early_views）。
# 登板や本塁打とチームの勝敗・月の比べは 595〜1,021 再生。オフの間は伸びない型を選ばない。
OFFSEASON_SKIP_KINDS = frozenset({
    'season_best', 'season_streak', 'season_insight', 'season_vs', 'season_momentum', 'season_game'})


def offseason_now(now=None):
    """WS 決着後（公式の結果で確かめた時だけ True）。"""
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    import ps_offseason
    try:
        snapshot = json.loads(Path('data/postseason.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return ps_offseason.completed_before(snapshot, now or datetime.now(timezone.utc))


def offseason_skip(key):
    return season_kind(key) in OFFSEASON_SKIP_KINDS


def season_title(topic, meta, offseason=None):
    """オフに出す今季の数字の回は、題の頭に年を入れて振り返りだと分かるようにする。"""
    import re
    year = re.search(r'_(20\d\d)(?:_|$)', topic or '')
    if not (topic or '').startswith('season_') or not year or year.group(1) in meta['title']:
        return meta
    if not (offseason_now() if offseason is None else offseason):
        return meta
    title = meta['title']
    head = re.match(r'【([^】]+)】', title)
    title = (f'【{year.group(1)}年・{head.group(1)}】{title[head.end():]}' if head
             else f'【{year.group(1)}年】{title}')
    return {**meta, 'title': title}


def season_kind(key):
    """PS・RSに共通の型。同じ日に同じ型を重ねない。"""
    return '_'.join(key.split('_')[:2])


def merge_records(older, newer):
    """同じ鍵は一度だけ数え、片方にだけある予約日などを保持する。"""
    return {key: {**(older.get(key) or {}), **(newer.get(key) or {})}
            for key in older.keys() | newer.keys()}


def paused(topic):
    topic = (topic or "").removeprefix("asset:")
    if topic.startswith('offseason_'):
        import offseason_switches
        return not offseason_switches.enabled()
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


def selectable(topic, spec, names=None):
    """自動選定は題に日本人名がある、公式RS成績の材料に限定する。"""
    if topic.removeprefix('asset:').startswith('mlb_term_') or (spec or {}).get('manual_only'):
        return False
    if paused(topic):
        return False
    if topic.startswith('offseason_'):
        return True  # 別workflowの公式速報。本数は既存の専用枠。
    if not spec:
        return False
    if topic.startswith('season_insight_'):
        return bool(spec.get('jp') and spec.get('insight') and spec.get('game_type') == 'R'
                    and spec.get('source', '').startswith('MLB Stats API'))
    if names is None:
        import json
        from pathlib import Path
        saved = json.loads(Path('data/season_topics.json').read_text(encoding='utf-8'))
        names = {r['jp'] for r in saved.get('topics', []) if r.get('jp')}
    title = spec.get('title') or spec.get('label', '')
    if not any(name and name in title for name in names):
        return False
    source = spec.get('source', '')
    regular = spec.get('game_type') == 'R' or (spec.get('season_stock') and 'レギュラーシーズン' in source)
    if not regular or 'MLB Stats API' not in source:
        return False
    # 成績だけ。PS、順位表、球団の結末、Savantの評価を混ぜない。
    forbidden = ('ポストシーズン', 'Statcast', 'Savant', '球団の結末', '順位表')
    content = title + str(spec.get('heading', '')) + str(spec.get('items', []))
    return not any(word in content for word in (*forbidden, '球団まとめ'))


if __name__ == "__main__":
    import sys
    # ワークフローの明示指定にも同じ選択条件を適用する。
    print(" ".join(t for arg in sys.argv[1:] for t in arg.split() if not paused(t)))
