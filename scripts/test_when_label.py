"""
「今夜」「明日」の呼び分けを、両競技の実際の開始時刻で検証する。

なぜこのテストが要るのか:
  欧州サッカーの深夜キックオフに合わせて「未明」の境界を9時にしたところ、
  MLBまで飲み込んだ。MLBの開始はJST 01時〜11時で07〜08時台が最多なので、
  08:15開始の試合が「今夜」になり、19時に見る人へ翌朝の試合を
  「今夜の注目試合」と呼んでいた。RSSにも動画のタイトルにも出ていた。

  MLBの開始時刻は自分で実測(94試合)していたのに、境界を決めるときに
  そこと突き合わせていなかった。片方の競技だけを見て決めない。
"""
import datetime
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "scripts")

import post_common as pc  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {label}: {got}" + ("" if ok else f" (期待 {want})"))


class FakeDT:
    _now = None

    @staticmethod
    def now(tz=None):
        return FakeDT._now.replace(tzinfo=tz)


_orig = pc.datetime
pc.datetime = FakeDT


def at(y, m, d, h, mi=0):
    FakeDT._now = datetime.datetime(y, m, d, h, mi)


def g(t):
    return {"start_time_jst": t}


# --- MLB: 19時に生成し、翌日の試合を予告する -------------------------------
# 実測(94試合)の開始分布は JST 01〜11時。07〜08時台が最多。
print("--- MLB 日次(19:00生成) ---")
at(2026, 8, 15, 19)
check("翌08:15 は明日", pc.when_label("08/16 08:15"), "明日")
check("翌11:10 は明日", pc.when_label("08/16 11:10"), "明日")
check("翌07:05 は明日", pc.when_label("08/16 07:05"), "明日")
check("翌03:20 は今夜", pc.when_label("08/16 03:20"), "今夜")
check("見出しは多数決で明日",
      pc.today_or_tomorrow_label([g("08/16 03:20"), g("08/16 08:10"),
                                  g("08/16 08:15")]),
      "明日の注目試合")

# --- 欧州サッカー: 19時台に生成し、20時に公開する ---------------------------
# キックオフは JST 21時〜翌6時。
print("\n--- 欧州サッカー 日次(19:20生成) ---")
at(2026, 8, 22, 19, 20)
check("当日22:00 は今夜", pc.when_label("08/22 22:00"), "今夜")
check("翌00:30 は今夜", pc.when_label("08/23 00:30"), "今夜")
check("翌04:00 は今夜", pc.when_label("08/23 04:00"), "今夜")
check("翌05:00 は今夜", pc.when_label("08/23 05:00"), "今夜")
check("見出しは今夜",
      pc.today_or_tomorrow_label([g("08/23 04:00"), g("08/23 02:30"),
                                  g("08/22 22:00")]),
      "今夜の注目試合")

# --- 未明の書き添え ---------------------------------------------------------
print("\n--- 時刻の表示 ---")
check("未明は添える", pc.kickoff_display("08/23 04:00"), "08/23 04:00（未明）")
check("朝は添えない", pc.kickoff_display("08/16 08:15"), "08/16 08:15")
check("空はそのまま", pc.kickoff_display(""), "")

# --- 壊れた入力 -------------------------------------------------------------
print("\n--- 読めない値 ---")
check("空文字", pc.when_label(""), "")
check("形式違い", pc.when_label("2026-08-16 08:15"), "")
check("見出しは空でも落ちない", pc.today_or_tomorrow_label([]), "注目試合")

pc.datetime = _orig
print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
