# Opus-15: 話題探しの下書き（AIが切り口を挙げ、数字はプログラムが公式から取って確かめる）

作成: 2026-10-06 深夜 コレスポのPCのClaude（エマ）。

> **コレスポのコードとデータ**: このリポジトリの `collespo/src/` にある写し（説明は `collespo/src/README.md`、main 341065c 時点）。指示書の中の「`scripts/…`」「`data/…`」「`assets/…`」は `collespo/src/` の下のパスとして読む。`collespo/src/` は書き換えない。成果物は `collespo/` の下（`src/` の外）に作り、PRで出す。秘密は書かない（APIキーなどは無い前提で、呼ぶ部分は差し替えられる形に）。本番のコードは直接変えない（取り込みはコレスポのPCのClaude）。

## 背景
いまの話題は決まった型の組み立て（`scripts/ps_game_story.py` 試合の話題・`ps_odds.py` 2勝0敗・`ps_momentum.py` 連勝・`ps_story.py` シリーズの総括・`season_topics.py`）。10/6、MLB.com の見出し「本拠地での突破は120年ぶり？」から、公式の試合記録で確かめて「勝てば本拠地で120年ぶりの突破」を話題にした（`ps_momentum.last_home_clinch`）。これを毎日自動でやりたい。**AIに数字を書かせない**のがコレスポの決まり。

## 作るもの（`collespo/scout/`）
1. `topic_scout.py`: 材料（`data/local_reporters.json` の見出し、`data/local_voices.json` のコメント、`data/postseason.json`、`data/ps_*_topics.json`〔既に出した・出す予定の話題〕）を読み、**Claude Haiku 4.5（`claude-haiku-4-5-20251001`）**に「切り口」と「それを言うのに要る数字の問い合わせ」を最大3つ、決まった JSON で出させる。問い合わせは決まった型だけ（例: `{"type": "last_home_clinch", "team_id": 145}`、`{"type": "season_record", "team_id": 145, "years": [2023, 2024, 2025]}`、`{"type": "series_history", "round": "D", "state": "2-0"}`）。API を呼ぶ部分は差し替えられる関数に（検査では固定の返事を使う）。
2. `verify.py`: 問い合わせの型ごとに、MLB Stats API から数字を取って確かめる関数（`ps_momentum.py`・`ps_odds.py` の関数を使い回す）。確かめられなかった切口は捨てる。結果を `ps_momentum` と同じ形の話題（`items` など、`style: "v3"`）にする関数も。
3. 料金の見積もり: 1回の入力・出力トークン数を、写しの材料で数えて書く（`scripts/token_log.py` の単価で）。
4. 検査 `collespo/scout/test_scout.py`（APIなし、固定の返事で）と `collespo/scout/README.md`（どのワークフローのどこで、何時に動かすか、出す前に人が見る段の案）。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
