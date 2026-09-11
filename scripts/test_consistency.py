"""
同じことを2か所で決めていないか、実際の値で突き合わせる。

なぜ要るのか:
  ここで見つかった不具合は、どれも「壊れている」のではなく
  「2か所が別々のことを言っている」形だった。片方だけ直して、
  もう片方が古いまま残る。動かしても例外は出ないので気づけない。

  実例:
    ・読み上げは players[0]、画面は pick_top() で別の選手を指していた
    ・「今夜/明日」を各所が自前で決め、同じ試合の呼び方が食い違った
    ・サッカーの理由は league の日本語名、判定はコードで比較していた
    ・サイトは games.json だけを読むのに、MLBしか渡していなかった
    ・公開している計算式と、実装の係数が別々に書かれていた

  どれも「1つの問いに答えが2つある」状態。ここではその形を探す。
"""

import inspect
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {label}: {got}"
          + ("" if ok else f" (期待 {want})"))


# --- 冒頭で挙げる選手が、読み上げと画面で同じか -----------------------------
print("--- 冒頭の選手 ---")
import generate_morning_short as ms  # noqa: E402
import morning_recap as mr  # noqa: E402

recap = ROOT / "data" / "morning_recap.json"
if recap.exists():
    d = json.loads(recap.read_text(encoding="utf-8"))
    players = ms.sort_players(d.get("players") or [])
    if players:
        narration = ms.build_narration({**d, "players": players}, "players")
        spoken = narration["segments"][0]["text"]
        check("読み上げの冒頭に、一覧1位の名前が入っている",
              players[0]["name"] in spoken, True)
# 選び方が2つ残っていないか
check("選手を選ぶ関数が1つだけ", hasattr(ms, "pick_top"), False)


# --- 「今夜/明日」を決める場所が1つか ---------------------------------------
print("\n--- 日付の呼び方 ---")
import post_common as pc  # noqa: E402

srcs = list((ROOT / "scripts").glob("*.py")) + [ROOT / "notability_engine.py"]
own = [f.name for f in srcs
       if f.name not in ("post_common.py", "test_consistency.py")
       and re.search(r'def (when_label|today_or_tomorrow_label)\b',
                     f.read_text(encoding="utf-8", errors="replace"))]
check("post_common 以外に同名の関数が無い", own, [])
check("競技で境目が違うことが1か所で決まっている",
      hasattr(pc, "_late_night_until"), True)


# --- 公開している計算式と、実装の係数が一致しているか -----------------------
print("\n--- 計算式の公開 ---")
# 数字を2か所に書かず、ページが実装から読むようになっているか。
# 手で書くと、片方を変えたときにもう片方が古いまま残る。
page = (ROOT / "scripts" / "generate_score_page.py").read_text(encoding="utf-8")
check("ページが土台を実装から読んでいる", "{mr.BATTER_BASE}" in page, True)
check("ページが倍率を実装から読んでいる", "{mr.BATTER_SCALE}" in page, True)
check("土台の数字がページに直接書かれていない",
      re.search(r"スコア = \d+ \+ 素点", page) is None, True)


# --- サイトが読むファイルに、両方の競技が入るか -----------------------------
print("\n--- サイトへ渡すデータ ---")
index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
reads = set(re.findall(r"fetch\('([\w./]+)'", index))
check("サイトが読むのは games.json だけ", "games.json" in reads, True)
wf = (ROOT / ".github" / "workflows" / "daily_notify.yml").read_text(encoding="utf-8")
check("その games.json に両方の競技を入れている",
      "merge_games.py" in wf, True)
check("MLBだけをコピーしていない",
      "cp notable_games.json public/games.json" in wf, False)


# --- 動画・タイトル・説明文が同じ材料を見ているか ---------------------------
print("\n--- 「今日の1人」 ---")
import player_screens as ps  # noqa: E402
import upload_youtube as uy  # noqa: E402

