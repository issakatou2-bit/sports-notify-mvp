# 短尺3修正（2026-10-14）

担当：ヒロ/Codex。隔離 clone `build/codex/tmp/short-polish-20261014`、枝 `hiro/short-polish-20261014`。基点 `843637b4134ec286cf691cb17aadaed7fcba628f`。
GitHub直結のcloneは接続失敗したため、新しいローカルcloneへ取得済みorigin/mainを取り込み、GitHub連携でmainのSHAが同一と照合した。共有コピーの制作ファイル・メモ・設定は変更していない。

## サッカー

- `club_display_names.json`へ欧州大会の70クラブを追加。CL/EL/UECLは各36クラブ、五大リーグは20/20/20/18/18クラブ。2026/27のUEFA参加一覧と、保存済み2026年のfootball-data.org順位表を`data/soccer_club_coverage.json`へ記録した。公式名・ESPN名・日本語名の別名も吸収する。本人指定のアストン・ヴィラ、マンチェスター・シティ等へ表示を統一し、狭い欄のshortは維持。
- ESPN日程をUTC単日8日分取得し、今後7日の未登録クラブを選定前に一覧化する。結果JSONと日次Actionsの既存summaryへ警告を出す。一部の日の取得失敗は明示して成功日の試合を保持する。未登録の試合だけ選定から外す。
- しきい値30は維持、上限4へ。別名で保存済みの同一カードは大会・両クラブ・時刻で重複排除する。
- 原稿は構造化された注目理由・昨季順位・所属情報等から作り、AI解説の自由文を取り込まない。順位等のないカードは対戦とホーム側の背景を伝え、成績や出場を補って作らない。
- 10/14の`data/soccer_games.json`は変更せず入力。選定IDは575353、575350、575352、575354の4試合。元入力を固定fixtureへそのまま保存した。
- 最終試作は **51.00秒**、声の各試合は **10.04/11.33/9.53/9.98秒**。4カードの表示は各10秒以上。声の設定は変更していない。動きonの場合も54.63秒で55秒以内、24代表コマを検査した。予告だけ55秒制限へ変更、順位/週末の40秒制限は維持。
- MP4：`build/short-polish/final/soccer/collespo_short.mp4`。全6画面の寸法・札・数字検査と画像確認済み。初回54.53秒の試作から重複文を削って最終版を作った。

## MLBと効果音

- `japanese_team_names.team_names`に名字と目立つ順を集約。2人以上は名字・読点、大谷→山本→佐々木。1人の既存フルネームと元の名簿を保持する。team_topics、PS、朝、予告、共通札で使用。
- 回帰例：`大谷翔平・佐々木朗希・山本由伸` → **大谷、山本、佐々木のドジャース**。実際のPS v4画面へ渡す文字も試験する。
- r3のintro/list/outroと長編、旧PSの転換音は画面の頭に1回・追加音量-10dB。行/チップごとのswishは削除。引用notifyとpop・marker・roll/stopは保持。引用が残る行の時刻を詰めないよう共通cuesも修正した。
- PS予告は保存した10/7の公式材料、同じ原稿・同じ音声尺で基点の音の関数と比較。**全効果音51→14回、swish39→0回**。roll2・stop2・marker3は同数。新しい転換音は7画面で各1回。比較は`build/short-polish/ps/sfx-comparison.json`。
- 最終PS MP4：`build/short-polish/final/ps/collespo_short.mp4`。サッカー/PSとも全尺復号を確認した。
- 公開、動画アップロード、リポジトリ変数変更は行っていない。

## 検証と指紋

追加の`test_short_polish.py`は11件通過。クラブ網羅、当日4件、別名重複、7日先の未登録/部分取得失敗、事実限定、MLB名字、専用画面、引用時刻、長編を固定材料で検査する。
本番の名字・音・予告尺を意図して変更したため、差分確認後`python scripts/update_protected_hashes.py --write`で`mlb-badge/protected-source.json`と`soccer-slots/v5-protected-source.json`を更新した。
`python scripts/run_checks.py`は149本の試験スクリプトを含めて「===== すべて通過 =====」、終了コード0。ログは`build/short-polish/run_checks-final.log`。元の名前/音の期待値を今回の仕様へ変更し、凍結した画素比較は旧ソースの形・配置を保持して表示する文字だけを共通名字へそろえた。差分検査と保護指紋検査も通過。
7日分の日程のライブ取得はこのPCの外部接続制限のため未実行。固定材料による検査とは区別する。リモートCIはこの手元検査と別に確認する。
