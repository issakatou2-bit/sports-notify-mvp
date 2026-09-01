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
    ps = load("data/postseason.json")

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
        # ポストシーズン進出争い。9月から10月だけの枠なので、
        # 材料がある日だけ見る。
        for lid in ("103", "104"):
            lg = (ps.get("leagues") or {}).get(lid)
            if lg:
                check("%s 進出争い(%s)" % (tag, lid),
                      g.render_ps_league, p, lg)
        if ps.get("leagues"):
            check("%s 今日終わったら" % tag, g.render_ps_bracket, p, ps)
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
    from PIL import Image as _I, ImageDraw as _ID
    _dd = _ID.Draw(_I.new("RGB", (g.W, g.H)))
    over, cut = [], []
    for row in (recap.get("players") or []):
        wide = (row.get("prev_score") is not None
                or row.get("avg_score") is not None)
        avail = (g.W - 560) if wide else (g.W - 300)
        head, size = g.fit_headline(_dd, row, avail)
        full = __import__("morning_recap").headline(row)
        if _dd.textlength(head, font=g.font(size)) > avail:
            over.append("%d字 %s" % (len(head), head))
        elif head != full:
            cut.append("%s → %s" % (full, head))
    if over:
        fails += 1
        print("NG  幅に収まらない行が%d件" % len(over))
        for o in over[:3]:
            print("      " + o)
    else:
        print("ok  すべて収まる(%d件)" % len(recap.get("players") or []))
    # 落とした行は、失敗ではないが黙って消えるので出す。
    # 落とすものが無くなってなお入らない日は、上の NG に出る。
    for c in cut[:5]:
        print("    落とした: " + c)

    fails += check_still(players, vids, voices, reps, talk)
    fails += check_expression()
    fails += check_longform()

    print("\nALL OK" if not fails else "\n%d FAILURES" % fails)
    return 1 if fails else 0


def check_still(players, vids, voices, reps, talk) -> int:
    """絵が本当に止まる時点が、使い回しを始める時点より前か。

    ここがずれていると、**最後の1つが一度も画面に出ない。**
    書き出す側は `p >= STILL_AFTER` で描くのをやめて前の絵を
    使い回す。そのとき絵がまだ動いていたら、出かかった絵を
    区間の残り全部に貼ることになる。

    実際そうなっていた。ANIM_END(0.45)で使い回しを始めていたが、
    どの画面も 0.455〜0.646 まで動いていた。
    2行の台詞が1行で切れ、9回の試合が8回で終わっていたのは
    これが原因。1つずつ確かめるのではなく、測って比べる。
    """
    import video_common
    print("\n--- 絵が止まる時点 < 使い回しを始める時点 ---")
    res = (vids[0].get("result") or {}) if vids else {}
    cases = []
    if players:
        cases.append(("選手一覧", lambda p: g.render_list(p, players, 0, 3)))
    if vids:
        cases.append(("現地の再生回数", lambda p: g.render_buzz(p, vids)))
        if res:
            cases.append(("スコアボード", lambda p: g.render_scoreboard(
                p, res, res.get("away_jp", ""), res.get("home_jp", ""))))
    if voices.get("voices"):
        cases.append(("ファンの声", lambda p: g.render_voices(p, voices)))
    if reps.get("posts"):
        cases.append(("番記者", lambda p: g.render_reporters(
            p, reps.get("posts"))))
    if reps.get("headlines"):
        cases.append(("見出し", lambda p: g.render_headlines(
            p, reps.get("headlines"))))
    if talk.get("teams"):
        cases.append(("話題のチーム", lambda p: g.render_talk(p, talk)))
    cases.append(("アウトロ", lambda p: g.render_outro(p)))

    cut = video_common.STILL_AFTER
    late, worst = [], 0.0
    for name, fn in cases:
        try:
            end = fn(1.0).tobytes()
        except Exception as e:                   # noqa: BLE001
            print("NG  %s: %s" % (name, str(e)[:80]))
            return 1
        stop = None
        # 40刻みで十分。ここは目安であって、0.001の差は問題にしない
        for i in range(41):
            p = i / 40
            try:
                if fn(p).tobytes() == end:
                    stop = p
                    break
            except Exception:                    # noqa: BLE001
                continue
        if stop is None:
            late.append("%s: 止まりません" % name)
            continue
        worst = max(worst, stop)
        if stop >= cut:
            late.append("%s: %.3f" % (name, stop))
    if late:
        print("NG  使い回しを始める %.2f より後まで動いている: %s"
              % (cut, "、".join(late)))
        print("      video_common.STILL_AFTER を上げてください")
        return 1
    print("ok  いちばん遅いもの %.3f < %.2f（%d画面）"
          % (worst, cut, len(cases)))
    return 0


