# ショート共通部品の修正（2026-11-08）

担当: Codex。共通の締め・音・重複字幕・見本作成の経路を修正。作業用コピー `build/codex/tmp/wt-offseason-outro`、枝 `hiro/short-common-1108`、起点 `a90c73e5`。既存コピーを再使用。各型の本文の書き換えと最初の3秒の台本改善は別作業 msg_268/275 の範囲。

## 締めの変更と尺

読み上げは「毎日更新しています。」、画面は「コレスポ」と「毎日 MLB・欧州サッカー」。番組表の一覧・次の番組の宣伝札は表示しない。事実としての次の試合の札（`next_line`）は保持する。実音声を切らず、目標2秒、上限2.5秒。長い・不正な音声は描画前に拒否する。

| 型 | 変更前（下限の設定／講評の実見） | 変更後 |
|---|---|---|
| 朝の日本人選手・PS・報道・ファンの声 | 共通の長い読み上げ、通常の締め下限4秒。報道・声の講評は約10秒 | 共通2.00〜2.50秒 |
| 欧州サッカー結果 | 通常の締め下限2.6秒、講評は約10秒 | 共通2.00〜2.50秒 |
| 欧州サッカー順位・週・予告・声・速報・得点 | 通常の締め下限2.6秒、順位の講評は約8秒 | 共通2.00〜2.50秒 |
| 日本代表（招集・予告・結果） | 専用のブランド締めは0秒（末尾の次戦情報は本文） | 本文の末尾へ共通2.00〜2.50秒 |
| MLB資産・シーズンまとめ・オフ・用語 | 共通の長い読み上げ、通常下限6秒。用語の掛け合いは別の尺配分 | 共通2.00〜2.50秒 |
| PS速報・選手ストーリー・選手画面 | 専用の末尾／既存の通常尺。PS通常区間下限3秒 | 共通2.00〜2.50秒 |
| 週次の答え合わせショート | 旧生成器の締め下限4.0秒、長い宣伝文 | 共通2.00〜2.50秒 |

変更前の実見は `build_reports/argon_review_20261108/` の講評（結果・順位・報道・声）による。設定の下限と実動画の秒数を混同しない。変更後は各尺計画器を2秒の音声で試験（計画尺2.12秒）、2.45秒の音声で上限2.50秒、3秒・NaN・負数を拒否。実VOICEVOXで全型を描画した値ではない。`short_common.duration` が本番の音声でも上限を検査する。

締めが短くなった分を理由に止めないため、新しい共通締めの原稿だけ全体下限を28→20秒（従来の猶予1秒は維持）とした。独立情報3件・各型の上限は維持。掛け合いの原稿選別では従来の締め相当を予約し、締め短縮だけで本文の採用数が変わらないようにした。

## BGM・効果音と実測

原因はサッカーなどの描画経路に混音の呼び出しが無かったことと、一部の既存経路が混音失敗を声だけで続行していたこと。従来の固定ゲインは追加のダッキングでも小さくなっていた。既存の許可済み `assets/bgm/fx_more2.mp3` と終止用の既存素材を再利用し、全ショートの混音経路へ接続した。追加の曲作り・素材導入・有料API利用はない。

ショート専用の混音は声とBGMを実測し、ダッキング後もBGMを声より約15 LU下へ調整。札が切り替わる瞬間に既存 `sfx.make('transition','b')` の短い音を使い、同じ札での話者交代には鳴らさない。効果音のピークは声より12dB以上下。混音後とAAC圧縮後を両方検査し、音量が大きすぎれば制作を止める。`audio_mix.json` と動画名ごとの `.audio_mix.json` に記録する。

以下は、大小・無音・単発の高いピークを含む人工の声相当の波形と、実際の既存BGM・効果音を混ぜた実測。実ナレーション全編の測定ではない。LUFSとdBTPはFFmpegのEBU R128測定、差はLU。[測定方法（FFmpeg公式）](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)

| 試験音 | 声 LUFS | BGM LUFS | 声との差 LU | AAC後 LUFS | AAC後 dBTP |
|---|---:|---:|---:|---:|---:|
| normal | -20.06 | -35.04 | 14.98 | -20.08 | -11.52 |
| quiet | -37.21 | -52.05 | 14.84 | -37.26 | -28.65 |
| hot | -13.99 | -28.97 | 14.98 | -14.00 | -5.57 |
| spike | -21.97 | -36.94 | 14.97 | -21.72 | -2.12 |

混音段の合格条件は差13〜17 LU・真のピーク−1.5 dBTP以下・−13 LUFS以下、圧縮後は−1 dBTP以下・−12 LUFS以下。従来の長編用 `mix_file` の既定値・本文・配信は変更していない。

