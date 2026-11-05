# 欧州サッカー予告の角度（2026-11-06依頼）

Codexが自分で実装・試験・保存材料の比較を確認した。commit・push・公開・変数変更なし。HANDOFF、実績台帳、認証・通信設定、VoiSonaは変更・使用していない。

## 作業場と取得の制約

`build/wt-preview-angles`、枝 `claude/preview-angles`。共有コピーの `.git/FETCH_HEAD` は書込み不可、独立コピーからの GitHub fetch もネットワーク制限で接続不可だった。依頼の独立作業場をローカルcloneで用意し、共有コピーに保存されていた `refs/remotes/origin/main`（771c96f7）をfetchして起点にした。GitHub上の最新mainとの一致は未確認。共有コピーにあった多数の未コミット差分は持ち込まず、変更しなかった。

## 変更と接続

選定CLIが角度の根拠を保存し、`preview_angles_version=1` の材料では本文・題を同じ再計算結果から作る。旧保存原稿の再現経路は維持。既存の素材照合に専用検査を足し、本文・題・表紙・角度の数値や名前の改変を止める。版番号は保存形式であり、環境変数や公開用の切替を追加していない。

既存の `soccer_preview.fetch_competition` はすでに大会の全試合と今季順位を取得していたため、同じ応答の根拠と取得日時も保存して再利用する（追加通信なし）。API取得・描画・事実検査を分け、描画と検査からは通信しない。

変更ファイルの行（作業コピー内）:

- `scripts/soccer_preview_angles.py`: integer:13, identity:17, fresh:21, read:26, ledger_rows:33, attach:71, angles:112, chosen:237, headline:249, body:280, check:289
- `scripts/soccer_preview.py`: fetch_preview_context:49, _headers:89, fetch_competition:93, is_stale:202, _ended:216, _season_year:227, _match_row:237, _table_rows:249, score_matches:275, build:340, v4_program:356, main:361
- `scripts/soccer_selected_preview.py`: preview_details:13, spoken_club:41, opening:52, program:57
- `scripts/soccer_selection.py`: policy:17, competitions:18, competition:19, kickoff:21, members:24, visible_members:31, missing_clubs:36, opponent_fallbacks:57, registration_warning:75, score:83, select:121, main:180
- `scripts/soccer_sanity_material.py`: compact:11, grounding:34, aliases:63, for_document:69, review:91
- `scripts/sanity_material.py`: document_day:12, blocking:25, _legacy_grounding:32, grounding:67, claim_context:72, _clock:104, check:117, _supported_claim:241, headline_grounding:289, _supported_headline_comeback:299, assess:348
- `scripts/test_soccer_preview_angles.py`: game:19, fixture:26, evidence:30, table:34, finished:42, Angles:49

## 角度の点と出どころ

順位は同じ大会・同じ季・同じTOTALグループだけ。日時は各角度の `retrieved_at`、生の根拠は `preview_angle_context`、抽出値は `values` に保存する。異なる角度から強い順に最大3個。勝点差に双方の順位・勝点を含めた場合は順位だけの角度を重ねない。題は主役カードの最上位の角度から作り、数字はその本文にも含める。

| 角度 | 点 | 出どころ・条件 |
|---|---:|---|
| 双方の順位・勝点・差 | 100（差3以下）/70 | football-data `/v4/competitions/{code}/standings` のTOTAL.table.position/points。保存試合の同大会の順位も取得日時付きで使用。bool・負値・欠測を除外 |
| 日本人双方の所属 | 95 | 保存材料 `soccer_games.json.jp_by_side`（なければ既存名簿）、`preview_out_names`を除いた双方の所属。出場の断定はしない |
| 決勝トーナメント | 90 | 試合の `phase=knockout` と `phase_source`。ラウンド・勝ち上がりの未取得部分は補わない |
| 直近5試合 | 85 | football-data 同大会matchesのFINISHED、同季、材料時刻より前。試合IDで重複除外し直近5件。勝分敗を数え、5件ない場合は空 |
| 日本人の既存公式個人成績 | 82 | 既存 `season_players`、FPL bootstrap-staticの保存集計。既存expectationの鮮度・本人・クラブ照合を通した日本人。今季FPL集計と明記し、ELなどの成績に言い換えない |
| 前回対戦 | 80 | football-data `/v4/matches/{id}/head2head`。双方のクラブID、FINISHED、過去日時を照合して最新1件。403等は空。ホーム/アウェーは当時の向きで表記 |
| すぐ上との差 | 75（差3以下）/50 | 同じTOTAL順位表のひとつ上のpositionのpointsとの差。欧州・降格の境界は推測しない |
| 一方の順位・勝点 | 65 | 同大会順位表または保存試合の取得済みstanding |
| 保存結果内の日本人成績 | 60 | `data/soccer_results.json.games[].players`。下記の数え方。全季の通算とは表記しない |
| 昨季順位 | 40 | 既存 `reasons.quality` と `preview_details` のクラブ名・範囲・1〜64位の照合。大会の異なる2クラブを順位差として比較しない |