def check_expression() -> int:
    """台詞に当てる表情。

    語を先勝ちで当てていたので、
    「いい投手ばっかりなのに、打線が点を取らないのだ」で
    ずんだもんが笑顔になった。公開した動画に出た。
    否定を先に見る形へ直したので、その形をここで押さえる。
    """
    print("\n--- 台詞に当てる表情 ---")
    try:
        import generate_longform as L
    except Exception as e:                       # noqa: BLE001
        print("[skip] 読み込めません: %s" % str(e)[:100])
        return 0
    cases = [
        # 否定が肯定より強い。これが公開された動画で外れた形
        ("いい投手ばっかりなのに、打線が点を取らないのだ。", "", "困り"),
        ("ピッチングはいいのに負けたってことなのだ。", "", "困り"),
        ("きょうのハイライト、ドジャースが負けたのだ？", "", "困り"),
        ("また打線が悪かったのだ？", "", "困り"),
        # 数のあとの「も」は多さに驚いている
        ("66万回以上も見られてるのだ。", "", "驚き"),
        ("高評価が421件もついているのよ。", "", "驚き"),
        ("5件の返信があるのだ。", "", "基本"),
        # 札の賛否は、書かれた語より確か
        ("そうなのだ。", "否定", "困り"),
        ("そうなのだ。", "肯定", "笑顔"),
        # **ただの問いは「問い」。腕は上げない。**
        # 分けていなかったときは、?で終わる文を全部「驚き」にしていた。
        # ずんだもんは聞き手なので、10行中9行が両手を挙げた顔になった。
        ("ベストバッターがそれなのだ？", "", "問い"),
        ("得点は回ごとにどう入ったのだ？", "", "問い"),
        ("その返信ではどう言われてるのだ？", "", "問い"),
        # 驚きは、本当に驚く言葉があるときだけ
        ("すごいのだ！", "", "驚き"),
        ("まさかそんなことがあるのだ", "", "驚き"),
        # ふつうの文
        ("いろいろな見方があるのだ。", "", "基本"),
        ("これは素晴らしい投球なのだ。", "", "笑顔"),
    ]
    bad = 0
    for text, mood, want in cases:
        got = L.expression_for(text, mood)
        if got != want:
            bad += 1
            print("NG  「%s」%s → %s（%s のはず）"
                  % (text[:30], ("／空気=" + mood) if mood else "", got, want))
    if not bad:
        print("ok  %d通り、当てた表情が変わっていません" % len(cases))

    # 偏り。ずんだもんの台詞は問いばかりなので、
    # 1つの表情に寄りすぎていないかを見る。
    zunda = ["今日のハイライトはどのくらい見られたのだ？",
             "得点は回ごとにどう入ったのだ？",
             "このハイライトで目立ってたのは誰なのだ？",
             "その返信ではどう言われてるのだ？",
             "別のコメントではどんなことが言われてるのだ？",
             "Yamamotoの防御率はいいのだ？",
             "66万回以上も見られてるのだ。",
             "かなり怒ってるのだ。",
             "いろいろな見方があるのだ。",
             "そうなのだ。"]
    from collections import Counter
    c = Counter(L.expression_for(t) for t in zunda)
    top, n = c.most_common(1)[0]
    if n > len(zunda) * 0.8:
        bad += 1
        print("NG  ずんだもんの台詞10行が「%s」に%d行寄っています" % (top, n))
        print("      台詞は変わっているのに、絵が同じままになります")
    else:
        print("ok  偏りなし（いちばん多い「%s」で%d/%d行）"
              % (top, n, len(zunda)))
    return bad