prof_path = ROOT / "data" / "player_profile.json"
if prof_path.exists():
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    title = uy.build_metadata("notable_games.json", "8月18日", "morning",
                              morning_mode="player")["snippet"]["title"]
    # 題はカタカナで出す(ラテン文字の綴りで始まると視聴継続が半分になる)。
    # 見るのは「同じ選手か」であって「同じ綴りか」ではない。
    check("タイトルの選手が、材料の選手と同じ",
          uy.title_name(prof["name"]) in title, True)
    body = uy.build_metadata("notable_games.json", "8月18日", "morning",
                             morning_mode="player")["snippet"]["description"]
    line = ps.stat_line(prof, prof.get("career") or {})
    check("説明文の通算が、画面と同じ書き方", line and line in body, True)


# --- 動画の区分名が、再生リスト・健康診断と揃っているか ---------------------
print("\n--- 区分名 ---")
import healthcheck as hc  # noqa: E402
import playlists as pl  # noqa: E402

expected = {k for k, _, _, _ in hc.EXPECTED_DAILY + hc.OPTIONAL_DAILY}
have = set(pl.PLAYLISTS)
check("健康診断が見る区分に、再生リストが全部ある",
      sorted(expected - have), [])

# サイトのその日ページに、その日出した動画が全部並んでいるか。
# 枠を足すたびにここを直し忘れると、作った動画がどこからも辿れなくなる。
import generate_archive_pages as ga  # noqa: E402
check("その日ページに、毎日出す動画が全部ある",
      sorted(expected - {k for k, _ in ga.DAY_VIDEO_KINDS}), [])
# 畳んだ枠は、その日ページには残す(過去の動画へ辿れなくなるため)。
# 毎日の一覧と健康診断からは外れているのが正しい。
check("畳んだ枠が毎日の一覧に残っていない",
      sorted(set(hc.RETIRED) & expected), [])



# --- コメント欄の回で、読み上げと画面が同じ声を見ているか -------------------
#
# 読み上げは冒頭で使った1件とやり取りの1件を外して読むのに、画面は
# 元の並びの先頭から描いていた。映っていない言葉を読み、読んでいない
# 言葉を映す状態になる。見ている側からは、どちらが本当か分からない。
print("\n--- コメント欄の回 ---")
import generate_morning_short as gms  # noqa: E402

_vs = {"source": "MLB公式ハイライトのコメント", "voices": [
    {"ja": "この守備は今年一番だろう", "title": "A", "likes": 900,
     "replies": 12, "tone": "称賛", "is_thread": True,
     "reply_ja": [{"ja": "いや別の方が上", "tone": "批判", "original": "x"}]},
    {"ja": "レンジャーズ頑張れ", "title": "B", "likes": 9, "replies": 0,
     "tone": "中立", "reply_ja": []},
    {"ja": "Detmersは勝利に値する", "title": "C", "likes": 18, "replies": 0,
     "tone": "称賛", "reply_ja": []},
    {"ja": "カナダから応援している", "title": "D", "likes": 4, "replies": 0,
     "tone": "中立", "reply_ja": []},
]}
_n = gms.build_narration({"voices": _vs, "players": [], "buzz": [],
                          "talk": {}, "reporters": {}, "date": "2026-08-18"},
                         mode="voices")
_seg = next((s for s in _n["segments"] if s["kind"] == "voices"), None)
_picked = ((_seg or {}).get("meta") or {}).get("picked") or []
_shown = [_vs["voices"][i]["ja"] for i in _picked]
check("画面に出す声が、読み上げの本文にすべて入っている",
      all(v.rstrip("。！!、.") in _seg["text"] for v in _shown), True)
check("やり取りで使う一言を、声の並びでもう一度読んでいない",
      _vs["voices"][0]["ja"] in _seg["text"], False)
check("画面と読み上げの件数が同じ",
      len(_picked), min(gms.VOICES_SHOWN, len(_vs["voices"]) - 1))



# 「毎日これを出しています」の一覧が、実際の枠と合っているか。
#
# 以前は動画の締め・説明文・「今日の1人」の締めで別々に書いてあり、
# 3つとも中身が違っていた。7本出しているのに6本・5本・6本。
# 毎日見ている人にいちばん届く場所で、間違ったことを言っていた。
print("\n--- 毎日の一覧 ---")
import post_common as pc  # noqa: E402

