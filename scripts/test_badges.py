#!/usr/bin/env python3
"""名前のある記録（QS・二桁奪三振・猛打賞など）の判定と加点。

なぜ検査が要るのか:
  **点数に効くので、間違えると順位が変わる。**しかも呼び名は
  画面と読み上げの両方に出るので、条件を1つずらすと
  「QSでもない日をQSと呼ぶ」ことになる。数字の誤りと同じ重さ。

  いちばんありそうな壊れ方は**包含関係**。9回を自責0で投げた日は
  完封でも完投でもHQSでもQSでもある。そのまま並べると
  記録が4つ付いた日に見えるし、加点も4つぶん乗る。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import morning_recap as mr  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%s %s: %r%s" % ("ok " if ok else "NG ", label, got,
                           "" if ok else "   (期待 %r)" % (want,)))


def P(**kw):
    """投手の1登板。指定しなかった項目は0。"""
    row = {"type": "pitcher", "ip": "0.0", "er": 0, "hits": 0, "so": 0,
           "bb": 0, "gs": 0, "saves": 0, "save_opp": 0, "holds": 0,
           "blown": 0, "wins": 0}
    row.update(kw)
    return row


def B(**kw):
    """打者の1試合。"""
    row = {"type": "batter", "ab": 0, "hits": 0, "hr": 0, "rbi": 0,
           "so": 0, "bb": 0, "hbp": 0, "sb": 0, "doubles": 0,
           "triples": 0, "tb": 0}
    row.update(kw)
    return row


def labels(row):
    return [b["label"] for b in mr.badges(row)]


print("--- 投手：包含するものは1つだけ ---")
# 9回を自責0。完封・完投・HQS・QSの全部に当てはまる。
check("完封の日は完封だけ",
      labels(P(ip="9.0", er=0, hits=2, so=8, bb=1, gs=1)), ["完封"])
# 無四球は回数・失点とは別の軸なので、完封と並んでよい。
check("完封＋無四球は両方出る",
      labels(P(ip="9.0", er=0, hits=2, so=8, bb=0, gs=1)),
      ["完封", "無四球"])
check("9回5失点は完投だけ（HQSにはならない）",
      labels(P(ip="9.0", er=5, hits=9, so=4, bb=2, gs=1)), ["完投"])
check("7回2失点はHQS", labels(P(ip="7.0", er=2, hits=5, so=6, bb=1, gs=1)),
      ["HQS"])
check("6回3失点はQS", labels(P(ip="6.0", er=3, hits=6, so=5, bb=2, gs=1)),
      ["QS"])
check("5回2失点はどちらでもない",
      labels(P(ip="5.0", er=2, hits=4, so=3, bb=1, gs=1)), [])
check("6回4失点はQSではない",
      labels(P(ip="6.0", er=4, hits=7, so=3, bb=2, gs=1)), [])
# 6.2回は6回3分の2。小数として6.2と読むとQSを落とす。
check("6.2回3失点もQS（回の小数を取り違えない）",
      labels(P(ip="6.2", er=3, hits=6, so=4, bb=1, gs=1)), ["QS"])
# 11奪三振も付く。奪三振は回数・失点とは別の軸なので並んでよい。
check("無安打無得点はノーヒッター",
      labels(P(ip="9.0", er=0, hits=0, so=11, bb=2, gs=1)),
      ["ノーヒッター", "二桁奪三振"])

print()
print("--- 投手：救援にQSは付かない ---")
# **QS・HQSは先発の記録。**gs を見ないと、7回を投げた救援に付く。
check("7回を投げた救援にHQSは付かない",
      labels(P(ip="7.0", er=1, hits=3, so=5, bb=0, gs=0)), [])
check("救援の無四球も付かない（先発の記録）",
      labels(P(ip="6.0", er=0, hits=1, so=4, bb=0, gs=0)), [])

print()
print("--- 投手：セーブとホールドは記録の実数だけ ---")
check("セーブが付いた日", labels(P(ip="1.0", so=2, saves=1)), ["セーブ"])
check("ホールドが付いた日", labels(P(ip="1.0", so=1, holds=1)), ["ホールド"])
# セーブ機会で投げて付かなかった日を「セーブ」と書くと嘘になる。
check("セーブ機会だが付かなかった日は何も出ない",
      labels(P(ip="1.0", so=1, save_opp=1)), [])
check("逆転を許した日も何も出ない",
      labels(P(ip="0.2", er=3, hits=3, blown=1, save_opp=1)), [])
check("セーブとホールドは同時に出さない",
      labels(P(ip="1.0", saves=1, holds=1)), ["セーブ"])

print()
print("--- 投手：奪三振 ---")
check("10奪三振は独立して並ぶ",
      labels(P(ip="7.0", er=1, hits=3, so=10, bb=1, gs=1)),
      ["HQS", "二桁奪三振"])
check("9奪三振では付かない",
      labels(P(ip="7.0", er=1, hits=3, so=9, bb=1, gs=1)), ["HQS"])
check("救援の10奪三振も数える",
      labels(P(ip="4.0", er=0, hits=1, so=10, bb=0, gs=0)), ["二桁奪三振"])

print()
print("--- 打者：包含するものは1つだけ ---")
check("2本塁打はマルチ本塁打だけ（マルチ安打を並べない）",
      labels(B(ab=4, hits=2, hr=2, rbi=4, tb=8)), ["マルチ本塁打"])
check("3安打2本塁打もマルチ本塁打",
      labels(B(ab=5, hits=3, hr=2, rbi=5, tb=10)),
      ["マルチ本塁打", "5打点"])
check("3安打は猛打賞", labels(B(ab=4, hits=3, doubles=1, tb=4, rbi=2)),
      ["猛打賞"])
check("2安打はマルチ安打", labels(B(ab=4, hits=2, tb=2, rbi=1)),
      ["マルチ安打"])
check("1安打では付かない", labels(B(ab=4, hits=1, tb=1)), [])
check("サイクル安打",
      labels(B(ab=5, hits=4, hr=1, doubles=1, triples=1, rbi=4, tb=10)),
      ["サイクル安打"])
# 三塁打が無い日をサイクルと呼ばない。
check("三塁打が無ければサイクルではない",
      labels(B(ab=5, hits=4, hr=1, doubles=2, triples=0, rbi=4, tb=9)),
      ["猛打賞"])
check("3本塁打", labels(B(ab=5, hits=3, hr=3, rbi=7, tb=12)),
      ["3本塁打", "5打点"])
check("マルチ盗塁", labels(B(ab=4, hits=1, sb=2, tb=1)), ["マルチ盗塁"])
check("無安打の日は何も出ない", labels(B(ab=4, hits=0, so=3)), [])

print()
print("--- 打者の呼び名が投手に出ない（逆も） ---")
# 投手の hits は**被安打**。打者の表を投手に当てると、
# 打たれた日に「猛打賞」が付く。
check("3被安打の投手に猛打賞は付かない",
      labels(P(ip="7.0", er=1, hits=3, so=10, bb=1, gs=1)),
      ["HQS", "二桁奪三振"])
check("3三振した打者にQSは付かない",
      labels(B(ab=4, hits=0, so=3)), [])

print()
print("--- 加点が点数に乗る ---")
# 9/10の実データ。**この並びを直すために入れた。**
yamamoto = P(ip="7.0", er=1, hits=3, so=10, bb=1, gs=1, wins=1)
murakami = B(ab=3, hits=1, hr=1, rbi=1, so=2, hbp=1, tb=4)
check("山本由伸（7回1失点10奪三振）", mr.contribution(yamamoto), 137)
check("村上宗隆（3打数1安打1本塁打）", mr.contribution(murakami), 89)
check("好投した投手が本塁打1本の打者より上に来る",
      mr.contribution(yamamoto) > mr.contribution(murakami), True)
check("加点の合計", mr.badge_points(yamamoto), 24)
check("何も付かない日は0", mr.badge_points(murakami), 0)

print()
print("--- 投手と打者の倍率がそろっているか ---")
# 9/11に倍率を変えた（投手1.2→1.8、打者3.6→3.1）。それまでは
# **投手が100点にほとんど届かなかった**（26日・151人日で2%、
# 打者は16%）。完封162点の上に打者の2本塁打182点が来ていた。
_shutout = P(ip="9.0", er=0, hits=2, so=8, bb=0, gs=1)
_two_hr = B(ab=4, hits=2, hr=2, rbi=4, tb=8, so=1)
check("完封が2本塁打より上",
      mr.contribution(_shutout) > mr.contribution(_two_hr), True)
# 1試合3本塁打は完封よりも稀なので、そこは打者が上でよい。
_three_hr = B(ab=5, hits=3, hr=3, rbi=7, tb=12)
check("3本塁打は完封より上",
      mr.contribution(_three_hr) > mr.contribution(_shutout), True)
# 倍率は定数から読む（数字をここに書き写すと、変えたときにずれる）。
check("投手の倍率が定数になっている",
      isinstance(mr.PITCHER_SCALE, float), True)

print()
print("--- 投げて打った日は二重に足さない ---")
two = {"type": "two_way",
       "pitching": P(ip="7.0", er=0, hits=3, so=10, bb=1, gs=1),
       "batting": B(ab=4, hits=3, hr=3, rbi=6, tb=12)}
p_only = mr.contribution({**two["pitching"], "type": "pitcher"})
b_only = mr.contribution({**two["batting"], "type": "batter"})
check("投手ぶんと打者ぶんの和になる", mr.contribution(two), p_only + b_only)
# 7回なので完封ではない（完封は27アウト）。投げた側はHQS。
check("呼び名は両方並ぶ", labels(two),
      ["HQS", "二桁奪三振", "3本塁打", "5打点"])

print()
print("--- 画面と読み上げ ---")
# 同じ点のときの並びは badges() の登録順で決まる。
# 回数と失点の軸（HQS）が先、奪三振が後。
check("画面は略記のまま", mr.badge_labels(yamamoto, limit=3),
      ["HQS", "二桁奪三振"])
# **VOICEVOXにQSを渡すと読みが確かめられない。**声は開いて言う。
check("読み上げは開く", mr.badge_speech(yamamoto, limit=3),
      ["ハイクオリティスタート", "二桁奪三振"])
check("限りを超えたら切る", len(mr.badge_labels(
    P(ip="9.0", er=0, hits=0, so=12, bb=0, gs=1), limit=2)), 2)
check("切っても点数には残る",
      mr.badge_points(P(ip="9.0", er=0, hits=0, so=12, bb=0, gs=1)),
      60 + 12 + 5)

print()
print("--- 欠けても落ちない ---")
check("空の行", mr.badges({}), [])
check("項目がNone", mr.badges({"type": "pitcher", "ip": None,
                               "er": None, "so": None}), [])
check("回が読めない文字列",
      mr.badges({"type": "pitcher", "ip": "-", "er": 0, "gs": 1}), [])
check("投げて打った日で片方が欠ける",
      mr.contribution({"type": "two_way", "pitching": P(ip="1.0"),
                       "batting": B()}) >= 0, True)

print(chr(10) + ("ALL OK" if not fails else "%d FAILURES" % fails))
sys.exit(1 if fails else 0)
