# 公開リポジトリの整理（2026-10-14）

サイトとリポジトリの公開は継続する。履歴は書き換えない。

## ページの連絡先

contact.html を sitemap に追加。about/services の個人メール表示・mailto を contact.html の案内へ統一。訂正・ご意見はYouTube、画像制作は既存のココナラへ。新しい窓口が決まったら contact.html のみ差し替える。
Podcast の配信情報は scripts/generate_podcast.py の EMAIL を維持した。公開RSSの連絡先にも残るので、専用アドレスの決定後に別途更新する。

## 管理対象から外す一覧

git rm --cached のみで手元のファイルは保持。以下は運営者のやり取り・作業履歴・判断・分析を含むため、公開コードの保守資料から外した。

- `docs/ARCHIVE_VISIBILITY_2026-10-12.md`
- `docs/ARTICLE_SOURCES_2026-10-12.md`
- `docs/BACKLOG.md`
- `docs/BACKSTAGE_GUARD_2026-10-12.md`
- `docs/CLAUDE_HANDOFF_2026-09-06.md`
- `docs/CLAUDE_HANDOFF_2026-09-07.md`
- `docs/CLAUDE_HANDOFF_2026-09-09.md`
- `docs/CLUB_DISPLAY_NAMES_2026-10-12.md`
- `docs/CONTENT_V3_2026-10-07.md`
- `docs/Cloud/Cloud-01.md`
- `docs/Cloud/Cloud-02.md`
- `docs/Cloud/Cloud-03.md`
- `docs/Cloud/Cloud-04.md`
- `docs/Cloud/Cloud-05.md`
- `docs/Cloud/Cloud-06.md`
- `docs/Cloud/Cloud-07.md`
- `docs/Cloud/Cloud-08.md`
- `docs/Cloud/Cloud-09.md`
- `docs/Cloud/Cloud-10.md`
- `docs/Cloud/Cloud-11.md`
- `docs/Cloud/Cloud-12.md`
- `docs/Cloud/Cloud-TEMPLATE.md`
- `docs/Cloud/Opus-01.md`
- `docs/Cloud/Opus-02.md`
- `docs/Cloud/Opus-03.md`
- `docs/Cloud/Opus-04.md`
- `docs/Cloud/Opus-05.md`
- `docs/Cloud/Opus-06.md`
- `docs/Cloud/Opus-07.md`
- `docs/Cloud/Opus-08.md`
- `docs/Cloud/Opus-09.md`
- `docs/Cloud/Opus-10.md`
- `docs/Cloud/Opus-11.md`
- `docs/Cloud/Opus-12.md`
- `docs/Cloud/Opus-13.md`
- `docs/Cloud/Opus-14.md`
- `docs/Cloud/Opus-15.md`
- `docs/Cloud/Opus-16.md`
- `docs/Cloud/Opus-17.md`
- `docs/Cloud/Opus-18.md`
- `docs/Cloud/README.md`
- `docs/Cloud/out/01_morning_v2.html`
- `docs/Cloud/out/01_ps_sources.md`
- `docs/Cloud/out/02_morning_decline.md`
- `docs/Cloud/out/03_glossary.md`
- `docs/Cloud/out/04_morning_v2b.html`
- `docs/Cloud/out/05_ps_bracket.html`
- `docs/Cloud/out/06_motion_demo.html`
- `docs/Cloud/out/06_motion_spec.md`
- `docs/Cloud/out/07_season_structure.md`
- `docs/Cloud/out/08_soccer_formats.html`
- `docs/Cloud/out/08_soccer_formats.md`
- `docs/Cloud/作業記録.md`
- `docs/DECISIONS.md`
- `docs/DESIGN_UNIFY_2026-10-07.md`
- `docs/DUO_IMPLEMENTATION_2026-10-09.md`
- `docs/EARLY_METRICS_2026-10-12.md`
- `docs/EVENING_FIX2_2026-10-12.md`
- `docs/EVENING_FIX_2026-10-12.md`
- `docs/EXPR_FAN2_2026-10-13.md`
- `docs/FACT_GUARDS_2026-10-12.md`
- `docs/GAME_STORY_LOOK_V4_2026-10-08.md`
- `docs/HANDOFF.md`
- `docs/HANDOFF_ARCHIVE_2026-09-14.md`
- `docs/HASHTAGS_2026-09-12.md`
- `docs/LIPSYNC_2026-10-13.md`
- `docs/MAIN_HANDOFF_BEFORE_REBASE_2026-10-12.md`
- `docs/MAIN_REFRESH_2026-10-12.md`
- `docs/MLB_BADGE_2026-10-12.md`
- `docs/MLB_BADGE_PREVIEWS2_2026-10-12.md`
- `docs/MLB_FORECAST_CHECK_2026-10-13.md`
- `docs/MLB_PINSTRIPE_2026-10-12.md`
- `docs/MLB_PINSTRIPE_CI_2026-10-12.md`
- `docs/NAME_ACCENT_2026-10-12.md`
- `docs/NAME_ACCENT_FLAT_2026-10-13.md`
- `docs/NAME_PHRASE_2026-10-12.md`
- `docs/NAME_READINGS_2026-10-12.md`
- `docs/NIGHT_MERGED_2026-10-12.md`
- `docs/NIGHT_WORK_2026-10-12.md`
- `docs/OPUS_INTAKE_2026-10-09.md`
- `docs/PILOT_DIALOGUE_2026-09-13.md`
- `docs/PLAN.md`
- `docs/PLAYER_PREVIEW_REPAIR_2026-09-12.md`
- `docs/PLAYLIST_SYNC_2026-10-12.md`
- `docs/PODCAST_HISTORY_2026-10-12.md`
- `docs/PS_AI_MATERIAL_2026-10-12.md`
- `docs/PS_ROLLOUT_2026-09-28.md`
- `docs/PS_TEMPLATE_UPDATE_2026-09-28.md`
- `docs/REVENUE_OPERATIONS.md`
- `docs/SHORT_LOOK_V4_2026-10-08.md`
- `docs/SHORT_V4_POLISH_2026-10-08.md`
- `docs/SITE_VIDEO_SEO_2026-10-13.md`
- `docs/SOCCER_COMPETITION_SOURCES_2026-10-12.md`
- `docs/SOCCER_PREVIEW_RESULTS_2026-10-12.md`
- `docs/SOCCER_RANK_REPAIR_2026-09-13.md`
- `docs/SOCCER_RESULTS_2026-10-10.md`
- `docs/SOCCER_RESULTS_SCHEDULE_2026-10-12.md`
- `docs/SOCCER_SELECTION_2026-10-12.md`
- `docs/SOCCER_SELECTION_COUNTS_2026-10-12.json`
- `docs/SOCCER_SELECTION_COUNTS_2026-10-12.md`
- `docs/SOCCER_V4_SLOTS_2026-10-10.md`
- `docs/SOCCER_V5_2026-10-11.md`
- `docs/SOCCER_V5_FEEDBACK_2026-10-12.md`
- `docs/SOCCER_V5_FINISH_2026-10-12.md`
- `docs/SOCCER_VOICES_2026-10-10.md`
- `docs/STALE_SHORTS_2026-10-10.md`
- `docs/STANDINGS_CTR_2026-10-13.md`
- `docs/TASK33_RESUME_2026-10-12.md`
- `docs/TEAM_NAMES_JA_2026-10-07.md`
- `docs/verification/mlb-badge-previews2-2026-10-12.json`
- `docs/verification/mlb-pinstripe-2026-10-12.json`
- `docs/verification/name-accent-2026-10-12.json`
- `docs/verification/name-accent-sources-2026-10-12.json`
- `docs/verification/name-phrase-2026-10-12.json`
- `docs/verification/name-query-summary-2026-10-12.json`
- `docs/verification/name-readings-saved-before-2026-10-12.json`
- `docs/verification/name-readings-saved-final-2026-10-12.json`
- `docs/verification/saved_dialogues_2026-10-12.json`
- `docs/verification/saved_output_after_2026-10-12.json`
- `docs/verification/saved_output_annotations_2026-10-12.json`
- `docs/verification/saved_output_before_2026-10-12.json`
- `docs/verification/soccer-v5-finish-2026-10-12.json`
- `docs/verification/task33-soccer-preview-results-2026-10-12.json`
- `docs/verification/task33-soccer-results-schedule-2026-10-12.json`
- `docs/verification/task33-soccer-selection-2026-10-12.json`
- `docs/weekly/2026-10-12.md`

