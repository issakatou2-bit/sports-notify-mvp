# 英語字幕（2026-10-14）

## 変更

COLLESPO_EN_CAPTIONS=on のときだけ、PS試合直後（season_game_*）と19時の日次に英語字幕を付ける。off/未設定なら現在の日本語字幕・投稿動作を維持。
日本語字幕のbuild_cuesを共用し、読み上げ原稿と音声manifestの実測秒から同じ区切り・時刻を英訳する。発話認識は行わず、各画面内は従来どおり文字数按分であり、単語単位の厳密な同期ではない。
翻訳はllm_modelsのtranslate（既定Sonnet 5.5）・backstage_guardを通し、配列件数・空欄・日本語残り・名前・数字・途中切れを検査。AI応答やOAuth情報を公開台帳へ書かない。
正式名表の入口はscripts/caption_names.py。球団名と日本人選手の英語は既存の共通名簿notability_engineを参照。他選手はMLB Stats API由来のdata/player_kana.jsonの英語キーを参照し、カナを別名として逆引きする。値の表を複製しない。

## 上限と共有枠

- COLLESPO_EN_CAPTIONS_DAILY_MAX：JSTの1日上限。既定1本。失敗したinsertも1本として予約し、その日は同じ動画へ再送しない。
- COLLESPO_EN_CAPTIONS_RESERVE：他処理へ残す単位。既定1000。
- captions.list=50、insert=400として先に予約。残量不足・重複・翻訳失敗・403をdata/en_caption_state.jsonとActionsの要約へ記録。
- 英語字幕を有効にした2ワークフローのみ同じconcurrency groupで直列化。既定のgroup/cancel動作は維持。既存stateはcheckout時に読み、各投稿後に保存する。

### 共有残量の入力（有効化前の設定作業）

推奨は YOUTUBE_SHARED_QUOTA_URL（HTTPS）に、APSC/Cloud側の運転役が現在の観測値を返す窓口を設定する。必要なら YOUTUBE_SHARED_QUOTA_TOKEN をSecretsへ。字幕を付ける直前と翻訳後に毎回取り直すため、PSの長時間の見張りでも開始時の古い値を使わない。通信失敗・HTTPエラーは不明として見送る。

保存した値を一時的に試す場合は YOUTUBE_SHARED_QUOTA_SNAPSHOT に、APSCと共用のCloudプロジェクトの実測残量をJSONで渡す。
例：{"quota_date":"2026-10-14","observed_at":"2026-10-14T10:00:00Z","remaining_units":8000}
quota_dateはYouTubeの太平洋時間の当日（夏時間を考慮）。observed_atはUTC等のタイムゾーン付き取得日時。5分を超えた値・将来の日時・日付違い・不明な残量では送らない。取得後に当リポジトリが予約した単位も差し引く。

字幕API自体には共用プロジェクトの残量取得口がなく、リポジトリにもCloud Monitoring用の権限・認証設定がない。したがってこのPRはCloudの使用量を自動取得したとは主張しない。Cloud/APSC側で残量を更新する運転役を用意するまでは、onでもquota_unknown/quota_snapshot_staleで見送りになる。値を10000と推測して有効化しない。
この残量値は読み取り時点の観測であり、APSCの同時使用を原子的には予約できない。共有側の更新・予約運用と合わせて使う。予備枠はそのための余裕であり、厳密な全処理の共有台帳ではない。

## OAuth

公式仕様：insert/listともyoutube.force-sslまたはyoutubepartnerが必要。
https://developers.google.com/youtube/v3/docs/captions/insert
https://developers.google.com/youtube/v3/docs/captions/list
scripts/youtube_auth.pyは既にforce-sslを要求し、captions.pyは更新時にscopeを再指定しない。コードと設定の要求は適合するが、Secretsのrefresh tokenに実際に付与された権限はこの作業で確認していない。403なら本人がyoutube_auth.pyでforce-ssl付きの認可を取り直し、ClaudeがSecretsを更新する。動画投稿だけ成功することは字幕権限の証明ではない。

正式名の出典： https://www.mlb.com/team / https://www.mlb.com/players

## 検証と残件

scripts/fixtures/captions/aligned.jsonを使う11件の単体検査で、時刻一致・翻訳契約・枠不足/不明/古い値・JST/Pacific日境界・重複・投稿成功/失敗・workflow接続を確認。外部API・Windowsフォント・保存動画・旧Gitコミットに依存しない。
CI、実API翻訳、字幕の実挿入、公開動画での表示は未確認。本人の変数有効化・認可確認・共有残量入力の準備後にClaudeが実運転を検証する。

従来の日本語SRTは固定材料で基点の出力と完全一致。差分の未定義名検査とYAMLの重複キー検査も通過。

全体のrun_checks.pyは「すべて通過」。追加後の11件の字幕検査・構文/未定義名・ワークフロー接続検査も通過。実API翻訳・実挿入・CI・公開物は未確認のまま。
