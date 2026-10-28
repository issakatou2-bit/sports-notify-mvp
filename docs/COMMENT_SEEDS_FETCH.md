# コメント候補の取得と失敗記録（2026-10-27）

`comment_seeds.py` は `reason` に呼出し名、1始まりのページ番号、例外型を残す。
HTTPError の場合は状態番号と `error.errors[0].reason` も残す。
同じ情報を標準出力にも出す。例外本文、鍵付きURL、応答本文全体は出さない。
API理由は許可した識別子だけを通し、不明・不正な本文は `unknown` にする。

通常は `allThreadsRelatedToChannelId` で最大10ページ、各100件を読む。
400/403/410 で `forbidden`、`insufficientPermissions`、`invalidParameter`、
`badRequest`、`operationNotSupported`、`unsupportedOperation` が返ったときだけ
動画別へ切り替える。quotaExceeded、通信切れ、不明な理由は停止する。
この分岐は当日の失敗原因や引数の廃止を断定するものではない。

代替経路は `data/published_videos.json` と `data/published_assets.json` の
`published_at` が現在から直近7日以内の `video_id` を重複除去し、新しい順で選ぶ。
日時不明、未来、明示的な非公開は除外する。
既定上限は50動画、各2ページ、各100件。CLI の `--max-videos` と
`--video-pages` で変更でき、workflow では50と2を明示する。
取得前と候補採用前に `videos.list` で自チャンネル所有と公開状態を確認する。
動画単位の `commentsDisabled` は `coverage.skipped` と標準出力に記録し続行する。
全動画でコメント無効でも取得処理自体は成功とし、候補0件を保存する。

代替時は途中までのチャンネル候補を捨て、動画別経路だけの候補を出す。
古い動画への新着コメントは読めないため `coverage.complete=false` とする。
候補動画数、実際のAPI呼出し数、上限による打切りも記録する。
`commentThreads` のページは動画ごと、`videos` のページは50件ずつの呼出し番号。
失敗時は古い候補を残さず `fetch_failed` と安全な理由を保存する。

API単位の見込み（既存 `early_views.py` の videos.list と同じ1呼出し1単位、
commentThreads.list も1単位としての計算。ネットを使わず実装上限から計算）：

| 経路 | commentThreads.list | videos.list | 合計上限の見込み |
| --- | ---: | ---: | ---: |
| 通常 | 10 | 最大1000動画を50件ずつ＝20 | 30単位 |
| 代替を含む | 通常の失敗まで最大10＋50動画×2＝110 | 取得前1＋採用前1 | 112単位 |

失敗した呼出しも計上し、再試行はしない。任意の上限 M動画・Pページ・C通常ページ
なら代替は最大 `C + M*P + 2*ceil(M/50)` 単位の見込み。
これは利用量見積りで、実APIや最新の割当仕様を確認した結果ではない。
10/27 10:31 の run 40433074758 の実原因は、応答が残っていないため未確認。
