#!/usr/bin/env python3
"""PS予告の見せ方（10/3 改善案A〜D）。描画と読み上げの対応。"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ps_program as pp  # noqa: E402
import ps_render_template as rt  # noqa: E402
from checks_report import check, section, done  # noqa: E402

_card = {"layout": "facts", "date": "2026-10-04", "source_url": "https://statsapi.mlb.com",
         "source_label": "MLB公式日程", "label": "PS予告", "headline": "ガーディアンズ\n対ホワイトソックス",
         "subhead": "シリーズの初戦", "card_index": 1, "card_total": 4, "production": True,
         "items": [{"label": "日本時間の開始予定", "value": "02:00", "value_size": 110},
                   {"label": "ガーディアンズ / 先発予定", "value": "パーカー・メシック", "value_size": 60},
                   {"label": "ホワイトソックス / 先発予定", "value": "Hagen Smith", "value_size": 60}],
         "scoreboard": {"need": 3, "rows": [
             {"abbr": "CLE", "name": "ガーディアンズ", "wins": 0, "color": "#00385D", "players": []},
             {"abbr": "CWS", "name": "ホワイトソックス", "wins": 0, "color": "#27251F",
              "players": ["村上宗隆", "西田陸浮"]}]}}
_seg = {"speaker": 2, "meta": {"card": _card},
        "text": "村上宗隆・西田陸浮のホワイトソックスは、ガーディアンズとの地区シリーズ第1戦。"
                "日本時間午前2時の予定です。ガーディアンズの先発予定はパーカー・メシックです。"}

section("C: 読み上げ中の行")
plan = pp.focus_plan(_seg)
check("文ごとに行が決まる", [x[2] for x in plan], [None, 0, 1])
check("時刻を言っている間は時刻の行", pp.focus_at(plan, 0.6), 0)
check("先発を言っている間はその球団の先発の行", pp.focus_at(plan, 0.9), 1)
check("スコアボードの無いカードは照らさない",
      pp.focus_plan({"text": "a。b。", "meta": {"card": {"items": []}}}), [])

section("A/B: 描画")
im, manifest = rt.render(_card, presenters="right")
box = manifest["presenters"][0]["box"]
check("立ち絵が下の題・右のボタン列に重ならない",
      box[3] <= rt.SAFE_BOTTOM and box[2] <= rt.SAFE_RIGHT, True)
said = [r["text"] for r in manifest["text"]]
check("スコアボードに日本人選手の名前", "村上宗隆・西田陸浮" in said, True)
check("略称バッジ", "CWS" in said and "CLE" in said, True)
check("用語メモは表紙だけ（カードには出さない）", "用語メモ" in said, False)
check("出典は出す", any(t.startswith("出典：") for t in said), True)
cover = dict(_card, card_index=None, scoreboard=None, layout="schedule",
             glossary="WCS 2勝 / DS 3勝", headline="村上宗隆のホワイトソックス\n明日10/04 DS",
             items=[{"when": "10/04 02:00", "home": "ガーディアンズ", "away": "ホワイトソックス"}])
_, m2 = rt.render(cover, presenters="left")
check("表紙には用語メモ", "用語メモ" in [r["text"] for r in m2["text"]], True)

section("PS情勢（20:00）: 日本人選手から・次の相手")
def _t(i, n, w, pl): return {"id": i, "name": n, "wins": w, "players": pl}
_rows = [
    {"key": "F:111-147", "round": "F", "round_jp": "ワイルドカードシリーズ", "stage": 1, "need": 2,
     "played": 2, "over": True, "winner": 147, "next": None,
     "teams": [_t(147, "ヤンキース", 2, []), _t(111, "レッドソックス", 0, ["吉田正尚"])]},
    {"key": "F:117-145", "round": "F", "round_jp": "ワイルドカードシリーズ", "stage": 1, "need": 2,
     "played": 2, "over": True, "winner": 145, "next": None,
     "teams": [_t(145, "ホワイトソックス", 2, ["村上宗隆"]), _t(117, "アストロズ", 0, [])]},
    {"key": "D:114-145", "round": "D", "round_jp": "地区シリーズ", "stage": 2, "need": 3,
     "played": 0, "over": False, "winner": None, "next": None,
     "teams": [_t(114, "ガーディアンズ", 0, []), _t(145, "ホワイトソックス", 0, ["村上宗隆"])]}]
_before = {"program_series": [dict(r, over=False, played=1, winner=None,
                                   teams=[dict(t, wins=min(t["wins"], 1)) for t in r["teams"]])
                              for r in _rows[:2]]}
_prog = pp.situation_program({"date_jst": "2026-10-01", "source_url": "https://statsapi.mlb.com"},
                             _rows, _before)
check("題は勝ち残った日本人選手の側", _prog["title"].split("｜")[0], "村上宗隆のホワイトソックスがWCS突破")
check("勝ち残った日本人選手のシリーズが先", _prog["segments"][0]["text"].startswith("村上宗隆"), True)
check("読み上げは日本人選手の側から（敗れた側でも）",
      any(x["text"].startswith("吉田正尚のレッドソックスは") for x in _prog["segments"]), True)
check("敗退した日本人選手の回は、勝ち残った側の回より後",
      [x["text"][:4] for x in _prog["segments"]][-1], "吉田正尚")
check("勝ち上がった球団の次の相手",
      [(i["label"], i["value"]) for i in _prog["segments"][0]["meta"]["card"]["items"]][1],
      ("ホワイトソックスの次の相手", "地区シリーズでガーディアンズ"))
check("勝数は下の行に重ねない（スコアボードにある）",
      [i["label"] for i in _prog["segments"][0]["meta"]["card"]["items"]
       if i["label"] in ("ホワイトソックス", "アストロズ")], [])

sys.exit(done())
