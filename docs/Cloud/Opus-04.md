# Opus-04: ショートの新デザインに「動き」を足すコードの下書き（カウントアップ・行が浮く・章の見出しカード）

作成: 2026-10-05 コレスポのPCのClaude（エマ）。別アカウントのリポジトリ（作業一覧つき）で、Opus 5.5 に頼む作業。

## 前提
- コレスポのコードは公開リポジトリ https://github.com/issakatou2-bit/sports-notify-mvp （ブランチ `main`）。**読むだけ。**取れなければ作業一覧を「保留」にして理由を書く。
- 成果物は作業をしているリポジトリの `collespo/` に、PRで出す。外部のAPIは使わない。秘密は書かない。

## 背景
本人（10/4）「全体に言えることだけど演出とかアニメーションとかもっと凝りたい」。動きの設計はクラウドがまとめた `docs/Cloud/out/06_motion_spec.md`（8つの動き）と、動く見本 `06_motion_demo.html`。新デザインの描画は `scripts/review_render.py`（シーズンまとめ・PSの話題・試合の話題）と `scripts/ps_render_template.py`・`scripts/ps_motion_template.py`（PSの予告・情勢）。いまの動きは、要素の入場と0.28秒の切り替え、読み上げ中の行の強調（`focus_plan`）くらい。

## 読むもの
1. `docs/Cloud/out/06_motion_spec.md`・`06_motion_demo.html`
2. `scripts/review_render.py`（`intro`・`list_page`・`people`）、`scripts/ps_motion_template.py`、`scripts/ps_render_template.py`
3. `scripts/generate_asset_video.py` の `render_v2`（`review_render` を呼ぶところ。1コマずつ `p` を渡している）
4. `scripts/video_common.py`（`ease_out` など）

## 作るもの（`collespo/`）
1. `collespo/motion.py`: 1コマずつ描く PIL 用の動きの部品。`06_motion_spec.md` の8つのうち、**まず3つ**:
   - **カウントアップ**: 数字が 0 から目標の値まで上がる（小数・%・「打数」のような単位つき、整数と小数の桁を崩さない）。最後の値は必ず材料の値そのもの。
   - **行が浮く**: 一覧の中で、いま読み上げている行（または主役の行）が少し大きく・明るくなる。
   - **章の見出しカード**: 0.3秒前後のワイプで入って、見出しを出し、次の画面へ渡す。
   それぞれ `p`（0〜1）から位置・大きさ・透明度を返す純粋な関数と、PILの画像に描く関数に分ける。
2. `collespo/review_render_motion.py`: `review_render.py` の `list_page`・`people` に上の動きを入れた版の下書き（**元のファイルは書き換えない**。同じ引数で呼べる別の関数として）。
3. `collespo/test_motion.py`: 純粋な関数の検査（カウントアップの最後が材料の値と一致・途中で桁が崩れない・p=0/1 の端・単調に増える）。書体が無い環境でも動く検査にする。
4. 見本: 書体が使えれば `collespo/samples/motion_*.png` に、p=0.25/0.5/1.0 の3コマずつ。
5. `collespo/README_motion.md`: コレスポ側への組み込み方（どのファイルのどこを差し替えるか）、尺への影響（読み上げの長さは変えない）、決めてほしいこと。

## 決まり
- 動きは情報を読ませるため。読む時間を削る飾りは入れない。Shortsの安全域（下18%・右13%）に大事な文字を置かない。
- 数字は材料の値をそのまま。カウントアップの途中の値は画面だけ（読み上げには使わない）。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