def check_longform() -> int:
    """長編(16:9)の画面。札の種類ぶんだけ描いてみる。

    ここを見ていなかったので、初版は台詞の箱が画面の外へ出たまま、
    5行を超えたぶんを黙って捨てたまま公開された。
    絵の良し悪しは見ないが、「置ける場所に収まっているか」は
    座標の計算なので、ここで確かめられる。
    """
    print("\n--- 長編(16:9)の画面 ---")
    bad = 0
    try:
        import generate_longform as L
    except Exception as e:                       # noqa: BLE001
        print("[skip] 読み込めません: %s" % str(e)[:120])
        return 0

    cards = {
        "score": {"type": "score", "away": "デトロイト",
                  "home": "ヒューストン", "away_score": 2, "home_score": 1,
                  "innings": [{"num": i, "away": 0, "home": 0}
                              for i in range(1, 13)]},
        "views": {"type": "views", "title": "デトロイト対ヒューストン "
                                            "ハイライト", "views": 318754},
        "quote": {"type": "quote", "text": "あれは投げてはいけない球だ" * 4,
                  "tone": "否定", "likes": 1240, "replies": 18,
                  "source": "MLB公式"},
        "stat": {"type": "stat", "name": "Tarik Skubal", "stat": "防御率",
                 "rank": 2, "value": "2.14"},
        "star": {"type": "star", "name": "Riley Greene",
                 "team": "デトロイト・タイガース", "line": "4打数2安打1本塁打"},
        "none": None,
        "unknown": {"type": "存在しない種類"},
    }
    # 長さは、短い一言から、1画面に入らない長さまで。
    texts = ["へえ。", "そうね。この試合、9回に決まったのよ。",
             "コメント欄はね、勝ったほうじゃなくて負けたほうの話で"
             "もちきりなの。いちばん支持されている一言が、これよ。",
             "なるほどなのだ。" * 20]

    for key, card in cards.items():
        for ti, txt in enumerate(texts):
            seg = {"speaker": 2 if ti % 2 else 3, "text": txt}
            try:
                pages = L.paginate([seg])
                for pg in pages:
                    im = L.render_line(1.0, pg, "assets/portraits",
                                       "デトロイト対ヒューストン", card)
                if blank(im):
                    bad += 1
                    print("NG  %s / %d字: 背景だけです" % (key, len(txt)))
                    continue
            except Exception as e:               # noqa: BLE001
                bad += 1
                print("NG  %s / %d字: %s: %s"
                      % (key, len(txt), type(e).__name__, str(e)[:90]))
                continue
            # 捨てていないか。全部の画面の行を繋ぐと元に戻るはず。
            joined = "".join("".join(pg["_lines"]) for pg in pages)
            if len(joined) < len(" ".join(txt.split())):
                bad += 1
                print("NG  %s: 台詞を%d字捨てました"
                      % (key, len(txt) - len(joined)))
    # 冒頭の札。台詞が空なので、割りつけが落ちないかも見る。
    try:
        pg = L.paginate([{"speaker": 3, "text": ""}])[0]
        im = L.render_intro(1.0, "ドジャース vs タイガース", "8月30日")
        st = {s["name"]: {"expr": "笑顔", "blink": False, "mouth": 2}
              for s in L.SPEAKERS.values()}
        L.paste_portraits(im, L.BOTH, "assets/portraits", st, "冒頭")
        if blank(im):
            bad += 1
            print("NG  冒頭の札: 背景だけです")
        elif pg["_lines"] != []:
            bad += 1
            print("NG  空の台詞から行が出ました: %r" % pg["_lines"])
    except Exception as e:  # noqa: BLE001
        bad += 1
        print("NG  冒頭の札: %s: %s" % (type(e).__name__, str(e)[:90]))

    if not bad:
        print("ok  札%d種 × 長さ%d通り、はみ出しも捨てもありません"
              % (len(cards), len(texts)))

    # 置ける場所どうしが重なっていないか。座標なので数えれば分かる。
    print("\n--- 長編の割りつけが重なっていないか ---")
    over = []
    if L.PANEL_Y1 >= L.TALK_Y0:
        over.append("札(%d)と台詞(%d)" % (L.PANEL_Y1, L.TALK_Y0))
    if L.TALK_Y1 > L.H:
        over.append("台詞の下端(%d)が画面(%d)の外" % (L.TALK_Y1, L.H))
    if L.H - L.PORTRAIT_H >= L.PANEL_Y1:
        pass                                    # 立ち絵は札より下から
    for size in L.TALK_SIZES:
        need = size + L.TALK_LEAD
        if (L.TALK_Y1 - L.TALK_Y0 - L.TALK_PAD * 2) < need:
            over.append("%dptが1行も入らない" % size)
    if over:
        bad += 1
        print("NG  " + "、".join(over))
    else:
        print("ok  札・台詞・立ち絵が重なりません")
    return bad


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
