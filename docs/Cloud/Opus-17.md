# Opus-17: 試合の話題・2勝0敗の話題も新デザイン（電光掲示板）に — 表紙の材料の下書き

作成: 2026-10-06 深夜 コレスポのPCのClaude（エマ）。

> **コレスポのコードとデータ**: このリポジトリの `collespo/src/` にある写し（説明は `collespo/src/README.md`、main 341065c 時点）。指示書の中の「`scripts/…`」「`data/…`」「`assets/…`」は `collespo/src/` の下のパスとして読む。`collespo/src/` は書き換えない。成果物は `collespo/` の下（`src/` の外）に作り、PRで出す。秘密は書かない（APIキーなどは無い前提で、呼ぶ部分は差し替えられる形に）。本番のコードは直接変えない（取り込みはコレスポのPCのClaude）。

## 背景
新デザイン `scripts/review_render_v3.py`（style="v3"）は、いま連勝の話題（`scripts/ps_momentum.py`）だけ。表紙は材料の `v3` の辞書（`who`・`big`・`unit`・`sub`・`tag`・`chips`・`ticker`）で描く（`ps_momentum.story` の最後を見る）。本人は「各種動画で使っていきたい」。

## 作るもの（`collespo/v3_topics/`）
1. `scripts/ps_game_story.py`（試合の話題）と `scripts/ps_odds.py`（2勝0敗・0勝2敗）に `v3` を足す変更案（差分と説明）。例: 試合の話題は `big`=勝った側の得点差やスコア、`chips`=回ごとの得点の場面（材料にあるもの）、`ticker`=次の試合。2勝0敗は `big`=「63」`unit`=「/70」など、材料の数字だけ。**材料に無い数字・言葉は足さない。**
2. 写しの `data/ps_game_topics.json`・`data/ps_odds_topics.json` で表紙と項目の画面を描いた PNG（`review_render_v3.intro` / `list_page` を使う。4〜6枚）。
3. 検査（v3 の数字が items の数字と一致すること）と README。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
