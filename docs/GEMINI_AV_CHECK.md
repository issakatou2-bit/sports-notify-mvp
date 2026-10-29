# 動画の全行・全画面の検査

`scripts/gemini_av_check.py` は許可済みの自作動画を受け取り、ローカルASR → Gemini → 台本との照合の順で検査する。公開・修正・非公開化・YouTubeへの書込みは行わない。実APIを呼ぶのはこのコマンドを明示実行した時だけ。CIの試験では偽CLIを使用する。

## 入力と出所の確認

動画と同じ版の時刻つき台本、全素材の出所記録が必要。時刻は完成mp4の先頭からの秒で、音声の長さだけで推測しない。字幕の分割、冒頭・締めの合唱、無声の札、画面切替、意図した重ねも含める。`lines` と `cuts` の両方が動画の先頭から末尾まで連続していなければ送信しない。行番号は生成元の行に対応させる。

台本の例（無声区間は `text` が空文字）：

```json
{
  "version": 1,
  "lines": [
    {"line_id": 1, "start": 0, "end": 2.5, "text": "今日は晴れです。", "subtitle": "今日は晴れです。", "expected_end_delta_seconds": -0.7, "intentional": "文末の余白0.7秒"}
  ],
  "cuts": [
    {"cut_id": 1, "start": 0, "end": 2.5, "screen": "自作の文字と図だけの画面", "intentional": "切替なし"}
  ]
}
```

出所の例。指紋は実ファイルのSHA256。`path` は出所JSONからの相対パスまたは絶対パス。未確認の項目を埋めて通さない。

```json
{
  "version": 1,
  "video_sha256": "完成mp4の指紋",
  "script_sha256": "時刻つき台本JSONの指紋",
  "review": {
    "evidence": "生成コードの版、全画面の確認記録、素材の出所を具体的に記す",
    "official_art": false,
    "personal_information": false,
    "secrets": false,
    "poster_names": false,
    "unreleased_private_material": false
  },
  "assets": [
    {"kind": "voicevox", "engine": "voicevox", "speaker": 2, "self_created": true, "path": "audio/seg_000.wav", "sha256": "音声の指紋", "evidence": "synthesize_narrationの実行記録とspeaker=2"},
    {"kind": "rendered_screen", "self_created": true, "path": "screens/cut_001.png", "sha256": "画面の指紋", "evidence": "描画コードと全画面の目視記録"}
  ],
  "audio_manifests": [{"path": "audio/manifest.json", "sha256": "保存済み音声manifestの指紋"}]
}
```

素材の種類は `voicevox`（話者2＝四国めたん、3＝ずんだもん）、`generated_bgm`、`generated_sfx`、`rendered_screen` のみ。声の全ファイルを音声manifestと照合する。公式立ち絵、外部から取得したBGM・効果音、投稿者名、私物、鍵、未確認素材は不可。BGMや絵が安全かを機械だけで証明できないので、出所と全画面の事前確認を省略しない。出所JSON自体はGeminiに送らない。

VoiSonaの印がある台本・素材・音声manifest・動画の受領記録は、音声抽出やASRより前に拒否する。`speaker=2` だけではめたんの声と判断できない。`voice_host=ui`、`voice_engine=voisona`、`voice_name=ui_ja_JP`、`voice_resolution.host=ui`、保存された `planned_host=ui`、雨衣等の印も拒否する。予定が雨衣で実際は代役の回も、今回の入口では保守的に除外する。呼出時の環境変数を変えても保存音声の出所は変わらない。

## 実行

`--out` は毎回新しい空のフォルダを指定する。前回の結果を上書きして混同しないため、使用済みの出力先は拒否する。声の素材はWAV/FLAC、画面の素材はPNG/JPEG/WebPに限る。閲覧禁止の置き場や秘密用ディレクトリは、ファイルを開く前に拒否する。

Python標準ライブラリとffmpeg/ffprobeが必要。ASRだけ既存のfaster-whisper環境を別Pythonとして指定できる。モデルは取得済みCTranslate2形式のフォルダを明示し、自動取得をしない。現在はCPU/int8・4スレッドで実行しGPUを使わない。将来GPU対応を足す場合は `heavy_wait.py --gpu` を必須にする。

```powershell
$env:PYTHONUTF8='1'
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 30 -- python scripts/gemini_av_check.py --video build/episode/video.mp4 --script build/episode/timeline.json --provenance build/episode/provenance.json --out build/episode/av-check --asr-python C:/Users/issak/Tools/accent-tools/venv/Scripts/python.exe --asr-model C:/path/to/existing/whisper-model
```

キーを読取・表示・環境変数へコピーする処理はない。登録済みのWindows鍵置き場をCLI自身が使う。請求先設定、モデル生成API、新規ダウンロードはしない。

