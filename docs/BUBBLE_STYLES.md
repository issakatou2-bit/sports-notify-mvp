# 斜めカットとガラスの吹き出し

`COLLESPO_BUBBLE=slant` / `glass` のときだけ切り替える。未設定・空文字・未知の値は既存の描画を通す。変数自体は今回設定していない。

- **slant**: クリーム地の斜めカット、話者色の帯と細い3本の線、濃い斜めの名札と話者色の名前。保存されたClaudeの見本の形を使う。小さい数字も読めるよう、数字の金色は濃くした。
- **glass**: `C:/Users/issak/Tools/shared-design/liquid_glass.py` の同一コピーを同梱。ぼかし3・屈折42・bezel46・darken0.22。白い本文に影、数字は(255,210,90)。名札も小さいガラスで話者色を0.6乗せ、名前は白＋濃い縁を付ける。
- **背景の案**: glassだけ `COLLESPO_GLASS_BACKGROUND=stripes`（既定、話者色の縦じま）/ `lights`（話者色のぼけた球場の光）。吹き出し近くに限定し、主情報の領域は変えない。
- 背景が明るい場合、文字の位置のコントラストが4.5未満なら本文の後ろに局所的な暗い補助を足す。指定のglass描画パラメータは変えない。数字を含む本文は実際の文字の不透明部分と、文字を重ねる前の画素を測る。名札は白文字を囲む不透明な濃い縁との比を測る。
- サッカーv5は専用字幕を持つため、変数指定時だけ `characters.bubble()` へ渡す。既定のv5字幕・進捗線は保持する。描画workflow15本で両変数をプロセスへ渡す。

## 試作の入口

共有コピーの `build/codex/tmp/bubble-styles-preview/review.html`。MLB17時（保存10/5材料）と欧州サッカー予告（保存9/18材料）を各3案、計6本。全33画面のPNG、一覧、保存音声つきMP4、`confirmation.json` を置いた。

これは各場面の静止画＋保存音声による見た目の試作。従来のフレーム描画を呼び、保存音声の文/話者/尺を照合した。動きの連続性・当日の情報・CI・公開物は未確認。投稿処理は呼ばない。

再現:

```sh
python scripts/preview_bubble_styles.py --mlb-dir /path/to/mlb-pinstripe-previews/1700-players --soccer-dir /path/to/soccer-v5-previews/preview --out /path/to/bubble-styles-preview
```

試作だけは保存音声を指定する。CI試験は同梱の固定材料と `assets/fonts/soccer-v5/NotoSansJP-VF.ttf` / `assets/fonts/Oswald[wght].ttf` を使い、上のローカル保存場所には依存しない。

## 確認

- `test_bubble_styles.py`: 未設定/未知値/空文の画素一致、両話者、明暗背景、2種類のガラス背景、本文/名札4.5以上、長文の黙った切捨て禁止、サッカーv5の既定画素一致と接続。
- 比較用の旧関数はmain09b1ea3eから固定材料に保存。検査時に過去のGitコミットを取り出さない。
- 既存の保護ハッシュは、今回意図して変えた `characters.py` の1件だけ既存の `update_protected_hashes.py --write` で更新。他の共通部品の基準は保持する。
- MLB既定6画面・サッカー既定5画面も旧関数と画素比較。新しい案は本文最小4.76、斜めカット5.58以上。画像を見て名前/本文/数字の配置も確認。6本とも動画の全尺復号に成功。
- `scripts/liquid_glass.py` は共通原本とSHA256一致。原本にある未使用変数は、そのまま使う指定に従い変更しない。
- 全体検査の最新記録は試作フォルダの `run_checks-final.log`。結果は作業報告へ。push・公開・本番変数設定は今回行わない。
