# UTC gameDate・時刻の日付照合監査（2026-10-28）

- 担当：Codex。対象起点は origin/main `c42da5dc`（#266 取り込み後）。共有 main の未コミット変更は使用・変更していない。
- 指定作業先：`build/codex/tmp/wt-utcdate`、枝 `hiro/utc-gamedate-audit-20261028`。共有 `.git` は書込拒否のため、新規cloneを作らず既存の `build/codex/tmp/thumbretry-repository.git` から origin/main を更新して worktree を作成した。
- 範囲：起点のGit管理下の Python・workflow 全642ファイル（Python 587、workflow 55）。scripts/、notability_engine.py、その他Python（docsの再現用1本・toolsの部品1本）を含む。live/ は依頼どおり除外。未追跡の他担当ファイル・build内の他案件・秘密・環境ファイルは読まない。
- 指定語の抽出は205行・99ファイル。下の全件表は**修正前の行番号**。さらに `.date()` / `fromisoformat` / `split('T')` / 比較演算 / API検索範囲 / 試合IDの利用を追って呼出元・消費側を確認した。単純な文字列一致の有無だけでは合否を決めていない。

## 実害と修正

1. `fetch_series_context` のID省略時に残ったUTC前方一致を除去。gamePkがあればそれだけで照合し、無ければofficialDate、さらに無ければscheduleの日付を使う。同じカードが複数ある日は第何戦かを断定しない。
2. `ps_series` のofficialDate欠損時に「UTC日付＋1日」としていた2経路（相手待ち・確定カード）を修正。確定gameDateならJSTの実日付を使い、未定の仮時刻から日付を作らない。公式日付のある従来経路は維持。
3. `next_line` の時刻未定表示でUTC日付を現地日付と呼ばない。公式日付が無いDH第2試合を、別日の第1試合へ結び付けない。
4. `soccer_race` の前日用保存、`soccer_slots_v4` の対象日・帯、`soccer_sanity_material` / `sanity_sources` の点検用対象日をJSTに統一。明示date_jst/dateを優先し、取得時刻しか無い場合だけ変換する。
5. `numbers_material` の鮮度判定、`early_views` の資産動画の日別分類・期間判定、`healthcheck` の公開欠品日数をJSTで比較する。
6. `buffer_daily` のJST配信日キーに対する失敗打切り期限もJSTに統一。日本の午前中に古いerrorが未解決扱いで残る誤りを修正。
7. `mlb_availability` / `game_hook_guard` のアーカイブ保存先は取得日でなく検索対象日を使う。engineの出力・archiveへ `schedule_date` を明示し、UTC翌日に取得した対象版でも同じ保存先を更新する。試合の更新は従来どおりIDも照合。新フィールドのない旧保存形式には従来の取得日を使うが、既存アーカイブや公開済み資料は書き直さない。

共通処理は `scripts/sports_dates.py`。時差のあるISO時刻はJSTへ直し、日付だけの資料はそのまま、時差不明の時刻は推測しない。同種の誤りを23件の固定境界試験に戻し、全run_checksの通常のtest_*.py列挙で毎回検査される。アーカイブ対象日は日本日付への変換を行わず、検索した公式日付を独立に維持する。

## 自分で行った再現・検証

- 外部へ送った実データではなく、依頼のgamePk・時刻を使う固定試合と固定の保存材料で再現。通知の経緯・公式番号5は依頼者の報告であり、今回新たにAPIから事故事実を確認したものではない。
- 米国10/27夜＝UTC10/28の第4戦と、米国10/28夜＝UTC10/29 00:00＝JST10/29 09:00の第5戦を同時に入力。ID省略でも5、ID指定でも5とする。
- 公式日付欠損のJST9:00を10/30とする誤り、同日DHの複数候補、異なる日のDH、時刻未定、UTC10/28 23:30＝JST10/29 08:30の鮮度・表示・点検・前日保存、BufferのJST午前8時の期限境界を固定した。
- 欧州側の問題なし経路にも、football-dataのUTC10/28 20:00＝JST10/29 05:00の当日数、ESPNと異なるoffset表記の同一時刻照合、前日の同カードを除外する試験を追加した。
- 修正前のHEADへ対象ソースだけ一時的に戻して19試験を実行：12失敗・2例外（残り5成功）。その後復元。Buffer追加試験は修正前にSystemExitで再現。アーカイブの追加3試験も修正前に3件すべて失敗し、修正後23試験すべて成功。ログ `build/utc-before-complete.log`、`build/buffer-before.log`、`build/archive-before.log`、`build/utc-after.log`。
- 保護指紋は更新前に対象を確認し、`scripts/fixtures/soccer-slots/v5-protected-source.json` の `soccer_slots_v4.package` だけを `scripts/update_protected_hashes.py --write` で更新。再確認ですべて一致。
- 全検査：2026-10-28 22:41:40〜23:14:37 JST、終了コード0、`===== すべて通過 =====`。構文583ファイル・試験215ファイルすべて成功、未定義名などの重大0・既存軽微53。今回の23境界試験、既存のMLB・PS・欧州・在籍・一言・保存漏れ検査を含む。検査条件の緩和・除外なし。
- 最初のheavy_wait実行はWindowsで子の標準出力が親のリダイレクトへ渡らなかったため中断。出力確認用の最小実行で再現後、子自身がログを開く `build/run_utc_checks.py` に変更し、同じ `heavy_wait.py --minutes 30` 内で全検査を最初から再実行した。ログ `build/run-checks-utcdate-final.log`、状態 `build/run-checks-utcdate-status.json`。
- その途中でアーカイブの追加修正を行ったため、終了途中のログを `build/run-checks-utcdate-before-archive-fix.log` に保全して中断し、最終ソースで全検査をもう一度最初から実行。途中版の結果は最終合格として数えない。
- 検査の後半で新規コマンド起動が一時的に `CreateProcessWithLogonW failed: 1909` で拒否され、読取・書込もできなくなった。起動済みの検査は中断せず、23:16前後に環境が復旧してから状態JSONと最終ログを読み、終了0・全件成功を自分で確認した。サインインや解除操作は行っていない。
- `PYTHONUTF8=1`、Python 3.14。TEMP/TMP/TMPDIRはworktree内の `build/check-tmp`、PYTEST_ADDOPTSのbasetempも同配下。子のstdinをDEVNULLにしてWindowsの無効入力ハンドルによる既存試験の誤停止を避ける。検査の省略や合否条件の変更はしない。
- pytestの一部ではWindowsのbackslashを引数解析が除去し、worktree直下に `UsersissakDesktoppwa-mvpbuildcodextmpwt-utcdatebuildcheck-tmppytest-final/` という一時フォルダもできた。これもworktree内であり、指定のPC外・共有tempへの書込ではない。削除せず保全し、生成物としてcommitには含めない。
- commitまで。push・PR・CI・実通知・外部APIへの書込・公開は行わない。CI/本番での改善効果は未確認。

