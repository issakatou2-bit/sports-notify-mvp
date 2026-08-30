#!/usr/bin/env python3
"""
画面を実データで実際に描いてみる。

なぜ要るのか:
  ここまでの検査は、どれも「コードを動かさずに分かること」を見ている。
  構文、未定義名、YAML、起動できるか。だが動画の画面は、動かして
  初めて壊れが出る種類のものが多い。

  実際に起きたもの:
    ・font(34, "regular") と呼んでいた(その版の font は大きさだけ取る)
    ・球団名が長すぎて1回の列に食い込んだ
    ・回ごとの合計と最終スコアが食い違ったまま描いていた
    ・材料の鍵が変わって、画面が丸ごと空になった

  どれも投稿するまで気づけない。1枚描いて、落ちないこと・
  真っ白でないことだけでも確かめれば、その日のうちに分かる。

  ここでは中身の良し悪しは見ない。「描けるか」だけを見る。

  ※ 内容が揃っているかは healthcheck.check_content が見ている。
    こちらは描画そのものの検査。

使い方:
  python3 scripts/test_render.py
"""

import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# 日本語フォントが無い環境でも、描けるかどうかは確かめられる。
# 字が豆腐になっても、落ちるかどうかと真っ白かどうかは分かる。
if not os.environ.get("COLLESPO_FONT"):
    for cand in ("C:/Windows/Fonts/NotoSansJP-VF.ttf",
                 "C:/Windows/Fonts/meiryo.ttc",
                 "C:/Windows/Fonts/YuGothR.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/liberation/"
                 "LiberationSans-Regular.ttf"):
        if pathlib.Path(cand).exists():
            os.environ["COLLESPO_FONT"] = cand
            break

try:
    import generate_morning_short as g
except Exception as e:                       # noqa: BLE001
    print("[skip] 読み込めません: %s" % str(e)[:150])
    sys.exit(0)

fails = 0


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def blank(im) -> bool:
    """背景だけの絵か。真っ白(真っ黒)を素通りさせないため。"""
    small = im.convert("RGB").resize((60, 100))
    return len(set(small.getdata())) <= 3   # noqa: PIL の非推奨警告は無視


def check(label, fn, *args, allow_none=False, **kw):
    """1枚描いてみる。落ちないこと、背景だけでないこと。"""
    global fails
    try:
        im = fn(*args, **kw)
    except Exception as e:                   # noqa: BLE001
        fails += 1
        print("NG  %s: %s: %s" % (label, type(e).__name__, str(e)[:110]))
        return
    if im is None:
        if allow_none:
            print("ok  %s: 材料が足りないので描かない(想定どおり)" % label)
        else:
            fails += 1
            print("NG  %s: 何も返しませんでした" % label)
        return
    if blank(im):
        fails += 1
        print("NG  %s: 背景だけです(材料が渡っていない可能性)" % label)
        return
    print("ok  %s" % label)


