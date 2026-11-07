# 区間ごとのコマ数の切り捨て修正（2026-11-08）

作業場所：`build/codex/tmp/wt-efficiency`、枝：`hiro/frame-total`。既存の写しを再利用した。開始時の未追跡の efficiency 報告は残した。
GitHub への fetch は接続拒否で失敗したため、共有コピーの origin/main（3084737e、#338 を含む）をローカル fetch して基点にした。GitHub 上の最新状態・CI は未確認。push・公開・設定変更はしていない。HANDOFF は読取のみ。

## 変更した場所

- `scripts/video_common.py:27`, `scripts/video_common.py:441` : 通算コマ数の共通関数と、音声の余白をサンプル数でそろえる処理。
- `scripts/generate_asset_video.py:1999` : #338の通算計算を共通関数へ移した。
- `scripts/generate_longform.py:960` : 分割ページのコマ割当と全体のまばたき用コマ数を共通化。
- `scripts/generate_morning_short.py:4144`, `scripts/generate_morning_short.py:4578` : 選手単独版と通常版の2つの描画ループを修正。
- `scripts/generate_verdict_short.py:536` : 答え合わせの区間コマ数を修正。
- `scripts/generate_video.py:1062` : 日次のコマ割当と音声結合を同じ計画尺に統一。
- `scripts/generate_weekly.py:499` : 週次の区間コマ数を修正。
- `scripts/generate_ps_preview.py:168` : 区間ごとのroundも累積誤差になるため共通化。
- `scripts/longform_render_v3.py:1203` : 長編の映像・効果音の時刻表を同じコマ境界に統一。
- `scripts/fan_events.py:92` : 表情と効果音の区間境界を修正。
- `scripts/lipsync.py:92` : 口パクの区間境界と配列の長さを修正。
- `scripts/hook_ab.py:170` : A/Bの場面・台詞開始時刻と全体尺を修正。
- `scripts/preview_motion.py:90` : 音声付きの動き見本のコマ割当を修正。
- `scripts/preview_solo_host.py:113` : 単独司会の音声付き見本のコマ割当を修正。
- `scripts/test_hook_ab.py:196`, `scripts/test_hook_ab.py:205` : 既存の場面境界の期待値を通算丸めに更新。
- `scripts/test_frame_total.py:26`, `scripts/test_frame_total.py:34`, `scripts/test_frame_total.py:70`, `scripts/test_frame_total.py:85`, `scripts/test_frame_total.py:106`, `scripts/test_frame_total.py:122` : 描画なしの回帰試験6件を追加。

- `scripts/fixtures/mlb-badge/protected-source.json:4` : 意図した生成器変更の保護指紋を更新（同じ表の generate_video.py も更新）。
- `scripts/fixtures/soccer-slots/v5-protected-source.json:6` : 共通処理と生成器2本の保護指紋を更新。画素の基点は変更していない。
- `scripts/test_dialogue_batch.py:501` : 試験のHTTP実装をSDKが実際に使うものに合わせた。httpx2固定による手元SDKとの型不一致を解消。
- `scripts/test_sanity_all_materials.py:66` : 既存試験のJSON読取りをUTF-8で明示。
- `scripts/test_sanity_grounding.py:76`, `scripts/test_sanity_grounding.py:110`, `scripts/test_sanity_grounding.py:174`, `scripts/test_sanity_grounding.py:324` : 同上（4か所）。
- `scripts/test_slant_by_episode.py:170` : run_checksから渡す試験用フォルダーを使用。単独起動時も作業場所内に作る。

## 計算と同期

共通関数は各境界を `round(sum(durations[:i]) * fps)` で出し、その差を区間のコマ数にする。合計は `round(sum(durations) * fps)` と一致する。Python の浮動小数点の半コマ境界でも #338 と同じ丸めになるよう、単純な逐次加算ではなく同じ sum を使う。
映像の開始は計画の音声開始から最大半コマの差で、区間数による誤差が蓄積しない。長編のページ分割、効果音、口パク、表情、A/B の記録も同じ境界を使う。

音声は区間の計画秒から通算サンプル数を計算する。従来省いていた20ms以下の余白も埋める。音声が計画尺を超える場合は停止する。日次動画も最低表示時間を含む同じ durations で音声を結合する。存在しない試合を飛ばしてコマ数が欠ける処理も、エラーで停止する形にした。

## 変更しなかった場所と理由