_kinds = {k for k, _, _, _ in pc.DAILY_LINEUP}
check("一覧の区分が、健康診断の見る枠と同じ",
      sorted(expected ^ _kinds), [])
check("一覧に重複が無い", len(pc.DAILY_LINEUP), len(_kinds))
check("説明文が一覧から作られている",
      all(name in "".join(uy.DAILY_LINEUP_LINES)
          for _, name, _, _ in pc.DAILY_LINEUP), True)


# 冒頭で名乗った試合が、いちばん最初に紹介されるか。
#
# 実測の離脱曲線では、どの回も動画の12〜21%(およそ8〜14秒)で人が急に減る。
# ちょうど1枚目が終わって試合の紹介が始まる位置。ところが過去17日のうち
# 7日は、冒頭で名前を出した試合が2番目や3番目に置かれていた。
# その名前を見て入ってきた人は、目当ての試合が始まる前に去っていたことになる。
#
# 並べ替えたので、今度は「読み上げの試合」と「画面が引く試合」がずれないかを見る。
# 画面は notable_games.json を別に読むので、位置がずれると別の試合が映る。
print("\n--- 冒頭の試合と、その後の並び ---")
import generate_narration as gn2  # noqa: E402

_late = _mismatch = 0
for _f in sorted((ROOT / "archive").glob("2026-*.json")):
    _d = json.loads(_f.read_text(encoding="utf-8"))
    _games = [g for g in _d.get("games", []) if g.get("is_notable")][:3]
    if len(_games) < 2:
        continue
    _orig = [g.get("matchup") or g.get("abbr_matchup") for g in _games]
    _work, _order = list(_games), list(range(len(_games)))
    _h = gn2.pick_hook(_work)
    _at = _h.get("at")
    if isinstance(_at, int) and 0 < _at < len(_work):
        _work.insert(0, _work.pop(_at))
        _order.insert(0, _order.pop(_at))
    # 見出しを組み立てている枝(「ゲーム差2.5の首位攻防戦」など)は、
    # その文字列が試合のJSONに出てこない。照合できる語を別に返している。
    _key = (_h.get("key") or _h.get("sub") or _h.get("big") or "").strip()
    if _key and _key not in json.dumps(_work[0], ensure_ascii=False):
        _late += 1
    for _i, _g in enumerate(_work):
        if _orig[_order[_i]] != (_g.get("matchup") or _g.get("abbr_matchup")):
            _mismatch += 1

check("冒頭で名乗った試合が、1つ目に来ている日数の欠け", _late, 0)
check("読み上げの試合と、画面が引く試合が同じ", _mismatch, 0)


# 「◯件のうち◯件」の母数が、絞る前の件数になっているか。
#
# 9/10は画面に出した6件すべてが大谷と佐々木の記事で、そこで
# 「6件のうち4件が大谷」と読み上げていた。見出しを**日本人選手の
# 名前だけ**で引いていたので、母数がその17人の記事しか無かった。
# 大谷で引いた記事が多いから大谷が最多、という循環。
print("\n--- 報道の「◯件のうち◯件」の母数 ---")
import generate_morning_short as gms2  # noqa: E402

_shown = [{"query": "Shohei Ohtani", "source": "MLB.com", "title": "a"},
          {"query": "Shohei Ohtani", "source": "Yahoo", "title": "b"}]
