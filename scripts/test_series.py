"""series.py の検査（題名の長さ・選手の判定）。python3 -m pytest -q scripts/test_series.py"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import series as s  # noqa: E402

ROSTER = ["大谷翔平", "山本由伸", "佐々木朗希", "村上宗隆", "松井裕樹", "鈴木誠也", "ヌートバー"]


def test_main_players_head_only():
    t = "【10/5更新】村上宗隆が所属するホワイトソックス対ガーディアンズの地区シリーズ第2戦｜10/6 PS全2試合 #Shorts"
    assert s.main_players(t, "morning_postseason", ROSTER) == ["村上宗隆"]
    # 19:00 予告（あすの試合）と 18:00 報道はシリーズに入れない
    assert s.main_players(t, "daily", ROSTER) == []
    assert s.main_players("【MLB】大谷翔平、…と現地紙｜報道 #Shorts", "morning_press", ROSTER) == []
    # 後ろの区切りにだけ出る名前は主役にしない
    t2 = "【MLB】ドジャース vs ブレーブス 現地のファンは何と言ったか｜大谷翔平の打席 #Shorts"
    assert s.main_players(t2, "morning_voices", ROSTER) == []


def test_ranking_and_many_names_have_no_main():
    t = "【MLB】松井裕樹・佐々木朗希・大谷翔平｜10月5日 日本人選手 勝利貢献スコア ランキング #Shorts"
    assert s.main_players(t, "morning", ROSTER) == []
    t3 = "【MLB】松井裕樹・佐々木朗希・大谷翔平の今日｜成績"
    assert s.main_players(t3, "longform", ROSTER) == []
    t2 = "【MLB】村上宗隆・松井裕樹の今日｜成績とポストシーズン"
    assert s.main_players(t2, "longform", ROSTER) == ["村上宗隆", "松井裕樹"]


def test_soccer_is_out_of_scope():
    t = "【欧州サッカー】遠藤航 リバプールの試合｜今夜の注目試合 #Shorts"
    assert s.main_players(t, "daily_soccer", ROSTER + ["遠藤航"]) == []


def test_series_title_keeps_search_words():
    t = "【10/5更新】村上宗隆が所属するホワイトソックス対ガーディアンズの地区シリーズ第2戦｜10/6 PS全2試合 #Shorts"
    new = s.series_title(t, ["村上宗隆"], "daily")
    assert new.startswith("【MLB】村上宗隆の今日｜")
    assert "ホワイトソックス" in new and "地区シリーズ" in new and "PS" in new
    assert new.endswith(" #Shorts") and "10/5更新" in new
    assert new.count("村上宗隆") == 1


def test_series_title_not_doubled_for_longform():
    t = "【MLB】村上宗隆・松井裕樹の今日｜成績とポストシーズン"
    assert s.series_title(t, ["村上宗隆", "松井裕樹"], "longform") == t


def test_evergreen_and_no_main_unchanged():
    t = "【MLB】大谷翔平｜通算成績・今季・受賞歴まとめ #Shorts"
    assert s.series_title(t, ["大谷翔平"], "morning_player") == t
    assert s.series_title("ほかの題", [], "daily") == "ほかの題"


def test_series_title_max_100():
    long = ("【MLB】現地はこう報じた「" + "大谷翔平が" + "とても長い見出し" * 12
            + "」｜10月3日 番記者の投稿と現地の見出し｜地区シリーズ #Shorts")
    new = s.series_title(long, ["大谷翔平"], "morning_press")
    assert len(new) <= 100
    assert new.startswith("【MLB】大谷翔平の今日｜") and new.endswith(" #Shorts")
    assert "地区シリーズ" in new  # 検索に効く区切りは残る


def test_description_head():
    store = {"大谷翔平": {"id": "PLabc"}}
    slugs = {"村上宗隆": "munetaka-murakami"}
    lines = s.description_head(["大谷翔平", "村上宗隆", "だれか"], store, slugs)
    assert lines[0] == "▶ 大谷翔平の回の一覧：https://www.youtube.com/playlist?list=PLabc"
    assert lines[1].endswith("players/munetaka-murakami.html")
    assert lines[-1] == ""
    assert s.description_head(["だれか"], {}, {}) == []


def test_assign_sorted_and_real_titles_fit():
    data = pathlib.Path(__file__).resolve().parent.parent / "src" / "data" / "published_videos.json"
    if not data.exists():
        return
    videos = json.loads(data.read_text(encoding="utf-8"))
    roster = s.load_roster()
    assigned = s.assign(videos, roster)
    assert assigned  # 主役の決まる回がある
    for items in assigned.values():
        keys = [it["published_at"] or it["day"] for it in items]
        assert keys == sorted(keys)
        for it in items:
            names = s.main_players(it["title"], it["kind"], roster)
            assert len(s.series_title(it["title"], names, it["kind"])) <= 100


def test_upload_metadata_uses_series_only_when_switched_on(monkeypatch):
    """SERIES_TITLE=1 のときだけ、アップロードの題と説明欄がシリーズの形になる。"""
    from unittest.mock import patch
    import upload_youtube as upload
    args = ("no-such-file.json", "10/4", "longform")
    kw = dict(longform_mode="numbers", jp_names=["村上宗隆"], longform_subject="村上宗隆 アダム・ダン率58.4%")
    with patch.object(upload, "_postseason_data", return_value={"phase": "postseason"}):
        monkeypatch.delenv("SERIES_TITLE", raising=False)
        off = upload.build_metadata(*args, **kw)["snippet"]
        monkeypatch.setenv("SERIES_TITLE", "1")
        on = upload.build_metadata(*args, **kw)["snippet"]
    assert "村上宗隆" in on["title"] and len(on["title"]) <= 100
    if s.main_players(off["title"], "longform", s.load_roster()) == ["村上宗隆"]:
        assert on["title"].startswith("【MLB】村上宗隆の今日｜"), on["title"]
        assert "村上宗隆の" in on["description"].splitlines()[1]