## 同じ文を二重に出さない方針

| 型 | 残す場所と理由 |
|---|---|
| 朝の報道・ファンの声、欧州の声 | 中央の大きい引用を残し、同文の下字幕を消す。引用の字を一度で追えるため。球団名の表示変換前の元文でも照合する。 |
| 朝の選手・PS、欧州結果・順位・週・予告 | 中央の数値・項目の札を残し、同文だけ下字幕を消す。別の因果説明や補足は下字幕に残せるため。 |
| 日本代表 | 中央の選手・所属・確定事実を残し、同文だけ下字幕を消す。名簿と所属を読む視線を保つため。 |
| MLB資産・用語・PS速報・選手回・答え合わせ | 中央の札を残し、同文だけ下字幕を消す。用語の短い定義や数値を大きく保ち、異なる説明は残せるため。 |
| 全型の締め | チャンネル名と共通の1行を残し、下字幕を出さない。2秒で読める情報量にするため。 |

小さな胸上のキャラと下隅の配置は既存部品を使用。新しい回転・めくり・強い弾みは追加していない。確認画像 `build_reports/short_common_20261108/contact.png` は締め2枚と重複の有無2枚（引用本文は確認用の仮文）。日本語をUTF-8で再生成し、同文字幕が無く補足字幕が残ることと安全域を検査した。

## sample_only の使い方

