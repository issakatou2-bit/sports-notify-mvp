# 日本代表の今季数字（2026-11-10）

作業枝：`claude/national-numbers`。起点は保存済み `origin/main` の `16910a71`。push・公開は行わない。

## 1. 招集の短編

- JFA名簿の本人・所属とESPNのリーグ別チーム名簿・選手名簿を照合し、公式の今季集計の参照だけを読む。出場・得点が欠測なら埋めない。GKは出場数のみ。
- 元応答、取得時刻、季、リーグ、選手ID、所属ID、出典URLを材料に保存。数字と元応答の不一致・別人・別季・古い取得を検査する。
- その日の選手で得点、次に出場数が目立つ選手を冒頭へ。未取得なら従来の冒頭。注意書きは説明欄に移した。字サイズ・点と札の動き・締め・BGM・公開時刻は既存のまま。
- 関連125件成功。構文・pyflakes致命項目・YAML・試験入口の静的検査成功。カードの静止画を自分で確認。無音動画を最後まで復号した。
- 共有見本：`build/codex/tmp/national_numbers_sample.mp4`。札の並べ：`build/wt-national-numbers/build_reports/national_numbers_20261110/short_cards.png`。
- **見本の今季数値は架空の試験値**。画面に明示し、sample_only以外では材料検査を通さず、公開検査も拒否する。実際の成績ではない。
- fixtureで確認できるのは鈴木彩艶・鎌田大地・坂元達裕の3人。残り25人はfixtureに成績応答がないため未取得。実通信で取れない選手の一覧ではない。
- 実ESPNの応答形、実際の全員の今季成績、実音声・CIは未確認。Claudeによる実取得と見本確認が必要。参照が想定と違う場合も数値を推測せず省略する。

変更：`scripts/soccer_national_numbers.py`、`soccer_national.py`、`soccer_national_pitch.py`、`soccer_national_publish.py`、`test_soccer_national_numbers.py`、`verify_national_numbers.py`、`scripts/fixtures/soccer_national_numbers.json`。

## 2. 試合前の長編

実装・検証を続ける。公開経路は追加しない。
