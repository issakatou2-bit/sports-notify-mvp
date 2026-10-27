# ショートの下限と情報量（2026-10-27）

依頼：本人10/27「情報1個ポン出しの20秒切るようなのはやめて」「2次情報を入れて30秒いくくらい」。

作業：`hiro/short-min-length-20261027`、保存した `origin/main c0afa455` 起点。共有の他担当差分を持ち込まず、`build/codex/tmp/wt-shortlen` で実施。共有 `.git` が書込不可のため、専用管理領域 `build/codex/tmp/shortlen-repository.git` から作成。commitまで、push・公開・本番変数変更なし。

## 調査の範囲と数え方

対象は日本時間2026-10-14〜10-27の14暦日。2台帳の動画IDを重複除外した公開履歴120本（現在非公開の記録2本も状態を明示）。横長の週次と長編は除外。

尺の直接資料は19本、残る101本は不明。直接資料は台帳の `duration_seconds` または同日・同種類/同topicの保存MP4をFFmpegで読んだ値。保存MP4とYouTube公開版のハッシュ同一性は未照合なので「保存版」と明示する。保存版で20秒未満2本、28秒未満5本。

情報数は独立した事実のまとまり。表紙と本文で同じ勝敗を再掲しても1件。主題1件＋補足2件以上を下限とする。保存原稿がない回は公開題で確認できる「1以上（全編不明）」とし、実際に1件だけだったと断定しない。資産の元材料しか残らない回は素材上の再現値であり公開映像の確定値ではない。引用は「その発言がある」件数で、発言内容を事実認定した数ではない。

出典：`data/published_videos.json`、`data/published_assets.json`、`data/analytics.json`、共有 `build/channel-audit-20261014〜16` の生成記録・原稿・MP4、各 `data/*_topics.json`。分析の平均視聴時間/平均視聴率から動画の尺を逆算しない。再現器：`scripts/audit_short_content.py`。

## 種類別の洗い出し

| 種類 | 本数 | 直接資料の秒数 | 尺不明 | 情報と短くなる条件 |
|---|---:|---|---:|---|
| asset/legend | 1 | 不明 | 1 | 1〜2人でも、殿堂入り年と通算本塁打・安打などを個別の事実として点検。札枚数を情報数としない。 |
| asset/rare | 1 | 不明 | 1 | 保存されたrare_808967はWHIPの1項目だけ。MIN_ITEMS=1で候補化する入口があり、従来は情報1件の回を作れた。 |
| asset/season_game | 10 | 70.83〜70.83 | 9 | 決勝点・先発・日本人の出場が少なく、引用しか残らない回は薄くなる。原稿の最終形で止める。 |
| asset/season_league | 4 | 不明 | 4 | 部門別の公式1位が複数ある回。残す項目が1つになれば見送り。 |
| asset/season_player | 8 | 50.08〜50.08 | 7 | 今季の成績＋昨季比較・節目・リーグ順位。年度と選手IDをそろえる。 |
| asset/season_story | 1 | 47.33〜47.33 | 0 | シリーズ結果と主役だけでなく、当該シリーズの本人の成績を使う。 |
| asset/season_team | 22 | 不明 | 22 | 最終成績＋球団内の主役等。上限に合わせて削った後に補足が2件残ること。 |
| asset/venue | 9 | 不明 | 9 | 同じ球場の公式材料。球場・街・実測成績を混ぜる場合も期間と母数を残す。 |
| asset/ws | 2 | 不明 | 2 | 2本とも台帳で現在private。誤りのある旧回を修正版の見本として再利用しない。 |
| daily | 6 | 39.89〜53.64 | 4 | PSが1試合の日。1対戦＋勝数の再掲だけでは補足不足。前戦・先発・次戦が未取得なら見送り。 |
| daily_soccer | 4 | 17.13〜17.13 | 3 | 保存版17.13秒。少数カードと短い開始時刻の読みだけで終了。保存版の全編情報数は不明。 |
| morning | 1 | 28.30〜28.30 | 0 | 保存原稿は当日1選手＋7日集計の2件。1選手だけの日、補足が欠ける日は止める。 |
| morning_postseason | 12 | 25.71〜26.69 | 10 | 保存版25.71/26.69秒。最終1シリーズになり勝数だけ、次戦の時刻が未確認のときは1件化する。 |
| morning_press | 10 | 49.37〜67.17 | 4 | 引用が多い日は上限超過もある。本文を削ったあとの独立情報を再計数。 |
| morning_voices | 12 | 79.71〜82.25 | 10 | 短い感想や同じ親コメントの反復は水増ししない。出典付きの独立した発言が必要。 |
| soccer_race | 10 | 18.43〜18.43 | 9 | 保存版18.43秒。画面の順位表は複数事実でも、声が主役の勝点差の反復だけになりやすい。 |
| soccer_results | 6 | 不明 | 6 | 得点経過が少ない/0対0/出場1人の日。結果だけで終わらず、確認済みの本人・チーム成績を使用。 |
| soccer_week | 1 | 23.70〜23.70 | 0 | 保存版23.70秒。名簿の画面数に対して声が短い。本人の成績とクラブ結果を区別して補う。 |

