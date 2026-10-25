# 公開前点検の共通入口

作業日2026-10-25、基点#240の92fa46c7。#240の枝を変更せず、
`hiro/sanity-gate-20261026`に積む。公開・設定切替・pushは対象外。

呼び方は全経路で次の6引数に統一する。材料は生成時の入力を原稿の
`sanity_materials`へ保存して渡す。原稿hashによる範囲指定・出典・取得日時を維持する。

```sh
python scripts/sanity.py --general --strict --narration 原稿.json --out 点検.json --hold-record 保留.json --kind 種類
```

| 経路 | 従来の差異・迂回 | 今回の接続 |
|---|---|---|
| daily_notify | 原稿・出力先が暗黙、別原稿まで既定で点検 | dailyの原稿を明示、従来のhold先を維持 |
| morning_recap | 原稿なしの事前点検、独立した数字照合で先に停止 | 原稿なし呼出しを廃止、数字照合の停止も共通入口へ |
| longform | kindが暗黙、数字照合の別停止 | kind明示、数字照合の停止も共通入口へ |
| asset_video | sanityを経ず投稿可能 | 各トピックの完成原稿を点検し失敗した1本をcontinue |
| season_review・ps_game_now | general/kindなし | 同じ6引数、&&で失敗した1本の投稿を止める |
| weekly_summary（weekly/verdict） | 両方ともsanityなし | 原稿ごとに独立したgate、成功条件で投稿 |
| soccer_daily・soccer_race・soccer_week | 出力先・hold・kindなし | 原稿ごとに明示、既存の成功条件を維持 |
| soccer_results | sanityなし、尺調整で原稿が変化 | 尺調整・描画後の完成原稿を点検 |
| soccer_voices・player_story | sanityなし | 原稿の生成後にgate |
| soccer_now・soccer_goal_short | Python内部から直接投稿 | 投稿要求・pending記録の前でsanity.commandの同じCLIをcheck=Trueで実行 |
| correct_video・design_preview・morning_design_preview | strictのみ、hold/kind等の欠落 | 同じ6引数、試作にも記録 |

16workflow・17個の直接呼出しと、Python経由の速報2種類が対象。
`sanity_workflows.errors()`をrun_checksへ組み込み、引数の欠落・順序・原稿違い・
必要呼出しの消失・投稿種類との不一致・投稿成功条件の消失・ループ内の失敗無視・記録保存漏れを検出する。
UI音声在庫の`current_checks`は再利用可否の予備検査であり、公開時の共通gateを代替しない。
`pilot_series`は公開できない非公開の教材試作で、独自の映像/音声検証がある。今回の公開gate対象外。
動画以外の通知・台帳照合・用語辞書・表示検査は用途を保つ。

停止は材料との確定した矛盾、原稿内の計算・数字の確定した誤り、原稿の読取不能。
AIのhighは停止の証拠ではない。材料による裏付けは通し、未知の主張は最大1回再点検する。
再点検後も根拠がない指摘は警告として残す。当季の所属・順位・成績は学習知識で上書きしない。
材料が支えると判定する際も、引用の一部だけを使って余分な主張や否定・過去文を免除しない。

停止候補には指摘行だけの2回目を作り、PS・順位表・名簿・試合結果を読み取り専用で再取得する。
元の原稿と共有dataは変更しない。別原稿の材料を流用せず、過去の日付へ現在の順位・所属を
上書きしない。取得失敗時は元の材料を維持し、既に確定した矛盾をAIの撤回だけで解除しない。
公式APIは最大8要求・各8秒、同一URLの失敗も繰り返さない。未対応のIDやキー不足は記録する。

再点検AIは指摘行・その人物/対戦の小さな材料・元見出しだけを1要求。
最大入力9000 UTF-8 bytes、出力700tokens、台帳の単価による保守的な見積上限$0.03。
上限超過・未知単価・日次上限・キーなしは機械照合だけ行い、スキップ理由を記録する。
SDKと内容の自動リトライは無効。原稿で使っている既存のモデル設定は変更しない。
hold recordと点検JSONの`attempts`に1回目/2回目の指摘・材料・対象行・取得成否・
AIの回数/費用を残す。全workflowで失敗時もartifactを保存する。

回帰集は[sanity_false_stops](../scripts/fixtures/sanity_false_stops/README.md)。
新しい誤停止は独立したJSON1件で自動的に試験対象になる。
リモートCI・実際の再公開・生の再取得/API応答は今回未確認。外部APIを呼ぶ試験は使わない。

検証：全run_checks終了0（構文525ファイル、試験193本、重大0・既存軽微53）。
最終の全体実行中は対象コード/固定材料682ファイルの変更0を確認した。
その後、`soccer_week`の保留記録の種類名を投稿側へ合わせ、投稿の種類との一致検査も追加した。
最後の3ファイルの変更は、構文・pyflakes、新17試験・週末/速報の関連試験、YAML・シェル・
引数値・呼出契約の検査を追加実行してすべて終了0。ログはローカル
`build/codex/tmp/sanity-gate-run-checks-final.log`と`sanity-gate-final-kind-checks.log`。
