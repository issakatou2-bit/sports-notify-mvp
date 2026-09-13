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
print("--- 線から遠すぎる話はしない（勝ち点で見る） ---")
# **9/13に順位の差から勝ち点の差へ変えた。**本番で初めて分かった。
# ラ・リーガ6節の日、久保建英のレアル・ソシエダは11位で、線
# （CL圏内4位・EL圏内5位）から6〜7つ離れていた。だが勝ち点では
#
#     4位 セビージャ      勝点10
#     5位 レアル・ベティス 勝点 9
#    11位 レアル・ソシエダ 勝点 7
#
# EL圏内まで勝点2、CL圏内まで勝点3。**1勝で届く距離**だった。
# 順位で切ると、いちばん話になる時期に何も出せない。
_tight = {"generated_at": "2026-09-13T00:00:00Z", "competitions": [{
    "code": "PD", "name_jp": "ラ・リーガ",
    "table": [
        {"position": 1, "team": "FC Barcelona", "points": 12, "played": 6,
         "gf": 0, "ga": 0},
        {"position": 2, "team": "Real Madrid CF", "points": 12, "played": 6,
         "gf": 0, "ga": 0},
        {"position": 3, "team": "Deportivo Alaves", "points": 10,
         "played": 6, "gf": 0, "ga": 0},
        {"position": 4, "team": "Sevilla FC", "points": 10, "played": 6,
         "gf": 0, "ga": 0},
        {"position": 5, "team": "Real Betis Balompie", "points": 9,
         "played": 6, "gf": 0, "ga": 0},
        {"position": 6, "team": "RC Deportivo La Coruna", "points": 8,
         "played": 6, "gf": 0, "ga": 0},
        {"position": 7, "team": "RCD Espanyol", "points": 7, "played": 6,
         "gf": 0, "ga": 0},
        {"position": 8, "team": "Athletic Club", "points": 7, "played": 6,
         "gf": 0, "ga": 0},
        {"position": 9, "team": "Atletico de Madrid", "points": 7,
         "played": 6, "gf": 0, "ga": 0},
        {"position": 10, "team": "Real Racing Club", "points": 7,
         "played": 6, "gf": 0, "ga": 0},
        {"position": 11, "team": "Real Sociedad de Futbol", "points": 7,
         "played": 6, "gf": 0, "ga": 0},
        {"position": 12, "team": "CA Osasuna", "points": 6, "played": 6,
         "gf": 0, "ga": 0},
    ]}]}
_d = sr.build(_tight)
_jp = {x["name"]: x for x in _d["competitions"][0]["jp"]}
check("11位でも勝点2差なら出す",
      bool(_jp.get("久保建英", {}).get("lines")), True)
check("いちばん近い線はEL圏内",
      _jp["久保建英"]["lines"][0]["label"], "EL圏内")
check("差は勝点2", _jp["久保建英"]["lines"][0]["diff"], 2)
check("言い方も正しい", _jp["久保建英"]["lines"][0]["text"],
      "EL圏内まで勝点2")
# 勝ち点で離れていれば落とす。
_far = {"generated_at": "2026-09-13T00:00:00Z", "competitions": [{
    "code": "PD", "name_jp": "ラ・リーガ",
    "table": [{"position": i, "team": "T%d" % i, "points": 40 - 3 * i,
               "played": 20, "gf": 0, "ga": 0} for i in range(1, 13)]
    + [{"position": 13, "team": "Real Sociedad de Futbol", "points": 1,
        "played": 20, "gf": 0, "ga": 0}]}]}
_far_jp = {x["name"]: x for x in sr.build(_far)["competitions"][0]["jp"]}
check("勝ち点で離れていれば落とす",
      _far_jp.get("久保建英", {}).get("lines"), [])
check("上限は定数", sr.MAX_POINT_GAP, 6)

print()
print("--- 順位が離れていても勝ち点が近ければ出す（旧・順位差の検査） ---")
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
print("--- 画面と読み上げで、差の言い方が同じか ---")
# **別々に組み立てない。**画面が「勝点で並んでいる」で読み上げが
# 「0点差」になると、どちらが本当か見ている側には確かめようがない。
import generate_morning_short as gms  # noqa: E402

check("差0", gms.race_gap_text(0), "勝点で並んでいる")
check("差あり", gms.race_gap_text(2), "勝点2差")
check("負の差も絶対値で", gms.race_gap_text(-2), "勝点2差")
check("材料が無ければ空", gms.race_gap_text(None), "")

print()
print("--- 順位争いの読み上げ ---")
_race = sr.build(preview("PD", [14, 12, 11, 10, 8, 7], played=6,
                         teams=["Real Madrid CF", "FC Barcelona",
                                "Sevilla FC", "Real Sociedad de Futbol",
                                "Villarreal CF", "Athletic Club"],
                         name="ラ・リーガ"))
_n = gms.build_narration({"race": _race, "date_jst": "2026-09-13",
                          "players": [], "voices": {}, "buzz": [],
                          "talk": {}, "reporters": {}},
                         mode="soccer_race")
_kinds = [x["kind"] for x in _n["segments"]]
check("順位争いの画面が入る", "race_line" in _kinds, True)
check("日本人選手の画面が入る", "race_japanese" in _kinds, True)
_line = next(x for x in _n["segments"] if x["kind"] == "race_line")
check("線の名前を言う", "CL圏内" in _line["text"], True)
# 差の言い方が画面と同じ関数から来ているか。
check("差の言い方が揃っている",
      any(gms.race_gap_text(l["diff"]) in _line["text"]
          for c in _race["competitions"] for l in (c.get("lines") or [])),
      True)

# **日付をずらさない。**成績の回は米国日付を1日進めてJSTにするが、
# 順位表は「いまの順位」なので、ずらす相手がいない。
check("date_jst を持っている", "date_jst" in _race, True)
_intro = _n["segments"][0]["text"]
check("渡した日付がそのまま出る", "9月13日" in _intro, True)

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