_pool = _shown + [
    {"query": "MLB playoff race", "source": "ESPN", "title": "c"},
    {"query": "MLB wild card", "source": "CBS", "title": "d"},
    {"query": "Roki Sasaki", "source": "NBC", "title": "e"},
    {"query": "MLB trade", "source": "MLB.com", "title": "f"},
]
_line = gms2.press_premise(_shown, _pool)
check("母数は絞る前の件数", "6件のうち2件" in _line, True)
check("絞った件数を母数にしていない", "2件のうち2件" in _line, False)
# リーグ全体の語が最多になる日に「MLB playoff raceの話題が最も多く」
# と読み上げても意味を持たない。
_league_pool = [
    {"query": "MLB playoff race", "source": "ESPN", "title": "a"},
    {"query": "MLB playoff race", "source": "CBS", "title": "b"},
    {"query": "MLB playoff race", "source": "MLB.com", "title": "c"},
    {"query": "Shohei Ohtani", "source": "Yahoo", "title": "d"},
]
check("リーグ全体の語が最多の日は何も言わない",
      gms2.press_premise(_shown, _league_pool), "")
check("母数が渡らない日も落ちない",
      isinstance(gms2.press_premise(_shown), str), True)

# 見出しを引く語に、リーグ全体のものが入っているか。
import local_reporters as lr  # noqa: E402

check("リーグ全体の語がある", len(lr.LEAGUE_QUERIES) >= 4, True)
check("日本人選手が枠を全部占めない上限がある",
      0 < lr.JP_CAP < lr.TOP_N, True)



# いま出られないサッカー選手を題に出さないか。
#
# 9/11に調べたところ、三笘薫は今季まだ1分も出ていなかった
# （ハムストリングの怪我、プレミアリーグ公式が復帰見込み10月10日と
# 公表）。それを「ブライトンの試合、三笘薫が所属」と題に出していた。
print(chr(10) + "--- 出られないサッカー選手を題に出さない ---")
import soccer_availability as sa  # noqa: E402

_out = sa.unavailable({"players": {
    "三笘薫": {"out": True, "reason": "Hamstring injury"},
    "遠藤航": {"out": False, "minutes": 0},
}})
check("怪我の選手だけを止める", sorted(_out), ["三笘薫"])
# **取れない日は誰も止めない。**題から名前が丸ごと消えるのを避ける。
check("材料が無い日は空", sa.unavailable({}), set())
check("選手が空でも落ちない", sa.unavailable({"players": {}}), set())

# 出場0分でも、公式が「出られる」と言っているなら止めない
# （ベンチ入りしている選手をこちらの判断で外さない）。
_built = sa.build([{"web_name": "Endo", "second_name": "Endo", "minutes": 0,
                    "goals_scored": 0, "assists": 0,
                    "chance_of_playing_next_round": 100, "news": ""}])
check("出場0分でも見込み100%なら出す",
      _built.get("遠藤航", {}).get("out"), False)
_hurt = sa.build([{"web_name": "Mitoma", "second_name": "Mitoma",
                   "minutes": 0, "goals_scored": 0, "assists": 0,
                   "chance_of_playing_next_round": 0,
                   "news": "Hamstring injury - Expected back 10 Oct"}])
check("見込み0%なら止める", _hurt.get("三笘薫", {}).get("out"), True)
check("理由も残す", "Hamstring" in (_hurt.get("三笘薫", {}).get("reason") or ""),
      True)
# 見込みが書かれていない選手（ふつうに出ている選手）を止めない。
_fine = sa.build([{"web_name": "Kamada", "second_name": "Kamada",
                   "minutes": 268, "goals_scored": 0, "assists": 1,
                   "chance_of_playing_next_round": None, "news": ""}])
check("ふつうに出ている選手は止めない",
      _fine.get("鎌田大地", {}).get("out"), False)


# 「所属チームの一戦」に投手の名前を出さないか。
#
# 9/11にユーザーから指摘。「明日今井達也が先発するわけでもないのに
# タイトルにそう書くのは釣り感がある」。先発は中4〜6日で回るので
# 明日投げないことが確定に近い日も多く、救援も連投は避ける。
# **投げるとAPIで確認できた日は1番の枝で先に拾っている**ので、
# ここに投手が残る意味がない。
print("\n--- 「所属チームの一戦」に投手を出さない ---")
_pitcher_game = [{
    "matchup": "Astros vs Angels", "is_notable": True,
    "jp_starters": [], "jp_players": ["今井達也"], "reasons": [],
}]
_h2 = gn2.pick_hook(_pitcher_game)
check("投手しかいない試合では所属の枝を使わない",
      _h2.get("big") != "所属チームの一戦", True)

