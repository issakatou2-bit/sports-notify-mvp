# Cloud-09: 17:00「日本人選手の成績」の新デザインを描くコードの下書き（Cloud-04 の手本を本番の描き方へ）

作成: 2026-10-05 PCのClaude。Cloud-01・04 で作った手本（`docs/Cloud/out/01_morning_v2.html`・`04_morning_v2b.html`）を、本番と同じ Python（PIL）で1コマずつ描くコードの**下書き**にする。PC側が検査・音声・動画にして本番へつなぐ。

## 0章 最初に必ず

`docs/Cloud/Cloud-TEMPLATE.md` の0章の決まりに従う（新しいファイルだけ、外部に通信しない、公開しない、秘密を書かない、拾い方）。読む順: `docs/Cloud/README.md` → この指示書 → 1章の材料。作業用ブランチは `cloud/09-morning-v2-render`（セッションで決められていればそれ）。

## 1章 作るもの

### A. `scripts/morning_v2_render.py`（新しいファイル）

17:00の回の画面を、新デザインで1枚ずつ返す関数の集まり。**今ある `scripts/review_render.py` と同じ書き方に合わせる**（`ps_brand_components` の `TOKENS`・`font`、`ps_render_template` の `background`・`SAFE_BOTTOM`・`SAFE_RIGHT`、`video_common` の `ease_out`）。

| 関数 | 中身 | 手本 |
|---|---|---|
| `cover(p, day_label, players)` | 表紙。上に小さく「10月4日（日本時間）日本人選手の成績」、いちばんの選手を大きく、下の3分の1に2位以下を1行ずつ | 04 の表紙 |
| `player(p, row, rank)` | 1人ずつ。打者は打数・安打・本塁打／打点・四球・得点の大きな数字、投手は投球回・被安打・自責／奪三振・四球・失点。場面（`clutch_label`・`clutch_plays`）があれば下に | 04 の2枚目 |
| `roster(p, rows, page, pages)` | 一覧。1枚4人まで、多い日はページを分ける | 04 の3枚目 |

- `p` は画面の中の進み具合（0〜1）。入場の動きは `review_render.py` と同じ程度（文字が少し下から現れる）。動きを増やしすぎない。
- 並び順は `scripts/generate_morning_short.py` の `sort_players` と同じ（自分で並べ直さない。呼ぶ）。
- 数字は材料の値をそのまま描く。**計算で作った数字を描かない**（並べ順の点数を描く場合は `morning_recap.contribution` を呼ぶ）。
- 投手の `hits` は被安打。打者と混ぜない。投手の行に `r`（失点）・`hbp`（死球）があれば描く（10/5から材料に入った）。
- 文字の大きさの下限: 本文40px、注記32px（1080×1920 の座標）。安全域（下18%・右13%）に大事な文字を置かない。

### B. `scripts/test_morning_v2_render.py`（新しいファイル）

- `data/recap_history/2026-09-25.json`（7人）と `2026-09-29.json`（3人）を材料に、各関数が 1080×1920 の画像を返すこと、ページ分けの枚数、並び順が `sort_players` と同じことを確かめる。
- **書体が無い環境でも落ちない検査**にする（書体を読めないときは描画の検査を飛ばし、並び順・ページ分けの検査だけ動かす）。クラウドで描画まで動かせたら、見本のPNGを `docs/Cloud/out/09_morning_v2_*.png` に3枚保存する。

- 完成の条件: A・B がそろい、`python scripts/test_morning_v2_render.py` が通る（描画を飛ばした場合はそう書く）。

## 2章 決まり

- 既存のファイルは書き換えない（呼ぶだけ）。足りない関数があれば、新しいファイルの中に書く。
- 材料に無い数字・選手を描かない。見出しに読点で区切るキャッチコピーを使わない。

## 3章 終わったら

main へPR。題 `Cloud-09: 17:00成績の新デザインを描くコードの下書き`。説明に「見方」（検査の動かし方、PNGの場所）と「決めてほしいこと」（スコアの数字を画面に出すか、など）。`docs/Cloud/作業記録.md` に「済」を追記。