def main() -> int:
    global fails
    if not os.environ.get("COLLESPO_FONT"):
        print("[skip] 日本語フォントが見つからないため飛ばします")
        return 0

    recap = load("data/morning_recap.json")
    buzz = load("data/mlb_buzz.json")
    talk = load("data/local_buzz.json")
    reps = load("data/local_reporters.json")
    voices = load("data/local_voices.json")
    profile = load("data/player_profile.json")

    players = recap.get("players") or []
    vids = buzz.get("videos") or []

    print("--- 夕方の5本の画面 ---")
    # 動きの途中と、描き終わりの両方を見る。
    # 途中だけ、終わりだけで落ちるものがある(アニメの分岐)。
    for p in (0.3, 1.0):
        tag = "途中" if p < 1 else "完成"
        if players:
            check("%s 選手一覧" % tag, g.render_list, p, players, 0, 3)
        if vids:
            check("%s 現地の再生回数" % tag, g.render_buzz, p, vids)
            res = (vids[0].get("result") or {})
            check("%s スコアボード" % tag, g.render_scoreboard, p, res,
                  res.get("away_jp", ""), res.get("home_jp", ""),
                  allow_none=True)
        if talk.get("teams"):
            check("%s 話題のチーム" % tag, g.render_talk, p, talk)
        if reps.get("posts"):
            check("%s 番記者" % tag, g.render_reporters, p,
                  reps.get("posts"))
        if reps.get("headlines"):
            check("%s 見出し" % tag, g.render_headlines, p,
                  reps.get("headlines"))
        vs = voices.get("voices") or []
        if vs:
            # 丸ごと渡す。一覧だけ渡すと落ちる(本番は voices_data を渡す)
            check("%s ファンの声" % tag, g.render_voices, p, voices)
            i = g.thread_index(vs)
            if i is not None:
                check("%s 返信のついた一言" % tag, g.render_thread, p, vs[i])
        # 日本人選手への称賛。称賛が0件の日は描かないので、
        # 材料がある日だけ見る。
        pr = (voices.get("jp_praise") or [])[:2]
        if pr:
            check("%s 現地の称賛" % tag, g.render_praise, p, pr)
        # 7日間の合計。8/28に足したのに、ここへ足すのを忘れていた。
        # 8/29がこの画面の初日で、その日は動画が1本も出ていない。
        # 原因かどうかは別として、描いたことが一度も無い画面を
        # 本番に出していた。
        if players:
            line, week = g.week_line(players)
            if week:
                check("%s 7日間の合計" % tag, g.render_week, p, week,
                      players[0].get("name", ""))
        check("%s アウトロ" % tag, g.render_outro, p)

    print("\n--- 冒頭(枠ごとに材料が違う) ---")
    extra = {"buzz": vids, "voices": voices, "reporters": reps,
             "talk": talk, "profile": profile}
    for mode in ("players", "player", "voices", "local", "press"):
        meta = {"mode": mode, "date_label": "8月21日"}
        top = players[0] if players else {}
        check("冒頭 %s" % mode, g.render_intro, 1.0, meta, top, extra)

    # 成績の行が、置ける幅に収まっているか。
    #
    # fit() は入らなくても最小の大きさを返すだけで、収まったとは
    # 言わない。投手の行に被安打と防御率を足した日に28字になり、
    # 最小の文字でも右へはみ出したまま公開された。
    # 「小さくすれば入る」は、ある長さから先は成り立たない。
    # スコアボードの最後の列が、動きの終わりまでに開くか。
    #
    # 1列ずつ開く速さを固定にしていたため、9回目は 0.46 で開くのに
    # 動きは 0.45 で止まり、9回が一度も描かれなかった。
    # 1対2の試合で推移が1対1のまま終わる、という形で出た。
    # 延長した日は10回以降も全部落ちていた。
    print("\n--- スコアボードの列が開き切るか ---")
    late = []
    for cols in (9, 10, 12, 15, 18):
        step = (g.ANIM_END - 0.14) / cols
        last = 0.10 + (cols - 1) * step
        if last >= g.ANIM_END:
            late.append("%d回: %.3f" % (cols, last))
    if late:
        fails += 1
        print("NG  動きの終わり %.2f に間に合わない: %s"
              % (g.ANIM_END, "、".join(late)))
    else:
        print("ok  9〜18回まで、最後の列が動きの終わりまでに開く")

    print("\n--- 成績の行が幅に収まるか ---")
    import morning_recap as _mr
    from PIL import Image as _I, ImageDraw as _ID
    _dd = _ID.Draw(_I.new("RGB", (g.W, g.H)))
    over = []
    for row in (recap.get("players") or []):
        head = _mr.headline(row)
        wide = (row.get("prev_score") is not None
                or row.get("avg_score") is not None)
        avail = (g.W - 560) if wide else (g.W - 300)
        size = g.fit(_dd, head, avail, (48, 44, 40, 36, 32, 28, 24))
        if _dd.textlength(head, font=g.font(size)) > avail:
            over.append("%d字 %s" % (len(head), head))
    if over:
        fails += 1
        print("NG  幅に収まらない行が%d件" % len(over))
        for o in over[:3]:
            print("      " + o)
    else:
        print("ok  すべて収まる(%d件)" % len(recap.get("players") or []))


    print("\nALL OK" if not fails else "\n%d FAILURES" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
