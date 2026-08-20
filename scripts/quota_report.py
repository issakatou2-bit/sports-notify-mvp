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

# YouTube Data API v3 の割り当て。
#
# ここは一度間違えた。「videos.insert = 1600ユニット」という広く出回っている
# 数字から「1日6本まで、日次4本なら資産動画は1本」と結論し、
# 動画を増やす計画をその制限に合わせようとした。
#
# Google Cloud Console の実測(2026年8月)がこう:
#
#   Video Uploads per day     100        3%   3回
#   Search Queries per day    100        4%   4回
#   Queries per day        10,000     1.51% 151
#
# アップロードも検索も、回数で数える別枠だった。10,000ユニットとは
# 別勘定で、そちらは1.51%しか使っていない。
# つまり動画の本数は当面まったく制約にならない。
#
# 教訓として残す: 広く知られた数字でも、その計画の前提にするなら
# 手元の管理画面で確かめること。ここでは1つの誤った数字から
# 「資産動画は1日1本」という、実際には存在しない制限を作りかけた。
YT_QUOTAS = {
    # (名前, 1日の上限, 数え方)
    "uploads": ("Video Uploads per day", 100, "回"),
    "search": ("Search Queries per day", 100, "回"),
    "queries": ("Queries per day", 10_000, "ユニット"),
}

# 10,000ユニット側から引かれるものの単価
UNIT_COSTS = {
    "thumbnails.set": 50,
    "videos.list": 1,
    "videos.update": 50,
    "playlistItems.insert": 50,
    "playlistItems.list": 1,
    "channels.list": 1,
    "commentThreads.list": 1,
}

# 毎日走るもの。(名前, 呼び出し, 回数)
DAILY_YT = [
    ("日次ショート", "videos.insert", 1),
    ("日次ショート サムネ", "thumbnails.set", 1),
    ("夕: 選手成績", "videos.insert", 1),
    ("夕: 選手成績 サムネ", "thumbnails.set", 1),
    ("夕: 現地の注目度", "videos.insert", 1),
    ("夕: 現地の注目度 サムネ", "thumbnails.set", 1),
    ("夕: 現地の声(press)", "videos.insert", 1),
    ("夕: 現地の声 サムネ", "thumbnails.set", 1),
    ("現地の再生回数を調べる", "search.list", 1),
    ("再生回数の取得", "videos.list", 1),
    ("現地のファンのコメント", "commentThreads.list", 4),
    # 再生リスト: 一覧を2回(日次と夕方)走査し、その日の5本を足す
    ("再生リストの走査", "playlistItems.list", 4),
    ("再生リストへの追加", "playlistItems.insert", 5),
    ("チャンネル情報", "channels.list", 2),
    # 英語のタイトル・説明文。既に入っているものは問い合わせだけ。
    ("英語メタデータの確認", "videos.list", 12),
    ("英語メタデータの付与", "videos.update", 5),
]

# AIの呼び出し。max_tokensは上限なので、実際はこれより少ない。
DAILY_AI = [
    ("注目試合の理由づけ", "notability_engine.py", 700, 3),
    ("日次ショートの原稿", "generate_narration.py", 300, 3),
    ("現地のファンの声 翻訳", "local_voices.py", 1500, 1),
    ("現地の番記者 翻訳", "local_reporters.py", 1200, 1),
    ("現地の見出し 翻訳", "local_reporters.py", 1200, 1),
    ("英語のタイトル・説明文", "localize_videos.py", 1600, 5),
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
    print("YouTube Data API")
    print("=" * 68)
    uploads = sum(n for _, c, n in DAILY_YT if c == "videos.insert") + args.assets
    searches = sum(n for _, c, n in DAILY_YT if c == "search.list")
    units = sum(UNIT_COSTS.get(c, 0) * n for _, c, n in DAILY_YT)
    units += UNIT_COSTS["thumbnails.set"] * args.assets

    for key, used in (("uploads", uploads), ("search", searches),
                      ("queries", units)):
        name, limit, unit = YT_QUOTAS[key]
        pct = used / limit * 100
        bar = "#" * round(pct / 100 * 30) + "." * (30 - round(pct / 100 * 30))
        print(f"  {name:26} {used:6,} / {limit:6,} {unit:5} "
              f"{bar} {pct:5.1f}%")
        if pct > 80:
            print(f"  ::warning:: {name} が8割を超えています")

    print(f"\n  日次{uploads - args.assets}本 + 資産{args.assets}本 = "
          f"{uploads}回のアップロード")
    print(f"  残り {YT_QUOTAS['uploads'][1] - uploads} 回")
    print("\n  アップロードは回数で数える別枠で、10,000ユニットとは"
          "別勘定。\n  動画の本数は当面まったく制約にならない。")
    print("  上限に達した場合は Quota extension request form で増枠申請できる。")

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
    print("  1. football-data.org の10リクエスト/分。")
    print("     サッカーの取得は3日に1回に絞ってある。")
    print("  2. Reddit の連続取得(429)。球団別は取れず、r/baseballのみ。")
    print("  3. Anthropicの残高。動画を増やすと翻訳と原稿のぶんが増える。")
    print("\n  YouTubeの本数は、当面ここに入らない(100回中"
          f"{uploads}回)。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
