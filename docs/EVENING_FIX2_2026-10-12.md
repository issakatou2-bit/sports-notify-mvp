# 10/12夜の制作停止修正

基点5499168c、枝hiro/evening-fix2-20261012。共有コピーとHANDOFFは編集しない。

- 20:00回の直接原因は `--narration` が argparse により `--narration-out` の省略と扱われ、動画制作ではなく原稿保存へ進んだこと。省略解釈を無効化し引数を明示。実行記録evening4_38210479214.logの1331〜1340行では音声は完成、動画なし、投稿見送り。
- LLMのhighは参考記録のみとする#138の実装は現行mainに存在し、制作側にもhigh停止条件はない。10/11保存材料に加え10/12の3指摘を固定材料へ追加。数字・勝敗・日時の機械照合を維持し、次戦番号の照合も追加。
- 動画が存在しない/空の回はアップロード前に明示的に見送り、無条件の「投稿しました」へ進ませない。
- soccer v5の順位表の右端をcharacters.reserved_width()から決め、クラブ名・試合数・勝点・ライン・勝点差の文字を語り手の左へ配置。検査を弱めていない。保存data/soccer_race.json全画面と固定勝点8を各3時点で検査。全画面画像はbuild/evening-fix2/all-screens.png。
- 17:30ファンのコメント欄は記録漏れではない。evening4ログ1376〜1393行で、英語動画名 `Shohei Ohtani 対 Jacob Misiorowski! (Both plate appearances in 2026 NLCS Game 1) | MLB Highlights` がv4札幅に入らずValueError。制作失敗で投稿へ進まず。今回は調査報告のみ。次の修正は元動画名の見出し短縮/複数行化と固定長文の検査。
- v5プレビューCLI検査が日々更新されるdata/soccer_games.jsonに依存していたため、既存保存fixtureへ固定。関連2検査も10/11保存試作soccer-v5-previews3/preview/material.jsonをfixture化して使用。検査対象のCLI/全画面描画・鎌田のFPL出典/欠測の区別は維持。

手元検査と保存材料の画面確認まで。CI・新しい実データでの動画制作・公開物は未確認。push/PR/公開/変数切替はClaude担当。

最終run_checksは「すべて通過」（build/evening-fix2/run_checks.log）。129本のテスト、構文384ファイル、v3の21/v4の71コマの画素一致を確認。初回は更新データに依存した上記2テストのみ失敗し、保存材料へ固定後の再実行で通過。
