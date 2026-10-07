# Opus-18: 長編（横長 1920×1080）を新デザイン「電光掲示板」で描く — 描画コードの下書き

作成: 2026-10-07 夜 コレスポのPCのClaude（エマ）。

> **コレスポのコードとデータ**: このリポジトリの `collespo/src/` にある写し（説明は `collespo/src/README.md`、main 6407782 時点）。指示書の中の「`scripts/…`」「`data/…`」「`assets/…`」は `collespo/src/` の下のパスとして読む。`collespo/src/` は書き換えない。成果物は `collespo/` の下（`src/` の外）に作り、PRで出す。秘密は書かない。外部APIは呼ばない。本番のコードは直接変えない（取り込みはコレスポのPCのClaude）。

## 背景
ショートは新デザイン（`scripts/review_render_v3.py`：球団色の地にピンストライプと照明・札・テロップ・四国めたん・BGM・効果音 `scripts/sound_mix.py`）へ移っている。長編（`scripts/generate_longform.py`、ずんだもんと四国めたんの対話、画面は `render_line` / `render_panel` / `_panel_*`）だけが古い見た目で、立ち絵も古い版。本人「長編も早く」。

モック: `collespo/指示書/mocks/E_Longform.dc.html`（960×540 で描いてあり本番の半分。CSS の `@keyframes` が動きの時刻表）、いまの画面 `collespo/指示書/mocks/longform_now.png`。

## 作るもの（`collespo/longform_v3/`）
1. `longform_render_v3.py`: `generate_longform.render_line(p, seg, …)` と同じ材料（seg・panel・topic）を受け、時刻 t（その台詞が出てからの秒）で 1920×1080 を描く関数。
   - 地: `review_render_v3.background` と同じ考え方を横長に（ストライプ・照明・上の帯）。球団色は panel の球団（分からなければ既定の色）。
   - 上: コレスポ・回の題・章の札（材料にある章の切れ目から。無ければ出さない）と進み具合の線。
   - 左: panel の札。`_panel_*` の種類（score/views/quote/stat/star/group/topic）ごとに、モックの札の作法で（大きな数字は Oswald で回って止まる、順位は目盛り、引用は札）。**数字・言葉は panel にあるものだけ**。
   - 右: 四国めたん（`assets/portraits/collespo-20260923/metan/3-black/base.png`）を大きく、ずんだもん（`…/zundamon/C-cheer/base-black-brow-candidate.png`）を少し小さく。話している方を明るく、もう一人は少し暗く。
   - 下: 字幕の札（話者の名前の札つき、文字が左から現れる）。
   - `cues()`（効果音の時刻、`sfx.KINDS`）を描画と同じ時刻表から。
2. 本番へのつなぎ方の説明（`README.md`）: `generate_longform.py` のどこで切り替えるか（環境変数で切り替え、既定は今の見た目）、BGM・効果音の重ね方（`generate_asset_video.add_sound` が手本）、尺は変えない。
3. 検査（`test_longform_render_v3.py`、APIなし）: 1920×1080、panel の種類ごとに描ける、材料に無い数字を描かない、話者の明暗。
4. 見本: 写しの材料で、panel の種類ごとに1枚ずつ PNG（`collespo/samples/longform_v3_*.png`）。材料の見本は `scripts/test_longform_material.py`・`test_dialogue.py` の中の固定の材料を使ってよい。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
