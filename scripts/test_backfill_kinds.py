#!/usr/bin/env python3
"""台帳補完が、題から枠を取り違えないか。

なぜ要るのか:
  規則が8月のままで、長編11本を「コメント欄の回」、順位争いを
  「欧州サッカーの日次」と判定していた。9/21と9/22は実際に、順位争いの
  動画を日次の記録として書き込んでいた。**取り違えると、欠けた記録を
  別の枠に書き込む。**

題は公開済みのものから写した固定の例。台帳そのものは日々増えるので
検査には使わない（日が変わると落ちる検査にしない）。
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import backfill_records as br  # noqa: E402
from checks_report import check, section, done  # noqa: E402

CASES = [
    ("longform", "【MLB】村上宗隆・千賀滉大のきょう｜成績と進出争い"),
    ("longform", "【海外の反応】ヤンキース 対 エンゼルス｜MLB公式コメント欄を読み解く"),
    ("soccer_race", "久保建英のレアル・ソシエダ、EL圏内まで勝点3｜ラ・リーガ 順位争い【欧州サッカー】#Shorts"),
    ("daily_soccer", "今夜の注目試合【サッカー】｜昨季18位から這い上がったレバンテ｜ラシン・サンタンデール vs ビジャレアル ほか #Shorts"),
    ("verdict", "【MLB】注目した試合、どうなった？｜09/07〜09/13 先週の答え合わせ #Shorts"),
    ("weekly", "【MLB】ロッキーズ連敗脱出、ガーディアンズ7連勝｜08/24〜08/30 1週間を振り返る"),
    ("weekly", "【MLB】岡本和真・鈴木誠也・ヌートバーほか｜09/07〜09/13 今週の日本人選手"),
    ("morning_postseason", "【MLB】レイズ 進出決定｜9月23日 ポストシーズン進出争い #Shorts"),
    ("morning_press", "【MLB】現地はこう報じた「大谷翔平は水曜日の出場予定」｜9月23日 番記者の投稿と現地の見出し #Shorts"),
    ("morning_voices", "【MLB】レイズ vs ヤンキース 現地のファンは何と言ったか｜返信3件ついたコメント 9月23日更新 #Shorts"),
    ("morning_local", "【MLB】現地でいちばん名前が挙がったのはドジャース｜8月23日 再生回数ランキングと話題のチーム #Shorts"),
    ("morning_player", "【MLB】Garrett Mitchell｜4打数3安打　1本塁打｜通算成績・受賞歴まとめ #Shorts"),
    ("morning", "【MLB】菊池雄星・今永昇太・佐々木朗希 ほか｜9月23日 日本人選手 勝利貢献スコア ランキング #Shorts"),
    ("morning", "【MLB】ブルージェイズ 岡本和真、4打数1安打｜9月22日の日本人選手 #Shorts"),
    ("daily", "ドジャース 山本由伸、先発予定｜9/24の注目試合【MLB】"),
]

section("公開済みの題の例")
for want, title in CASES:
    check("%s: %s" % (want, title[:30]), br.kind_of(title), want)

section("取り違えやすい組み合わせ")
check("長編の「コメント欄を読み解く」をコメント欄の回にしない",
      br.kind_of("【海外の反応】X｜MLB公式コメント欄を読み解く"), "longform")
check("順位争いを欧州サッカーの日次にしない",
      br.kind_of("X｜セリエA 順位争い【欧州サッカー】#Shorts"), "soccer_race")
check("サッカーの注目試合をMLBの注目試合にしない",
      br.kind_of("今夜の注目試合【サッカー】｜X #Shorts"), "daily_soccer")
check("分からない題は空（書き込まない）", br.kind_of("何かの動画"), "")

sys.exit(done())