0個の場合だけ通常の「所属クラブが相手と対戦」の題へ戻る。その際も保存結果を数える処理は試し、無ければ所属だけを本文に出す。主観や出場予想の埋め草は新経路に入れない。

保存結果の数え方: キックオフの属する7月〜翌6月の範囲で、材料取得時刻以前に終了した結果のみ。選手名とその当時のクラブが今回の所属クラブに一致し、statusがstarter/substituteでappearance_evidenceがある記録を `(name,event_id)` で1出場と数える。重複が矛盾する試合は除外。得点・アシストは各出場の全記録に数値とstats_sourceがある項目だけ合計（欠測を0にしない）。保存分に国内・欧州の両方があれば両方を含む。移籍前の別クラブ、7月以前、未来の結果は含めない。現在のファイルは日次の保存分であり、全季を網羅する台帳ではない。

取得方法は [公式Quickstart](https://www.football-data.org/documentation/quickstart) と [API policies](https://docs.football-data.org/general/v4/policies.html) を11/5に参照。チームごとのmatchesを2回ずつ取る方式と比較し、大会ごとの一括取得と既存応答の再利用を採用。第三者ライブラリや公開コードの追加・転用なし。

## 保存済み3試合の前後

材料: `data/soccer_games.json`、取得時刻 `2026-11-05T09:53:48.574581+00:00`。個人成績の出典日時は角度に別途保持。外部APIは呼んでいない。比較は同じ保存材料を1試合ずつにし、変更前互換経路と新版経路を同じ条件（検証プロセス内だけlook=v6/short=v4/focus=on/title_v2=on/solo=metan）で計算。実際の公開用変数は読取り・変更していない。

### 1. espn-401915526

変更前の題: 鎌田が今季FPL集計3アシスト｜パレス対ホッフェンハイム｜ヨーロッパリーグ #Shorts

変更前の本文: 日本時間2時45分、クリスタルパレス対ホッフェンハイム。クリスタルパレスの登録メンバーには、鎌田大地が入っています。ホッフェンハイムの登録メンバーには、町田浩樹が入っています。

変更後の題: 【欧州サッカー】鎌田大地のクリスタルパレスが町田浩樹所属のホッフェンハイムと対戦 #Shorts

変更後の本文: 日本時間2時45分、クリスタルパレス対ホッフェンハイム。クリスタルパレスには鎌田大地、ホッフェンハイムには町田浩樹が所属しています。鎌田大地は今季FPL集計で1得点 3アシストです。


使用した角度: japanese_pair（95点、soccer_games.json.jp_by_side / JP_PLAYERS_SOCCER、取得2026-11-05T09:53:48.574581+00:00） / season_player（82点、https://fantasy.premierleague.com/api/bootstrap-static/、取得2026-11-05T10:01:23.245204+00:00）


### 2. espn-401915537

変更前の題: 久保ソシエダはリヨンと対戦｜ヨーロッパリーグ #Shorts

変更前の本文: 日本時間2時45分、レアル・ソシエダ対リヨン。レアル・ソシエダの登録メンバーには、久保建英が入っています。

変更後の題: 【欧州サッカー】久保建英のレアル・ソシエダがリヨンと対戦 #Shorts

変更後の本文: 日本時間2時45分、レアル・ソシエダ対リヨン。レアル・ソシエダには久保建英が所属しています。


使用できる追加角度なし。保存結果の計数も試したが該当記録なし。対戦と所属の事実に戻った。


### 3. espn-401915825

変更前の題: 鈴木唯人のフライブルクはトラブゾンスポルと対戦｜カンファレンスリーグ #Shorts

変更前の本文: 日本時間2時45分、トラブゾンスポル対フライブルク。フライブルクの登録メンバーには、鈴木唯人、後藤啓介、山本理仁が入っています。

変更後の題: 【欧州サッカー】鈴木唯人のフライブルクがトラブゾンスポルと対戦 #Shorts

変更後の本文: 日本時間2時45分、トラブゾンスポル対フライブルク。フライブルクには鈴木唯人・後藤啓介・山本理仁が所属しています。


使用できる追加角度なし。保存結果の計数も試したが該当記録なし。対戦と所属の事実に戻った。


## 試験

heavy_waitの開始可否を確認してから全試験・静的検査を実行。試験ランナーはsocket接続を禁止し、新規試験はrequests/urllibも禁止。APIは偽応答、待機はmock。音声合成なし。

初回に既存試験を1プロセスで束ねたところ、別試験の環境設定が干渉して110件中10件が失敗した。通常の入口と同様にファイルごとの別プロセスへ修正した最終結果は下表。コードの不具合としてはhead2headのスコアと点数の引数名衝突を試験で見つけて修正済み。

| 試験 | 件数 | 結果 |
|---|---:|---|

| test_soccer_preview_angles | 11 | 成功 |
| test_soccer_stable | 13 | 成功 |
| test_soccer_selection | 12 | 成功 |
| test_soccer_match_interest | 12 | 成功 |
| test_soccer_story_lines | 11 | 成功 |
| test_soccer_title_v2 | 20 | 成功 |
| test_sanity_soccer | 10 | 成功 |
| test_soccer_preview_results | 12 | 成功 |
| test_soccer_focus | 11 | 成功 |


合計112件成功。新規11件は、角度抽出、点順、同大会・同季、直近5試合の終了/未来/重複、欠測、台帳重複、前回対戦の向き、杯戦、題・本文・表紙の照合、API要求数・403・鍵なし、FPLの大会分離、取得時刻・キャッシュを確認。3実材料の新版も専用照合と既存sanity_material.checkの両方を自分で通した。


`python scripts/run_checks.py --section static --import-workers 4`（heavy_wait経由、最終の変更後）: failed=0、70.0秒。最初は指定通り並列数省略でも成功（258.2秒）。最終確認は起動確認のみ4並列。`git diff --check`成功。ログ: `build/angles-check/`。CI・実音声・完成動画・公開は未実施。


## 呼ぶ回数と残ること

- N=1日の選定試合数、C=その中の無料対応大会の種類数、H=football-dataの数値試合IDを持つ数。追加取得を使う場合の通常要求は **2C+H（最大3N）**。大会のstandingsとFINISHED matchesを各1回、head2headを試合ごと1回。同大会2試合なら2×1+2=4回。最大4試合が別大会なら4×3=12回で、1分には詰めない。
- 各追加要求の前に6.1秒空ける。429は既存 `_football_data_get` のRetry-After待機に従う（1論理要求の再試行上限3、再試行を含む試行数の上限は3×(2C+H)）。他ジョブとの同じ鍵の使用は既存API側の残量・429処理に従う。
- 既存soccer_previewの全試合・今季順位の応答を残す変更は **追加0回**。このキャッシュは取得48時間以内・同季・同大会の分だけ再利用する。
- 今夜の保存済み選定4試合はEL/UECLのESPN IDで、無料対応大会集合（PL/PD/SA/BL1/FL1/CL）と数値football-data IDに該当しないため、上記追加取得は **4試合×0回=0回**。この作業全体でも実API 0回。鍵の値は読取り・表示・記録していない。
- 現行workflowは選定ステップへ鍵を渡していない。設定変更は禁止なので手を付けていない。無料対応大会の新規追加取得をこのステップで実稼働させるには、Claude側で鍵の受渡し方を判断する必要がある。今回のコードは環境変数が渡された時だけ取得し、無い時は既存キャッシュ・保存順位・所属・FPL・結果台帳から作る。keyをコマンドラインに渡す入口は増やしていない。
- 欧州出場圏・降格圏の大会別の現在の確定枠は未取得。境界を固定数字で推測せず、すぐ上との差だけ実装。大会の細かなラウンド、2試合合計、進出確定も未取得なら言わない。
- head2headの無料枠での実際の可否は未確認（依頼通り本物APIなし）。取れない時は空で継続する。EL/UECLの試合に国内順位を流用しない。
- 2例で新たな数字を出せなかったのは、保存材料に当該大会の戦績がなく、結果台帳にも該当選手の終了記録がないため。見どころを創作していない。キャッシュの新形式は既存取得が次回走ると保存されるが、今回data/は更新していない。
- 原稿の55秒上限と既存の試合数調整は維持。実音声の長さ・スマホ画面の見え方は未確認。長い実原稿については既存fit_previewで計測する必要がある。
