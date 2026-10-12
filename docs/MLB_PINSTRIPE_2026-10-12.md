# MLBの縦じま札 2026-10-12

完了: ヒロ。基点main 2f86ba3f、隔離clone mlb-pinstripe-20261012、枝 hiro/mlb-badge-20261012。HANDOFFへの追記なし。
対象: MLB v4の名前の左の札、変数の受け渡し、既定の画素一致/全枠検査、声つき保存材料試作2本。
本人の指定でpinstripeを本番描画へ接続する。運用変数の設定・公開・pushは行わない。

## 接続

最新mainから作った枝へ5de76bddの見本枝をmergeして継続。`COLLESPO_MLB_BADGE=pinstripe`かつMLB共通LOOK=v4のときだけ、short_v4_cardsのinline/team/mini札をmlb_pinstripe_badgeへ渡す。サッカーのクラブ札を変更しない。未設定/別の値とv3は従来の描画へ戻る。

斜めB・左の縦じま・Oswald Boldの番号書体を維持。名前の行を詰めないため、現行の札の幅と高さの中へ収める。以前の92px見本をそのまま貼って名前の位置を押し広げない。模様は左帯だけ、文字の背面は球団主色、白/黒のうち見える字色を使う。

MLBの本番/補正/手動見本の9workflowでリポジトリ変数を受け渡す。変数自体の設定と動画の投稿は行っていない。Claudeが本人確認後に設定する。

## 検査

- 変更前のmain 2f86ba3fから96画面のSHA256を凍結し、未設定時はすべて画素一致。v3も札単体で画素一致。
- 有効時は成績/7人成績/コメント/報道/予告/PS情勢/資産9種類の計15枠、インライン札164箇所を検査。全札のstyle=pinstripe、追加の配置異常0。基準にも存在した資産冒頭等の余白警告19件は解消したと報告せず、変更で増えていないことを照合。
- 30球団×名前の書体サイズ18/28/36/48で、字と模様の領域が重ならないこと、文字が札内にあること、コントラスト4.5以上を確認。
- 過去の見本のprotected-source SHAは、接続を追加したshort_v4_cardsだけ新しい値へ更新。その他4本は同一。96画面の未設定の画素検査を追加して、この意図した接続が既定を変えないことを別に押さえた。本番から見本モジュールをimportしない検査も維持。

## 声つき試作

保存先 `C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/mlb-pinstripe-previews/`。index.html、1700-players.mp4、1900-forecast.mp4、各contact/poster、before-after.png、confirmation.json、各フォルダの保存原稿/音声/描画ログ。

17時は10/5の成績、19時は10/7のPS保存資料を使用。当日の情報ではない。成績の鮮度検査は変更せず、見本の子プロセス内だけ保存日の時計へ固定。17時の本番bignumber_scenesで話者/原稿を準備してから合成し、生成器の声と場面を一致させる。保存元の資料SHAは生成の前後で照合する。

再現: `python scripts/preview_mlb_pinstripe.py --out ../mlb-pinstripe-previews --ffmpeg-dir ../media-tools`。このPCでは既存imageio_ffmpegのffmpeg 7.1を見本用フォルダへコピーして使った（インストールではない）。中断後は同じ原稿の完成済み音声/動画だけ`--resume`で再利用できる。

残り: 本人の声つき試作確認、Claudeのpush/PR #139更新/CI、変数設定。

19時の動画を本番生成器で通したところ、既存のps_program.render_segmentがnext_lineだけlayers=Trueでも2値を返し、動画側の3値受け取りで停止した。defaultの2値は保ち、layers=TrueではRGBAの前景も返す2行の修正と保存forecastの回帰試験を追加。途中で止まったMP4を完成扱いにせず、ps_program_gate.jsonがある完成版だけ再利用する。修正後にrun_checksをもう一度実行し、終了コード0・125試験ファイルNG0・末尾「===== すべて通過 =====」を確認。

完成版の完全デコードは2本ともPASS。FFmpeg 7.1のコンテナ時間は17時31.38秒/19時93.50秒、映像H264・音声AAC・1080×1920。19時のgateは期待7画面/音声7件と一致。全体を覆うcontact画像と実寸posterを目視し、札・名前・字幕に切れ/重なりなし。声の聴取合格とは区別する。before-after.pngと元材料SHAも確認。実測の出所はmedia-check.json、要約はdocs/verification/mlb-pinstripe-2026-10-12.json。

Claudeの取得元: `C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/mlb-pinstripe-20261012` の `refs/heads/hiro/mlb-badge-20261012`。main取込と公開物の確認は別段階。
