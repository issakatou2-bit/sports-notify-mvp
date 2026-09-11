#!/usr/bin/env python3
"""サッカーの順位争いの材料が、嘘にならないか。

なぜ検査が要るのか:
  順位の話は**ずれたらすぐ嘘になる。**「CL圏内」と言いながら
  圏外のクラブを映す、「残留圏外」と言いながら17位のクラブを出す、
  といった間違いは、順位表を見れば誰でも分かってしまう。

  実際 cutline を添字で切っていたとき、17位が2クラブいる日に
  「17位のトッテナムは残留圏外」と出ていた。9/11の実データでは
  6大会のうち5つで同順位が起きていた。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import soccer_race as sr  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def table(code, pts, played=6, teams=None):
    """順位表。勝点を上から渡す。同順位は position を明示する。"""
    names = teams or ["Club %d" % (i + 1) for i in range(len(pts))]
    return [{"position": i + 1, "team": names[i], "points": p,
             "played": played, "won": 0, "draw": 0, "lost": 0,
             "gf": 0, "ga": 0}
            for i, p in enumerate(pts)]


PL_TEAMS = ["Manchester City FC", "Arsenal FC", "Chelsea FC",
            "Newcastle United FC", "Aston Villa FC", "Liverpool FC",
            "Everton FC", "Brentford FC", "Leeds United FC",
            "Brighton & Hove Albion FC"]


def preview(code, pts, played=6, teams=None, name="プレミアリーグ"):
    return {"generated_at": "2026-09-11T00:00:00Z",
            "competitions": [{"code": code, "name_jp": name,
                              "table": table(code, pts, played, teams)}]}


print("--- 節が足りない大会は出さない ---")
# 開幕直後は順位に意味が無い。**黙って省くと「データが無い」のか
# 「まだ早い」のか区別できない**ので、ready を False にして返す。
d = sr.build(preview("PL", [9, 7, 6, 5, 4, 3], played=3))
check("3節では出さない", d["competitions"][0]["ready"], False)
check("使う大会に入らない", d["picked"], [])
check("節の数は返す", d["competitions"][0]["played"], 3)

d = sr.build(preview("PL", [14, 12, 11, 10, 8, 7], played=6))
check("6節なら出す", d["competitions"][0]["ready"], True)
check("使う大会に入る", d["picked"], ["PL"])

print()
print("--- 線の前後 ---")
c = d["competitions"][0]
lines = {ln["label"]: ln for ln in c["lines"]}
check("CL圏内の線がある", "CL圏内" in lines, True)
check("圏内の最後は4位", lines["CL圏内"]["inside"][-1]["position"], 4)
check("圏外の最初は5位", lines["CL圏内"]["outside"][0]["position"], 5)
check("線をまたぐ差", lines["CL圏内"]["diff"], 2)
# 9月に「残留争い」と言っても、38節のうち6節しか終わっていない。
check("残留は折り返し前には出さない", "残留" in lines, False)

d19 = sr.build(preview("PL", list(range(40, 20, -1)), played=20))
check("折り返しを過ぎたら残留も出す",
      "残留" in {ln["label"] for ln in d19["competitions"][0]["lines"]},
      True)

print()
print("--- クラブ名は日本語表記 ---")
d = sr.build(preview("PL", [14, 12, 11, 10, 8, 7, 6, 5, 4, 3],
                     played=6, teams=PL_TEAMS))
c = d["competitions"][0]
names = [r["team"] for ln in c["lines"] for r in ln["inside"] + ln["outside"]]
check("英語名が残っていない",
      [n for n in names if any(ch.isascii() and ch.isalpha() for ch in n)],
      [])

print()
print("--- 日本人選手と、その線までの差 ---")
# リバプール6位、ブライトン10位、リーズ9位。
jp = {x["name"]: x for x in c["jp"]}
check("リバプールの遠藤航が入る", "遠藤航" in jp, True)
check("順位も返す", jp["遠藤航"]["position"], 6)
check("クラブ名は日本語", jp["遠藤航"]["club_jp"], "リバプール")
check("線までの差が付く", bool(jp["遠藤航"].get("lines")), True)
# **言い方は1か所で作る。**画面と読み上げで別々に組み立てると
# 食い違う（成績の回で一度起きている）。
check("そのまま読める形の文が付く",
      bool(jp["遠藤航"]["lines"][0].get("text")), True)

print()
print("--- 言い方 ---")
check("圏外で差あり",
      sr.phrase({"label": "CL圏内", "side": "outside", "diff": 3}),
      "CL圏内まで勝点3")
# 差0で「まで勝点0」は意味が通らない。勝点では並んでいて
# 得失点差で下、という状態。
check("圏外で差0",
      sr.phrase({"label": "EL圏内", "side": "outside", "diff": 0}),
      "EL圏内と勝点で並んでいる")
check("圏内で差あり",
      sr.phrase({"label": "CL圏内", "side": "inside", "diff": 2}),
      "CL圏内。落ちるまで勝点2")
check("圏内で差0",
      sr.phrase({"label": "残留", "side": "inside", "diff": 0}),
      "残留だが、すぐ下と勝点で並んでいる")
check("材料が無ければ空", sr.phrase({}), "")
check("差が欠けていれば空",
      sr.phrase({"label": "CL圏内", "side": "inside"}), "")

print()
print("--- 線から遠すぎる話はしない ---")
# 16位のクラブに「CL圏内まで勝点6」と言っても、間に12クラブいる。
far = sr.build(preview(
    "PL", [20, 19, 18, 17, 16, 15, 14, 13, 12, 11,
           10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
    played=10,
    teams=["T%d" % i for i in range(1, 16)] + [
        "Brighton & Hove Albion FC", "Liverpool FC", "Leeds United FC",
        "T19", "T20"]))
_far_jp = {x["name"]: x for x in far["competitions"][0]["jp"]}
check("16位のクラブに上位の線を付けない",
      _far_jp.get("三笘薫", {}).get("lines"), [])
check("それでも順位表には出る", _far_jp.get("三笘薫", {}).get("position"), 16)

print()
print("--- 昨日からの動き ---")
now = preview("PL", [14, 12, 11, 10, 8, 7], played=6,
              teams=["A", "B", "C", "D", "E", "F"])
before = preview("PL", [14, 12, 11, 10, 8, 7], played=5,
                 teams=["A", "B", "C", "E", "D", "F"])
d = sr.build(now, before)
mv = {ln["label"]: ln["moved"] for ln in d["competitions"][0]["lines"]}
check("CL圏内に入ったクラブ", mv["CL圏内"]["in"], ["D"])
check("出たクラブ", mv["CL圏内"]["out"], ["E"])
# **「変化なし」と「昨日の記録が無い」を混ぜない。**
d0 = sr.build(now)
check("昨日の記録が無い日は空",
      [ln["moved"] for ln in d0["competitions"][0]["lines"]][0], {})

print()
print("--- 出す順 ---")
# 題に日本人選手の名前があると平均395再生、無いと192再生。
# **先頭に来た大会が題になる**ので、名前がある大会を先に。
two = {"generated_at": "x", "competitions": [
    {"code": "PD", "name_jp": "ラ・リーガ",
     "table": table("PD", [14, 12, 11, 10, 8, 7], 6,
                    ["Real Madrid CF", "FC Barcelona", "Sevilla FC",
                     "Real Betis Balompié", "Villarreal CF",
                     "Athletic Club"])},
    {"code": "PL", "name_jp": "プレミアリーグ",
     "table": table("PL", [14, 12, 11, 10, 8, 7], 6, PL_TEAMS[:6])},
]}
d = sr.build(two)
check("日本人選手がいる大会を先に", d["picked"][0], "PL")

print()
print("--- 欠けても落ちない ---")
check("空の材料", sr.build({})["picked"], [])
check("順位表が空の大会",
      sr.build({"competitions": [{"code": "PL", "table": []}]})
      ["competitions"][0]["ready"], False)
check("知らない大会は線が無い",
      sr.build({"competitions": [
          {"code": "XX", "table": table("XX", [9, 7, 5, 3], 9)}]})
      ["competitions"][0]["lines"], [])
check("played が欠けている行",
      sr.build({"competitions": [{"code": "PL", "table": [
          {"position": 1, "team": "A", "points": 3}]}]})
      ["competitions"][0]["played"], 0)
check("要約が落ちない", isinstance(sr.summary(sr.build({})), str), True)

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
