# 日本代表の今季数字（2026-11-10）

作業場所：`build/wt-national-numbers`、枝 `claude/national-numbers`。起点はこのPCに保存された `origin/main` の `16910a71`。短編を `13afa1f4` にcommitした後、長編と共通の検査を次のcommitにまとめた。push・公開・実績データの更新なし。

## 変えた所

短編は、その日の選手の今季得点、次に出場数から冒頭の1人を選ぶ。数字がない日は従来の冒頭。札にリーグ戦の出場数・得点を加え、GKは出場数だけにした。字サイズ、色、点と札の動き、締め2秒、BGMは引き継ぎ、数字の行の分だけ札を縦に広げた。「名簿順・先発配置ではない」の注意は説明欄へ移した。

取得は既存の `soccer_results.fetch_json` を共用。ESPNのリーグ別チーム一覧→所属名簿→選手の公式statistics参照を辿る。本人・所属・リーグ・季が一致し、整数として読める出場数・得点だけを使う。未取得はゼロで補わない。今季の数字が確認できた場合、リーグ札もその取得資料を優先する。

取得時刻・出典URL・選手ID・所属ID・リーグ・シーズン・元応答を `numbers.json` と材料内に保存する。元応答との不一致、出典材料の脱落、別人・別季・重複・未来/古い取得、アシストしかない応答は検査で止めるか数字を省く。公式名簿の読みを番組内だけで使い、欧州追跡の42人には追加していない。

長編は既存の週まとめの札・字幕・v3描画・BGMを再利用。全28人のポジション別の表→数値を確認できた注目の最大3人→保存資料にある相手との対戦→試合日時の順。MF/FWはJFAの一括区分のまま。異なるリーグの数字を実力順位とは言わない。

| 相手 | 材料の試合日時（JST） | 材料に記録する公開予定 | 保存資料の対戦 | 見本の台詞/札 |
| --- | --- | --- | --- | --- |
| ブラジル | 11/14 19:15 | 11/13 20:00 | 2026/6/30 1対2、2025/10/14 3対2 | 53行/17枚 |
| パラグアイ | 11/17 22:10 | 11/16 20:00 | 2025/10/10 2対2 | 52行/17枚 |

相手・日時・会場は `data/soccer_national_fixtures.json`、過去の対戦は `data/soccer_national_results.json` から取る。日時の根拠は依頼文に記された**ClaudeのJFA確認**。自分での実通信確認ではない。

新しい `soccer_national_long.yml` は手動のsample_only/render_onlyだけ。公開経路、予約実行、鍵の参照、実績の書き込みは作っていない。上の20:00は予定の記録で、予約済みではない。動画は全行一致するWAVが必要で、WAV実測＋既存の区間余白で180〜240秒を外れる場合は原稿見直しとして停止する。速度や無音追加で合わせない。

招集12:00、前日予告19:30、結果22:00（遅い試合は翌朝8:00）は変更なし。`choose()` の構文木が起点と同じことも自分で確認した。

## 自分で確認したこと

| 試験ファイル | 件数 |
| --- | ---: |
| test_soccer_national.py | 58 |
| test_soccer_national_squad.py | 17 |
| test_national_pitch.py | 9 |
| test_soccer_national_numbers.py | 13 |
| test_soccer_national_long.py | 11 |
| test_name_reading_guard.py | 22 |
| test_soccer_official_names.py | 3 |
| test_short_common.py | 9 |
| test_soccer_weekly_long.py | 21 |
| 合計（重複実行を除く） | 163 |

構文、pyflakesの致命項目、YAML、試験入口の検査は成功。既存の軽微な警告は残る。短編の静止画・両長編の全34札を描画し、札の並べ、題、全28人の原稿、試合日時・対戦結果を目で確認した。短編の無音動画は最後まで復号した。根拠の脱落を止める修正後も数字の13件を再実行した。

一括入口は `python scripts/verify_national_numbers.py --long`。重い実行はheavy_waitを通し、入口でも7:20〜8:40・19:15〜22:10に開始しない。検査ログは見本フォルダ内。

## 見本と未確認

- 要望の無音動画：共有ルートの `build/codex/tmp/national_numbers_sample.mp4`。
- 札・全台詞・材料・検査結果：`build_reports/national_numbers_20261110/`（共有ルートと作業場所の両方）。短編は `short_cards.png`、長編は `brazil/review.png`・`paraguay/review.png`、全ポジションの並べは各 `all_positions.png`、原稿は各 `dialogue.json`。
- **見本の今季数値はすべて架空の検証値**。本人・所属IDは保存済みESPN材料から写し、成績は試験用に作った。画面に明示し、sample_only以外の材料検査・短編の公開検査では拒否する。
- fixtureの検証値は鈴木彩艶8試合、鎌田大地13試合2得点、坂元達裕11試合7得点。実際の成績として使わない。
- 実ESPNの参照形・収録有無・実際の今季成績は未確認。実取得時の欠測者は `numbers.json` の `missing` に残る。ライブ確認は依頼どおりClaude側。
- 実音声は未確認。ローカルCPU版VOICEVOXの起動時、作業場外のAppDataに一時辞書を書く処理が権限で拒否された。自分で起動したプロセスは残していない。実WAVでの読み・3〜4分の尺、CIの見本はClaude側で確認が必要。ローカル再確認用に `verify_national_voice.py --url http://127.0.0.1:50122` を用意した。

fixtureで今季数値を取得できない25人（**実データでの失敗一覧ではない**）：

- GK：早川友基、小久保玲央ブライアン。
- DF：板倉滉、渡辺剛、町田浩樹、伊藤洋輝、瀬古歩夢、中野就斗、菅原由勢、鈴木淳之介。
- MF/FW：伊東純也、南野拓実、相馬勇紀、小川航基、前田大然、堂安律、田中碧、中村敬斗、佐野海舟、久保建英、鈴木唯人、松木玖生、佐野航大、福田師王、後藤啓介。

## 変更ファイル

- 短編・共通：`scripts/soccer_national_numbers.py`、`soccer_national.py`、`soccer_national_pitch.py`、`soccer_national_publish.py`、`name_reading_guard.py`。
- 長編：`scripts/soccer_national_long.py`、`render_soccer_national_long.py`、`data/soccer_national_fixtures.json`、`.github/workflows/soccer_national_long.yml`。
- 検証：`scripts/test_soccer_national_numbers.py`、`test_soccer_national_long.py`、`verify_national_numbers.py`、`verify_national_long.py`、`verify_national_voice.py`、`scripts/fixtures/soccer_national_numbers.json`。
- 本報告。共有HANDOFFは担当の1行だけを完了へ更新し、commitに含めない。

Claudeの見本実行：短編は依頼の `soccer_national.yml --ref claude/national-numbers -f sample_only=true`。長編は `soccer_national_long.yml --ref claude/national-numbers -f opponent=brazil -f sample_only=true -f render_only=true`（パラグアイ版は `opponent=paraguay`）。いずれもここからは実行していない。