得点ショート `soccer_goal_short` と速報 `soccer_now` は期間中の公開台帳・専用速報台帳に該当記録なし（公開0本）。ただし短尺化するコード経路があるため検査と保存材料の確認版の対象にした。

## 入れた決まりと停止箇所

- `docs/SHORT_CONTENT_POLICY.md`：30秒程度、厳格な下限28秒、主事実＋独立した補足2件。言い換え・長い間で延ばさず、作れなければ見送り/統合。
- `scripts/short_content.py`：最終の区間と元の表示材料で長さ・情報数を検査。短縮で落ちた画面の情報も除外。不明な形・出典なしを推測合格にしない。
- 全ショートの本番描画入口（PS、日次、朝、資産、答え合わせ、サッカー予告/順位/週末/結果/声/速報/得点、選手ストーリー）で音声結合/本編描画前に実行。横長の週次と長編は変更対象外。
- 不合格は `short_content_gate.json` とMP4名別の `.short_content.json` に理由を保存し、例外で停止。Actions実行時はステップ要約にも理由を記録。
- 公開器でもMP4名別の合格記録、制作前より新しいMP4、実尺と計画の一致、下限と既存上限を確認。失敗後の古いMP4と別動画の合格を流用しない。
- 完成尺と情報数を既存の台帳書込み口へ渡す。以後の公開記録には `duration_seconds`、`short_information_count`、`short_content_policy` を保存する。
- 既存の上限（40、45、55＋猶予、60秒等）は各入口の値を引継ぎ。札・書体・字サイズ・キャラ・敬語は既存の生成/描画部品を使用。

## 種類別の確認版と2次情報

確認版は保存材料の字幕・札・構成の確認用。音声は合成していない。尺は6字/秒の仮見積りに基づく実MP4で、音声同期・実音声の尺・音質の確認版ではない。28秒へ合わせる定数や無音は追加していない。公開に使える合格記録も発行していない。本番は実音声で再検査する。

各段の頭・中・終わりを既存の描画関数から出力し、`scripts/visual_capture.py video` で一覧化。保存先は同worktreeの `build/short-min-length/previews/<種類>/`。

