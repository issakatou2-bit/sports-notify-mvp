# ⑰ 試合の話題・投手の話題のv4札（2026-10-08）

基点 main b3d6cfc（local remote build/wt-0907 の fix-0907）。隔離clone `build/codex/tmp/game-v4-20261008`、枝 `hiro/game-v4-20261008`。push/PR/公開/変数切替はエマ。

## 実装

- `review_render_v3.intro/list_page/people` に LOOK=v4 かつ game/spotlight の分岐だけ追加。v3 と他の資産の経路はそのまま。caption/presenter/progress/ticker/outro は編集なし。
- `asset_v4_cards` は⑯の short_v4_cards を使う。表紙の大きなスコア、数字＋小さい単位の札、回別スコアボードと球団札、決勝点の主語と回、選手の大数字、クリーム色の引用と属性札。地はコレスポの色。
- `ps_game_story.inning_score` が公式 feed の liveData.linescore を `game_v4.score` へ写す。回番号の連続・整数の得点・両球団・回別合計と総得点を照合。最終回裏が未実施の場合の欠落だけ「—」とし、欠落を0で補わない。取得不可/不一致は既存の試合結果の文を使う。延長の回も9回ごとの次ページへ送る。
- `game_v4.decisive` は公式プレーの回・主語・打球の種類。Field Error で説明が throwing error の場合は「相手の送球失策」、種類不明は「相手の失策」。暴投/捕逸も相手が主語。バッターを失策の主語にしない。既存の原稿・items・読み方は変えない。
- 同じセグメントの2項目/日本人選手は原稿の順に文字数比率で表示を切り替える。長い引用は54pxを保って全文を改ページ。小さな成績の札は最大10個を2段にし、それ以上は次ページへ。

## 固定材料・画像

- `scripts/fixtures/v3-rules/game-v4.json`：10/8保存の試合の話題849826（MIL/SD）・849833（CLE/CWS）と既存の山本849819投球。回別得点は保存済み `mlb_buzz.json` の公式由来 result と当該 `ps_game_topics.json` の対戦・総得点を照合して採用。山本は別の日の固定材料であり、2試合の素材と混ぜない。
- `linescore-849826/849833.json` はその回別得点を公式feed形へ縮めた検査材料。今回の環境ではMLBのソケット接続が拒否されたため、再取得した生feedとして扱わない。
- 再作成：`COLLESPO_SHORT_LOOK=v4` を試作のプロセスだけに指定し、フルパスのPython `-X utf8 scripts/preview_asset_v4.py --out C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/game-v4-previews`。
- 3枚の一覧PNGと全寸の全画面PNG、各画面の時刻・札・配置・原稿の `game-v4-confirmation.json`。検査結果を加えた最終確認は `confirmation.json` にまとめる。画像の安全域検査は音声の同期検証ではない。

## 検査・次の一手

- `test_v3_rules` の既存v3/v4別プロセスに固定材料3本を追加。すべての札/引用ページ/選手、読む順、素材の数字、回別合計と欠落、延長ページ、失策の主語を検査。run_checks は既存の自動検出で毎回実行する。
- 全体検査の結果・v3の基点との画素/原稿比較・保護された共通関数の比較は最終 `confirmation.json` に記録。test_clutch の MLB 接続拒否だけ、本人の既存指定に従い除外し元ログを残す。除外なしの接続検査やCI成功とは区別する。
- エマ：新しい公式feedから材料を再生成し、声つき全尺で札の切替・引用ページを確認。その後本人確認とPR。ここでは環境変数の本番切替をしない。

手元の最終結果: run_checks 最後は「===== すべて通過 =====」（本人指定の test_clutch / statsapi.mlb.com / WinError10013 だけを除外、元ログ保存）。test_v3_rules は v3/v4 とも19検査通過。main b3d6cfc とのv3比較は15種類279画面の原稿・画素一致。許可された共通3関数の分岐以外は不変。確認画像3枚・全26画面の配置検査通過。CI・音声同期・新しい生feed取得は未検証。
