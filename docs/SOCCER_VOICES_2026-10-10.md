# 欧州サッカーの現地ファンの反応（ヒロ㉖）

## 入口と取り込み

- 隔離clone: `build/codex/tmp/soccer-voices-20261010`、`hiro/soccer-voices-20261010`。
- 手元の最新材料: エマの `build/wt-0907`、クラブ色 #125 相当の `1ed2902`（親は main #123 `a2da6d0`）から。新聞の題 #124 `8f883e1` もローカルから取り込み（clone内の `ff38c3b`）。GitHubへの通信・push・PR・公開なし。
- Opus183の41人の別名表を `data/soccer_voice_names.json` へ。正式名・所属は実行時に `JP_PLAYERS_SOCCER` から引き直す。
- `soccer_voices.yml` は手動実行だけ、`publish=false`。書体を入れてから実材料・画面を検査。公開する場合は未来の予約時刻が必要。

## 作る条件

1. `soccer_buzz` の両クラブの名簿と `jp_players` の共通部分だけを対象にする。名字だけが2人に当たる場合は使わず、別選手のフルネームの一部も使わない。
2. 既存 `local_voices.fetch_youtube_comments` で1本ずつ取得。親と返信の関係・高評価・返信件数を保持し、出典をサッカーに直す。足りない試合は次の候補へ。
3. 既存 `local_voices.translate(..., sport='soccer')` を呼ぶ。MLBの既定動作は保持。サッカーは調子なし・未知の調子を採用しない。
4. 訳とは別のAPI呼び出しで、原文/訳/返信の親を照合。非批判・悪口なし・追加なし・人物の役割・名前を全てtrueと判断できた行だけ使う。応答欠落・途中切れ・壊れたJSON・重複ID・booleanでない値は不採用。
5. 原文に無い数字（出現数・小数・単位前の漢数字を含む）、得点/アシスト/警告/退場、別選手をローカルで検査。判定は原文・訳・親のSHA256に結びつけ、後から変わった訳を出さない。
6. 訳した後も名前つきの声が3件以上必要。原文/訳の重複・批判・悪口・個人攻撃を除く。親と返信は一度ずつ同じ画面で、読んでいる札を明るく、読み終えた札を暗くする。
7. 引用本文は切らない。長すぎる返信/引用を外し、3件残らなければ作らない。声の設定は変えない。WAVの実測とmanifest/原稿を照合し、動画のフレーム丸めと完成MP4も40秒以内を検査。

## 描画と見本

- 新設枠はv4専用。共通の背景・字幕・立ち絵・円ワイプ・締めは既存のまま。クラブ色は #125 の表、知らない色は中立。本文中のクラブ名の左へ、材料の同じクラブの札を同じ行/高さで付ける。
- 原文と訳を同じ札に載せる。書体で描けない絵文字は画面のみ除外し、保存原文と訳は保持。球団名の札込みで折り返し、英文の句読点も同じベースラインにそろえる。
- 見本 `scripts/fixtures/soccer-voices/fictional.json` は **架空**。Opus183の手作りの訳に返信・クラブ名の検査例を加えた。`--sample` で読んだものは入力のフラグに関係なく架空にする。全画面（締めを含む）に架空の表示。workflowとupload_youtube双方で投稿を拒否する。
- rootの `build/codex/tmp/soccer-voices-preview/` に声つき `collespo_soccer_voices.mp4`（28.93秒、実WAV計28.821秒）・6画面の `all-screens.png`・原文/訳の `material.json`・原稿・音声・`verification.json`。投稿なし。
- 再作成: `COLLESPO_SHORT_LOOK=v4` の環境で `python scripts/preview_soccer_voices.py --out <確認用の場所>`。既存VOICEVOX（50021）を使用。`--screens-only` は画面だけ。

## 検査と残り

- `test_soccer_voices` は名前・批判/判定欠落・返信文脈・役割の判定・追加数字/出来事・重複・40秒・位置/クラブの札・架空の投稿拒否・workflowの既定値/書体の順を検査。`test_v3_rules` のv3/v4両方へ組み込み、`run_checks` が毎回動かす。
- 手元の最終 `run_checks` は終了0、最後の行 `===== すべて通過 =====`。`test_soccer_voices`（各26件）と `test_v3_rules` のv3/v4を含む。確認の出力はrootの試作フォルダの `confirmation.json` と `run_checks.log` に統合。
- ローカルの見本は取得/訳のAPIを呼ばない。人物・訳の判定は固定応答で検査し、実コメントと実LLM応答で正しさを確認したとは扱わない。
- 次はエマの取り込み/CI、手動・publish=falseで実コメントの原文/訳/名前/出典を確認、本人の声つき見本の確認。自動の定時実行は追加しない。
