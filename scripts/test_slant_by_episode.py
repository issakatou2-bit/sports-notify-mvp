"""斜めカット型の b/c の使い分けと、題のクラブ名（Opus-33・作業280）の検査。

    python -m pytest scripts/test_slant_by_episode.py
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import slant_by_episode as sbe  # noqa: E402

SLANT = {"COLLESPO_BUBBLE": "slant"}

# 指示書（Opus-33）の分け方。数字・成績の回は b、話題・反応の回は c。
NUMBER_EPISODES = ["morning_players", "ranking", "morning_postseason", "soccer_race",
                   "soccer_result", "soccer_week", "daily", "soccer_daily",
                   "soccer_preview", "ps_odds"]
TOPIC_EPISODES = ["morning_voices", "reddit", "morning_press", "morning_local",
                  "morning_player", "jp_reaction", "longform", "longform_numbers"]


def test_table_has_only_b_and_c():
    assert set(sbe.VARIANT_BY_EPISODE.values()) <= set(sbe.VARIANTS)
    assert sbe.DEFAULT_VARIANT in sbe.VARIANTS


@pytest.mark.parametrize("episode", NUMBER_EPISODES)
def test_number_episodes_are_b(episode):
    assert sbe.slant_variant(episode, SLANT) == "b"


@pytest.mark.parametrize("episode", TOPIC_EPISODES)
def test_topic_episodes_are_c(episode):
    assert sbe.slant_variant(episode, SLANT) == "c"


def test_each_episode_follows_the_table():
    # 表を入れ替えたら、そのとおりに変わる（本人が入れ替えられる）。
    for episode, want in sbe.VARIANT_BY_EPISODE.items():
        assert sbe.slant_variant(episode, SLANT) == want
    old = sbe.VARIANT_BY_EPISODE["morning_voices"]
    try:
        sbe.VARIANT_BY_EPISODE["morning_voices"] = "b"
        assert sbe.slant_variant("morning_voices", SLANT) == "b"
    finally:
        sbe.VARIANT_BY_EPISODE["morning_voices"] = old


def test_not_slant_changes_nothing():
    # 本番（斜めカット型でない吹き出し）では何も返さない＝見た目は変わらない。
    assert sbe.slant_variant("morning_voices", {}) is None
    assert sbe.slant_variant("morning_players", {"COLLESPO_BUBBLE": "round"}) is None
    assert sbe.slant_variant("morning_players", {"COLLESPO_SLANT_VARIANT": "c"}) is None


@pytest.mark.parametrize("forced", ["b", "c", "a"])
def test_forced_variant_applies_to_every_episode(forced):
    env = dict(SLANT, COLLESPO_SLANT_VARIANT=forced)
    for episode in NUMBER_EPISODES + TOPIC_EPISODES + ["unknown"]:
        assert sbe.slant_variant(episode, env) == forced


def test_episode_from_env_and_unknown_default():
    assert sbe.slant_variant(None, dict(SLANT, COLLESPO_EPISODE="morning_press")) == "c"
    assert sbe.slant_variant(None, SLANT) == sbe.DEFAULT_VARIANT
    assert sbe.slant_variant("new_episode", SLANT) == sbe.DEFAULT_VARIANT


@pytest.mark.parametrize("args,want", [
    (("morning", "players"), "morning_players"),
    (("morning", "voices"), "morning_voices"),
    (("morning", "press"), "morning_press"),
    (("morning", None), "morning_players"),
    (("daily", None, "mlb"), "daily"),
    (("daily", None, "soccer"), "soccer_daily"),
    (("longform", None, "mlb", "voices"), "longform"),
    (("longform", None, "mlb", "numbers"), "longform_numbers"),
    (("soccer_race",), "soccer_race"),
])
def test_episode_key(args, want):
    assert sbe.episode_key(*args) == want


# ------------------------------------------------------------------ 題のクラブ名

OLD_NAMES = ["マンチェスター・シティ", "アストン・ヴィラ"]


@pytest.fixture
def display_table():
    """表示名の表（data/club_display_names.json）の代わり。写しには本物の表が無いため。"""
    import notability_engine as ne
    if not hasattr(ne, "club_display_text"):
        pytest.skip("Opus-32（作業279）の club_display_text がまだ入っていない版")
    # mainにある表をそのまま使う。読み込みの場所は増やさない。
    from scripts import club_display_names as names
    assert names.display('Paris Saint-Germain FC')=='パリ・サンジェルマン'
    return ne


def _soccer_games(tmp_path):
    game = {"home_team_name": "マンチェスター・シティ", "away_team_name": "パリ・サンジェルマン",
            "start_time_jst": "2026-10-15 04:00", "is_notable": True, "league": "CL"}
    path = tmp_path / "soccer_games.json"
    path.write_text(json.dumps({"games": [game]}, ensure_ascii=False), encoding="utf-8")
    return path


def test_title_uses_display_names(display_table, tmp_path):
    import upload_youtube as uy
    body = uy.build_metadata(str(_soccer_games(tmp_path)), "10/15", "daily",
                             narration_path=str(tmp_path / "none.json"),
                             archive_dir=str(tmp_path), sport="soccer")
    title = body["snippet"]["title"]
    assert "マンチェスターC" in title and "パリ・サンジェルマン" in title, title
    for old in OLD_NAMES:
        assert old not in title, title
    assert len(title) <= 100


def test_title_helper(display_table):
    import upload_youtube as uy
    t = "【欧州サッカー】マンチェスター・シティ vs パリ・サンジェルマン｜アストン・ヴィラも #Shorts"
    fixed = uy.club_display_title(t)
    assert fixed == "【欧州サッカー】マンチェスターC vs パリ・サンジェルマン｜アストンヴィラも #Shorts"
    assert uy.club_display_title(fixed) == fixed           # 2回通しても同じ
    assert uy.club_display_title("【MLB】大谷翔平｜10/14") == "【MLB】大谷翔平｜10/14"


def test_asset_title_goes_through_display(display_table, monkeypatch):
    import upload_youtube as uy
    meta = {"title": "【サッカー】アストン・ヴィラの本拠地 #Shorts", "lead": ["説明"], "tags": []}
    monkeypatch.setitem(uy.ASSET_META, "test_villa", meta)
    body = uy.build_asset_metadata("test_villa")
    assert body["snippet"]["title"] == "【サッカー】アストンヴィラの本拠地 #Shorts"


@pytest.mark.parametrize('episode,variant',[('morning_players','band'),('morning_voices','glass'),
    ('reddit_reaction','glass'),('japan_reacts','glass'),('player_story','glass'),
    ('soccer_results','band'),('soccer_voices','glass'),('ps_preview','band'),('longform','glass')])
def test_actual_bubble_receives_episode(episode,variant,monkeypatch):
    from PIL import Image
    import bubble_styles as bubbles
    monkeypatch.setenv('COLLESPO_BUBBLE','slant')
    monkeypatch.delenv('COLLESPO_SLANT_VARIANT',raising=False)
    monkeypatch.delenv('COLLESPO_EPISODE',raising=False)
    token=sbe.CURRENT_EPISODE.set(episode)
    try:
        im=Image.new('RGB',(1080,1920),(20,40,35))
        bubbles.draw(im,'metan','3安打を記録。')
        assert im.info['bubble_style']['variant']==variant
    finally:sbe.CURRENT_EPISODE.reset(token)


def test_single_tuning_table_and_fixed_camera():
    import calm_motion
    import motion
    assert motion.SETTINGS is calm_motion.TUNING


if __name__=='__main__':
    raise SystemExit(pytest.main([__file__,'-q']))
