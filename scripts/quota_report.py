#!/usr/bin/env python3
"""
1日に何をどれだけ消費するのかを出す。

    python3 scripts/quota_report.py

なぜ要るか:
  無料枠や上限にぶつかると、その日の配信が丸ごと止まる。
  ぶつかってから気づくのでは遅い。動画を1本増やすたびに
  どこがどれだけ埋まるのかを、увеличивать前に見えるようにしておく。

数字の出どころ:
  YouTube Data API の単価は公開されている固定値。
  AIのトークン数は max_tokens(上限)から見た最悪値で、
  実際の消費はこれより少ない。
"""

import argparse
import sys

# YouTube Data API v3 の単価(公開値)。1日あたり10,000ユニット。
YT_COSTS = {
    "videos.insert": 1600,
    "thumbnails.set": 50,
    "search.list": 100,
    "videos.list": 1,
    "playlistItems.insert": 50,
}
YT_DAILY_LIMIT = 10_000

# 毎日走るもの。(名前, 呼び出し, 回数)
DAILY_YT = [
    ("日次ショート", "videos.insert", 1),
    ("日次ショート サムネ", "thumbnails.set", 1),
    ("朝: 選手成績", "videos.insert", 1),
    ("朝: 選手成績 サムネ", "thumbnails.set", 1),
    ("朝: 現地の注目度", "videos.insert", 1),
    ("朝: 現地の注目度 サムネ", "thumbnails.set", 1),
    ("朝: 現地の声(press)", "videos.insert", 1),
    ("朝: 現地の声 サムネ", "thumbnails.set", 1),
    ("現地の再生回数を調べる", "search.list", 1),
    ("再生回数の取得", "videos.list", 1),
]

# AIの呼び出し。max_tokensは上限なので、実際はこれより少ない。
DAILY_AI = [
    ("注目試合の理由づけ", "notability_engine.py", 700, 3),
    ("日次ショートの原稿", "generate_narration.py", 300, 3),
    ("現地のファンの声 翻訳", "local_voices.py", 1500, 1),
    ("現地の番記者 翻訳", "local_reporters.py", 1200, 1),
    ("現地の見出し 翻訳", "local_reporters.py", 1200, 1),
]
WEEKLY_AI = [
    ("週次まとめの原稿", "generate_weekly_narration.py", 700, 8),
]

# 認証も上限も無いもの。ここが増えても費用は動かない。
FREE = [
    ("MLB Stats API", "試合・成績・プレーごとの記録", "認証不要・上限なし"),
    ("football-data.org", "サッカーの日程と順位", "無料枠 10リクエスト/分"),
    ("Bluesky 公開API", "番記者の投稿", "認証不要"),
    ("Google ニュース RSS", "現地の見出し", "認証不要"),
    ("Reddit RSS", "現地のファンの投稿", "認証不要・連続取得で429"),
    ("VOICEVOX", "読み上げ音声", "自前で起動・費用なし"),
    ("GitHub Actions", "実行環境", "公開リポジトリは無料"),
    ("GitHub Pages", "サイト配信", "無料"),
    ("OneSignal", "プッシュ通知", "無料枠あり"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", type=int, default=0,
                    help="その日に資産動画を何本上げるか")
    args = ap.parse_args()

    print("=" * 68)
    print("YouTube Data API (1日 10,000ユニット)")
    print("=" * 68)
    total = 0
    for name, call, n in DAILY_YT:
        cost = YT_COSTS[call] * n
        total += cost
        print(f"  {name:26} {call:20} {cost:6,}")
    if args.assets:
        a = (YT_COSTS["videos.insert"] + YT_COSTS["thumbnails.set"]) * args.assets
        total += a
        print(f"  {'資産動画 ' + str(args.assets) + '本':26} "
              f"{'insert+thumb':20} {a:6,}")

    pct = total / YT_DAILY_LIMIT * 100
    print(f"\n  合計 {total:,} / {YT_DAILY_LIMIT:,}  ({pct:.0f}%)")
    left = YT_DAILY_LIMIT - total
    print(f"  残り {left:,} ユニット"
          f" = 資産動画 あと{left // 1650}本")
    if pct > 80:
        print("  ::warning:: 8割を超えています。資産動画を回す余裕がありません")

    print()
    print("=" * 68)
    print("Anthropic API (Haiku 4.5)")
    print("=" * 68)
    day_out = 0
    for name, where, mt, n in DAILY_AI:
        day_out += mt * n
        print(f"  {name:26} {where:30} {mt:5} x{n}")
    week_out = sum(mt * n for _, _, mt, n in WEEKLY_AI)
    for name, where, mt, n in WEEKLY_AI:
        print(f"  {name:26} {where:30} {mt:5} x{n}  (週1)")

    month = day_out * 30 + week_out * 4
    print(f"\n  1日の出力トークン上限: {day_out:,}")
    print(f"  1か月の上限:           約{month:,} トークン")
    print("  ※ max_tokensは上限であって実際の消費ではない。")
    print("     実測は毎回ログに出るので、そちらが本当の数字。")
    print("  ※ 入力トークンは別途かかるが、"
          "プロンプトが短いので出力より小さい。")

    print()
    print("=" * 68)
    print("費用も上限も無いもの")
    print("=" * 68)
    for name, what, note in FREE:
        print(f"  {name:22} {what:22} {note}")

    print()
    print("=" * 68)
    print("増やすと最初に詰まる場所")
    print("=" * 68)
    print("  1. YouTubeの1日の割り当て。動画1本で1,650ユニット。")
    print(f"     いまの{len([x for x in DAILY_YT if x[1] == 'videos.insert'])}本で"
          f"{total:,}使うので、資産動画は日に{left // 1650}本まで。")
    print("  2. football-data.org の10リクエスト/分。")
    print("     サッカーの取得は3日に1回に絞ってある。")
    print("  3. Reddit の連続取得(429)。球団別は取れず、r/baseballのみ。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