_batter_game = [{
    "matchup": "White Sox vs Tigers", "is_notable": True,
    "jp_starters": [], "jp_players": ["村上宗隆"], "reasons": [],
}]
check("打者なら残す（毎日スタメンの可能性がある）",
      gn2.pick_hook(_batter_game).get("sub"), "村上宗隆")

_both = [{
    "matchup": "Cubs vs Reds", "is_notable": True,
    "jp_starters": [], "jp_players": ["今永昇太", "鈴木誠也"],
    "reasons": [],
}]
check("投手と打者が両方いる球団なら打者を選ぶ",
      gn2.pick_hook(_both).get("sub"), "鈴木誠也")

# 投げると分かっている日は、これまでどおり1番で拾う。
_starting = [{
    "matchup": "Dodgers vs Padres", "is_notable": True,
    "jp_starters": [{"name": "山本由伸"}], "jp_players": ["山本由伸"],
    "reasons": [],
}]
_h3 = gn2.pick_hook(_starting)
check("先発予定は「先発予定」で出す", (_h3.get("big"), _h3.get("sub")),
      ("先発予定", "山本由伸"))


# サッカーのタブが、大会名の一覧で絞られていないか。
#
# トップページは 5大リーグの名前を配列で持っていて、
# **チャンピオンズリーグがその中に無かった。**CLしかない日は
# タブが丸ごと空になり「今はシーズンオフのため試合がありません」
# と出た。9/9がそれで、代表ウィークでリーグ戦が休み、翌日のCL6試合
# だけがある日だった。**データには入っていたのに映らなかった。**
#
# 一覧で持つ限り、EL・カンファレンスリーグ・国内カップが来るたびに
# 同じことが起きる。足し忘れても静かに消えるので、気づけない。
print("\n--- サッカーのタブの絞り方 ---")
_home = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("大会名の一覧で絞っていない",
      ".includes(g.league)" not in _home, True)
check("MLB以外をサッカーとして扱っている",
      "g.league !== " + chr(39) + "MLB" + chr(39) in _home, True)


# 見張りが見る名前と、記録に残る名前が同じか。
#
# 一覧は "postseason"、記録は "morning_postseason" だった。
# **健康診断は毎日この1件を「出ていない」と数えていた。**
# それが本数の突き合わせで打ち消されていたので、9/7に成績の回が
# 本当に欠けたときも一緒に飲み込まれ、「問題なし」で終わった。
print("\n--- 見張りの名前と、記録の名前 ---")
import healthcheck as hc4  # noqa: E402

_rec = json.loads((ROOT / "data" / "published_videos.json")
                  .read_text(encoding="utf-8"))
_unknown = [k for k, _, _, _ in hc4.EXPECTED_DAILY + hc4.OPTIONAL_DAILY
            if hc4._record_key(k) not in _rec]
check("記録に無い名前を見張っていない", _unknown, [])

# 対応表そのものが、投稿側の付け方と合っているか。
import upload_youtube as uy4  # noqa: E402
check("進出争いの記録名が投稿側と同じ",
      hc4.RECORD_KEY.get("postseason"),
      uy4.record_kind("morning", "postseason"))
check("成績の記録名が投稿側と同じ",
      hc4._record_key("morning"), uy4.record_kind("morning", "players"))


# 二重投稿の守りが、全部の枠に効いているか。
#
# 9/7、成績の回を手で出し直したところ、その完走を合図にしている長編が
# 続けて走り、その日2本目の長編が公開された。守りは daily と morning
# にしか効いていなかった。週次と答え合わせも漏れていた。
print("\n--- 二重投稿の守り ---")
import upload_youtube as uy5  # noqa: E402

# --kind の選択肢は main() の中で組み立てているので、外からは
# 取り出せない。ソースの choices=[...] をそのまま読む。
_kinds = set()
for _line in (ROOT / "scripts" / "upload_youtube.py").read_text(
        encoding="utf-8").split("choices=[", 1)[-1].split("]", 1)[0].split(","):
    _line = _line.strip().strip('"' + "'")
    if _line:
        _kinds.add(_line)
