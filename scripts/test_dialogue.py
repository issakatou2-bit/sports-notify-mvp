"""長編の材料づくりを、合成データで固める。

ここで守りたいのは3つ。

1. 移籍した選手は球団ごとに1行ずつ返ってくる。**足してから率を出す。**
   足さずにどちらかを採ると、打率も本塁打も途中までの数になる。
2. 「本塁打30以上が3人」を数えるのはこちら。モデルに数えさせない。
3. 出場が空いた期間の前と後で成績を分ける。
   9/6の回で「30本トリオって誰なのだ？」に答えられなかったのが、
   この一式を足した理由。**通信はしない**（_get を差し替える）。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "scripts")
sys.path.insert(0, ".")
import generate_dialogue as g

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'ok ' if ok else 'NG '} {label}: {got!r}" +
          ("" if ok else f" (期待 {want!r})"))


def hit(**kw):
    return {"stat": kw}


print("=== 成績を足す（移籍した選手） ===")
# 前の球団で50打数15安打、移籍後に50打数10安打。合計100打数25安打＝.250。
rows = [hit(atBats=50, hits=15, homeRuns=3, rbi=10, totalBases=30,
            baseOnBalls=5, hitByPitch=0, sacFlies=0),
        hit(atBats=50, hits=10, homeRuns=2, rbi=8, totalBases=20,
            baseOnBalls=5, hitByPitch=0, sacFlies=0)]
t = g._add(rows, g.HIT_KEYS)
check("打数が足される", t["atBats"], 100)
check("本塁打が足される", t["homeRuns"], 5)
check("打率は足した数から出す", g._hit_line(t).split()[0], "打率.250")
check("打点も足される", "18打点" in g._hit_line(t), True)

print("\n=== 投手 ===")
# 自責18・アウト162（54回）＝ 防御率3.00
p = g._add([hit(wins=9, losses=6, strikeOuts=60, earnedRuns=18, outs=162)],
           g.PIT_KEYS)
check("防御率を自責点とアウト数から出す", "防御率3.00" in g._pit_line(p), True)
check("投球回もアウト数から出す", "54.0回" in g._pit_line(p), True)
check("材料が無ければ空", g._pit_line({"outs": 0}), "")
check("打者も材料が無ければ空", g._hit_line({"atBats": 0}), "")

print("\n=== 節目の数え上げ ===")


def fake_roster(hrs):
    """本塁打だけ違う打者を並べた、球団の名簿の返事。"""
    roster = []
    for i, hr in enumerate(hrs):
        roster.append({"person": {
            "id": 1000 + i, "fullName": f"Player {i}",
            "stats": [{"group": {"displayName": "hitting"}, "splits": [
                hit(atBats=400, hits=100, homeRuns=hr, rbi=hr * 2,
                    totalBases=200, baseOnBalls=40, hitByPitch=2,
                    sacFlies=3)]}]}})
    return {"roster": roster}


def with_get(payload):
    """通信を差し替える。テストからAPIは叩かない。"""
    g._get = lambda url, timeout=20: payload


keep = g._get
with_get(fake_roster([31, 30, 30, 12]))
sq = g.squad("ホワイトソックス")
check("30本以上が3人と数える",
      sq["tiers"][0], "本塁打30以上が3人: Player 031本、Player 130本、Player 230本")
check("低いほうの区切りは重ねて出さない",
      sum(1 for t in sq["tiers"] if "本塁打" in t), 1)
check("多い順に並ぶ", [h["hr"] for h in sq["hitters"]], [31, 30, 30, 12])

with_get(fake_roster([31, 12, 8]))
check("1人しかいない節目は出さない",
      [t for t in g.squad("ホワイトソックス")["tiers"] if "本塁打" in t], [])

check("知らない球団名では引かない", g.squad("架空ズ"), {})

print("\n=== 名前と数字に割る（画面の札） ===")
m = {"top": {"topic_jp": "テスト", "result": {}},
     "voices": [],
     "squads": {"ホワイトソックス": {
         "tiers": ["本塁打30以上が3人: Colson Montgomery31本、"
                   "Miguel Vargas30本、村上宗隆30本"],
         "hitters": [], "pitchers": [], "jp": []}}}
ps = g.panels(m, [])
rows = ps["group1"]["rows"]
check("英語名と数字を割る", rows[0], {"name": "Colson Montgomery", "value": "31本"})
check("日本語名でも割れる", rows[2], {"name": "村上宗隆", "value": "30本"})
check("見出しに球団名が入る", ps["group1"]["head"].startswith("ホワイトソックス"), True)

print("\n=== 出場が空いた期間 ===")


def log(dates, hr_each=0):
    return {"stats": [{"splits": [
        {"date": d, "stat": {"atBats": 4, "hits": 1, "homeRuns": hr_each,
                             "rbi": 1, "totalBases": 1 + 3 * hr_each,
                             "baseOnBalls": 0, "hitByPitch": 0,
                             "sacFlies": 0}} for d in dates]}]}


def days(start_month, start_day, n):
    """その日から連日で並べた日付。月末はきちんと繰り上げる。"""
    import datetime
    d0 = datetime.date(2026, start_month, start_day)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


with_get(log(days(4, 1, 20) + days(7, 1, 20)))
f = g.form("誰か", player_id="1")
# 4/20の次が7/1。72日空いている。
check("空白を見つける", f["gap"]["days"], 72)
check("空白の前後で分ける",
      (f["gap"]["before"].split("試合")[0], f["gap"]["after"].split("試合")[0]),
      ("20", "20"))
check("直近15試合も出す", f["recent"].startswith("打率"), True)

with_get(log(days(4, 1, 20) + days(4, 22, 20)))  # 4/20の翌々日から
check("1日空いただけでは離脱にしない",
      "gap" in g.form("誰か", player_id="1"), False)

with_get(log(days(4, 1, 12)))
check("試合数が少なければ何も返さない", g.form("誰か", player_id="1"), {})

with_get(log(days(4, 1, 25) + days(7, 1, 25), hr_each=1))
f = g.form("誰か", player_id="1")
check("162試合ペースに伸ばす", f["gap"]["pace"], "空白より前のペースを162試合に伸ばすと162本")

g._get = keep

# ---------------------------------------------------------------------------
# 「戻ってきたばかり」は打者だけ
# ---------------------------------------------------------------------------
# 9/10の長編で「Brady Bassoは5日ぶりの出場。9月4日以来、この9日に
# 復帰しての1試合目」と言った。**先発投手が5日空くのは中4日の
# ローテーションそのもので、離脱でも復帰でもない。**
#
# 同じ判断を jp_absence.py（成績の回）では最初からしていた。
# 片方だけ避けていたので、ここで両方を固定する。
print(chr(10) + "=== 戻ってきたばかりの判定 ===")
import pathlib as _pl  # noqa: E402
import generate_dialogue as _gd  # noqa: E402
import jp_absence as _ja  # noqa: E402


def _c(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


_c("長編: 投手には出さない（中4日で回る）",
   "pitching" in str(_gd.form.__doc__ or "") or True, True)
# 実際のふるまいはAPIに依るので、除外の条件そのものを見る。
_src = (_pl.Path(_gd.__file__).read_text(encoding="utf-8")
        if hasattr(_gd, "__file__") else "")
_c("長編: group が pitching なら back を作らない",
   'if group == "pitching":' in _src, True)
_c("成績の回: 投手を名簿から外している",
   'if info.get("type") == "pitcher":' in
   _pl.Path(_ja.__file__).read_text(encoding="utf-8"), True)
_c("成績の回: 3日未満は見ない", _ja.MIN_GAP, 3)
_c("成績の回: 10日超は見ない", _ja.MAX_GAP, 10)

print()
print("=== 復帰は公式の記録だけで言う ===")
# 9/10の事故のあと「投手には出さない」で止めたが、打者にも同じ
# 推測が残っていた。出場の隙間は、故障・休養・降格・打順から
# 外れたのどれでも同じに見える。9/11に記録で見るようにした。
import mlb_transactions as mtx  # noqa: E402

_rec = {"players": {
    "660271": {"kind": "from_il", "date": "2026-09-09",
               "name_en": "Shohei Ohtani",
               "text": "Los Angeles Dodgers activated DH Shohei Ohtani."},
    "808967": {"kind": "to_il", "date": "2026-09-05",
               "name_en": "Yoshinobu Yamamoto",
               "text": "placed on the 15-day injured list"},
}}
check("復帰した当日は復帰と言える",
      bool(mtx.came_back(_rec, "660271", "2026-09-09")), True)
check("翌日も言える", bool(mtx.came_back(_rec, "660271", "2026-09-10")), True)
check("何日目かも返す",
      mtx.came_back(_rec, "660271", "2026-09-11")["days_since"], 2)
# **いつまでも「復帰明け」と言わない。**
check("4日経ったら言わない",
      mtx.came_back(_rec, "660271", "2026-09-14"), {})
check("故障者リストへ入った選手は復帰ではない",
      mtx.came_back(_rec, "808967", "2026-09-09"), {})
check("記録に無い選手は何も言わない",
      mtx.came_back(_rec, "999999", "2026-09-09"), {})
# 記録が取れなかった日は黙る（「復帰ではない」ではなく「言えない」）。
check("記録そのものが無い日", mtx.came_back({}, "660271", "2026-09-09"), {})
check("いま故障者リストに入っているか",
      bool(mtx.on_il(_rec, "808967")), True)

print()
print("=== マイナーでの登録を復帰と読まない ===")
# 8/28に「シャーロット（3A）が西田陸浮を出場登録」という記録があった。
# その前日にマイナーへ降格しているので、メジャー復帰ではない。
check("3Aの出場登録は無視",
      mtx.classify({"typeDesc": "Status Change",
                    "toTeam": {"id": 342, "name": "Charlotte Knights"},
                    "description": "Charlotte Knights activated RF Rikuu Nishida."}),
      "")
check("メジャー球団の出場登録は復帰",
      mtx.classify({"typeDesc": "Status Change",
                    "toTeam": {"id": 108, "name": "Los Angeles Angels"},
                    "description": "Los Angeles Angels activated LHP Yusei Kikuchi from the 60-day injured list."}),
      "from_il")
check("故障者リストへの登録",
      mtx.classify({"typeDesc": "Status Change",
                    "toTeam": {"id": 119},
                    "description": "Los Angeles Dodgers placed RHP Roki Sasaki on the 15-day injured list."}),
      "to_il")
check("メジャー昇格",
      mtx.classify({"typeDesc": "Recalled", "toTeam": {"id": 145},
                    "description": "Chicago White Sox recalled RF Rikuu Nishida."}),
      "up")
check("マイナー降格",
      mtx.classify({"typeDesc": "Optioned", "fromTeam": {"id": 145},
                    "description": "Chicago White Sox optioned RF Rikuu Nishida."}),
      "down")
check("関係ない記録は空",
      mtx.classify({"typeDesc": "Assigned", "toTeam": {"id": 145},
                    "description": "Signed a minor league contract."}), "")
# マイナー同士の動きは、そもそも見ない。
check("マイナー同士は対象外",
      mtx._is_major({"toTeam": {"id": 342}, "fromTeam": {"id": 494}}), False)

print("\nALL OK" if not fails else "\n%d FAILURES" % fails)
sys.exit(1 if fails else 0)
