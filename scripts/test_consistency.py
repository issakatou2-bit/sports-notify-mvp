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
    check("タイトルの選手が、材料の選手と同じ", prof["name"] in title, True)
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

_kinds = {k for k, _, _ in pc.DAILY_LINEUP}
check("一覧の区分が、健康診断の見る枠と同じ",
      sorted(expected ^ _kinds), [])
check("一覧に重複が無い", len(pc.DAILY_LINEUP), len(_kinds))
check("説明文が一覧から作られている",
      all(name in "".join(uy.DAILY_LINEUP_LINES)
          for _, name, _ in pc.DAILY_LINEUP), True)


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
    _key = (_h.get("sub") or _h.get("big") or "").strip()
    if _key and _key not in json.dumps(_work[0], ensure_ascii=False):
        _late += 1
    for _i, _g in enumerate(_work):
        if _orig[_order[_i]] != (_g.get("matchup") or _g.get("abbr_matchup")):
            _mismatch += 1

check("冒頭で名乗った試合が、1つ目に来ている日数の欠け", _late, 0)
check("読み上げの試合と、画面が引く試合が同じ", _mismatch, 0)


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

print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