# 日付で引かないのは資産動画だけ。ほかは全部守りの対象に入っていること。
check("守りから漏れている枠",
      sorted(_kinds - set(uy5.DATED_KINDS) - {"asset"}), [])


# 「所属」を「対決」と読み替えられないようにしてあるか。
#
# 8/20の19時の回で、両チームに日本人投手が在籍しているだけの試合を
# 「日本人投手対決」と紹介した。先発は2人とも別の投手で、
# その日は誰も投げていない。原稿はAIが書くので、渡す事実の並びが
# 誤解を誘わない形になっているかを、こちらで見張る。
print("\n--- 所属と先発の区別 ---")
import generate_narration as gn3  # noqa: E402

_g = {"home_team_name": "アストロズ", "away_team_name": "エンゼルス",
      "start_time_jst": "08/21 09:10",
      "reasons": [{"tag": "jp", "text": "アストロズには今井達也が所属",
                   "visible": True},
                  {"tag": "jp", "text": "エンゼルスには菊池雄星が所属",
                   "visible": True}],
      "home_probable": {"name": "Peter Lambert", "era": "3.11"},
      "away_probable": {"name": "Grayson Rodriguez", "era": "7.17"}}
_facts = gn3.build_game_facts(_g)
check("所属だけの日は、出るとは限らないと書き添える",
      "出るとは限りません" in _facts, True)

# 日本人が先発する日は、断りが要らない(むしろ邪魔になる)
_g2 = dict(_g)
_g2["home_probable"] = {"name": "Yusei Kikuchi", "name_jp": "菊池雄星",
                        "era": "3.20"}
check("日本人が先発する日は書き添えない",
      "出るとは限りません" in gn3.build_game_facts(_g2), False)
check("AIへの条件に「対決と書かない」が入っている",
      "「対決」" in inspect.getsource(gn3.narrate_game), True)


# 1枚目の帯と、そこで読み上げる文が同じものを指しているか。
#
# 現地の報道の回で、帯は「いちばん短い見出し」、読み上げは「1件目」を
# 選んでいた。画面に見出しが2つ並び、声は下の方だけを読む形になり、
# 見ている側からは、どちらが本題か分からなかった。
print("\n--- 1枚目の帯と読み上げ ---")

_rep = {"headlines": [
    {"jp": "大谷翔平が6年連続30本塁打シーズンを達成、MVP争いでペースを維持"},
    {"jp": "ダルビッシュはカブスの良い補強か"},
    {"jp": "レッドソックスが連勝を4に伸ばす"},
]}
_data = {"reporters": _rep, "voices": {}, "buzz": [], "players": [],
         "talk": {}, "date": "2026-08-20"}
_n = gms.build_narration(_data, mode="press")
_intro = _n["segments"][0]
_band, _ = gms.intro_topic("press", _intro["meta"], None,
                           {"reporters": _rep, "voices": {}, "buzz": []})
check("帯の見出しが、読み上げの本文に入っている",
      bool(_band) and _band[:12] in _intro["text"], True)


# 名前の照合で、アクセント記号のせいで別人を出さないか。
#
# 現役に Díaz は6人いる。アクセントを落とさずに数えていたため、
# Diaz(1人) と Díaz(5人) に割れ、前者だけが「同姓なし」として
# 残っていた。ファンが書く "diaz" に、無関係な選手の成績が
# 付くところだった。
print("\n--- 名前の照合 ---")
import mentioned as mn  # noqa: E402

check("アクセントを落とせている", mn.fold("Edwin Díaz"), "Edwin Diaz")
check("姓もアクセントを落とす", mn._surname("Edwin Díaz"), "Diaz")
_by_last, _ = mn._roster()
# 同姓が複数いる姓は、照合から外れていること
_dupes = [s for s in ("Diaz", "Diaz".lower()) if s in _by_last]
check("同姓が複数いる姓は照合しない", _dupes, [])

