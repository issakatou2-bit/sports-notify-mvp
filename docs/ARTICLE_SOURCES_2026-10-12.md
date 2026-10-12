# ㉙追加2 現地報道の記事出典を原稿と対応させる

- clone `build/codex/tmp/article-sources-20261012`、枝 `hiro/article-sources-20261012`、基点 `origin/main bbf0073`。
- 選択理由: BACKLOG「現地の報道 — 各記事への出典リンクを概要欄に」は本人判断を追加で必要とせず、RSS→採用原稿→概要欄の対応をコードで直せる。mainには見出しのRSSリンク保存も概要欄の経路もないことを確認した。

## 変更

`local_reporters`でRSSをXMLとして読み、見出し/媒体/日付と同じitemのlinkを保存。CDATA/実体参照/名前空間を扱い、リンクがない見出しもURLを推測せず空で保存する。http/https以外、制御文字、認証情報付きURL等は使わない。

`generate_morning_short`は冒頭/本文で実際に選んだ見出しだけを、その原稿のmeta.source_headlinesへ保存する。読まなかった見出しや前回の一覧を出典に追加しない。動画の読み上げ/画面の選び方は変えない。

`upload_youtube`のpress枠の概要欄は、その保存原稿から記事の媒体名/原見出し/URLを並べる。重複URLを除き、URLを途中で切らずに説明欄用の合計長を守る。古い原稿に出典metadataがなければ後のRSSを推測で結び付けない。他の枠には追加しない。

## 検証と残り

- 追加6件の固定材料: 同じRSS項目からの対応/CDATA/実体参照/リンクなし、名前空間とfetchの接続、安全でないURL、冒頭/本文の選択済み出典と不採用見出しの除外、重複/長さ/旧原稿、保存原稿→概要欄と他枠不変。
- 最終run_checksは「===== すべて通過 =====」。手元ログ `build/verification/run_checks.log`。
- 外部通信/実API呼び出し/実アップロード/公開ページ変更はしていない。RSS/HTTPは偽物、URLのexample.invalidも試験用。CI・実RSSによる新出力・公開物は未検証。
- 保存するGoogleニュースのリンクはRSSが返した転送URLで、転送先の媒体の元記事へ到達することや公開説明欄のクリック可否は今回確認していない。URLのない古い記録は自動復元しない。
- まとめ枝へは取り込まず独立commitで渡す。Aのlocal_reporters受信検査、他のgenerate_morning_short/upload_youtubeの既存修正も保持して統合する。Claudeが取込/CIを行う。共有コピー/㉗/push/PR/公開/変数は変更なし。
