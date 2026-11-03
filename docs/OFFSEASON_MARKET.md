# 移籍市場の手入力

`data/offseason_market.json` の `entries` に Claude が確認済みの材料を書く。初期値は空。
書式例は `scripts/fixtures/offseason-market/example.json`。架空の材料であり本番へコピーしない。

- 項目: `id`（再利用しない英数字）、`title`（日本語選手名＋空白＋短い結論、36字まで）、`name_en`、`checked_on`（確認日、YYYY-MM-DD）、`facts`、`reports`。
- 確定行: `id`、`label`、`text`（句点まで含む発話の全文）、`source_url`。発表元の一次資料で確認した文だけを書く。
- 本文は「です・ます」の敬語。話者交代の自動整形で変わる表現は入力時に直す。完成原稿の本文は整形後も材料と完全一致させる。
- 報道行: 同じ欄に `outlet`（日本語の媒体名）を追加。本文は必ず「〜と媒体名が報じています。」の1文にする。金額・移籍先の予想はここだけ。
- 各行に任意の `illustration` を付けられる（例: `"illustration":"contract_sign.png"`）。assets/illustrations/SOURCES.jsonに登録した画像だけを使う。省略時は従来の画面。登録書式はassets/illustrations/README.mdを参照。
- 題で金額や移籍先の予想を断定しない。題に入れる数字は確定行にある数字だけにする。
- 合計3つ以上の重複しない情報が必要。同じ事実の言い換え・日付だけの分割はしない。検査は行の重複を防ぐが、情報の独立性・一次資料の正しさは執筆担当が確認する。
- 出典URLは各行に付ける。5ch・Yahooコメント・Redditは使わない。コメント主の名前を出さない。別URLに転載された禁止材料も使わない。
- 確認日の当日だけ候補になる。事実の更新は新しい項目ID・行IDで書く。既存IDの再利用では再公開しない。
- 切替は既存 `COLLESPO_OFFSEASON_NEWS=on`。新しい変数はない。連載「日本人選手の来季」の番号は `offseason_published.json` の成功記録を共用する。
- `next_asset --season` では市場を日本人資産より先に1本まで選ぶ。オフ専用経路も市場を先に選び、同じ番号の公式取引連載を同時に選ばない。公開前にも1日1本を確認する。
- 原稿・札・説明欄は材料の本文を写す。元の文章・数字を追加しない。音声の読み替えは既存の辞書に従う。27〜60秒・情報3つ以上は既存 `short_content` で実音声から判定する。
- `offseason_sample` 付き原稿と example.com のURLは本番で拒否する。見本は架空だと冒頭で明示する。

試験は `heavy_wait` の中で `py -3 -m unittest discover -s scripts -p test_offseason_market.py`。
