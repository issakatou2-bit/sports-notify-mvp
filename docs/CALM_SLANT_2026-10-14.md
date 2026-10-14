# 279・280の取り込み

担当: Codex / `hiro/calm-slant-20261014`。基点main: `843637b4134ec286cf691cb17aadaed7fcba628f`。

適用メモを先に読み、279→280の順に適用した。旧mainとの差で拒否された箇所は現在の制作経路へ手で接続した。通常のHTTPS cloneはこの実行環境から接続できなかったため、GitHub接続でmainのSHAを取得し、同じcommitを持つローカル履歴から`--no-hardlinks`で独立cloneした。並行作業の未コミット変更は含めていない。

## 動き

- `COLLESPO_MOTION=on`だけ有効。#175のカメラの切り出し・画面全体の拡大を撤去し、読み上げ中の札だけ1.04倍・1.08倍の明るさにする。切替は0.25秒、2枚を同時に強調しない。
- #175の音声区間・既存の描画接続を保持し、`motion.SETTINGS`を`calm_motion.TUNING`と同じ表へ統合。背景・入場・数字・立ち絵もこの表から控えめにする。
- v3の項目札は`frame(focus=...)`へ直接接続し、#175の一覧の描き直しと二重適用しない。原稿と一致する区切り・見出しがない場合は強調しない。資産動画は原稿を作る関数と同じ関数で同期を求める。
- `v3_slot_render.py`のcuesと、並行するshort-polishの効果音・サッカー予告・選手名の短縮は変更しない。

## 吹き出しとクラブ名

- `COLLESPO_BUBBLE=slant`だけ回による選択を有効にする。bは既存の`band`、cは`glass`、aは`dark`へ対応。既存の`cream/dark/band/glass`の明示指定も保持する。
- 数字・成績・日程はb、話題・反応・長編はc。mainの実際の名前（soccer_results、reddit_reaction、japan_reacts、player_story等）も表に登録した。
- 各制作器から回を`ContextVar`へ渡す。ワークフローやリポジトリ変数の変更は不要。`COLLESPO_SLANT_VARIANT`の明示指定が最優先。`COLLESPO_EPISODE`も保持する。
- クラブ名は既存の`club_display_names.py`と`data/club_display_names.json`を共用し、JSONローダーを増やさない。帯・題・説明欄・題の修復も通す。正式な表ではマンチェスターC、パリ・サンジェルマン、アストンヴィラ。Opus検査の仮称パリSGへ表は変更しない。

## 検証

- 変数MOTION/BUBBLEを未設定にして、基点mainと取り込み後を204画面で比較し、SHA256（全RGB画素）がすべて一致。朝の成績・反応・PS予告/情勢・一覧・シーズンまとめのv3/v4、0.2/1.5/4秒。記録は`build/codex/tmp/calm-slant-preview-20261014/off-comparison.json`、各画面の指紋は`main-off.json`/`branch-off.json`。
- オフでもクラブの表示名の修正だけは常時有効。これは本人の指定に従う。上記のMLB画像比較にはサッカー名の修正を含めない。
- Opusの検査をmainの正式な表・現在の描画へ合わせ、回の選択が実際の吹き出しに届く検査を追加。#175の検査へ全フレームのカメラ固定・最大1.04倍・同時強調1枚までの条件を追加した。
- 保護指紋は`python scripts/update_protected_hashes.py --write`で更新。理由は、静かな動きの描画・既存表を通すティッカー・制作入口で回を渡す1行の追加。オフの基点比較・既存検査を維持するための更新で、保護対象の削除はない。
- サッカーv4も、基点mainのティッカーだけを同じ表示名にそろえて71画面を比較し全画素一致。旧画素の基点は、名前の修正が入る予告12画面だけ更新した（`v5-base-pixels.json`、理由も同ファイルに記録）。v3の21画面や他のv4画面の基点は維持する。古い吹き出しを固定した#175の回帰検査は`COLLESPO_SLANT_VARIANT=cream`を明示し、回別b/cの検査と両立させた。旧クラブ名を固定した成績・題の2検査も正式名へ合わせた。
- 試作: `build/codex/tmp/calm-slant-preview-20261014/mlb-1700/preview.mp4`。保存した10/5の成績・原稿・WAVを照合して制作。MOTION=on＋BUBBLE=slant（b/band）、31.625秒・24fps・759フレーム。札3項目と音声・字幕の区間一致、安全域、全尺復号、音声トラックの非無音がPASS。カメラは常に1.0倍、札は最大1.04倍。代表画像で一覧・松井・佐々木・大谷の順の強調を実見した。
- 手元の最終検査: 2026-10-15 00:04 JST、`python scripts/run_checks.py`は「===== すべて通過 =====」、終了コード0。150本の試験スクリプトを含む全体検査が通過。ログはcloneの`build/run_checks-final.log`。CIとPRは別に確認する。

公開・アップロード・リポジトリ変数の変更は実行していない。試作用の保存材料は過去の日付で、当日の成績として扱わない。
