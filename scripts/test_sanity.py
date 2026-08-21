#!/usr/bin/env python3
"""
常識の検査が、正しい行を止めないか。

なぜ要るのか:
  8/21の「今日の1人」が出なかった。原因は前日に入れたこの検査で、
  通算成績を今季の幅で見ていた。Zach Netoの通算443安打・79本塁打・
  234打点が、今季の上限(270・75・200)を3か所で超える。
  この枠は通算成績そのものが主題なので、毎回止まる作りだった。

  検査が誤って止めると、被害は「動画が1本出ない」で済まない。
  出ない理由が検査だと気づくまで、原因を別の場所で探すことになる。

  なので、幅の側を試験する。歴代記録を入れて通ることを確かめる。
  記録を通さない幅は、いつか必ず本物を止める。

使い方:
  python3 scripts/test_sanity.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import sanity  # noqa: E402

fails = 0


def ok(label, line):
    """正しい行。止めてはいけない。"""
    global fails
    bad = sanity.check_line("X", line)
    if bad:
        fails += 1
        print("NG  止めてしまった [%s] %s" % (label, line))
        for b in bad:
            print("      " + b[:96])
    else:
        print("ok  通る [%s] %s" % (label, line[:52]))


def ng(label, line):
    """壊れた行。止めなければいけない。"""
    global fails
    if not sanity.check_line("X", line):
        fails += 1
        print("NG  素通りさせた [%s] %s" % (label, line))
    else:
        print("ok  止める [%s] %s" % (label, line[:52]))


print("--- 歴代記録が通ること(幅が狭すぎないか) ---")
ok("通算安打 ピート・ローズ", "通算 4256安打　打率.303")
ok("通算本塁打 バリー・ボンズ", "通算 762本塁打　1996打点")
ok("通算打点 ハンク・アーロン", "通算 2297打点　3771安打")
ok("通算盗塁 リッキー・ヘンダーソン", "通算 1406盗塁　3055安打")
ok("通算勝利 サイ・ヤング", "通算 511勝　316敗　防御率2.63")
ok("通算奪三振 ノーラン・ライアン", "通算 5714奪三振　324勝")
ok("通算セーブ マリアノ・リベラ", "通算 652セーブ　防御率2.21")

print("\n--- ふつうの行が通ること ---")
ok("今日の1人(実データ)", "通算 打率.243　443安打　79本塁打　234打点　78盗塁")
ok("今季", "今季 打率.231　21本塁打　61打点")
ok("昨季", "昨季 打率.257　26本塁打　62打点")
ok("一試合(打者)", "6打数5安打　1本塁打　1二塁打　7打点")
ok("一試合(投手)", "今季 12勝5敗　防御率2.85　180奪三振")
ok("完投", "9.0回 12奪三振 1失点")

print("\n--- 壊れた行は止まること(幅が広すぎないか) ---")
ng("打数より安打が多い", "2打数3安打")
ng("安打より本塁打が多い", "4打数1安打　2本塁打")
ng("今季の本塁打が記録超え", "今季 450本塁打")
ng("防御率の桁", "今季 防御率180.00")
ng("通算でもありえない", "通算 50000安打　9000本塁打")
ng("回に対する奪三振", "5.0回 20奪三振")

print("\n--- 原稿の言い回しで誤検出しないこと ---")
import json  # noqa: E402
import tempfile  # noqa: E402

good = [
    "大谷翔平は今季45本塁打、打率2割9分1厘。",
    "佐々木朗希は6回3分の1を投げて7奪三振、1失点。",
    "通算443安打、79本塁打。25歳の遊撃手です。",
    "打率3割2分ちょうど、今季140安打。",
    "この試合は5対3でドジャースが勝ちました。",
]
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                 encoding="utf-8") as f:
    json.dump({"segments": [{"text": t} for t in good]}, f,
              ensure_ascii=False)
    path = f.name
found = sanity.check_narration([path])
if found:
    fails += 1
    print("NG  原稿を誤って止めた:")
    for b in found:
        print("      " + b[:96])
else:
    print("ok  正しい原稿は通る")

print("\nALL OK" if not fails else "\n%d FAILURES" % fails)
sys.exit(1 if fails else 0)
