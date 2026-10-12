# ヒロからエマへ 2026-10-12 夜作業

各cloneは `build/codex/tmp/` の下。すべて同じ `origin/main bbf007319bf9d6f4e9e31bfdf8b770980fb4d189` から独立している。作業開始時にmainの既修正を確認し、残る生成側の不足を対象にした。共有の未commit変更と㉗ `hiro/soccer-v5-20261011` は変更していない。

| 項目 | clone / 枝 | commit | 内容 / 詳細 |
| --- | --- | --- | --- |
| A | backstage-20261012 / hiro/backstage-20261012 | 9b57203faa7ab1df416a197b985caeb4f78239c6 | 共通辞書・1回訂正・行除外/失敗・ログ・費用記録。docs/BACKSTAGE_GUARD_2026-10-12.md |
| B | fact-guards-20261012 / hiro/fact-guards-20261012 | fd6a8757184ea2774d5a7c7565928b7fb38ed284 | 得点/PS前後、訳の役割、会場の照合。docs/FACT_GUARDS_2026-10-12.md |
| D1 | ps-material-20261012 / hiro/ps-material-20261012 | c41ef43617e796ec7fb852c7b4b7ea867156adcf | PS入力からRS連勝/直近/進出状態を除外。docs/PS_AI_MATERIAL_2026-10-12.md |
| D2 | archive-public-20261012 / hiro/archive-public-20261012 | この資料を含む枝のHEAD | 確認済み公開状態を台帳へ保存し過去一覧で守る。docs/ARCHIVE_VISIBILITY_2026-10-12.md |

A/B/D1/D2の最終run_checksはいずれも全108試験ファイル・NG0「===== すべて通過 =====」。各cloneの `build/verification/` に手元ログを保持。CI/新実API生成/公開物の確認はしていない。課金呼び出し、push、PR、公開、リポジトリ変数の切替はしていない。

DはBACKLOGの生成側で解決できる2件を選んだ。公開判断やデザイン判断を追加で必要とせず、実際の入力/一覧の問題に対する回帰検査を作れるため。

## 取り込みで残すもの

- A/B/D1はnotability_engine.py、A/Bはgenerate_dialogue/local_voices/mlb_buzzを共有する。同じmainからの独立差分なので、どれか一方を捨てずに統合する。
- 各docs/HANDOFF.mdはmainにないためadd/addになる。完了の現在地と詳細資料への入口を短くまとめる。BACKLOG/DECISIONSも各枝の追記を保つ。
- 10/10夜点検本文は共有コピー・mainに見つからずGitHub取得も404。10/8・10/9と共有HANDOFFの記録を使ったが、未入手の資料の残件を網羅したとはしない。
- Bの文章検査は実際の失敗と明確な周辺表現を対象とする。自由文全体の意味保証ではない。新実例は辞書/検査/試験材料へ戻す。
- D2は台帳に残る状態を守る。状態がない昔の手動変更と予約後の実公開は別の照合が必要。既存の公開データ/動画を今回書き換えてはいない。

モデル: GPT-6。実際のサブモデル/深さと週の使用率はこのセッションのツールから取得できず、変更前後の率を推測しない。