# 同じ日に出す5本が、同じ言葉で始まっていないか。
#
# 現地編と報道編は、先頭が枠の名前で固定されていた。7日並べると
# 変わるのは日付だけで、フィードでは同じ動画を出し直しているように
# 見える。YouTubeの規約が「変化に乏しい動画」を名指ししている形でもある。
# 先頭はその日の中身から取る。
print("\n--- 同じ日の5本の書き出し ---")
import upload_youtube as _uy  # noqa: E402

_heads = {}
for _mode in ("players", "player", "voices", "local", "press"):
    _t = _uy.build_metadata("notable_games.json", "8月21日",
                            kind="morning", morning_mode=_mode
                            )["snippet"]["title"]
    _heads[_mode] = _t.split("｜")[0].replace("【MLB】", "").strip()
    check(f"{_mode} は100字以内", len(_t) <= 100, True)

_dupe = [h for h in _heads.values() if list(_heads.values()).count(h) > 1]
check("書き出しがかぶっていない", sorted(set(_dupe)), [])

# 中身が変われば書き出しも変わること(枠の名前を置いているだけなら変わらない)。
#
# 「見出しが必ずある」ことは求めない。20時間より古いものは使わない
# 作りなので、手元のデータが一晩たてば空になる。それは正しい動作で、
# テストが落ちる理由にはならない。見出しがあるときに題へ入るか、
# 無いときに既定の題へ落ちるか、その繋がりだけを見る。
_head = _uy.top_headline()
_press = _uy.build_metadata("notable_games.json", "8月21日", kind="morning",
                            morning_mode="press")["snippet"]["title"]
if _head:
    check("見出しがあれば題に入る", _head in _press, True)
else:
    check("見出しが無ければ既定の題", "現地メディアは何と言っているか" in _press,
          True)
check("現地編の書き出しはその日の話題から", bool(_uy.top_talked_team()), True)

# 日本人選手の読みが、名簿のローマ字と合っているか。
#
# 漢字をそのままVOICEVOXへ渡すと読みを推測する。「田中碧」は
# Ao Tanaka なので「タナカ・アオ」だが、推測なら「みどり」もありうる。
# 読みは名簿のローマ字から決まっているので、突き合わせられる。
print("\n--- 日本人選手の読み ---")
import unicodedata as _ud  # noqa: E402
from generate_narration import speech_name as _sp  # noqa: E402
from notability_engine import (  # noqa: E402
    JP_PLAYERS_MLB as _M, JP_PLAYERS_SOCCER as _S)

_KATA = "".join(chr(c) for c in range(0x30A1, 0x30FB)) + "ー・"
_bad = []
for _p in list(_M) + list(_S):
    _k = _p.get("kana")
    if not _k:
        continue
    if any(c not in _KATA for c in _k):
        _bad.append((_p["name_jp"], _k, "カタカナ以外が混じっている"))
        continue
    # ローマ字の姓と、読みの先頭が対応しているか(ざっくり)
    _fam = _p["name_en"].split()[-1].lower()
    _head = _k.split("・")[0]
    if len(_fam) >= 3 and len(_head) < 2:
        _bad.append((_p["name_jp"], _k, "姓の読みが短すぎる"))
check("読みが全員そろっている",
      [p["name_jp"] for p in list(_M) + list(_S) if not p.get("kana")],
      ["ヌートバー"])
check("読みの形がおかしいもの", _bad, [])
check("田中碧はタナカ・アオ", _sp("田中碧"), "タナカ・アオ")
check("遠藤航はエンドウ・ワタル", _sp("遠藤航"), "エンドウ・ワタル")


