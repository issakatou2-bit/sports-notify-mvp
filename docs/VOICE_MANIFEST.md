# 声と表示時刻の保存

2026-10-29。対象版の音声・字幕・カットの出所を保存する追加記録。描画・音声設定・題・公開処理は変更しない。#267 の `docs/GEMINI_AV_CHECK.md` を形式だけ参照した。検査コードは取り込んでいない。

## 保存先

- 共通合成先の `voice_manifest.json`。既存の `manifest.json` は従来どおり描画に使う。
- 動画の隣の `<動画の拡張子を除いた名前>/voice_manifest.json` と `render_timeline.json`。同じ出力先で複数本作っても各動画の記録を保持する。
- 出力先直下の `render_timeline.json` は最後に書き出した動画の記録。動画別フォルダの方が正本。
- 関係する19 workflowの各制作jobに、失敗時も `build/**/voice_manifest.json` と `build/**/render_timeline.json` を14日残すartifactを追加。`run_checks.check_commit_list` が両方の保存漏れも検査する。音声ファイル自体や立ち絵を新たにartifactへ追加する処理ではない。

## 音声

`version: 1`、`segments` 配列。行番号 `line_id` は元のセグメントの `index+1`。各行に `speaker_key`、`voice_engine` (`voicevox` / `voisona`)、実際のVOICEVOX `speaker`（VoiSonaや無音はnull）、`source_speaker`（元の進行役番号）、`actual_voice_key`、相対 `file`、実WAVの `duration`、実ファイル全体の `sha256`、`text`、`status` を持つ。指紋は音声ファイルのもの。結合後の音声の指紋とは区別する。

予定は `planned_host` / `planned_engine` と、保存済み `host_assignment` / `host_delivery` / `voice_resolution` を残す。雨衣からめたんへ作り直した場合、`previous_attempt` の雨衣予定も保持し、実声はVOICEVOXとする。呼出時の環境から過去ファイルの声を推定しない。声が無い行は `unavailable`、旧素材で生成元を証明できない行は `unknown`、停止した雨衣注文は `status: held` と空の配列。古い成功記録を残さない。

`synth_one` の単独利用、`solo_host.synthesize` の直接生成、キュー/在庫の受領先 `ui_voice_stock.install` に記録を置いた。`ui_voice_queue.configure` の受領は同じ `install` または共通合成を通る。共通合成の終了時に全行と予定をまとめ直す。

単独関数が更新中の一覧は `status: partial`、共通合成の全行を確定した一覧は `complete`。途中で止まった生成を以前の完了記録と取り違えない。

`seg_003_short.wav` への短縮でも元の4行目を保ち、予定も引き継ぐ。サッカー結果の `fit_段階_指紋.wav` のように名前に行番号を持たない再生成は、呼出元の保存済み `index` を明示して記録し直す。字幕時刻の追加は他の描画器と同じく別の対応段階。

## 表示

`version: 1`、`lines` / `cuts` の `start` / `end` は動画先頭からの秒、終了は排他的。実際のpipeへの書込みに成功したフレームを数え、完成mp4の `nb_frames` とfpsで末尾を確定する。台本順・音声長から表示時間を逆算しない。カットの開始は次画面を描いて出力した最初のコマ。既存の切替が重なる旨は `intentional` に記す。

`lines` は元の行の対応と実際に出力した区間。合唱は `source_line_ids` に両方の元行を残す。長編のページ分割でも同じ元行へ戻せる。`subtitles` に描画された字幕ページごとの実 `start_frame` / `end_frame` / `subtitle` を保存し、字幕のない区間も空文字で残す。`lines.subtitle_start` / `subtitle_end` はその行の字幕表示範囲（字幕なしはnull）。フェード中の前字幕は別の重ね区間にも記録する。文字の途中まで現れる演出では、その字幕ページの全文と最初の可視コマを記録する方式であり、文字ごとのOCR時刻ではない。

`line_id` / `cut_id` は#267に合わせて重複しない正の整数。通常は元行番号、合唱では先頭の元行番号を代表とし、元行の全対応は `source_line_ids` に保持する。同じ元行が別区間に再登場するときだけ新しい検査番号を割り当てる。

`source_lines` は外された行も含む一覧、`rendered: false` は実際に出力されなかった行。字幕が元の文と違っていても実際に描いた文を残し、既存の描画の誤りをこの追加処理で直さない。`video_sha256` / `voice_manifest_sha256` で完成物と結び付ける。

## 対応状況

| 入口 | 実フレーム記録 |
|---|---|
| `generate_morning_short.py` | 通常の全mode、旧描画、daily_v3、数字ドーン、`build_player_video` |
| `soccer_slots_v4.py` | 朝のsoccer_race/weekから委譲されるv4/v5/v6を含む。共通の`render_video`で観測 |
| `generate_longform.py` | 従来版・v3、分割字幕、冒頭/締めの合唱 |
| `generate_asset_video.py` | 従来版・v2/v3/v4、ゲームUI、内部ページ切替 |
| `generate_video.py`、`generate_weekly.py` | 未接続。共通合成の声の記録のみ |
| `generate_ps_preview.py`、`ps_program.py` | 未接続。共通合成の声の記録のみ |
| `short_saved_render.py`、`generate_verdict_short.py` | 未接続。共通合成を使用した範囲の声のみ |
| `soccer_results_render.py`、`soccer_voices_render.py`、`player_story_render.py` | 未接続。共通合成/単独合成を使用した範囲の声のみ |
| 配信・リハーサル、個別試作 | 対象外。混合動画から声の出所を再推定しない |

## Gemini入口との関係

動画別の `voice_manifest.json` は #267 が照合する `segments[].file` / `speaker` / `voice_engine` に合わせた相対パス。`render_timeline.json` は `version: 1` の `lines` / `cuts` を持つ。新しい記録だけでGeminiへ送信できるとはしない。別途、#267の出所JSON、全素材の指紋・出所・全画面の確認が必要。雨衣予定が残る回は代役になっていても#267で拒否される。

素材の分類は [ASSET_PROVENANCE.md](ASSET_PROVENANCE.md)。送信可否はClaudeと本人が判断する。自動送信や許可フラグの設定は追加しない。

設計時に [OpenTimelineIO の時刻範囲](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/docs/tutorials/time-ranges.md) と比較した。表示先の時間軸と元素材を分ける考え方を参照し、既存の単純なフレーム書出しには追加依存を入れず、観測したフレーム番号と素材参照をJSONで保存する。
