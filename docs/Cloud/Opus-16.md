# Opus-16: 長編の台本を Message Batches API（半額）で作る下書き（間に合わなければ今の呼び方に戻す）

作成: 2026-10-06 深夜 コレスポのPCのClaude（エマ）。

> **コレスポのコードとデータ**: このリポジトリの `collespo/src/` にある写し（説明は `collespo/src/README.md`、main 341065c 時点）。指示書の中の「`scripts/…`」「`data/…`」「`assets/…`」は `collespo/src/` の下のパスとして読む。`collespo/src/` は書き換えない。成果物は `collespo/` の下（`src/` の外）に作り、PRで出す。秘密は書かない（APIキーなどは無い前提で、呼ぶ部分は差し替えられる形に）。本番のコードは直接変えない（取り込みはコレスポのPCのClaude）。

## 背景
API代は直近14日で $1.80。うち長編の台本（`scripts/generate_dialogue.py`、Sonnet 5.5）が半分強。台本の中身を変えずに安くできるのは Batch（料金が半分、ただし結果が返るまで最長24時間）。長編は 15:10 ごろに作り始め 21:00 に予約公開なので、待てる時間はある。

## 作るもの（`collespo/batch/`）
1. `generate_dialogue.py` への変更案（差分 `dialogue_batch.patch` と説明）: 台本を作る呼び出しを Batch で出し、決めた時刻（例: 17:30 JST）までに返らなければ取り消して、いまの呼び方（`_create`）で作る。プロンプト・モデル・effort・検査（longform_editorial 等）は変えない。`token_log.record` に Batch の単価（半額）で残す。
2. 失敗の扱い（エラー・refusal・一部だけ失敗）と、何度も作り直す日の扱い。
3. 検査（API なし、Batch の返事を固定して）。
4. 見積もり: 直近14日の `data/token_usage.json` の dialogue で、月いくら減るか。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
