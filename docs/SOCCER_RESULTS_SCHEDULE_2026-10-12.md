# 朝8時のサッカー結果（㉝）

担当: ヒロ。main 50b2ef94（#138）から別clone。既存の結果枠は手動のみ、締め8時だったので変更が必要。HANDOFFはmainの版を保持。

- data/soccer_results_schedule.json: 締め07:15、生成07:20、公開08:00。期間は当日の締め以上〜翌日の締め未満。
- soccer_results_clock.window/target_dayへ区切りを集約。終了時刻が冬時間の06:50でも同じ夜に入る。定時は最後に締めた夜を選び、手動の空日付は従来どおり前日を選ぶ。--dateの明示指定は維持。
- workflowのcronはUTC22:20（JST翌07:20）。SOCCER_RESULTS_PUBLISH=trueだけ定時実行し予約公開する。未設定/falseは定時処理を起動しない。手動のpublish/publish_atは既存どおり。
- 生成が8時を過ぎた場合は未来の予約検査が公開を止める。遅延を即時公開に置き換えない。GitHubのscheduleは定刻を保証しないため、正確な生成開始にはClaude側の外部cron運用が必要（ここでは設定を変更しない）。
- 新規3試験: 冬時間の終わり、締め直前/ちょうど、年末年始、cronと共通表、公開条件。既存の結果/画面の検査も通過。

run_checks: 118試験ファイル、NG0、最後「===== すべて通過 =====」。ログ build/run_checks.log。手元検査まで。CI・実データの生成・公開確認はしていない。

別枝の予告→結果とこの枝のsoccer_results.ymlは重なる。取り込み時はschedule条件と、追加する材料/描画の処理を両方残す。現在の主枝が㉜取込前の50b2ef94だったため、最新main更新後の統合検査はClaude側で確認。

## 2026-10-12 新しい会話での再開

- エマの取得済みorigin/main 2f86ba3f（#138/#128/#140を含む）へ更新。直接git fetchは通信制限で最新リモートの再取得不可。共有コピーの差分は変更していない。
- 締め07:15・開始07:20・公開08:00を共通表へ。定時はSOCCER_RESULTS_PUBLISH=trueだけ。定時は最後に締めた夜、手動の空日付は従来の前日を選ぶ。
- 最終検査: run_checksの123試験ファイルNG0・終了0、すべて通過。ログbuild/run_checks-resume-final.log（UTF-8）。PYTEST_DISABLE_PLUGIN_AUTOLOAD=1でPC側の追加機能を読み込まず実行。検査の除外なし。
- CI・新規ライブ取得・公開物の確認は今回行っていない。push・PR・公開・変数変更なし。取り込みはエマ。
- サッカー3枝の統合確認用は別clone task33-integration-20261012。取り込み順は選定→定時→予告接続。soccer_results.pyのCLIでは対象日を決めた後に予告を読む。
- 再開メモのPowerShell送信時の文字化けをコミット前に修復。UTF-8ファイルから実行し、連続した疑問符/置換文字を検査する補助はbuild/codex/tmp/finalize_task33_20261012.py。