動画は1本ずつ渡す。14,000,000 bytesを超えたら `files upload --wait` の `files/<id>` を使う。503だけ30秒・60秒空けて最大2回再試行する。認証・料金・回数枠・その他のエラーは再試行せず未検査で止まる。失敗時も `api-events.json` に時刻・操作・試行回数・終了番号を残す。CLIの生エラーは秘密が混ざる可能性があるため保存・表示しない。アップロードしたファイルの保管はCLI仕様上48時間。

## 結果の読み方

- `asr-transcript.json`：行の開始/終了で音声を分け、正解台詞をプロンプトに入れない独立した文字起こしと単語時刻。短い同文の繰返しが1つにまとめられる誤検出を減らす。
- `asr-comparison.json`：行ごとの文字差（編集距離/CER）、聞こえた文字列、先頭・末尾単語の秒。表記差も候補に残し、誤読と決めない。
- `gemini-raw.txt` / `gemini-response.json`：受け取った答えとJSON。全行に7観点、聞こえた台詞、見えた字幕、秒の差、指摘・理由を要求する。
- `result.json`：台本・動画の指紋、期間、行/カットの回答数、要確認だけの一覧。重複・未知の番号はエラー、欠番や不明は要確認。全部okでも実際の文と台本に差があれば拾う。

終了番号は0＝指摘なし、2＝要確認、1＝拒否・検査失敗。ASR未実施を0にしない。0も公開許可や人の耳の代わりにはしない。声開始－字幕開始、声終了－字幕終了を秒で記す。意図した余白は台本に `expected_start_delta_seconds` / `expected_end_delta_seconds` で指定でき、予定との差が0.3秒超なら要確認にする（省略時の予定は0秒）。文末の0.7秒の余白まで毎回誤りとしないため、実際の描画と音声の時間から指定する。無声行に声の開始/終了秒を捏造させない。

全フレームの復号でファイル破損を検査するが、文字の内容を全フレームOCRする処理ではない。Geminiは内部で映像を時間方向にサンプリングするため、全時間を渡し全行・全カットの答えを求めても全フレームの視認は保証できない。短い一瞬の字崩れ・息を拾う性能は実測が必要。長編で回答が途切れても、欠番を合格にしない。非常に長い回は同じ台本を安全に分割する拡張が次の課題。

使った回ごとに共有 `Geminiの耳と目.md` の記録表へ日時・対象・結果・気づきを1行残す。共有パスが書込不可なら追記予定行とその制約を報告に残し、更新済みと書かない。

## VoiSonaが入り得る経路（origin/main c42da5dc、2026-10-28確認）

| 動画・経路 | 根拠コード | 扱い |
|---|---|---|
| 朝、朝の声/報道、日次、PS朝/結果、サッカー日次/順位/週次/結果/声/速報、日本人の反応、選手の話、Reddit反応 | `host_split.py:KINDS`、`prepare`、`synthesize_narration.py:main` | 半々割付/ソロの保存音声次第。実声manifestを確認するまで対象外 |
| 資産ショート（season系、WS等） | `host_split.asset_kind`、`generate_asset_video.py:main`、`solo_host.for_segments` | 同上 |
| PS番組・PS予告 | `ps_program.py`、`generate_ps_preview.py` の `ui_voice_queue.configure` と共通音声生成 | 同上 |
| 16:9長編 | `generate_longform.py:main` の保存manifest読込・`ui_voice_queue.configure` | 通常の2人掛合いはVOICEVOXだが、保存素材から取り得るため種類だけで許可しない |
| 週次・訂正・デザイン試作等、共通音声生成を使う入口 | `.github/workflows/*.yml` の `synthesize_narration.py` 呼出、`solo_host.for_segments` | 全行speaker=2のソロ設定や保存音声に注意。manifestが無ければ対象外 |
| サッカー結果の差替え・章の音声 | `soccer_result_story.py:resynthesize`付近、`soccer_slots_v4.py` | `voice_host=ui`/host設定で `solo_host.synthesize`。対象外 |
| 手元の生配信・リハーサル | `japan-reacts-numbers3-20261016/live/voice.py:Voice` の既定use_voisona=True、ui行の `synthesize_ui` とused='voisona'、`collespo_live.py` の引数接続を自分で確認 | 混合済みmp4/音声は対象外。安全な描画静止画だけなら別の確認手順が必要 |

共通の実体は `solo_host.synthesize`（VoiSona REST）と `ui_voice_worker.py` → `voisona_talk`、受領側は `ui_voice_queue.py` / `ui_voice_stock.py`。speakerキーは2のままでも実声が雨衣になる。静止画に限る場合でも公式立ち絵・投稿者名が含まれれば送れない。このスクリプトは混合動画からの自動音声分離や禁止素材の自動マスクは行わない。