- `scripts/generate_longform.py:971` : フェード時間。区間のコマ数を減らさず、合計尺には影響しない。
- `scripts/generate_morning_short.py:4155`, `scripts/generate_morning_short.py:4588` : 同上。2つの描画ループにあるフェード時間。
- `scripts/generate_video.py:1072` : 同上。
- `scripts/soccer_national_render.py:166` : 音声結合前に各区間を整数コマへ切り上げ、その同じ秒数を描画に使う。切り捨て誤差はない。
- `scripts/soccer_results_render.py:295` : 同上。
- `scripts/soccer_voices_render.py:231` : 同上。
- `scripts/pilot_media_sampler.py:82` : 音声なし・投稿なしの資料比較見本。pilot_media.pyの検査でdurationは1〜15の整数に限定され、端数の切り捨ては発生しない。
- `scripts/pilot_media.py:49` : 上記の整数秒の検査。
- `scripts/pilot_render.py:310` : 単一の通算時間軸を描く試作。区間ごとの切り捨てではない。
- `scripts/preview_game_ui_short.py:46` : 整数秒の単一の見本。
- `scripts/motion.py:269` : 演出の長さ。合計コマ数を決める処理ではない。
- `scripts/video_common.py:298` : まばたきの局所的な演出時間。近くのint(t*fps)もその位置参照。
- `scripts/lipsync.py:106` : 口の配列の位置参照。query_framesのint(searchsorted)も音素選択で、区間のコマ割当ではない。

## 自分で確認した試験

- 新規 `python scripts/test_frame_total.py`：6試験成功。描画・ffmpeg・APIは起動せず、実際の描画ループの割当部分だけを抽出して検査。
- 対象9生成スクリプトの10ループについて、20区間×1.03秒と端数混在60区間を検査。30fpsでは20区間の合計618コマで計画と一致。共通関数は24・30・60・29.97fps、200区間、半コマ境界、ゼロコマ区間、空配列も検査。
- 長編の時刻表・効果音、口パク・表情・A/B記録の開始と終了を照合。合成WAV（1区間1.02秒、計画1.0301秒×20区間、1000Hz）で20,602サンプル、各開始差は最大半サンプル。
- 既存4試験成功：A/Bの時刻と公開記録、口パクの保持・無音、音声サイドカーと末尾、長編時刻表。単独実行の新規試験は約2秒、既存4試験は0.42秒。
- 最初の新規試験では、BOMの読取りと試験でのfps指定漏れを修正。半コマの丸め差も検出し、共通関数を上記の式へそろえてから全6試験が通過した。
- run_checks：1回実行、2026-11-07 22:58開始、1692.0秒。静的検査は全項目成功、259本の試験中6本で問題が出た。保護指紋2本、Windowsの既定文字コード2本、一時フォルダーの権限1本、SDK試験のHTTP実装不一致1本。意図した指紋更新と試験の修正後、失敗した5本を通常のPython起動で再実行してすべて成功（SDK40件、札2件、文字コード関係2本、斜めカット47件）。サッカーv5は初回の画素比較92枚が成功しており、失敗していた保護指紋の1試験だけ再実行して成功。全体の2回目は実行していないため、修正後の全体終了コード0は未確認。初回ログ・所要時間JSON・個別再試験ログは作業場所の build_reports/frame_total_20261108/ に保存。
- 差分の空白エラーと日本語の文字化け：ステージしたコード・新規試験・報告書を find_mojibake.py と git diff --cached --check で最終確認。

- 追加確認（2026-11-07）：長編の旧表示・新表示の paginate を実際に呼び、20区間×1.03秒を各60ページへ分割。いずれも24fpsで494コマとなり、計画と一致。描画は実行していない。

完成動画の描画・再生確認、GitHub CI、公開結果は確認対象外。新規試験以外の既存試験はrun_checksの通常構成で実行する。

## 追記：11/07 23:50の本番停止対策（この節が現行）

### 修正した箇所

- `scripts/video_common.py:422`, `scripts/video_common.py:461`, `scripts/video_common.py:484`
- `scripts/generate_video.py:939`, `scripts/generate_video.py:1038`, `scripts/generate_video.py:1083`
- `scripts/test_frame_total.py:166`, `scripts/test_frame_total.py:173`, `scripts/test_frame_total.py:185`, `scripts/test_frame_total.py:192`, `scripts/test_frame_total.py:205`