## 欧州サッカーなど、抽出語の外も追った主要経路

| 箇所 | 何と何を比べるか・判定 |
|---|---|
| `notability_engine.py:2622`（起点） | 問題なし。football-dataに渡すdateFrom/dateToはUTCの日次取得範囲。19時JSTから欧州当夜～日本翌朝の予告用で、JSTの開始日と等しいという照合はしない。試合IDとUTC開始時刻を保持。 |
| `scripts/soccer_selection.py:126,187` | 問題なし。取得材料の日時をJSTに変換して公開対象日と比較し、キックオフは時差付き時刻で窓内判定。 |
| `scripts/soccer_extra_fixtures.py:23,52` | 問題なし。ESPNのevent.dateは時差付き時刻として保持。大会・両クラブ・開始時刻の組で既存と統合し、event IDも保持。 |
| `scripts/soccer_results.py:135,172` | 問題なし。実終了時刻をJSTの夜～翌朝窓と比較。summaryはevent IDと開始の瞬間、クラブ・得点も一致必須。 |
| `scripts/soccer_result_followup.py:26,58` | 問題なし。両クラブ＋時差付き開始時刻の完全一致で予告と結果を結合。次戦は当該結果の終了時刻より後だけ。 |
| `scripts/soccer_now.py:85,196` | 問題なし。日本の夜の対象日はJST実終了時刻から判定。候補選定も開始の瞬間の範囲で行う。 |
| `scripts/soccer_match_interest.py:156` | 問題なし。日本へ変換した開始の月日・曜日・分に両クラブと大会の一致を足し、候補が1件のときだけ付記する。 |
| `scripts/soccer_preview_history.py:15` | 問題なし。generated_atをJSTへ変換して対象日キーを生成。 |
| `scripts/thesportsdb_check.py:39,49` | 問題なし。UTCへ変換した開始日をUTCの日次API検索に使用し、大会・ホーム/アウェーのクラブも完全一致、複数なら採用しない。日本日付との混同なし。 |
| `scripts/next_line.py:144` | 問題なし。残るgameDate[:10]は並べ替え用のキー。現地/JST日付との同一性の根拠にはせず、試合はgamePkで持つ。 |
| `scripts/game_hook_guard.py:107,145,192` | 実害あり・修正。generated_atのUTC日を対象archive名・feedの版の日付に使い、対象日指定や日またぎで別版へ向く。schedule_dateを優先する共通archive_dayへ変更。明示対象日のある新版では取得時刻を試合の対象日として使わない。 |
| `scripts/ps_momentum.py:136` | 問題なし。残るgameDate[:10]は年内の突破試合の時系列キー。日付を出したり米国/JSTの特定日と比べたりしない。 |
| `docs/audit-evidence/20261026/soccer-crowded/reproduce.py` / `tools/portrait-common/portrait_parts.py` | 問題なし。前者は固定した資料の再現、後者は絵の部品操作。UTC試合時刻を現地/JST日付へ文字列照合する経路なし。 |

## 指定語の全件一覧（修正前HEADのファイル:行）

各行の式が比較の入力または加工元。「問題なし」は今回変更しない。比較のない保存・表示・件数制限も区別して残す。