この変更の取込後、GitHub Actionsで対象workflowのRun workflowを開き、既存の型・topic・modesなどは従来どおり選び、`sample_only=true` にする。既定はbooleanのfalse。falseと定時実行の既存入力・cron・通常動作は保持する。[入力の型（GitHub公式）](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

- 朝の4本: `morning_recap.yml` の既存 `modes` で選択。成果物は `sample-morning`、`sample-morning_voices`、`sample-morning_press`、`sample-morning_postseason`。
- MLB日次: `daily_notify.yml` → `sample-daily`。資産・用語: `asset_video.yml` → `sample-asset`。`season_review`、`offseason_news`、`ps_game_now`、`player_story` は `sample-<workflow名>`。
- 欧州: `soccer_daily/results/race/week/voices/now/goal_short.yml` → `sample-<workflow名>`。代表: `soccer_national.yml` → `sample-soccer_national`。
- 週次答え合わせ: `weekly_summary.yml` → `sample-verdict`。見本時は別の長編の制作を省略する。

mp4と音量の検査記録を7日間のartifactに保存。見本時はYouTube・SNS・公開台帳・コミット・通知・Pages更新を飛ばす。描画と公開が同じ段の型は描画直後で分岐して公開命令へ到達させない。通常のSNS向けartifactも保存しない。`workflow_run` の後続も見本の識別を読み、さらに後ろへ識別を伝える。朝の全描画が失敗しても識別artifactを残す。素材不足でmp4が作れなければ失敗として知らせ、空の見本を成功扱いにしない。既存の公開スイッチ・実際の変数や予約の設定は変更していない。

## 確認結果と限界

- 関連25試験ファイルが成功。前回残った3組（掛け合い画面、日本代表の補充、PS番組）も成功。画面検査の状態を試験ごとに明示し、締めを追加しても本文の札だけの検査を保った。
- `scripts/run_checks.py` を全体・非分割で1回実行。初回は終了コード1、1326.6秒、262試験ファイル中24組で失敗。失敗した24組と影響範囲を含む49組を修正後に再試験し、すべて成功。全体の再実行はしていない。ログ `build_reports/short_common_20261108/run_checks.log`、時間記録 `check_timings.json`。
- 共通締めの上限、BGM実測、圧縮後のピーク、同文と補足の出し分け、見本の公開命令不達、後続workflowの識別伝播、旧入力・定時の保持、長編の既存試験を確認。
- 最終の静的検査14項目も成功。文字化け検査を最後に実施。変更された関数の意図しない削除なし。
- 実VOICEVOXでの全型の完成動画、GitHub上の実行、リモートCI、Argon再採点は未実施。前回VOICEVOX接続が応答せず、今回はローカルのコード・試験・静止画と実測混音で確認した。次はClaudeが取込後にsample_onlyで完成見本を作り、Argonへ再採点する。
- 作業・試験開始は指定の禁止時間外。HANDOFF、鍵、公開・予約・切替の実設定は触っていない。ローカルコミットのみ、push・公開・外部への通知なし。

## 変更したファイル

- `.github/workflows/`: `asset_social.yml`, `asset_video.yml`, `bluesky_reconcile.yml`, `buffer_daily.yml`, `daily_notify.yml`, `longform.yml`, `morning_recap.yml`, `offseason_news.yml`, `player_story.yml`, `ps_game_now.yml`, `season_review.yml`, `soccer_daily.yml`, `soccer_goal_short.yml`, `soccer_national.yml`, `soccer_now.yml`, `soccer_race.yml`, `soccer_results.yml`, `soccer_voices.yml`, `soccer_week.yml`, `watchdog.yml`, `weekly_summary.yml`
- `build_reports/`: `short_common_20261108.md`
- `scripts/`: `characters.py`, `daily_v3.py`, `duo.py`, `duo_presenter.py`, `generate_asset_video.py`, `generate_morning_short.py`, `generate_narration.py`, `generate_ps_preview.py`, `generate_verdict_short.py`, `generate_video.py`, `offseason_market.py`, `offseason_news.py`, `player_screens.py`, `player_story.py`, `player_story_render.py`, `preview_bubble_all.py`, `ps_program.py`, `render_timeline.py`, `review_render_v3.py`, `sample_only.py`, `sample_source.py`, `short_common.py`, `short_content.py`, `short_saved_render.py`, `short_v4_cards.py`, `soccer_national.py`, `soccer_national_render.py`, `soccer_now.py`, `soccer_readable.py`, `soccer_results_render.py`, `soccer_slots_v4.py`, `soccer_v5_cards.py`, `soccer_voices.py`, `soccer_voices_render.py`, `sound_mix.py`, `test_bubble_all.py`, `test_daily_v3.py`, `test_dialogue_batch.py`, `test_offseason_market.py`, `test_offseason_news.py`, `test_outro_next.py`, `test_player_story.py`, `test_ps_design_v3.py`, `test_ps_program.py`, `test_reddit_reaction.py`, `test_sanity_grounding.py`, `test_short_common.py`, `test_short_polish.py`, `test_short_sample.py`, `test_soccer_daily_retry.py`, `test_soccer_length.py`, `test_soccer_national.py`, `test_soccer_national_squad.py`, `test_soccer_preview_results.py`, `test_soccer_race_length.py`, `test_soccer_results.py`, `test_soccer_results_polish.py`, `test_soccer_results_upload.py`, `test_soccer_slots_v4.py`, `test_soccer_stable.py`, `test_soccer_stats.py`, `test_soccer_title_v2.py`, `test_soccer_v5.py`, `test_soccer_voices.py`, `test_trial_readiness.py`, `test_unified_v3.py`, `test_v3_rules.py`, `test_voices_alignment.py`
- `scripts/fixtures/mlb-badge/`: `protected-source.json`
- `scripts/fixtures/offseason-real/`: `protected-source.json`
- `scripts/fixtures/short-common/`: `workflow_baseline.json`
- `scripts/fixtures/soccer-slots/`: `v5-protected-source.json`

## 全体検査後の修正と検証方法

全体検査は2026-11-08 16:10から1回実行（262ファイル）。静的項目はすべて成功し、試験24組で失敗が出たため、共通仕様と既存試験の整合を修正した。最終状態は49組の再試験と14項目の静的再確認で成功。元の全体検査ログは失敗時のまま保存し、合格したものに書き換えていない。

- 同文字幕の省略は画像のメタデータに理由を記録し、見本の点検でも意図した省略と描画漏れを区別する。補足の字幕は引き続き検査する。
- 市場の読み上げと原稿照合の締めを統一。PSは従来と新しい締めの双方の記録キーを読み、見た目の変更で既存の公開を重複させない。台帳への書き込みはしていない。
- 旧い保存資料との比較は本文を厳密に保ち、共通の締めだけを正規化。長さの境界を再現する試験音は、短縮した宣伝の時間を本文の無音WAV側へ移す人工入力であり、実音声の測定値ではない。古い長い締めの音声を新しい読み上げとして流用しない。
- 動きの後の余白と英字幕の読字時間を反映した後も、締めの最終尺は2.5秒以下。2.45秒の試験音声を動きありで計算し、最終75フレーム/30fps（2.50秒）以下を確認。締めの旧英字幕は残さない。締めの画面は既存の静止予算内で止める。
- Windowsの再試験はPYTHONUTF8=1、pytestの一時領域はこの作業コピー内へ指定。実SDKを偽通信で試す検査は、そのSDK自身が使うHTTPクライアントで構築し版差に対応した。外部通信・有料API呼び出しはない。
- 確認用のローカルスクリプトは build/codex/tmp/finish_short_common_1108.py。全体検査の一度だけの実行記録を保持し、失敗分と変更の影響範囲だけを追加確認した。ログは build_reports/short_common_20261108/repair_test_*.log、最終の静的確認は final_static.log。
