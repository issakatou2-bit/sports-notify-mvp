# PS試合直後のコメント誤訳修正（2026-10-27）

対象は `nn6eGTOqQs4` / `season_game_849804`。起点は保存済み `origin/main` の `8706f0ff`、枝は `hiro/ps-comment-fix-20261027`。push・公開・音声生成・本番変数変更は行っていない。

## 原因と変更

当該topicの `items` と `game_v4` には10対1、9回裏のレイズの1点、先発成績、3回表の決勝点があった。資産原稿の保存では `sanity_sources.capture(narration)` だけを呼び、実際に使ったtopicが渡らず、点検が空材料になった。実行記録 `40430142762` の713〜719行は、high指摘が未確認扱いで公開へ進んだことを示す。なおAIの「9回裏は行われていないはず」という推測は保存済みの各回得点と異なる。今回の確定根拠はその推測ではなく「レイズ1点と大量得点の矛盾」。

- `generate_asset_video.build_narration` で当該topicだけの事実を添付する。最終スコア、全回の得点、先発・投手の札、決勝点、game_pk、試合日、公式出典URLを原稿に保存する。`ps_game_now.yml` と `correct_video.yml` の既存 `--kind asset` が同じ添付材料を読む。再点検用の短縮材料にも残る。
- `ps_comment_facts.py` で得点と点差の主張を機械照合する。0/1点と「大量得点」、具体的な得点数・回・最後の点差・最終スコア・満塁本塁打を検査する。英語の単数 `a/one/1 run` を複数点へ変える訳も採用しない。
- `ps_game_story.pick_voice` は不一致、得点材料欠測、解釈できない得点主張を次候補へ送る。安全な候補がなければコメントを付けない。皮肉の意訳をAIで作り直して自動採用することはしない。
- `local_voices` の翻訳指示に `big run / only / finally` の皮肉・誇張、単数の保持、確信のない訳の不採用を追加。採否はこの指示だけに依存しない。
- `sanity_material` から同じ機械照合を呼ぶため、保存済みの誤訳原稿もAIなしで停止する。既存の札の見た目・口調・サイズは変更していない。

この検査は自由文の万能な意味解析ではない。PSコメントの得点主張で解析できない形は採用しない。得点と関係のない感想は維持する。既存の「未確定highは一律に止めない」という共通方針は変更せず、今回の実材料との矛盾を確定させる。

## 自分での確認

`scripts/fixtures/ps_comment/849804.json` に8706f0ffの当該topicを全項目そのまま固定し、実指摘を添付した（個人名のある投稿者情報は含まない）。保存済みtopicとの全項目一致を自分で確認した。新しい8試験は、実際の資産原稿生成への材料添付、high確定、再取得失敗後の確定維持とAI呼出し0、`--strict --kind asset` の終了1・`upload_held=true`・保留記録、実得点経過を渡す候補選択、点数/点差の異常と正しい1点の受理、否定/願望/別試合での誤停止防止、訂正後の声と札からの除去を検査する。既存 `test_ps_game_story.py` の14試験、新規ファイルのpyflakes、`git diff --check` も通過。

全体検査結果：実行中。確定後に追記する。

ローカル全体ログ：`build/codex/tmp/wt-psfix/build/run-checks-psfix.log`（非commit）。コード・固定材料試験の確認であり、CI・実API・実音声・完成動画・YouTube非公開化の成功は未確認。他担当の非公開化手続きは自分の確認結果として扱っていない。外部API呼出し・追加費用は0。

## Claudeによる差し替え手順

1. この枝のcommitを確認し、通常のpush・PR・CI・main取込を行う（この作業ではpushしない）。共有Git管理領域は書込制限があるため、指定worktreeの管理情報は `build/codex/tmp/psfix-repository.git` に置き、共有 `.git/objects` を参照している。worktreeは `build/codex/tmp/wt-psfix`。通常の枝への移植は、このworktreeから `git format-patch -1 --output-directory ../psfix-transfer` でpatchを書き出し、通常の作業場所で `git am <patchのパス>` でも可能。
2. 旧動画の非公開化の成功を確認する。まだ公開中なら既存 `hold_video.yml` を `video=nn6eGTOqQs4, write=true, release=false` で実行する。YouTube枠切れの場合は復旧後に結果を確認する。
3. 追加した `data/corrections/ps_comment_849804_20261027.json` を使う。8706f0ffの当時の材料を取得し、`from` 一致を確認して、問題のコメントの札1件と `voice` を除去する。新しい解釈のコメントは足さない。最終スコア・先発・決勝点・既存の見た目は維持する。
4. main取込後、通常のリポジトリ作業場所から確認用を実行する。

```powershell
gh workflow run correct_video.yml --ref main -f fix=ps_comment_849804_20261027 -f mode=render
```

5. 当該実行の `corrected-video` 成果物で、原稿 `build/corr/narr.json` の `sanity_materials`、`sanity_correction.json` の停止なし、MP4の台詞と札から誤訳が消えたこと、スコア10対1・先発・決勝点・既存の札/口調を確認する。
6. 確認後、同じ道具で差し替える。

```powershell
gh workflow run correct_video.yml --ref main -f fix=ps_comment_849804_20261027 -f mode=publish
```

7. 既存workflowが次の同シリーズ試合の開始/終了を検査し、新版公開→訂正説明→旧版非公開→台帳更新を行う。新URLと旧動画非公開、台帳 `data/published_assets.json` の `season_game_849804` を確認する。次戦開始後に鮮度検査で止まった場合は `allow_after_next_game` を勝手に有効にせず、既存の扱いに従う。
