# 10/13夜 欧州予告の停止修正

- 基点: origin/main `9de21222`。隔離 clone `build/codex/tmp/soccer-reason-badge-20261013`、枝 `hiro/soccer-reason-badge-20261013`。共有コピー・HANDOFFは変更しない。
- 停止記録: `build/codex/tmp/logs-20261013/soccer1900_38380420146.log`（Actions 38380420146、19:00 JST）。表紙のクラブ名を含む文が v5 の札検査で停止。
- 見出しと注目理由は、既存引用用の文字分割と `club_name` を再利用。名前に札を添え、表紙は最大2行。札なしクラブ名を拒否する検査は維持。
- coverage は PL・PD・BL1・SA・FL1を含む14大会が HTTPError。「試合なし」ではなく取得失敗。記録にHTTP番号はなく、代表戦期間が原因と断定できない。
- ESPN の補完取得を範囲指定から既存の結果取得と同じ単日指定（UTC当日・翌日）へ変更。重複IDを統合、片日の失敗も失敗として保持。HTTP番号・理由を残し、正常な空配列だけ `no_games / 試合なし`。壊れた材料も failed にする。今回取得した大会の前回エラーは更新し、取得していない大会のエラーは保持。
- ライブ復旧は未検証。シェルからの外部通信は WinError 10013、web取得不可、ブラウザは接続先への許可拒否。日別指定が実環境で復旧するかはエマの再実行で確認が必要。
- 固定材料: main保存の `data/soccer_games.json` から記録の選定ID `575345 / 575346` の2試合を抽出し、`scripts/fixtures/soccer-interest/saved-preview-20261013.json` に同梱。新しい日程の公式照合として扱わない。
- 手元出力: `build/codex/tmp/soccer-reason-badge-preview/`。声つき `collespo_short.mp4` は17.53秒、`01.png`〜`04.png` と `all-screens.png`、材料・原稿・音声・verification.jsonを保存。全4画面の一覧と修正後表紙を目視確認。音声内容の聴感確認は未実施。
- 回帰検査: 今夜の2試合の選定と全画面の複数時刻、クラブ名入り理由の札、札なし文字の拒否、単日URL、重複、片日失敗、HTTP番号、空/不正配列、Windows文字化け検知。固定材料・同梱フォントを使用し、古いGitコミットに依存しない。
- CI・公開物の確認なし。push・PR・公開・リポジトリ変数変更は行わない。

全体検査は終了コード0、`===== すべて通過 =====`。136本のテスト・v3の21コマ/v4の71コマ画素一致も通過。ログはプレビュー内 `run_checks.log`。完成MP4の全フレーム・音声デコードはエラーなし。