同種の将来の手渡しメモ・日付付き運営資料・監査証拠は .gitignore で除外。公開技術資料を追加する場合は内容を確認し明示的な例外を設ける。

## 依存先の扱い

- 保存原稿を使う検査は、個人連絡先を含まない固定原稿を scripts/fixtures/saved-output/dialogues.json に同梱して参照先を変更。
- scripts/status.py は手元の HANDOFF を任意で読む。存在しない場合は空一覧を返すため、CI/公開処理には必須でない。
- SCHEDULE.md は時刻照合検査、team_cards_sample.json は描画例で使うので公開の技術資料として保持。
- 週次分析は公開Gitへのcommitを止め、Actions成果物（30日保存）へ。サイトの生成・配信には影響しない。
- ソース内の経緯コメントに旧文書への言及があっても、実行時に読まないものは残す。

過去のコミットや外部の写しに残る情報は、この変更では消えない。

## 手元の検証

run_checks.pyは「すべて通過」。管理対象だけをcheckout-indexで新しい環境へ書き出し、126件が不在でも保存原稿検査7件と整合性検査121件が通過。全126件は元の隔離cloneの手元に保持した。週次レポート8件、制作サービス7件も通過。web全体のメール/個人アドレス検索で該当なし。
Nodeがこの実行環境で利用できず、既存のtest_web_*.cjsは未実行。CI・実配信・公開サイトの反映は未確認。

取り込み時は共有コピーの同名ファイルと未commit変更を先に退避すること。Gitの管理からの除外は、この枝の手元ファイルを保持する操作である。別コピーへcommitを取り込む際のGitの削除動作まで、手元保持を保証するものではない。共有コピーへの直接のcheckout/resetはしない。