- 音声が区間計画を超えても0.02秒以内なら余白0で続ける。実際に書いた累積サンプル数と計画の累積を比較し、次の余白で吸収する。吸収しきれなければ末尾のWAVの写しを短くし、全体を round(sum(durations) * sample_rate) にそろえる。元の音声ファイルは変更しない。調整時は警告を1行出す。0.02秒を超える区間超過だけ停止する。
- 無い試合の区間は、前のフレーム（先頭なら背景）を予定コマ数ぶん書く。区間ごとに警告を1行出し、frame_noにも全コマを加える。後続の区間を進める。
- `scripts/fixtures/mlb-badge/protected-source.json:5`, `scripts/fixtures/soccer-slots/v5-protected-source.json:6`, `scripts/fixtures/soccer-slots/v5-protected-source.json:7` : 意図した生成器の変更に対応する保護指紋3項目だけを既存の更新器で更新した。画素の基点は更新していない。

### 「止まる形」の洗い直し

| 箇所 | 確認と対応 |
|---|---|
| 前回追加した音声の n < 0 での停止 | 0.02秒以内は上記の警告・補正へ。超過が0.02秒を超える場合だけ、依頼どおり停止を残す。 |
| 前回追加した範囲外 game_index での停止 | 警告・フレーム保持へ変更。負数、上限以上、None、文字列も停止しない。 |
| 日次動画で共通音声結合を呼ぶようにしたことによる、話者確認の新しい停止経路 | 日次だけ strict_audio=False とし、話者情報が不一致でも警告で続ける。音声や話者の設定は変更しない。 |
| 同じ導入で増えた、口パク情報の不備による停止経路 | 日次だけ警告で続け、途中までの口パク情報を捨てる。壊れた付属JSON・指紋不一致などの ValueError/KeyError/OSError を対象にする。 |
| その他の生成器で従来からあった話者・口パクの確認、公開前の尺の照合、ffmpeg失敗 | 従来の停止条件を維持。 |
| それ以外の前回追加の停止条件 | e4e30624の追加行と呼出経路を照合し、上記以外に明示的に停止へ変更した処理はなし。試験のassertは本番の停止条件とは別。 |

### 本題と関係がないため外した試験変更

- scripts/test_dialogue_batch.py：SDK内部のHTTP実装を使う変更を撤回。
- scripts/test_sanity_all_materials.py：手元の文字コードに対応するUTF-8指定を撤回。
- scripts/test_sanity_grounding.py：同上（4か所）。
- scripts/test_slant_by_episode.py：手元の権限に対応する一時保存先指定を撤回。

4本とも3084737eの内容へ戻し、バイト単位で一致を確認した。別PRは作らず、この枝の基点との差分から除いた。GitHub接続先で、基点に含まれる[#343](https://github.com/issakatou2-bit/sports-notify-mvp/pull/343)のhead c4ad158f2492a497a6c23d0556bb96411469f1c4の[検査1193](https://github.com/issakatou2-bit/sports-notify-mvp/actions/runs/42375495290)がcompleted/successであることを自分で確認した。今回の枝はpushしておらず、今回の変更のCI結果ではない。

### 自分で確認した試験

- scripts/test_frame_total.py：11試験成功。既存6件に加え、端数のある音声長そのままの20区間、半サンプル程度の超過の持越し・末尾調整、0.02秒の境界と超過、日次の警告と既存呼出しの停止の区別、無い試合のコマ保持・警告1行を検査した。描画もffmpegも起動していない。
- 44,100Hz・45,427サンプルの音声を20区間並べ、合計908,540サンプルで計画と一致。次の余白で吸収できる場合と、末尾の写しを切る場合を検査し、元音声が不変であることも確認した。
- 追加の既存5試験成功：A/B時刻と公開記録、口パクの保持と無音、口パクの付属情報と末尾、長編時刻表、MLB札の保護指紋。
- run_checks：1回実行（2026-11-07 23:52開始、翌00:19まで）、1584.0秒、終了コード1。全259本のうち255本成功、失敗は撤回した4本だけ。test_dialogue_batchは手元SDKとhttpx2の型不一致、test_sanity_all_materials・test_sanity_groundingは既定cp932でUTF-8のJSONを読むため、test_slant_by_episodeは手元の既定pytest一時フォルダーの権限によるもの。前回と同じ手元環境の理由なので、この枝へ再び修正を入れていない。追加11試験は全体検査内でも成功。静的検査は全項目成功（重大な未定義名0、起動確認の欠落0）。全体を再実行していない。今回のログと所要時間JSONは build_reports/frame_total_20261108/run_checks_followup.log と run_checks_followup_timings.json に保存。
- 日本語の文字化け・差分の空白検査：find_mojibake.pyによる追加差分の文字化け検査、git diff --cached --check、報告書のUTF-8読取りを最終確認。

作業場所・枝は同じ。HANDOFF・公開設定・声の切替・鍵は変更していない。push・公開・新規CIの起動はしていない。