| 種類 | 確認版の秒数 | 情報数 | 補足2件以上（新規追加または既存から維持） | 出典/材料 |
|---|---:|---:|---|---|
| asset_game | 36.40 | 3 | 最終結果に、3回表の決勝打＋両先発の投球成績。引用はこの確認版から除外。 | `保存した公式生成材料: season_game_849804` |
| asset_league | 38.30 | 4 | 主部門に加え、別部門の公式1位を2件以上。 | `保存した公式生成材料: season_league_103_hitting` |
| asset_legend | 35.97 | 6 | 殿堂入り年に、通算本塁打＋通算安打。既存の1枚の札にある独立した事実を個別点検。 | `保存した公式生成材料: legend_158` |
| asset_player | 48.23 | 5 | 今季成績に、自己最多＋昨季比較（同年同選手の公式集計）を維持。 | `保存した公式生成材料: season_player_660271` |
| asset_rare | 34.07 | 3 | WHIPだけの回に、同じ山本由伸の2026年成績＋昨季（2025年）比較を追加。選手ID/年度/終了済みを確認。 | `保存した公式生成材料: rare_808967` |
| asset_story | 52.23 | 5 | シリーズ結果に、バウアーズのシリーズ成績＋大谷などの当該シリーズ成績を維持。 | `保存した公式生成材料: season_story_L_119_158` |
| asset_team | 30.57 | 3 | 最終成績に、シーズンの結末＋球団の主役を維持。1本に収まる3項目を選択。 | `保存した公式生成材料: season_team_119` |
| asset_venue | 54.87 | 5 | 球場の基本情報に、保存された2026年の試合平均得点（88試合）＋球場固有の情報。期間と母数を維持。 | `保存した公式生成材料: venue_american_family_field` |
| daily | 57.53 | 6 | 前戦の最終スコア＋前戦のホーム球団。同じ公式日程にある場合だけ。先発・勝数・開始予定も維持。 | `build\channel-audit-20261014` |
| daily_soccer | 32.93 | 3 | 同じ試合の両クラブの順位。選定済みの注目理由と開始予定を維持。 | `scripts/fixtures/soccer-daily/20261026.json` |
| morning | 29.00 | 3 | 主役以外の当日成績2人。人数の宣伝と順位だけを補足にしない。 | `scripts/fixtures/bignumber/morning_recap.json` |
| morning_postseason | 29.47 | 4 | 最終1組のWSで、前戦10対1＋レイズのホーム開催＋3回表のコントレラスの決勝打。公式日程と試合topicのID・両球団・得点を照合。 | `build\channel-audit-20261014` |
| morning_press | 58.37 | 5 | 出典を持つ別の見出し/記者の報道を維持。引用を成績の証拠にしない。 | `scripts/fixtures/comment/local_reporters-preview.json` |
| morning_voices | 47.40 | 3 | 別の親コメントを2件。長い返信枝を外し、同じ発言の反復で増やさない。 | `scripts/fixtures/comment/local_voices-preview.json` |
| soccer_goal_short | 35.00 | 7 | 上田の得点時刻＋最終結果＋本人の出場とシュート。朝の結果と同じ既存構成へ接続。 | `scripts/fixtures/soccer-stats/saved-cases.json case 2` |
| soccer_now | 31.70 | 7 | 0対0でも、田中/鎌田の本人の出場・シュートに加え、チームのシュート13対12・保持率50.6対49.4を補足。 | `scripts/fixtures/soccer-stats/saved-cases.json case 0` |
| soccer_race | 29.43 | 5 | 順位表の2クラブの現在順位・勝点を声でも明示し、同じ消化試合数の時点も補足。勝点差の同文反復を置換。 | `data/soccer_race.json` |
| soccer_results | 53.03 | 12 | 得点時刻・各日本人の出場/個人成績を維持。保存された最終名簿と試合経過。 | `scripts/fixtures/soccer-stats/saved-cases.json case 1` |
| soccer_week | 35.67 | 15 | 鎌田/坂元の本人の出場時間と、所属クラブの相手・最終スコアを区別して補足。 | `data/soccer_jp_week.json` |

PSの1組だけの回は、公式日程の前戦と同じ試合の既存topicを照合する。レイズ/ブリュワーズの最終1組の見本は、保存済み `postseason.json` と `ps_game_topics.json` の最終スコア欄から再構成したもの。

追加材料は `sanity_materials` に添付して既存点検へ渡す。PSは前戦の得点・球団と決勝点、サッカーは同じ試合の最終名簿/詳細成績、rareは同じ年度・選手ID・終了済みシーズン。新しいAPI用途・有料API・新しい取得はなし。

## 自分で行った確認

実行と目視の結果は `build/short-min-length/validation.json` と `review.json` を参照。未作成/未記入なら未確認。担当者の過去の報告を自分の検証としていない。

重い描画と検査は `C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 30 -- ...` を使用し、20:50〜22:10を避ける。全run_checksは `PYTHONUTF8=1`、TEMP/TMP/PYTEST_DEBUG_TEMPROOTをworktree内に設定。

未確認：リモートCI、本番の実音声・同期、実SNS、実際の公開結果。push/公開/本番変数/共有VoiSonaは操作していない。

## 14日分の全記録

「1以上・全編不明」は情報1件だけという意味ではない。材料値は公開映像の完全な情報数ではない。