# 見出しを切ったせいで、元と違うことを言っていないか。
#
# 「サミー・ソーサが大谷翔平の落選を明かし、ナ・リーグMVPを選出」を
# 読点で切ると「大谷翔平の落選を明かし」になる。元は投票の話なのに、
# 大谷が何かから落選したように読める。同じ形で「…したのは融資の
# ためではない」の否定が落ちたこともある。切ってよいのは句点だけ。
print("\n--- 見出しの切り方 ---")
_LONG = [
    ("読点しかない", "サミー・ソーサが大谷翔平の落選を明かし、ナ・リーグMVPを選出", ""),
    ("否定が末尾", "いいえ、ドジャースが大谷翔平と契約したのは融資のためではない", ""),
    ("句点の先に否定", "大谷翔平が2本塁打。しかし勝ちには結びつかなかったわけではない", ""),
    ("短すぎる頭", "速報。ドジャースがデンバーで勝利を手にし、地区首位を守った", ""),
    ("句点で切れる", "大谷翔平が2本塁打。ドジャースはデンバーで勝利を手にした",
     "大谷翔平が2本塁打"),
]
for _label, _src, _want in _LONG:
    check(f"見出し {_label}", uy._clip(_src, 26), _want)
check("題は100字以内",
      len(uy.build_metadata("notable_games.json", "8月22日", kind="morning",
                            morning_mode="press")["snippet"]["title"]) <= 100,
      True)


# 対戦名の並びと、スコアの並びが揃っているか。
#
# 「アウェー vs ホーム」に直したとき、直す場所が8つあった。1つでも
# 残ると、対戦名は左がアウェーなのにスコアは左がホーム、という形で
# 別の試合に見える。動かしても例外は出ない。
print("\n--- 対戦名とスコアの並び ---")
import weekly_stats as _ws  # noqa: E402

_g = {"abbr_matchup": "ARI vs BOS", "matchup": "ダイヤモンドバックス vs レッドソックス",
      "home_abbr": "BOS", "away_abbr": "ARI",
      "home_team_name": "レッドソックス", "away_team_name": "ダイヤモンドバックス",
      "league": "MLB",
      "final_score": {"home": 9, "away": 4, "winner": "home"}}
_rows = _ws.day_lines([_g])
check("スコアはアウェー先", _rows[0][1] if _rows else "", "4 - 9")
check("勝った側はホーム", _rows[0][4] if _rows else "", "レッドソックス")
# 生成側も同じ向きか
import notability_engine as _ne  # noqa: E402
check("生成が away を先に置いている",
      'f"{away_name} vs {home_name}"' in
      (ROOT / "notability_engine.py").read_text(encoding="utf-8"), True)
check("サイトも away を先に置いている",
      "awayLabel + ' vs ' + homeLabel" in
      (ROOT / "web" / "index.html").read_text(encoding="utf-8"), True)


# 公開時刻が1か所からしか来ていないか。
#
# 16:30/17:30/21:00 が healthcheck・early_views・ワークフローの3か所に
# 書き写されていた。時刻を動かすたびに直し忘れる場所が増える。
# 一次情報は post_common.DAILY_LINEUP だけにする。
print("\n--- 公開時刻の出どころ ---")
_at = {k: at for k, _, _, at in pc.DAILY_LINEUP}
check("健康診断が一覧と同じ時刻を見ている",
      {k: a for k, _, a, _ in hc.EXPECTED_DAILY + hc.OPTIONAL_DAILY}, _at)
import early_views as _ev  # noqa: E402
check("初動の見出しも一覧から作られている",
      all(_ev.KIND_LABEL.get(k, "").startswith(a) for k, a in _at.items()),
      True)
# ワークフローが持つ公開時刻が、一覧と食い違っていないか
_wf = (ROOT / ".github" / "workflows" / "morning_recap.yml").read_text(
    encoding="utf-8")
for _k, _mode in (("morning", "players"), ("postseason", "postseason"),
                  ("morning_voices", "voices"), ("morning_press", "press")):
    # 同じ行で見る。以前は「その文字列がファイルのどこかにあるか」
    # だったので、17:00の枠が2つあるうちの片方だけ動かしても通った。
    _pat = re.compile(r"^\s*" + re.escape(_mode) + r"\)\s*AT=\"([^\"]*)\"",
                      re.M)
    _m = _pat.search(_wf)
    check(f"ワークフローの {_mode} が {_at[_k]}",
          _m.group(1) if _m else "(行が無い)", _at[_k])

print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
