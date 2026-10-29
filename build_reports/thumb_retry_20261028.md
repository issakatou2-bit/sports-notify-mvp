# 枠切れサムネイルの自動付け直し（2026-10-28）

指定の `build/codex/tmp/wt-thumbretry`、枝 `hiro/thumb-retry-20261028`。
起点は `origin/main a05746aa6576a13b871df987db666af35b1c7f4d`。
GitHub の main API と一致することを自分で確認した。共有の未コミット変更には触れていない。
共有 `.git` は書込不可のため、`build/codex/tmp/thumbretry-repository.git` に管理領域を置いた worktree。

## 実装

- 投稿後の `HttpError 403` の JSON に `reason: quotaExceeded` がある場合だけ、元画像と `video_id/kind/title/failed_at` を `build/thumbnail_pending/` に保存。種類は既存の投稿記録と同じ区分。保存に失敗しても投稿記録を続ける。電話番号未確認等は従来どおり警告だけ。
- 公開・通常投稿の16ワークフロー（夕方、日次、週次、資産、訂正、長編、選手、PS直後、シーズン、サッカー7経路）に `thumbnail-pending` の保存を追加。常時終了処理、画像がある時だけ、保存3日。未発表素材を暗号化している非公開試作 `pilot_series` は対象外。
- 新しい `thumbnail_retry.yml` は毎日07:20 UTC（16:20 JST）と手動。main 限定、同時実行を直列化。手動でも16時より前は何もしない。
- `gh api --paginate --slurp` で main の完了実行を一覧化し、前日16時から実行時点までに完了した回の `thumbnail-pending` を取得する。作成時刻だけで判断せず完了側の `updated_at` も確認。別枝・fork・PR・未完了実行を除外する。
- 画像の失敗日時も確認し、24時間未満だけ採用。同じ動画は1本にまとめる。ZIP全体は展開せず、検証した11文字の動画IDに対応するPNGだけ取り出す。
- 書込み前に `thumbnail-retry-YYYY-MM-DD` の着手記録を保存し、同日の2回目を止める。印の保存に失敗したら書き込まない。印の後に途中終了・依存導入失敗等が起きても、その日は再送しない（重複防止を優先）。自動生成画像も `snippet.thumbnails` に入るため、その有無で設定済みとは判断しない。
- `reset_thumbnail.py --write --quota-warning` に引渡す。既存の存在確認に加え `channels.list(mine=True)` と `snippet.channelId` で本人所有を確認する。枠切れは取得・設定のいずれも警告終了し、残りを翌日に持ち越さない。対象・結果ログは3日保存。
- データJSONの書込先は増やさず、公開台帳・変数・鍵・公開時刻・絵の内容を変えていない。

## 比較した公開資料

GitHubの公式[artifact API](https://docs.github.com/en/rest/actions/artifacts)と[download-artifact](https://github.com/actions/download-artifact)、[CLIの取得](https://cli.github.com/manual/gh_run_download)を確認した。実行番号が既知なら公式Actionで取得できるが、今回は複数の投稿実行を時刻で選ぶ必要があるため、指定どおりAPI一覧とZIP取得を採用。外部コードの転載・追加Action導入なし。
YouTubeの公式[thumbnails.set](https://developers.google.com/youtube/v3/docs/thumbnails/set)と[エラー一覧](https://developers.google.com/youtube/v3/docs/errors)を確認し、403全体ではなくJSONのreasonで枠切れだけに限定した。

## 自分で確認したこと

- 追加23試験：元画像とメタ情報保存、403 quotaだけ保存、他の403/429/400/非HttpError/不正JSONは保存しない、追記・重複排除、投稿処理からの保存、成功時は保存しない。
- 回収：実行なし・保存物なし、同日2回目、16時前、元PNG取得、複数ページ、古い/fork/PR/未完了/未来の実行、期限切れ・別保存物、24時間/境界/未来の画像、同一動画の重複、不正ID、空の適用、適用前の再期限確認。
- 付け直し：所有外は拒否、quota発生後は残りを送らない。workflow契約：全16投稿経路の保存と、新しい日次印が書込みより前であること。
- `python -m pytest scripts/test_thumbnail_retry.py scripts/test_upload_retry.py scripts/test_commit_list_check.py --basetemp=build/pytest-thumb -q`：28成功＋8 subtests（10/28 JST、4.38秒）。新規分はunittest直接実行でも23成功。
- 新規・変更部分のpyflakes、差分空白、共有の文字化け検査は成功。
- 実行40458559334のGitHub APIを自分で読み、`status=completed`、`event=workflow_dispatch`、main枝、本人リポジトリ、`updated_at` が実際に返ることを確認。画像取得やYouTubeへの書込みはしていない。
- 全 `run_checks`：**終了0、すべて通過**（10/28 10:21:10〜10:44:07 JST、約23分、出典 `build/run-checks-thumb-retry.log`）。構文573ファイル、全210試験ファイル、重大0・軽微53。`check_commit_list`、YAML、共通点検の呼出し、秘密の受渡し、依存関係、ワークフロー参照も成功。`test_data_commit` も成功。
- 実行は `PYTHONUTF8=1`、TEMP/TMPとpytest一時置場をworktree内へ指定し、`C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 30 -- python -u build/run_full_checks.py` で包んだ。Windowsの標準入出力を明示するwrapperを使用。19:15〜20:40の重処理なし、18:30前に完了。

## 未確認と次

実API、GitHub Actions上のCI、実際のサムネイル復旧は未確認。秘密は読んでいない。push・変数変更・実投稿・実付け直しはしていない。
この仕組みがmainへ入った後の投稿から画像保存が始まるため、過去10/27・10/28分の画像を遡って自動回収はしない。既存の手動道具で別途扱う。
確認担当がcommitを見直してpush/PR/CIを行い、最初の枠切れ日と空の日にActions上の保存・復旧結果を確認する。