| JST日 | 種類 | 動画ID / topic | 秒 | 情報数 | 確認資料 | 現在の台帳状態 |
|---|---|---|---|---|---|---|
| 2026-10-14 | asset/legend | `hpMMAxAd89g` / legend_158 | 不明 | 2（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-15 | asset/rare | `8SUiQaWe4S8` / rare_808967 | 不明 | 1（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-14 | asset/season_game | `cp-8BvqpXFI` / season_game_849813 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-15 | asset/season_game | `AaivcUiJ6qg` / season_game_849811 | 70.83 | 7（原稿/材料） | build\channel-audit-20261015\game\collespo_asset_season_game_849811.mp4 | public |
| 2026-10-16 | asset/season_game | `GhJYUObTp3I` / season_game_849810 | 不明 | 6（原稿/材料） | build\channel-audit-20261016\season\collespo_asset_season_game_849810.mp4 | public |
| 2026-10-16 | asset/season_game | `-WWdo4q-JcE` / season_game_849818 | 不明 | 4（原稿/材料） | build\channel-audit-20261016\season\collespo_asset_season_game_849818.mp4 | public |
| 2026-10-18 | asset/season_game | `TCoMDZVRXRY` / season_game_849816 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-19 | asset/season_game | `zfxuzBjLI3U` / season_game_849817 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-20 | asset/season_game | `AVJnsG7EE_s` / season_game_849815 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-24 | asset/season_game | `Mq8KO8H3Xbc` / season_game_849805 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-25 | asset/season_game | `U6_YLrfbIvk` / season_game_849802 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-27 | asset/season_game | `nn6eGTOqQs4` / season_game_849804 | 不明 | 3（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-19 | asset/season_league | `r7Yt5yndfWE` / season_league_103_hitting | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-19 | asset/season_league | `UW5pbvQ7zbg` / season_league_103_pitching | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-19 | asset/season_league | `nPX10OMwAAU` / season_league_104_hitting | 不明 | 3（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-20 | asset/season_league | `4DMS6qKPFiQ` / season_league_104_pitching | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-15 | asset/season_player | `_lVSOtJXLTY` / season_player_579328 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-15 | asset/season_player | `bLxYZkEeqOs` / season_player_608372 | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-16 | asset/season_player | `oUnzHmg2RZQ` / season_player_660271 | 50.08 | 5（原稿/材料） | build\channel-audit-20261016\season\collespo_asset_season_player_660271.mp4 | public |
| 2026-10-17 | asset/season_player | `LHztdQNYoZs` / season_player_808963 | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-17 | asset/season_player | `bImzF8TYDck` / season_player_808967 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-18 | asset/season_player | `F1fgyP39SN4` / season_player_663457 | 不明 | 3（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-18 | asset/season_player | `J4wWh8qT4co` / season_player_672960 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-18 | asset/season_player | `zBJOl4IStlU` / season_player_673540 | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-16 | asset/season_story | `QYAEPt9xIog` / season_story_L_119_158 | 47.33 | 5（原稿/材料） | build\channel-audit-20261016\season\collespo_asset_season_story_L_119_158.mp4 | public |
| 2026-10-14 | asset/season_team | `GSuIy03IVZ4` / season_team_143 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-14 | asset/season_team | `fm0fctswB3w` / season_team_147 | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-17 | asset/season_team | `h394lQ-a7hs` / season_team_119 | 不明 | 9（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-17 | asset/season_team | `muKOwUuZVx4` / season_team_144 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-20 | asset/season_team | `w1KvvfC13W8` / season_team_108 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-20 | asset/season_team | `kjCwVKXgQz8` / season_team_109 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-21 | asset/season_team | `jSkBbAiXqXw` / season_team_115 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-21 | asset/season_team | `ZzOB0orhcHk` / season_team_121 | 不明 | 7（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-21 | asset/season_team | `0H-if7Faq3s` / season_team_138 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-21 | asset/season_team | `EeKD20nkUBc` / season_team_141 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-22 | asset/season_team | `NyKvO78_s0s` / season_team_110 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-22 | asset/season_team | `ggK2mq4gvtY` / season_team_113 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-22 | asset/season_team | `RegoJCkIY7w` / season_team_116 | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-22 | asset/season_team | `Yjxu2NxjP2c` / season_team_118 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-23 | asset/season_team | `U4gJbDLMdhg` / season_team_120 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-23 | asset/season_team | `C-V93694TnI` / season_team_133 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-23 | asset/season_team | `Qo69lcgyftU` / season_team_134 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-23 | asset/season_team | `vnF5bMEM6FA` / season_team_136 | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-24 | asset/season_team | `aZi8QZaJwzI` / season_team_137 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-24 | asset/season_team | `-YjM2J9Hh_Q` / season_team_140 | 不明 | 4（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-24 | asset/season_team | `-IXQWF9hLx8` / season_team_142 | 不明 | 6（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-25 | asset/season_team | `Pbke2tvHvOQ` / season_team_146 | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-16 | asset/venue | `k7r7xd3wXhE` / venue_american_family_field | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-17 | asset/venue | `EagVRSOZdC0` / venue_angel_stadium | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-18 | asset/venue | `sO-1LP-EBq0` / venue_busch_stadium | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-19 | asset/venue | `eX70JU6dti0` / venue_chase_field | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-20 | asset/venue | `tmbAB3s15t4` / venue_citi_field | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-22 | asset/venue | `gI_vpXO3n4Y` / venue_citizens_bank_park | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-23 | asset/venue | `wwc5s0wlJx8` / venue_comerica_park | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-24 | asset/venue | `HOKntIm9hew` / venue_daikin_park | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-25 | asset/venue | `26CCbE7OeAs` / venue_globe_life_field | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | public |
| 2026-10-22 | asset/ws | `4bZAY2JNlEQ` / ws_title_history | 不明 | 8（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | private |
| 2026-10-23 | asset/ws | `nvqLtsVPSEA` / ws_schedule | 不明 | 5（原稿/材料） | 保存生成材料の独立した事実の札（公開映像の確定値ではない） | private |
| 2026-10-14 | daily | `3JTBaNavYbI` / 2026-10-14 | 39.89 | 4（原稿/材料） | build\channel-audit-20261014\preview\video\collespo_short.mp4 | 記載なし |
| 2026-10-15 | daily | `JphOpGVs9V4` / 2026-10-15 | 53.64 | 7（原稿/材料） | build\channel-audit-20261015\preview\video\collespo_short.mp4 | 記載なし |
| 2026-10-18 | daily | `yLi7saNnTAE` / 2026-10-18 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-19 | daily | `pt5op6OiDlI` / 2026-10-19 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-24 | daily | `wHPKEFaRvps` / 2026-10-24 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-26 | daily | `6i973MO7epU` / 2026-10-26 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-14 | daily_soccer | `vnMBOjZ1o0Q` / 2026-10-14 | 17.13 | 1以上・全編不明 | build\channel-audit-20261014\soccer\collespo_short.mp4 | 記載なし |
| 2026-10-15 | daily_soccer | `v9liJ18zQVQ` / 2026-10-15 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | 記載なし |
| 2026-10-18 | daily_soccer | `T_daXQFCjY8` / 2026-10-18 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-21 | daily_soccer | `3XOnyWk-gI0` / 2026-10-21 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-16 | morning | `63gbUaygi9s` / 2026-10-16 | 28.30 | 2（原稿/材料） | build\channel-audit-20261016\morning\players.mp4 | public |
| 2026-10-14 | morning_postseason | `pqG9757XUv0` / 2026-10-14 | 26.69 | 1以上・全編不明 | build\channel-audit-20261014\morning\postseason.mp4 | 記載なし |
| 2026-10-15 | morning_postseason | `Nsykm04es6U` / 2026-10-15 | 25.71 | 1以上・全編不明 | build\channel-audit-20261015\morning\postseason.mp4 | 記載なし |
| 2026-10-18 | morning_postseason | `Bw93l9uHvnA` / 2026-10-18 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-19 | morning_postseason | `jIH1d2ANJDg` / 2026-10-19 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-20 | morning_postseason | `EUQpIXF_srY` / 2026-10-20 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-21 | morning_postseason | `SzbKc7VcHbw` / 2026-10-21 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-22 | morning_postseason | `tUqx1lJLHkE` / 2026-10-22 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-23 | morning_postseason | `mc8kd26Jt2o` / 2026-10-23 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-24 | morning_postseason | `wJFwyLzRHO8` / 2026-10-24 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-25 | morning_postseason | `Dcyae_uD1x0` / 2026-10-25 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-26 | morning_postseason | `grTm1IOzVRA` / 2026-10-26 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-27 | morning_postseason | `na2PP2Yx4i4` / 2026-10-27 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-14 | morning_press | `Hvv-ofthG40` / 2026-10-14 | 53.50 | 1以上・全編不明 | build\channel-audit-20261014\morning\press.mp4 | 記載なし |
| 2026-10-15 | morning_press | `w0c3bI9FpA8` / 2026-10-15 | 67.17 | 1以上・全編不明 | build\channel-audit-20261015\morning\press.mp4 | 記載なし |
| 2026-10-16 | morning_press | `8kay0TjLK6E` / 2026-10-16 | 53.27 | 5（原稿/材料） | build\channel-audit-20261016\morning\press.mp4 | public |
| 2026-10-17 | morning_press | `HCRHGAUGSik` / 2026-10-17 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-18 | morning_press | `Y8LiuGA1bKo` / 2026-10-18 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-19 | morning_press | `VEhlBgcHlaU` / 2026-10-19 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-20 | morning_press | `ntjVU3Ik6U0` / 2026-10-20 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-24 | morning_press | `MQyma6NVRbA` / 2026-10-24 | 49.37 | 1以上・全編不明 | data/published_videos.json | public |
| 2026-10-26 | morning_press | `98c6houYAbU` / 2026-10-26 | 52.50 | 1以上・全編不明 | data/published_videos.json | public |
| 2026-10-27 | morning_press | `0LeUJdKUw-4` / 2026-10-27 | 50.60 | 1以上・全編不明 | data/published_videos.json | public |
| 2026-10-14 | morning_voices | `c_pI12pRxYU` / 2026-10-14 | 82.25 | 1以上・全編不明 | build\channel-audit-20261014\morning\voices.mp4 | 記載なし |
| 2026-10-15 | morning_voices | `zW8JeKSEmkk` / 2026-10-15 | 79.71 | 1以上・全編不明 | build\channel-audit-20261015\morning\voices.mp4 | 記載なし |
| 2026-10-17 | morning_voices | `uASx-MBIqr4` / 2026-10-17 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-18 | morning_voices | `bP4hTDqk0KU` / 2026-10-18 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-19 | morning_voices | `mMZIGs8s7kk` / 2026-10-19 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-20 | morning_voices | `mIrRIYO-w6Y` / 2026-10-20 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-21 | morning_voices | `tywbA8wR0pE` / 2026-10-21 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-22 | morning_voices | `uaPKIuQtqXU` / 2026-10-22 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-23 | morning_voices | `ohC1Yt8JwMY` / 2026-10-23 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-25 | morning_voices | `cY3aKqeaJU8` / 2026-10-25 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-26 | morning_voices | `qhtwyyiDRc8` / 2026-10-26 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-27 | morning_voices | `bwpoowrG9XI` / 2026-10-27 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-14 | soccer_race | `H1VbsickNdc` / 2026-10-14 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | 記載なし |
| 2026-10-15 | soccer_race | `wDqkt4M96SA` / 2026-10-15 | 18.43 | 6（原稿/材料） | build\channel-audit-20261015\soccer-race\race\collespo_morning_soccer_race.mp4 | 記載なし |
| 2026-10-18 | soccer_race | `9dAFjjPhais` / 2026-10-18 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-19 | soccer_race | `SC7vftxNYXg` / 2026-10-19 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-20 | soccer_race | `O-kPTcaKhRI` / 2026-10-20 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-21 | soccer_race | `6sjyMqV3ZOM` / 2026-10-21 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-23 | soccer_race | `5SeDIE6VDLs` / 2026-10-23 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-24 | soccer_race | `Hk5PATDQd2E` / 2026-10-24 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-25 | soccer_race | `1Yo8cT2bqOo` / 2026-10-25 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-26 | soccer_race | `lWLeND89bas` / 2026-10-26 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-21 | soccer_results | `-1WicwElsrA` / 2026-10-20 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-22 | soccer_results | `mAdaRHA_404` / 2026-10-21 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-23 | soccer_results | `EkFT0Bm9u7w` / 2026-10-22 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-24 | soccer_results | `1skqllJd8D4` / 2026-10-23 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-25 | soccer_results | `1Iy8UsDuSl8` / 2026-10-24 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-26 | soccer_results | `LWUL4lgaKb8` / 2026-10-25 | 不明 | 1以上・全編不明 | 全編の原稿未保存。題の主事実1件以上 | public |
| 2026-10-15 | soccer_week | `qNqzkqsk4sU` / 2026-10-15 | 23.70 | 15（原稿/材料） | build\channel-audit-20261015\soccer-week\week\collespo_morning_soccer_week.mp4 | 記載なし |
