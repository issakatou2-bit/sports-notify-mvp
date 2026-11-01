"""weekly_report.py の検査（固定の小さな材料 fixtures/data で）。

  python3 -m pytest -q collespo/weekly_report/test_weekly_report.py
"""
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import weekly_report as wr  # noqa: E402

DATA = HERE / "fixtures" / "weekly-report" / "data"


def _load():
    raw = wr.snapshots(wr.load(DATA / "analytics.json"))
    items = wr.published_items(wr.load(DATA / "published_videos.json"),
                               wr.load(DATA / "published_assets.json"))
    return raw, items


def test_types_and_private_assets():
    _, items = _load()
    types = {i["id"]: i["type"] for i in items}
    assert types == {"A1": "17:00 成績", "A2": "17:00 成績", "B1": "19:00 予告",
                     "L1": "長編", "G1": "試合の話題"}  # 非公開の T1 は入らない


def test_lag_is_estimated_from_first_appearance():
    raw, items = _load()
    assert wr.estimate_lag(items, raw) == 2


def test_values_after_1_and_7_days():
    raw, items = _load()
    snaps = wr.shift(raw, 2)
    # A1 は 10/01 公開。1日後（10/02 まで入った保存）は 2つ目の値 300
    row, _ = wr.value_after(snaps, "A1", date(2026, 10, 1), 1)
    assert row["views"] == 300
    row, _ = wr.value_after(snaps, "A1", date(2026, 10, 1), 7)
    assert row["views"] == 740
    # まだ保存に入っていない日（G1 の公開10日後）は None
    row, d = wr.value_after(snaps, "G1", date(2026, 10, 3), 10)
    assert row is None and d is None


def test_summary_medians_and_threshold():
    raw, items = _load()
    s = wr.summarize(items, wr.shift(raw, 2), date(2026, 10, 7))
    assert s["17:00 成績"]["n"] == 2
    assert s["17:00 成績"]["med1"] == (300 + 80) / 2
    assert s["19:00 予告"]["over"] == 1          # 最新 2,220 回
    assert s["19:00 予告"]["subs"] == 1
    assert s["試合の話題"]["over"] == 1          # 最新 1,450 回
    assert "長編" not in s                        # 9/25 公開は週の外


def test_missing_is_unknown_not_zero():
    raw, items = _load()
    s = wr.summarize(items, wr.shift(raw, 2), date(2026, 9, 30))
    assert s["長編"]["n"] == 1 and s["長編"]["nl"] == 0
    assert s["長編"]["medl"] is None and s["長編"]["over"] == 0


def test_default_week_ends_at_last_day_in_data():
    md = wr.build(DATA)  # 最新の保存 10/12、遅れ2日 → 10/10 までの週
    assert "2026-10-04〜2026-10-10" in md


def test_render_has_note_and_table():
    md = wr.build(DATA, date(2026, 10, 7))
    assert "近似の注意" in md and "約2日" in md
    assert "| 17:00 成績 | 2 | 190 |" in md
    assert "19:00 予告" in md and "試合の話題" in md


def test_two_weeks_before_and_missing_values_are_explicit():
    md=wr.build(DATA,date(2026,10,14),lag=2)
    assert '2週前に公開した回の7日の値（2026-10-01〜2026-10-07）' in md
    raw,items=_load()
    s=wr.summarize(items,wr.shift(raw,2),date(2026,10,7))['17:00 成績']
    assert f"| 17:00 成績 | 2 | {s['n7']} | {wr.fmt(s['med7'])} |" in md


if __name__=='__main__':
    import pytest
    raise SystemExit(pytest.main([__file__,'-q','-p','no:cacheprovider']))