| ファイル:行 | 抽出した式（比較入力・加工元） | 実害・理由と対応 |
|---|---|---|
| `.github/workflows/longform.yml:135` | `at = str(d.get("updated_at") or "")[:10]` | 問題なし。UTC updated_atの採取日とJST今日を注意書きで比較するだけ。警告的な表示に限られ、試合選定・制作・公開を止めず対象を変えない（午前中の表示差は残る）。 |
| `.github/workflows/soccer_daily.yml:99` | `print((d.get('generated_at') or d.get('date') or '')[:10])` | 問題なし。generated_atはUTC、比較相手TODAYもdate -u。UTC同士の取得日比較で、試合の日本日付には流用しない。 |
| `notability_engine.py:2305` | `else g.get("gameDate", "").startswith(date_str)):` | 実害あり・修正。米国の対象日とUTC gameDateの前方一致で前夜を選ぶ。gamePk優先、ID省略時はofficialDate（無ければscheduleのdates[].date）で候補を集め、複数なら番号を決めない。 |
| `notability_engine.py:2450` | `start_time_utc=g.get("gameDate"),` | 問題なし。gameDate/utcDateをstart_time_utcへ保存するだけ。日本向け表示は既存の時差変換で生成し、ここでは日付切出しで試合を選ばない。 |
| `notability_engine.py:2693` | `start_time_utc=m.get("utcDate"),` | 問題なし。gameDate/utcDateをstart_time_utcへ保存するだけ。日本向け表示は既存の時差変換で生成し、ここでは日付切出しで試合を選ばない。 |
| `scripts/audit_saved_outputs.py:92` | `return val[:10]` | 問題なし。ISO時刻は直前にJSTへ変換済み。[:10]へ達するのは日付のみの値などで、UTCのまま日本日付と照合しない。 |
| `scripts/backfill_records.py:154` | `day = when.strftime("%Y-%m-%d")` | 問題なし。whenは公開時刻をJSTへ直したもの。日別キーはJST、APIへ渡すpublish_atは明示的にUTCへ戻す。 |
| `scripts/backfill_records.py:160` | `"publish_at": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),` | 問題なし。whenは公開時刻をJSTへ直したもの。日別キーはJST、APIへ渡すpublish_atは明示的にUTCへ戻す。 |
| `scripts/base_rates.py:60` | `out.append((f.name[:10], g, fs))` | 問題なし。[:10]はYYYY-MM-DDで始まる保存済み試合日ファイル名。UTC時刻ではない。 |
| `scripts/best_of_day.py:132` | `day = args.date or (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")` | 問題なし。JSTのnowから前日を作る。UTCの切出しとの比較ではない。 |
| `scripts/buffer_api.py:75` | `top = tuple(sorted(str(key) for key in result)[:10])` | 問題なし。[:10]は辞書キーの一覧を10件に制限するだけ。日付ではない。 |
| `scripts/buffer_daily.py:748` | `if row.get('state') == 'error' and key[:10] < (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat():` | 実害あり・修正。JSTの配信日キーとUTCの2日前を比較し、日本の午前中は期限切れのerrorを保留し続ける。現在日もJSTに統一。 |
| `scripts/captions.py:209` | `timezone(timedelta(hours=9))).strftime("%Y-%m-%d")` | 問題なし。字幕公開日の作成前にJSTを指定している。 |
| `scripts/competitors.py:248` | `args.stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M")` | 問題なし。UTCの取得実行識別子。現地日付・試合の特定には使わない。 |
| `scripts/dialogue_batch.py:209` | `today = t0.astimezone(JST).strftime("%Y-%m-%d")` | 問題なし。t0をJSTへ変換してから当日キャッシュの日付キーにする。 |
| `scripts/duo.py:32` | `if 'T' in value else date.fromisoformat(value[:10]))` | 問題なし。ISO時刻ならJSTへ変換する分岐が先。[:10]は日付だけの値を読む分岐。 |
| `scripts/early_views.py:89` | `date = (v.get("published_at") or "")[:10]` | 実害あり・修正。UTC published_atの先頭10字をJSTの掲載日キー・集計開始日と比較して誤分類・除外する。JSTへ変換。 |
| `scripts/early_views.py:303` | `stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M")` | 問題なし。UTC実行時刻を履歴の識別子にするだけ。日別の動画分類とは別。 |
| `scripts/generate_asset_video.py:813` | `t = dt.datetime.strptime(str(date_str)[:10], "%Y-%m-%d")` | 問題なし。シーズン開幕日（APIのstartDate、日付のみ）の表示。試合開始のUTC時刻ではない。 |
| `scripts/generate_dialogue.py:767` | `since = back_rec["date"][:10]` | 問題なし。取引の米国公式dateと同じ米国日付の選手成績ログを比較する。もう一方の[:10]は選手一覧を10人に制限。 |
| `scripts/generate_dialogue.py:970` | `for n in find_players(texts)[:10]:` | 問題なし。取引の米国公式dateと同じ米国日付の選手成績ログを比較する。もう一方の[:10]は選手一覧を10人に制限。 |
| `scripts/generate_narration.py:194` | `day = (x.get("date") or "")[:10]` | 問題なし。復帰の公式日付（日付のみ）を読むか、JST指定nowから昨日を作る。gameDate時刻を日付と比較しない。 |
| `scripts/generate_narration.py:766` | `yesterday = (_dt.datetime.now(jst) - _dt.timedelta(days=1)).strftime("%Y-%m-%d")` | 問題なし。復帰の公式日付（日付のみ）を読むか、JST指定nowから昨日を作る。gameDate時刻を日付と比較しない。 |
| `scripts/generate_player_pages.py:134` | `entries.append((m.group(0)[:10], p))` | 問題なし。保存ファイル名からYYYY-MM-DDを読む。UTC時刻ではない。 |
| `scripts/generate_ps_preview.py:133` | `draw_lines(d, r['at'][:10] + 'の投稿・翻訳', 90, y + 160, 30, MUTED)` | 問題なし。記者投稿の原時刻の日付表記。日本日付と比較せず、試合特定・番号・選別には使わない。 |
| `scripts/generate_soccer_page.py:150` | `t = dt.datetime.strptime(str(date_str)[:10], "%Y-%m-%d")` | 問題なし。jp_dayはシーズンのstartDate/endDate（日付のみ）用、生成日はページの更新表示。試合時刻は別のjp_datetimeでUTC→JST変換。 |
| `scripts/generate_soccer_page.py:362` | `generated = _now.strftime("%Y-%m-%d")` | 問題なし。jp_dayはシーズンのstartDate/endDate（日付のみ）用、生成日はページの更新表示。試合時刻は別のjp_datetimeでUTC→JST変換。 |
| `scripts/generate_verdict_short.py:172` | `days.append((f.name[:10], g))` | 問題なし。試合結果の保存ファイル名YYYY-MM-DDを読む。UTC時刻ではない。 |
| `scripts/healthcheck.py:242` | `if when.astimezone(JST).strftime("%Y-%m-%d") != day:` | 問題なし。JSTに変換した公開時刻・JST指定nowと対象版の日付を比較。MLB結果の米国日付には既定の+1日を使い、gamePkを対象日に置換しない。 |
| `scripts/healthcheck.py:336` | `+ timedelta(days=MLB_GAME_KINDS[kind])).strftime("%Y-%m-%d")` | 問題なし。JSTに変換した公開時刻・JST指定nowと対象版の日付を比較。MLB結果の米国日付には既定の+1日を使い、gamePkを対象日に置換しない。 |
| `scripts/healthcheck.py:344` | `.strftime("%Y-%m-%d")):` | 問題なし。JSTに変換した公開時刻・JST指定nowと対象版の日付を比較。MLB結果の米国日付には既定の+1日を使い、gamePkを対象日に置換しない。 |
| `scripts/healthcheck.py:465` | `days = sorted({(v.get("published_at") or "")[:10]` | 実害あり・修正。UTC公開日をJST今日から引き、当日公開を1日前とする。閾値の境界で不要な欠品警告になるためJSTへ変換。 |
| `scripts/healthcheck.py:591` | `else now).strftime("%Y-%m-%d")` | 問題なし。JSTに変換した公開時刻・JST指定nowと対象版の日付を比較。MLB結果の米国日付には既定の+1日を使い、gamePkを対象日に置換しない。 |
| `scripts/healthcheck.py:596` | `day = args.date or (now - timedelta(days=1)).strftime("%Y-%m-%d")` | 問題なし。JSTに変換した公開時刻・JST指定nowと対象版の日付を比較。MLB結果の米国日付には既定の+1日を使い、gamePkを対象日に置換しない。 |
| `scripts/host_split.py:41` | `day = date.fromisoformat(str(day)[:10])` | 問題なし。話者割当の対象日（YYYY-MM-DD）を受ける。UTC試合時刻との比較ではない。 |
| `scripts/local_voices.py:802` | `for c in raw[:10]:` | 問題なし。[:10]はコメントを10件に制限するだけ。 |
| `scripts/missing_kinds.py:61` | `day = day or now.strftime("%Y-%m-%d")` | 問題なし。nowはJST指定。公開の版の日付キー同士を比べる。 |
| `scripts/mlb_availability.py:160` | `day = str(payload.get('generated_at', ''))[:10]` | 実害あり・修正。検索対象日と取得UTC日が異なる再実行で別日のarchiveを選び、対象版の絞込みが反映されない。engineから明示schedule_dateを引き継ぎ、同じgame_idだけ更新。旧形式は従来の取得日で互換読込。 |
| `scripts/mlb_forecast.py:123` | `row=dict(game_id=g['gamePk'],start_time_jst=g.get('gameDate'),jp_players=[])` | 問題なし。公式gameDateを一時的にstart_time_jst欄へ渡すが、expectationでISO時刻として読みJST変換後に対象日と比較し、game_idも維持。 |
| `scripts/mlb_transactions.py:174` | `back = datetime.strptime(x["date"][:10], "%Y-%m-%d").date()` | 問題なし。復帰dateとonはともに米国の公式日付（日付のみ）。UTC開始時刻を切り出していない。 |
| `scripts/mlb_transactions.py:175` | `day = (datetime.strptime(on[:10], "%Y-%m-%d").date() if on` | 問題なし。復帰dateとonはともに米国の公式日付（日付のみ）。UTC開始時刻を切り出していない。 |
| `scripts/morning_recap.py:1012` | `d = datetime.strptime(str(us_date)[:10], "%Y-%m-%d").date()` | 問題なし。us_dateはMLB scheduleの検索対象日（日付のみ）。結果の日本日付を別途+1しておりUTC gameDateは使わない。 |
| `scripts/next_asset.py:320` | `for k in todo[:10]:` | 問題なし。[:10]は候補を10件に制限するだけ。 |
| `scripts/next_line.py:139` | `by[pk] = max(old, g, key=lambda x: x.get("gameDate") or "")` | 問題なし。gameDateはUTC同士で順序付け・開始時刻として利用。_sort_keyの[:10]は欠損時の並べ替え専用で日付照合ではない。officialDateとJST昨日の比較は時刻未定行の保守的な古さ制限（最大1日の幅を許す）で、試合番号や開始日付を推測しない。 |
| `scripts/next_line.py:144` | `return (g.get("officialDate") or (g.get("gameDate") or "")[:10],` | 問題なし。gameDateはUTC同士で順序付け・開始時刻として利用。_sort_keyの[:10]は欠損時の並べ替え専用で日付照合ではない。officialDateとJST昨日の比較は時刻未定行の保守的な古さ制限（最大1日の幅を許す）で、試合番号や開始日付を推測しない。 |
| `scripts/next_line.py:145` | `int(g.get("gameNumber") or 1), g.get("gameDate") or "")` | 問題なし。gameDateはUTC同士で順序付け・開始時刻として利用。_sort_keyの[:10]は欠損時の並べ替え専用で日付照合ではない。officialDateとJST昨日の比較は時刻未定行の保守的な古さ制限（最大1日の幅を許す）で、試合番号や開始日付を推測しない。 |
| `scripts/next_line.py:167` | `iso = g.get("gameDate")` | 問題なし。gameDateはUTC同士で順序付け・開始時刻として利用。_sort_keyの[:10]は欠損時の並べ替え専用で日付照合ではない。officialDateとJST昨日の比較は時刻未定行の保守的な古さ制限（最大1日の幅を許す）で、試合番号や開始日付を推測しない。 |
| `scripts/next_line.py:198` | `and x.get("officialDate") == g.get("officialDate")` | 実害あり・修正。officialDate欠損同士のNone==Noneで、同じカードの別日の第1試合を第2試合の開始基準にする。公式日付の存在を必須にした。 |
| `scripts/next_line.py:225` | `if when is None and (g.get("officialDate") or "") < (now.astimezone(JST) - timedelta(days=1)).strftime("%Y-%m-%d"):` | 問題なし。gameDateはUTC同士で順序付け・開始時刻として利用。_sort_keyの[:10]は欠損時の並べ替え専用で日付照合ではない。officialDateとJST昨日の比較は時刻未定行の保守的な古さ制限（最大1日の幅を許す）で、試合番号や開始日付を推測しない。 |
| `scripts/next_line.py:269` | `od = g.get("officialDate") or (g.get("gameDate") or "")[:10]` | 実害あり・修正。時刻未定かつ公式日付欠損時、UTC日付を現地日付と断定する。欠損時は日時未定とし、UTC仮時刻から現地日付を推測しない。 |
| `scripts/next_line.py:389` | `facts = {"game_pk": g.get("gamePk"), "gameDate": g.get("gameDate"), **wf,` | 問題なし。gameDateはUTC同士で順序付け・開始時刻として利用。_sort_keyの[:10]は欠損時の並べ替え専用で日付照合ではない。officialDateとJST昨日の比較は時刻未定行の保守的な古さ制限（最大1日の幅を許す）で、試合番号や開始日付を推測しない。 |
| `scripts/numbers_material.py:98` | `return date.fromisoformat(str(value)[:10])` | 実害あり・修正。UTC updated_atの先頭10字をJSTの今日と比較し、新しい数字の材料を古い扱いにする。時刻はJST変換、日付だけの資料は維持。 |
| `scripts/pilot_media.py:40` | `date.fromisoformat(asset["captured_at"][:10])` | 問題なし。素材のcaptured_atが日付として読めるかの形式確認だけ。試合や日本日付との比較はない。 |
| `scripts/player_profile.py:440` | `"date_jst": datetime.now(JST).strftime("%Y-%m-%d"),` | 問題なし。datetime.now(JST)で日本日付を生成する。 |
| `scripts/player_screens.py:377` | `d = (bio.get("debut") or "")[:10]` | 問題なし。debutはAPIのデビュー日（日付のみ）。表示専用。 |
| `scripts/post_tiktok.py:276` | `today = time.strftime("%Y-%m-%d")` | 問題なし。投稿処理のOS日付・確認時刻。UTC文字列との日付照合や試合の特定は行わない。 |
| `scripts/post_tiktok.py:378` | `checked_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")` | 問題なし。投稿処理のOS日付・確認時刻。UTC文字列との日付照合や試合の特定は行わない。 |
| `scripts/post_tiktok.py:379` | `data.setdefault(args.kind, {})[time.strftime("%Y-%m-%d")] = {` | 問題なし。投稿処理のOS日付・確認時刻。UTC文字列との日付照合や試合の特定は行わない。 |
| `scripts/preview_daily_v3.py:24` | `edition = date.fromisoformat(d["updated_at"][:10])` | 問題なし。保存した固定見本の版を再現するローカル試作専用。動的な当日判定や公式の試合特定・公開経路ではない。 |
| `scripts/preview_short_content.py:58` | `game = dict(gamePk=topic['game_pk'],gameType=active[0]['round'],gameDate=topic['game_date'],` | 問題なし。固定見本を構築するローカル試作。game_pkを明示し、更新日表示は当日との照合には使わない。 |
| `scripts/preview_short_content.py:91` | `data = dict(players=[], date_jst=material['updated_at'][:10], **{mode if mode=='voices' else 'reporters':material})` | 問題なし。固定見本を構築するローカル試作。game_pkを明示し、更新日表示は当日との照合には使わない。 |
| `scripts/preview_unified_v3.py:83` | `data={'players':[],mode if mode=='voices' else 'reporters':material,'date_jst':material['updated_at'][:10]}` | 問題なし。固定見本のローカル試作。UTC試合を日付で選ぶ処理ではない。 |
| `scripts/probe_jp_highlight.py:178` | `by_day.setdefault(d.strftime("%Y-%m-%d"), []).append(` | 問題なし。調査専用。アップロード日（UTC）を結果対象日と翌日の広い2日分で候補抽出し、球団も確認する。gamePkの断定・公開には使わない。 |
| `scripts/probe_jp_highlight.py:195` | `+ timedelta(days=1)).strftime("%Y-%m-%d"), [])` | 問題なし。調査専用。アップロード日（UTC）を結果対象日と翌日の広い2日分で候補抽出し、球団も確認する。gamePkの断定・公開には使わない。 |
| `scripts/probe_soccer_dates.py:43` | `f"{[m.get('utcDate') for m in ms][:3]}")` | 問題なし。API日付フィルタを比較する調査出力。utcDateを表示するだけで試合を日付照合しない。 |
| `scripts/probe_soccer_dates.py:48` | `print("PL 第6節:", st, [(m.get("utcDate"), m.get("status"))` | 問題なし。API日付フィルタを比較する調査出力。utcDateを表示するだけで試合を日付照合しない。 |
| `scripts/ps_comment_facts.py:116` | `day = (topic.get('game_date') or '')[:10]` | 問題なし。[:10]で初期化後、game_dateがある場合は必ず直下でJSTへ変換し上書き。game_pkも付ける。 |
| `scripts/ps_editorial.py:39` | `day = datetime.fromisoformat(game['officialDate']) + timedelta(days=1)` | 問題なし。未定時刻にはofficialDate、確定時刻にはUTC→JST変換を使い、年度も公式date/seasonを確認。 |
| `scripts/ps_editorial.py:42` | `start = datetime.fromisoformat(game['gameDate'].replace('Z', '+00:00'))` | 問題なし。未定時刻にはofficialDate、確定時刻にはUTC→JST変換を使い、年度も公式date/seasonを確認。 |
| `scripts/ps_editorial.py:71` | `official_year = datetime.fromisoformat(game['officialDate']).year` | 問題なし。未定時刻にはofficialDate、確定時刻にはUTC→JST変換を使い、年度も公式date/seasonを確認。 |
| `scripts/ps_game_now.py:92` | `start = _utc(g.get("gameDate"))` | 問題なし。gameDateを時差付きdatetimeへ変換し現在時刻と比較。gamePkを保持。 |
| `scripts/ps_game_story.py:296` | `start = mlb_headlines.utc(game.get("gameDate"))` | 問題なし。gameDateは開始時刻・UTCの投稿時刻との前後比較。[:19]もUTC同士（MLB/YouTube/BlueskyのZ時刻）で、米国・日本の日付とは比較しない。game_pkを保持。 |
| `scripts/ps_game_story.py:489` | `start = (game.get("gameDate") or "")[:19]` | 問題なし。gameDateは開始時刻・UTCの投稿時刻との前後比較。[:19]もUTC同士（MLB/YouTube/BlueskyのZ時刻）で、米国・日本の日付とは比較しない。game_pkを保持。 |
| `scripts/ps_game_story.py:558` | `"game_date": game.get("gameDate"),` | 問題なし。gameDateは開始時刻・UTCの投稿時刻との前後比較。[:19]もUTC同士（MLB/YouTube/BlueskyのZ時刻）で、米国・日本の日付とは比較しない。game_pkを保持。 |
| `scripts/ps_momentum.py:58` | `return sorted(out, key=lambda g: g.get("gameDate") or "")` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_momentum.py:136` | `out.append(((done[-1].get("gameDate") or "")[:10], desc, me(done[-1]) == "home"))` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_momentum.py:220` | `if not nxt or not nxt.get("gameDate"):` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_momentum.py:222` | `start = datetime.fromisoformat(nxt["gameDate"].replace("Z", "+00:00"))` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_momentum.py:257` | `items.append(("次の試合", f"日本時間{ps_odds.jst_label(nxt['gameDate'])}　"` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_momentum.py:260` | `season = int((nxt.get("gameDate") or "0000")[:4])` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_momentum.py:265` | `after = (s["games"][-1].get("gameDate") or "")[:19]` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_momentum.py:304` | `"next_game": nxt["gameDate"], "streak": n, "road": road,` | 問題なし。gameDateはUTC順の時系列。clinchesの[:10]は年内の最後の突破を並べるキー専用で、現地日付や日本日付と比較・表示しない。投稿のafterもUTC同士。 |
| `scripts/ps_odds.py:83` | `by[key][g["gamePk"]] = (g.get("gameDate") or "", winner, h["team"]["id"])` | 問題なし。gamePkで重複排除しgameDateはUTCの順序付け。次戦の表示・現在時刻比較は時差付きdatetime/JST変換を使う。 |
| `scripts/ps_odds.py:135` | `for g in sorted(series_games, key=lambda g: g.get("gameDate") or ""):` | 問題なし。gamePkで重複排除しgameDateはUTCの順序付け。次戦の表示・現在時刻比較は時差付きdatetime/JST変換を使う。 |
| `scripts/ps_odds.py:159` | `if not nxt or not nxt.get("gameDate"):` | 問題なし。gamePkで重複排除しgameDateはUTCの順序付け。次戦の表示・現在時刻比較は時差付きdatetime/JST変換を使う。 |
| `scripts/ps_odds.py:161` | `start = datetime.fromisoformat(nxt["gameDate"].replace("Z", "+00:00"))` | 問題なし。gamePkで重複排除しgameDateはUTCの順序付け。次戦の表示・現在時刻比較は時差付きdatetime/JST変換を使う。 |
| `scripts/ps_odds.py:173` | `f"日本時間{jst_label(nxt['gameDate'])}　{home}の本拠地")]` | 問題なし。gamePkで重複排除しgameDateはUTCの順序付け。次戦の表示・現在時刻比較は時差付きdatetime/JST変換を使う。 |
| `scripts/ps_odds.py:177` | `for g in sorted(games_now, key=lambda g: g.get("gameDate") or "")` | 問題なし。gamePkで重複排除しgameDateはUTCの順序付け。次戦の表示・現在時刻比較は時差付きdatetime/JST変換を使う。 |
| `scripts/ps_odds.py:220` | `"next_game": nxt["gameDate"],` | 問題なし。gamePkで重複排除しgameDateはUTCの順序付け。次戦の表示・現在時刻比較は時差付きdatetime/JST変換を使う。 |
| `scripts/ps_program.py:203` | `relevant = not g.get('officialDate') or g['officialDate'] in unresolved_days` | 問題なし。確定gameDateはJST変換して対象日と比較。未定はofficialDateの2日幅で確認し、決められない場合は止める。最後の試合はUTC順＋gamePkで選ぶ。 |
| `scripts/ps_program.py:205` | `relevant = datetime.fromisoformat(g['gameDate'].replace('Z', '+00:00')).astimezone(JST).date().isoformat() == target` | 問題なし。確定gameDateはJST変換して対象日と比較。未定はofficialDateの2日幅で確認し、決められない場合は止める。最後の試合はUTC順＋gamePkで選ぶ。 |
| `scripts/ps_program.py:214` | `if not g.get('officialDate') or g['officialDate'] in unresolved_days:` | 問題なし。確定gameDateはJST変換して対象日と比較。未定はofficialDateの2日幅で確認し、決められない場合は止める。最後の試合はUTC順＋gamePkで選ぶ。 |
| `scripts/ps_program.py:217` | `start = datetime.fromisoformat(g['gameDate'].replace('Z', '+00:00')).astimezone(JST)` | 問題なし。確定gameDateはJST変換して対象日と比較。未定はofficialDateの2日幅で確認し、決められない場合は止める。最後の試合はUTC順＋gamePkで選ぶ。 |
| `scripts/ps_program.py:471` | `start = datetime.fromisoformat(game['gameDate'].replace('Z', '+00:00')).astimezone(JST)` | 問題なし。確定gameDateはJST変換して対象日と比較。未定はofficialDateの2日幅で確認し、決められない場合は止める。最後の試合はUTC順＋gamePkで選ぶ。 |
| `scripts/ps_program.py:499` | `game = max(finished, key=lambda g: (g.get('gameDate', ''), g['gamePk']))` | 問題なし。確定gameDateはJST変換して対象日と比較。未定はofficialDateの2日幅で確認し、決められない場合は止める。最後の試合はUTC順＋gamePkで選ぶ。 |
| `scripts/ps_series.py:151` | `w["days"].append((g.get("officialDate")` | 実害あり・修正。officialDate欠損時にUTC gameDate[:10]を現地日付として翌日へ進めるため、JST9:00の試合をさらに翌日と表示する。確定した開始時刻はJSTで日付を出し、時刻未定は空欄。相手待ち・確定カードの両方を修正。 |
| `scripts/ps_series.py:152` | `or (g.get("gameDate") or "")[:10],` | 実害あり・修正。officialDate欠損時にUTC gameDate[:10]を現地日付として翌日へ進めるため、JST9:00の試合をさらに翌日と表示する。確定した開始時刻はJSTで日付を出し、時刻未定は空欄。相手待ち・確定カードの両方を修正。 |
| `scripts/ps_series.py:187` | `s["upcoming"].append((g.get("officialDate")` | 実害あり・修正。officialDate欠損時にUTC gameDate[:10]を現地日付として翌日へ進めるため、JST9:00の試合をさらに翌日と表示する。確定した開始時刻はJSTで日付を出し、時刻未定は空欄。相手待ち・確定カードの両方を修正。 |
| `scripts/ps_series.py:188` | `or (g.get("gameDate") or "")[:10],` | 実害あり・修正。officialDate欠損時にUTC gameDate[:10]を現地日付として翌日へ進めるため、JST9:00の試合をさらに翌日と表示する。確定した開始時刻はJSTで日付を出し、時刻未定は空欄。相手待ち・確定カードの両方を修正。 |
| `scripts/ps_spotlight.py:184` | `when = f"日本時間{ps_odds.jst_label(nxt['gameDate'])}　{rnd}第{nxt.get('seriesGameNumber')}戦"` | 問題なし。gameDateのUTC同士の前後比較か、時差付きdatetimeでの時刻比較。表示はJSTへ変換。 |
| `scripts/ps_spotlight.py:204` | `"game_date": game.get("gameDate"), "won": won,` | 問題なし。gameDateのUTC同士の前後比較か、時差付きdatetimeでの時刻比較。表示はJSTへ変換。 |
| `scripts/ps_spotlight.py:246` | `start = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))` | 問題なし。gameDateのUTC同士の前後比較か、時差付きdatetimeでの時刻比較。表示はJSTへ変換。 |
| `scripts/ps_spotlight.py:261` | `and x["gameDate"] > g["gameDate"]` | 問題なし。gameDateのUTC同士の前後比較か、時差付きdatetimeでの時刻比較。表示はJSTへ変換。 |
| `scripts/ps_story.py:60` | `return sorted(out, key=lambda g: g.get("gameDate") or "")` | 問題なし。gameDateのUTC時系列の並べ替え。日付切出しで試合を選ばない。 |
| `scripts/ps_unified_v3.py:25` | `date = str(card['date'])[:10]` | 問題なし。card.dateは検証済みの番組のJST対象日。開始日がある項目は日付を別途読む。UTC開始時刻ではない。 |
| `scripts/reddit_reaction.py:96` | `return dict(program='reddit_reaction',program_label='ファンの反応',can_make=True,label=material['updated_at'][:10],` | 問題なし。保存材料の更新日を版の表示へ使うだけ。UTCと日本日付を比較した試合特定・当日判定ではない。 |
| `scripts/retry_thumbnails.py:46` | `f"&created=%3E%3D{(start - timedelta(days=1)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",` | 問題なし。検索範囲をUTC時刻へ明示変換してAPIへ渡す。 |
| `scripts/review_board.py:113` | `day = day or (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")` | 問題なし。JST nowから対象前日を生成。UTC文字列と比較しない。 |
| `scripts/sanity_refresh.py:209` | `date_jst=datetime.fromisoformat(g['gameDate'].replace('Z', '+00:00')).astimezone(` | 問題なし。gameDateをJSTへ変換してdate_jstを作りgamePkとともに保存。 |
| `scripts/sanity_sources.py:63` | `stamp = data.get('date_jst') or data.get('date') or (data.get('updated_at') or data.get('generated_at') or '')[:10]` | 実害あり・修正。UTC取得日と原稿のJST対象日を比較し、当日の保存材料を点検から外す。明示対象日優先、時刻しか無ければJSTに変換。 |
| `scripts/sanity_sources.py:168` | `data.get('date') or (data.get('generated_at') or data.get('updated_at') or '')[:10])` | 実害あり・修正。UTC取得日をsanity_date_jstとして保存し、別日の材料と照合する入口になる。共通のmaterial_dayへ。 |
| `scripts/series_check.py:18` | `day = dt.date.fromisoformat(g["officialDate"])` | 問題なし。まずgamePkで対象試合を取得。officialDateは検索範囲用、後続試合は球団・試合種別・UTC時刻・別gamePkで照合。 |
| `scripts/series_check.py:26` | `if (pair == ids and x["gamePk"] != game_pk and x["gameDate"] > g["gameDate"]` | 問題なし。まずgamePkで対象試合を取得。officialDateは検索範囲用、後続試合は球団・試合種別・UTC時刻・別gamePkで照合。 |
| `scripts/soccer_jp_week.py:164` | `ident = match.get('id') or (match.get('utcDate'), teams)` | 問題なし。utcDateは_jst_date/_day_jpで日本日付へ変換してtodayや週末範囲と比較。ID＋組合せも保持。rows[:10]は表示件数。 |
| `scripts/soccer_jp_week.py:169` | `for m in sorted(ms, key=lambda x: x.get("utcDate") or ""):` | 問題なし。utcDateは_jst_date/_day_jpで日本日付へ変換してtodayや週末範囲と比較。ID＋組合せも保持。rows[:10]は表示件数。 |
| `scripts/soccer_jp_week.py:190` | `"day": _day_jp(m.get("utcDate")),` | 問題なし。utcDateは_jst_date/_day_jpで日本日付へ変換してtodayや週末範囲と比較。ID＋組合せも保持。rows[:10]は表示件数。 |
| `scripts/soccer_jp_week.py:191` | `"utc": m.get("utcDate") or "",` | 問題なし。utcDateは_jst_date/_day_jpで日本日付へ変換してtodayや週末範囲と比較。ID＋組合せも保持。rows[:10]は表示件数。 |
| `scripts/soccer_jp_week.py:320` | `if _jst_date(m.get("utcDate")) == today.isoformat():` | 問題なし。utcDateは_jst_date/_day_jpで日本日付へ変換してtodayや週末範囲と比較。ID＋組合せも保持。rows[:10]は表示件数。 |
| `scripts/soccer_jp_week.py:345` | `and first <= _jst_date(m.get('utcDate')) <= last]` | 問題なし。utcDateは_jst_date/_day_jpで日本日付へ変換してtodayや週末範囲と比較。ID＋組合せも保持。rows[:10]は表示件数。 |
| `scripts/soccer_jp_week.py:424` | `for r in rows[:10]:` | 問題なし。utcDateは_jst_date/_day_jpで日本日付へ変換してtodayや週末範囲と比較。ID＋組合せも保持。rows[:10]は表示件数。 |
| `scripts/soccer_preview.py:181` | `end = dt.datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()` | 問題なし。シーズンendは日付のみで終了判定。utcDateは未加工の開始時刻として保存し、利用側で時差変換。 |
| `scripts/soccer_preview.py:201` | `"utc": m.get("utcDate"),` | 問題なし。シーズンendは日付のみで終了判定。utcDateは未加工の開始時刻として保存し、利用側で時差変換。 |
| `scripts/soccer_race.py:176` | `end = date.fromisoformat(str(season.get("end"))[:10])` | 問題なし。season.endは時刻を持たないシーズン終了日。UTC試合時刻ではない。 |
| `scripts/soccer_race.py:676` | `stamp = str(preview.get("generated_at") or "")[:10]` | 実害あり・修正。UTC generated_at[:10]とJST今日の比較で、午前中の当日順位資料を前日用に保存できない。JST変換して比較。 |
| `scripts/soccer_result_context.py:70` | `if not g.get('utcDate'):continue` | 問題なし。UTC開始時刻をそのまま保存。後続試合は球団と開始時刻で絞り、表示はJST変換。 |
| `scripts/soccer_result_context.py:71` | `upcoming.append(dict(home=g['homeTeam']['name'],away=g['awayTeam']['name'],start_utc=g['utcDate'],source=url,competition=code))` | 問題なし。UTC開始時刻をそのまま保存。後続試合は球団と開始時刻で絞り、表示はJST変換。 |
| `scripts/soccer_results.py:123` | `if abs((utc(match['utcDate'])-utc(game['start_utc'])).total_seconds())>600:continue` | 問題なし。football-dataとESPNの双方のUTC時刻をdatetimeにして差600秒以内＋ホーム/アウェーの同一クラブを照合。日本日付切出しで結合しない。 |
| `scripts/soccer_sanity_material.py:24` | `(data.get('generated_at') or data.get('updated_at') or '')[:10],` | 実害あり・修正。UTC取得日をdate_jstに入れ、原稿の日本日付との照合で外れる。共通のmaterial_dayへ。 |
| `scripts/soccer_slots_v4.py:149` | `day=(data.get('date_jst') or data.get('date') or data.get('generated_at','')[:10])` | 実害あり・修正。UTC取得日を番組の日本日付・帯の日付とし、日付付き点検や表示が前日になる。共通のmaterial_dayへ。 |
| `scripts/soccer_slots_v4.py:152` | `_d=__import__('datetime').date.fromisoformat(day[:10]);day=f"{_d.month}月{_d.day}日（{'月火水木金土日'[_d.weekday()]}）"` | 問題なし。ここで読むdayは対象日（日付のみ）で、画面用の月日へ整形する。UTCの時刻を再度切り出さない。 |
| `scripts/soccer_week_publish.py:23` | `return at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')` | 問題なし。公開日時をJSTで決め、API送信用はUTCへ変換する。 |
| `scripts/social_audit.py:156` | `keys = (','.join(sorted(str(k) for k in data)[:10])` | 問題なし。[:10]は辞書キーの表示を10件に制限するだけ。 |
| `scripts/status.py:182` | `print("== コレスポ %s ==" % now.strftime("%Y-%m-%d %H:%M JST"))` | 問題なし。nowはJSTの状態表示。試合のUTC日付との比較はない。 |
| `scripts/test_content_v3.py:72` | `data={'players':[],mode if mode=='voices' else 'reporters':material,'date_jst':material['updated_at'][:10]}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_correct_video.py:34` | `return {"dates": [{"games": [{"gamePk": 3, "gameType": "D", "officialDate": "2026-10-06",` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_correct_video.py:35` | `"gameDate": "2026-10-07T01:30:00Z",` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_correct_video.py:38` | `{"gamePk": 3, "gameDate": "2026-10-07T01:30:00Z", "status": {"abstractGameState": "Final"},` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_correct_video.py:40` | `{"gamePk": 4, "gameDate": "2026-10-08T02:00:00Z", "status": {"abstractGameState": "Final"},` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_correct_video.py:42` | `{"gamePk": 9, "gameDate": "2026-10-08T05:00:00Z", "status": {"abstractGameState": "Final"},` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_next_line.py:417` | `g['gameDate']=(now+timedelta(days=7)).isoformat();g['officialDate']='2026-10-14'` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_next_line.py:419` | `g['gameDate']=(now+timedelta(days=7,seconds=1)).isoformat()` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_editorial.py:26` | `'officialDate': '2026-09-29', 'gameDate': '2026-09-30T00:00:00Z',` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_editorial.py:30` | `'officialDate': '2026-10-03', 'gameDate': '2026-10-03T07:33:00Z',` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_game_now.py:64` | `"gameDate": (NOW - timedelta(hours=2)).isoformat()}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_game_now.py:66` | `"gameDate": (NOW + timedelta(hours=3)).isoformat()}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_game_now.py:68` | `"gameDate": (NOW + timedelta(hours=20)).isoformat()}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_game_now.py:70` | `"gameDate": (NOW - timedelta(hours=4)).isoformat()}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_game_now.py:72` | `"gameDate": NOW.isoformat()}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_game_story.py:63` | `GAME = {"gamePk": 849829, "gameType": "D", "gameDate": "2026-10-03T17:00:00Z",` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_momentum.py:20` | `g = {"gamePk": pk, "gameDate": date, "gameType": game_type,` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_odds.py:17` | `return {"gamePk": pk, "gameDate": date, "status": {"abstractGameState": state},` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:29` | `games.append(dict(gamePk=1000+index*10+n,gameType='F',season='2026',officialDate=start.date().isoformat(),` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:30` | `gameDate=start.isoformat(),seriesGameNumber=n,gamesInSeries=3,` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:33` | `games.append(dict(gamePk=2000+index,gameType='D',season='2026',officialDate='2026-10-03',` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:34` | `gameDate='2026-10-03T18:00:00+00:00',seriesGameNumber=1,gamesInSeries=5,` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:166` | `game['officialDate']='2026-10-15';game['gameDate']='2026-10-15T18:00:00Z'` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:193` | `missing_day=copy.deepcopy(games);missing_day[0].pop('officialDate')` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:198` | `games[0]['officialDate']='2026-10-15'` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:201` | `games[0]['officialDate']='2026-09-29'` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:267` | `first['gameDate']='2026-09-29T23:30:00+00:00'` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:291` | `elif broken=='stale':case['schedule']['dates'][0]['games'][0]['officialDate']='2025-09-29'` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_program.py:341` | `officialDate='2026-10-31',gameDate='2026-10-31T18:00:00+00:00',` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_series.py:36` | `"seriesGameNumber": n, "gameDate": day + "T22:00:00Z",` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_series.py:151` | `g["officialDate"] = off` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_series.py:152` | `g["gameDate"] = off + "T07:33:00Z"      # 時刻未定の仮の時刻` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_spotlight.py:33` | `GAME = {"gamePk": 849819, "gameType": "D", "seriesGameNumber": 3, "gameDate": "2026-10-06T22:00:00Z"}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ps_spotlight.py:51` | `{"gameDate": "2026-10-07T22:00:00Z", "seriesGameNumber": 4})` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_sanity_gate.py:215` | `officialDate='2026-10-24', status=dict(abstractGameState='Final'), teams=dict(` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_sanity_gate.py:219` | `nxt.update(gamePk=2, officialDate='2026-10-25', seriesGameNumber=2,` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_sanity_gate.py:227` | `score['gameDate'] = '2026-10-25T01:00:00Z'` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_series_context.py:15` | `return {'gamePk': pk, 'gameDate': date, 'seriesGameNumber': number, 'gamesInSeries': 7,` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_short_content.py:173` | `game = dict(gamePk=12,gameType='W',seriesGameNumber=1,gameDate='2026-10-26',` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_daily.py:78` | `day=data['generated_at'][:10]` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_daily.py:87` | `_,plan=next(preview.plans());data=plan['data'];narr=plan['narration'];day=data['generated_at'][:10]` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_expansion.py:212` | `matches = [dict(utcDate=stamp, status=status) for stamp, status in (` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_jp_week.py:41` | `"matchday": md, "utcDate": utc}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_jp_week.py:150` | `w.today_count({"PL": [{"utcDate": "2026-09-22T16:00:00Z"},` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_jp_week.py:151` | `{"utcDate": "2026-09-22T14:00:00Z"}]},` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_length.py:44` | `day = plan['data']['generated_at'][:10]` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_results.py:93` | `fd={'FL1':[{'status':'FINISHED','utcDate':g['start_utc'],'homeTeam':{'name':'OGC Nice'},'awayTeam':{'name':'Lille OSC'},'score':{'fullTime':g['score']}}]}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_soccer_spread.py:71` | `days[t.astimezone(JST).strftime("%Y-%m-%d")].append(` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_topic_hub.py:79` | `'officialDate':'2026-10-14','gameDate':'2026-10-15T00:00:00Z'}]}]})` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_v3_rules.py:52` | `data={'players':[],mode if mode=='voices' else 'reporters':material,'date_jst':material['updated_at'][:10]}` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_verify_published.py:65` | `day = (now + timedelta(days=day_offset)).strftime("%Y-%m-%d")` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_verify_published.py:92` | `.strftime("%Y-%m-%d"):` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_verify_published.py:96` | `.strftime("%Y-%m-%d"): {"video_id": "x"}}}), 1)` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_verify_published.py:98` | `run({"daily": {NOW.strftime("%Y-%m-%d"):` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/test_ws_topics.py:42` | `return {"gamePk": pk, "gameDate": date, "seriesGameNumber": n,` | 問題なし。固定入力・期待値・試験用の時刻操作。運用の照合や公開には使わず、既存試験は変更しない。今回の境界試験を別に追加。 |
| `scripts/token_log.py:81` | `day = datetime.now(JST).strftime("%Y-%m-%d")` | 問題なし。JST nowから利用量の日別キー・30日前のJST日付を作る。 |
| `scripts/token_log.py:128` | `day = datetime.now(JST).strftime("%Y-%m-%d")` | 問題なし。JST nowから利用量の日別キー・30日前のJST日付を作る。 |
| `scripts/token_log.py:144` | `cut = (datetime.now(JST) - timedelta(days=30)).strftime("%Y-%m-%d")` | 問題なし。JST nowから利用量の日別キー・30日前のJST日付を作る。 |
| `scripts/topic_hub.py:200` | `item['game_date'] = g.get('officialDate'); item['scheduled_game_at'] = utc(g.get('gameDate'))` | 問題なし。game_dateはofficialDate、scheduled_game_atはgameDateを時刻として保持。試合の特定はgame_pk。 |
| `scripts/upload_youtube.py:779` | `return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` | 問題なし。公開予定日時は時差付きで作り、APIへはUTCに変換する。 |
| `scripts/venue_weather.py:148` | `want = local.strftime("%Y-%m-%dT%H:00")` | 問題なし。開始UTCへAPIの球場現地offsetを足した時刻と、同じ球場現地時刻の気象配列を比較。日本日付との混在はない。 |
| `scripts/verify_published.py:54` | `day = now.strftime("%Y-%m-%d")` | 問題なし。nowはJSTで日次記録のJST版キーと比較。 |
| `scripts/verify_published.py:116` | `prev = (now - timedelta(days=1)).strftime("%Y-%m-%d")` | 問題なし。nowはJSTで日次記録のJST版キーと比較。 |
| `scripts/weekly_stats.py:48` | `entries.append((f.name[:10], f))` | 問題なし。YYYY-MM-DDの保存ファイル名で期間を選ぶ。UTC開始時刻ではない。 |
| `scripts/ws_topics.py:133` | `g.get("gameDate") or "",` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
| `scripts/ws_topics.py:400` | `"""APIの gameDate（UTC）を、日本時間の「10月24日（土）9時」に。未定は「未定」。"""` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
| `scripts/ws_topics.py:416` | `iso = g.get("gameDate")` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
| `scripts/ws_topics.py:499` | `first_label = jst_label(first.get("gameDate"),` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
| `scripts/ws_topics.py:528` | `label = jst_label(g.get("gameDate"),` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
| `scripts/ws_topics.py:564` | `return sorted(unique.values(), key=lambda g: (g.get("officialDate") or` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
| `scripts/ws_topics.py:565` | `g.get("gameDate") or "",` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
| `scripts/ws_topics.py:566` | `g.get("gameDate") or "", g["gamePk"]))` | 問題なし。gamePkで一意化し公式日付・UTC時刻で並べる。表示はjst_label、未定時刻を確定時刻として使わない。 |
