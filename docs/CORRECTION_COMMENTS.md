# 訂正コメントの確認

リポジトリ変数 `COLLESPO_CORRECTION_WATCH` を **`on`** にすると毎朝7:37 JSTに実行。
未設定・`off`・`true` は実行しない。`COLLESPO_COMMENT_SEEDS` とは独立。
既存の `YOUTUBE_API_KEY` と `comment_seeds.collect` の取得・公開確認を使い、新しい取得口やAI呼出は追加しない。

自チャンネルの公開動画の公開トップレベルコメントから、誤り・訂正、表記・読み、数値・日付、紛らわしさ、名称の区別を規則で選ぶ。
動画ID・現在の題・本文・指摘の種類をActionsの要約に出す。投稿者名・投稿者URL・コメントIDは出さず、本文はHTMLとして解釈させない。
指摘の正しさは未確認。動画修正や返信はしない。

定時実行の遅れを考慮して過去48時間を確認するため、同じコメントが翌日にも出ることがある。
最大10ページ（1,000件）で止め、範囲が不完全な場合は要約と警告に明示する。返信・期間外・検索規則に合わない指摘は対象外。
取得失敗は候補なしとせず失敗終了し、既存のGitHub Actions失敗通知の対象になる。
候補ありはActionsの警告欄に件数を出す。既存の運営者専用通知先はないため外部通知は追加せず、一般視聴者向けOneSignalには送らない。
本文をdata・git・artifactへ保存しない（Actions要約には残る）。追加AI費用は0、YouTube APIは最大10回のcommentThreadsと候補動画の50本単位のvideos照会。

確認: `python -m unittest discover -s scripts -p test_correction_comments.py`、`python scripts/run_checks.py`。
