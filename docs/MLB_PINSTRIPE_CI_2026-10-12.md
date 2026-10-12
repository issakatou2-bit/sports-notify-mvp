# MLB 縦じま札の CI 検査修正（2026-10-12）

対象：PR #139、`hiro/mlb-badge-20261012`、修正前 `98829681`。

## 原因と修正

`pinstripe_ci_fail.txt` は、切り替え前の `players/0` の全画面 SHA256 比較で失敗している。固定 JSON の欠落や縦じまの描画失敗に到達する前の失敗。
変更前の保存ハッシュは Windows で取得したもの。`ps_brand_components.font` は Windows ではメイリオ/Bahnschrift、Ubuntu CI では Noto CJK/DejaVu を選ぶため、同じ固定材料でも全画面の画素は異なる。Pillow/FreeType の版の差もハッシュには含まれる。

検査を、固定 JSON と main `2f86ba3f` の凍結済み `short_v4_cards.py` による変更前画面と、現在の未設定画面との同一環境での画素比較に変更。凍結ソースは出典と SHA256 を記録して照合する。現在のコード自身から期待値を作らない。従来の Windows ハッシュは過去の記録として残し、case/frame の固定一覧のみ利用する。

通常の検査ではリポジトリ同梱 NotoSansJP と Oswald に固定し、個人PCのフォントを使わない。全96画面の一致、全15枠・164札の切り替え、30球団×4寸法の読みやすさ、v3不変、既存配置警告からの増加ゼロを引き続き検査する。`--system-fonts` で通常の描画環境も追加確認できる。本番の描画・フォント・動画・公開設定には変更なし。

## 検証

同じ `players/0` を手元のメイリオと同梱 Noto で描き、前者だけ保存ハッシュに一致することを確認（`font-evidence.json`）。同梱フォントと手元の通常フォントの両方で修正後の96画面比較・164札・30球団検査が成功（`bundled.log` / `system.log`）。既定の札の1画素を意図的に変えると `players/2` で比較が失敗し、未設定時の退行を検出することも確認（`mutation.log`）。

`run_checks` は全125テストファイル・その他検査を通過、終了コード0。`git diff --check` も成功。ログ：`build/codex/tmp/pinstripe-ci-checks/run_checks.log`。
GitHub の再実行結果は未確認。push は Claude が担当。
