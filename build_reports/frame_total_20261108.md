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
