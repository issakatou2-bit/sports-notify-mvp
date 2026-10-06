# Opus-12: 案C「逆襲グラフ」を本番の描画（PIL）に — 年ごとの勝ち数の棒グラフ部品

作成: 2026-10-06 夜 コレスポのPCのClaude（エマ）。

> **コレスポのコードとデータ**: このリポジトリの `collespo/src/` にある写し（説明は `collespo/src/README.md`、main ee7d192 時点）。指示書の中の「`scripts/…`」「`data/…`」「`assets/…`」は `collespo/src/` の下のパスとして読む。`collespo/src/` は書き換えない。成果物は `collespo/` の下（`src/` の外）に作り、PRで出す。秘密は書かない。外部APIは呼ばない（材料は写しの `data/` だけ）。

## 共通の作法（3つの指示書 Opus-11〜13 で同じ）
- 10/6、本人が新デザインのモック4案（A 電光掲示板・B 数字ドーン・C 逆襲グラフ・D コメント欄ライブ）を見て「ABCDどれも各種動画で使っていきたい」。**A は本番に入った**: `scripts/review_render_v3.py`（描画）・`scripts/sfx.py`（効果音）・`scripts/sound_mix.py`（BGMと効果音の重ね合わせ）。まずこの3つを読むこと。
- モックは `collespo/指示書/mocks/`（`A_Scoreboard.dc.html` など。540×960 で描いてあり、本番の 1080×1920 の半分。CSS の `@keyframes` と `animation-delay` が動きの時刻表）。画像（`/_blob/…`）は読めなくてよい（立ち絵の位置だけ見る）。
- **review_render_v3.py と同じ作法で書く**: 時刻は「その画面が出てからの秒」t（p は使わない）。時刻表を定数で持ち、描画と `cues()`（効果音の時刻 `[(秒, 種類, 案, 追加dB)]`、種類は sfx.KINDS）が同じ定数を見る。重い部品（札・帯・背景の層）は `functools.lru_cache` で1回だけ作り、毎コマは貼るだけ（1コマ 50ms 以内が目安）。背景は動き続ける（使い回さない）。色は `review_render_v3.colors(team_id)` を使う。書体は `ps_brand_components.font` と `review_render_v3.num_font`。安全域（`ps_render_template.SAFE_BOTTOM`・`SAFE_RIGHT`）の外に大事な文字を置かない。
- 数字・言葉は材料にあるものだけ。足さない・言い換えない（コレスポの決まり）。
- 本番へのつなぎ込み（generate_*.py の変更）はしない。つなぎ方は README に書く（取り込みはコレスポのPCのClaudeがやる）。
- 見本: 材料の写しで描いたコマを PNG で3〜6枚（`collespo/samples/`）。できれば 24fps で数秒の mp4（無理なら PNG だけでよい）。
- 検査: `collespo/test_<名前>.py`（unittest、外部APIなし）。大きさ 1080×1920・時刻表と cues の一致・材料に無い数字を描かない、を確かめる。


## 作るもの
1. `collespo/chart_render.py`: 年ごとの勝ち数の棒が下から伸び、今季の棒だけ金色、5割（81勝）の点線、最後にポストシーズンの成績の札（例「4-0」）が線でつながって出る（モック `C_Comeback.dc.html`）。関数は `chart(t, records, team_id, ps=None, title_lines=...)`。records は `[(年, 勝, 敗), …]`（古い順）。棒の高さは勝ち数に比例（1つの物差しで描く。ラベルは実際の値）。
2. **つなぎ方の提案**: (a) `scripts/ps_momentum.py` の連勝の話題（すでに `records` を取っている。`story()` の引数）に「歩み」の画面として足す形、(b) `scripts/season_topics.py` の球団まとめに足す形。どちらも、材料（topics の JSON）に何を持たせればよいかを具体的に（キー名・形）。review_render_v3 の項目の画面に「グラフの画面」を1種類足す形が望ましい（`list_page` と同じ並びで、項目の代わりにグラフ）。
3. `cues()`: 棒が伸びる（rise）、札が出る（pop か impact）。
4. 見本（写しの材料から ホワイトソックス 2023 61-101・2024 41-121・2025 60-102・2026 84-78 とPS 4-0 で）・検査・`collespo/README_chart.md`。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
