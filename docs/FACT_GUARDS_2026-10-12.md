# B 夜点検で見つかった生成側の事実照合

- 枝: `hiro/fact-guards-20261012`。clone: `build/codex/tmp/fact-guards-20261012`。
- 基点 `bbf0073`。10/11 23時台にGitHub mainと手元origin/mainの一致を確認。ネット接続制限のため同じGitオブジェクトを共有コピーから別cloneへ取得。共有の未commit変更は保持した。
- 読んだ資料: 共有docs/CHANNEL_FACT_AUDIT_2026-10-08_NIGHT.md、10-09_NIGHT.md、共有HANDOFFの最新記録。指定の10-10_NIGHT.mdは共有docs・mainに存在せず、GitHub取得も404。見ていない資料を見たとは扱わない。

## mainで既に直っていた部分

numbers_materialの1得点の注意書き、generate_dialogueの第何戦/試合前後の説明、local_voicesの観客/選手を区別する翻訳指示、notability_engineの「迎える」限定検査と訂正経路。今回これらを重複実装するのでなく、値の保存と機械照合の不足を補った。

## 変更

1. `mlb_buzz`がboxscoreの各打者のruns/hits/rbiを別フィールドで保存し、長編の生成材料にも得点を渡す。日本人の名字は既存press_names.SURNAMEを参照。numbersの元の行からもrunsを検査根拠として保持し、二刀流はbattingの得点を使う。
2. PSの試合前・試合後の球団ごとの勝敗、次戦番号、双方にとって決着戦かを構造値で保存。シリーズをリードするwinningTeamと今日の勝者は別扱い。リード側が未取得/参加球団と不一致なら推測で数値を埋めない。
3. `game_fact_guard`で、0安打→無得点、本人の得点値、第何戦、試合後の勝敗を試合前のプレーへ接続する表現、決着戦/負けたら終わりの誤りを検査する。生成時に停止し、既存verify_numbers --strictでも再検査する。照合は季節のfactsが空でも働く。正しい試合後の2勝2敗/次の第5戦、片方だけ負けたら敗退、無得点の二重否定は通す。
4. `comment_actors`を訳の受け取り後へ接続。原文・親・返信で、Yankeeに根拠のない「選手」の役割を足した訳やfan/crowdを選手の主体に変えた訳を除外する。理由をログへ残す。正しい観客→選手の声援や選手の明記は通す。
5. `soccer_venue.roles`が構造データのhome_team_name/away_team_nameだけでホームを決め、プロンプトと検査の両方が同じ決定を使う。matchupの表示順から推測しない。既存クラブ表と会場照合専用のLens/OL別名を参照し、迎える/本拠地/敵地/訪れる、中立地/未知を検査。既存の一度の再生成と不採用経路へ接続する。RC LensとStade de Reimsは同じクラブにしない。

## 試験材料と検証

`scripts/fixtures/fact-guards/night_failures.json`に、保存公式box（849822）の大谷0安打1得点、保存公式日程（849832）の第4戦、実際の誤文、OL/Lensの逆転を保存。保存日程にはhydrateのseriesStatusがないため、公式のseriesGameNumber/gamesInSeries/両球団leagueRecordから試験用hydrate形式へ写したことを明記した。原文コメント全体は保存されていないため、点検で確認したYankeeと退場/観客妨害の文脈を短い試験文で再現し、全体の逐語引用とは扱わない。

- 追加14件の手元検査を確認。実誤文の拒否/正常例/欠測/二刀流/未知のシリーズリード/厳格CLI/翻訳からの除外/会場の共通判定。外部通信・課金なし。
- 二刀流と未知リードの補強を含む最終run_checksは「===== すべて通過 =====」。記録は `build/verification/run_checks-final.log`。最初の全体検査も通過した。
- CI・新しい実API生成結果・公開物は未検証。保存済み実資料での回帰検査を、新しい公開結果の確認と扱わない。㉗/共有コピー/公開データは不変。

## 残りと取り込み

規則は今回の誤りと周辺の明確な表現を対象にする。任意の文章全体の意味保証ではない。新しい実例は試験材料と規則に戻す。numbersモードの得点照合とvoicesモードの当該試合のPS時点照合を区別する。

Claudeがこの枝のcommitを取得し、Aと両方の変更を保持して統合する。共有するgenerate_dialogue/local_voices/mlb_buzz/notability_engineとdocs/HANDOFF/BACKLOG/DECISIONSの統合時に、いずれか一方の変更を捨てない。push/PR/公開/変数切替はしていない。
