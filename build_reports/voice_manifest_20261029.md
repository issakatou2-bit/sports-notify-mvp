# 声の出所と実フレーム時刻の保存（2026-10-29）

担当: Codex。JSONの追加・保存・検査を実施。push・公開・本番変数変更・Gemini送信なし。

枝は `hiro/voice-manifest-20261029`、作業先は `build/codex/tmp/wt-voicemanifest`、起点は `origin/main c42da5dc1c9bd31795605333b99e1809b2c2a244`。本体`.git`の書込制限のため、既存objectsを参照する `build/codex/tmp/voicemanifest-repository.git` でworktree管理。cloneなし。レビューは作業先で `git show HEAD`。#267からは入力形式のみ参照し、検査コードはコピーしていない。

## 変更

- `voice_manifest.py` と共通合成・solo_host・キュー/在庫の受領先に、行番号、話者キー、実engine、実VOICEVOX番号、相対ファイル名、実WAV長、SHA256を記録。予定と実声を区別し、雨衣からの作り直し前の予定も保存する。無音・未知・停止・生成途中を明示する。
- `seg_003_short.wav` へ短縮した場合も元の行番号と予定を保持。`soccer_result_story.py` の任意名の短縮ファイルは保存済みindexと出所を明示して記録し直す。追加8試験、関連サッカー5＋7試験を別プロセスで確認した。
- `generate_morning_short.py` の旧版・daily_v3・数字ドーン・今日の1人、`generate_longform.py` の従来/v3、`generate_asset_video.py` の各版で実writeフレームを記録。朝のサッカー順位/週次から委譲される `soccer_slots_v4.py` も接続。字幕ページ・合唱・切替・キャッシュ・内部ページを含む。
- 完成mp4のfps/フレーム数で末尾を確定。台本順や音声長から字幕時刻を逆算しない。`lines` / `cuts` は#267に合わせたversion=1・一意な正の整数。合唱の全元行は `source_line_ids`、外された行も `source_lines` に保存。字幕なしは空文字/null。
- 19 workflowで2JSONを失敗時も14日artifact保存。`media_records_check.py` を `run_checks.check_commit_list` に接続し、jobごとの保存漏れを検出。
- 音声先の `voice_manifest.json` と、動画別の `<動画名>/voice_manifest.json`・`render_timeline.json` を保存。共用の出力先でも各動画の記録を保持し、音声参照を相対パスへ直す。出力先直下のtimelineは最後の動画の写し。

## 自分で確認

- 10/28 23:40 JST、関連試験41件成功・1件既存skip・70 subtests成功。実WAV、指紋・長さ、予定/実声、無音・停止、字幕分割・合唱・キャッシュ・丸め、実mp4、artifact欠落を確認。
- 10/28 23:51〜23:52 JST、起点と変更後を別プロセスで比較。**242描画サンプルのRGB全画素、4本の書出しループの400フレーム、2話者の合成要求とWAVが全て一致**（248比較、差分0）。描画器の最終修正後、10/29 00:19〜00:21 JSTの再比較も同じ248比較・差分0。旧画面・日次v3/v4・数字ドーン・資産v3/v4・長編従来/v3・サッカーv6を含む。圧縮前の全画素比較であり、全本番動画の遡及比較ではない。
- 10/28 23:57 JST、単音6本で実長編v3を末尾まで書出し。152フレーム/24fps、4区間・4カット・8字幕区間。6WAVの相対参照・指紋、合唱を含む元6行、2JSONと動画の結び付きを確認。単音のengineはunknownとし、実声の証明には使わない。出力約0.9MB。
- 全run_checks初回は10/28 23:52〜10/29 00:14 JST。構文586成功、軽微53、終了1。キャッシュ画像の参照2指摘、サッカー既存呼出しの試験1件、偽バイトの音声試験1件、既存Windows標準入力ハンドルの試験1件を検出。キャッシュ専用記録・既存3引数呼出しを維持し、試験音声は共通 `voice_test_fixture.py` で実PCMへ再生成。Windows入力はローカル検査用driverでNULを明示し、本番コードを変更しない。
- **最終版の全run_checksは10/29 00:46:04〜01:07:44 JST、終了0。構文587ファイル、全215試験ファイル成功、重大0・既存軽微53。** 00:21〜00:43の再検査も終了0。その途中に短縮音声の記録を補正したため、最終版を固定して全体を再実行した。保護指紋・差分・素材36フォルダの列挙も照合した。

重い検査は全て `heavy_wait.py --minutes 30` 内、`PYTHONUTF8=1`、PythonのTEMP/TMPとpytestの一時置場はworktree内。Windowsの子プロセスで出力が消える環境に対応し、実Pythonとログdriverを明示。空の初期ログを合格の根拠にしていない。新規起動のエラー1909は00:00ごろと01:00ごろに発生、開始済みの検査は継続し、それぞれ00:15と01:16に復旧を確認。認証・アカウント設定を変更していない。

ログ（作業先内）: `build/media-tests.log`、`build/pixel-after-fixes.log`、`build/media-pixels-after-fixes/{result,before,after}.json`、`build/e2e-render.log`、`build/media-e2e/summary.json`、`build/manifest-frozen-unit.log`、`build/soccer-length-final.log`、`build/soccer-polish-final.log`、`build/run-checks-frozen.log` と同名status.json。保護指紋は指定の `update_protected_hashes.py --write` で2件更新。

## 素材と残確認

- [出所一覧](../docs/ASSET_PROVENANCE.md): 対象版14フォルダ、共有だけ22フォルダ（不明）、計36を区別。README・履歴・共有docsに基づく分類であり、**全項目のGemini送信可否は未判断**。禁止フォルダや私的な素材置場を開いていない。
- [形式と対応一覧](../docs/VOICE_MANIFEST.md): 他の描画器は未接続として列挙。#267には別途、素材の実ファイル・出所JSON・全画面の確認が必要。雨衣予定や実VoiSonaの記録を含む回は保守的に除外される。
- 実Gemini、実VOICEVOX/VoiSonaの新規生成、人の聴感、CI、本番公開は未確認。描画・合成・音量・話速・題・公開の設定は変更していない。
- C空きは開始37.48GiB、作業中の観測最小28.85GiB（00:48）、終了前38.18GiB（01:16）。単独10GB超の書出しなし。7:20より前に終了。
- 共有READMEは書込範囲外で未更新。追加候補: `声と実フレームの記録 | D/pwa-mvp/docs/VOICE_MANIFEST.md | 動画 | 実声・元行・指紋と描画フレームを保存し、送信許可と区別する`。

次はClaudeがcommitレビュー→push/PR/CI。素材の送信可否と#267への接続はClaudeと本人が判断する。
