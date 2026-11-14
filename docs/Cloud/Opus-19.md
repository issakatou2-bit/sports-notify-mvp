# Opus-19: 欧州サッカー（5大リーグ）のショートを、MLB の新デザイン（v4）以上の見た目にする — 見本の絵と描画の部品の下書き

作成: 2026-10-08 夜 コレスポのPCのClaude（エマ）。

> **コレスポのコードとデータ**: 最新は公開リポジトリ `issakatou2-bit/sports-notify-mvp` の main。`https://github.com/issakatou2-bit/sports-notify-mvp/archive/refs/heads/main.tar.gz` を取って読む（このリポジトリの `collespo/src/` の写しは古い）。成果物は `collespo/soccer_v4/` に作り、PRで出す。秘密は書かない。外部の有料APIは呼ばない（football-data.org なども呼ばない。下の保存済みの材料を使う）。本番のコードは直接変えない（取り込みはコレスポのPCのClaude）。

## 背景
- 10/8、ポストシーズンの試合の話題でチャンネル登録者が伸びた。本人「MLBで来てくれたのだとしたら、いかに魅力的に5大リーグをコンテンツとして伝えるかも大事。MLB並み、いやそれ以上のコンテンツとクオリティで」。10月末にMLBのシーズンが終わると、3月まではサッカーが主になる。
- MLB のショートは新しい見た目 v4 になった: `scripts/review_render_v3.py`（地・字幕 `caption`・進み具合 `progress`・立ち絵 `presenter`・帯 `ticker`・締め `outro`）、`scripts/short_v4_cards.py`・`scripts/asset_v4_cards.py`（札の部品）、`scripts/v3_slot_render.py`。切り替えは環境変数 `COLLESPO_SHORT_LOOK=v4`。決まりは `docs/DESIGN_V3_SYSTEM.md` の「今後に生きる決まり」（球団名には必ず球団色の札、読んでいる文を字幕に、数字は材料にあるものだけ、など）。
- いまの欧州サッカーのショートは古い見た目: `scripts/soccer_preview.py`（19:00 欧州サッカー、材料 `data/soccer_preview.json`・`data/soccer_games.json`）、`scripts/soccer_race.py`（順位争い、`data/soccer_race.json`）、`scripts/soccer_jp_week.py`（日本人選手の週末）。描画は `scripts/generate_morning_short.py` などの古い部品。
- 声は四国めたん（解説）。会話の回ではずんだもんも出す方向（本人「めたんが喋ってるだけの動画が多い」）。

## 作るもの（`collespo/soccer_v4/`）
1. **見本の絵（1080×1920、最低6枚）** `collespo/samples/soccer_v4_*.png`: 保存済みの材料（上の `data/soccer_*.json`、無い項目は使わない）で、v4 の部品と同じ作法で描く。
   - 試合の結果: スコアボード（両クラブの札・スコア・**得点経過の時間軸**（分と得点者、ホーム／アウェーを上下に）・前半後半の区切り）。
   - 日本人選手: 名前＋クラブの札、出場時間・ゴール・アシストなど材料にある数字の札、大きな数字（無ければ札だけ）。
   - 順位表: リーグごと、上位と自分のクラブの周り、**CL・EL・降格の線を色で**、勝点の差。
   - 週末の注目試合（予告）: 日時（日本時間）を大きく、両クラブの札、日本人選手、順位の並び。
   - 表紙: その日の主役（日本人選手かクラブ）と大きな数字。
   - 締めは共通の `review_render_v3.outro` を使う（作らない）。
2. **クラブ色の表** `club_colors.json`: 5大リーグ（プレミア・ラ・リーガ・ブンデス・セリエA・リーグアン）の今季の全クラブの主色・2色目（16進）。出典の種類をメモに（公式のブランド資料・ユニフォームなど。推測で埋めない。分からないものは空にして一覧に書く）。
3. **描画の部品の下書き** `soccer_v4_cards.py`: 上の絵を描く関数（材料の辞書を受けて、時刻 t の 1080×1920 を返す）。v4 の部品を呼び、地・字幕・立ち絵・帯・締めは作り直さない。数字は材料にあるものだけ。
4. **検査** `test_soccer_v4_cards.py`（APIなし）: 寸法・安全域（`v3_rules.check_layout` を使う）・材料に無い数字を描かない・クラブ名の横にクラブの札。
5. **README.md**: 本番へのつなぎ方（どの枠のどこで切り替えるか、`COLLESPO_SHORT_LOOK=v4` のときだけ）、材料に足すと良いもの（得点経過・出場時間など、football-data.org の無料枠で取れるかの見込み）、MLB より良くするための工夫の案（3〜5個）。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
