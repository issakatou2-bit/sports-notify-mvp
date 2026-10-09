# 欧州サッカーの日本人選手の結果（㉔・2026-10-10）

## 材料と判定

- 基点は `d0cd3f4`（ローカル `build/wt-0907` の `emma/soccer-results`）。隔離 clone は `build/codex/tmp/soccer-results-20261010`、ブランチは `hiro/soccer-results-20261010`。
- `scripts/soccer_results.py` は日本時間の前日に**終了した**5大リーグの試合を対象にする。ESPN の scoreboard を UTC の前日・当日それぞれ単日指定で取得し、summary の試合終了イベントの実時刻で日付を確定する。開始時刻から終了を推測しない。
- 姓＋名の頭文字で `notability_engine.JP_PLAYERS_SOCCER` と当日の両クラブの登録名簿を照合する。移籍で名簿の所属が古い場合も、実際の ESPN team ID に結びつける。照合できない選手は「出場なし」と推測しない。両クラブの先発11人を確認できない試合は除外する。
- 先発・途中出場・ベンチで出場なし、得点・アシスト・警告・退場を個人成績から保存する。不明な数字は `null` のまま。順位は得点＞アシスト＞先発＞途中。出場なしは一覧だけ。全員が出場なしの日は動画を作らない。
- scoreboard と summary の試合ID・開始時刻・クラブ・スコアを照合する。football-data.org を取得できた場合は既存 `soccer_jp_week.fetch_matches` でスコアを照合し、不一致の試合を除外する。取得不可／該当試合なしは別の状態として記録する。
- オウンゴールの ESPN `detail.team.id` は得点を受けるクラブであり、選手所属とは違う場合がある。日本人選手の得点として数えない。得点経過がスコアに足りない場合は「未取得」と明記し、補わない。

## 画面・声・公開の入口

- `soccer_results_render.py` が原稿と描画を共通で作る。表紙の最初から筆頭選手と本人の数字を出し、筆頭の試合結果／得点経過、全日本人選手の一覧、共通 `review_render_v3.outro` に続ける。他の試合も材料・説明欄に残る。
- `soccer_v4_cards.py` と `data/club_colors.json` は Opus の部品。読み込み場所だけ変更した。色がないクラブは中立色。クラブ名の同じ行・左隣に同じクラブの札を置く。
- 既存の `r3.presenter`、`characters.py` の既定絵と吹き出し、字幕・声の設定をそのまま使う。実 WAV と原稿・話者・札を照合し、動画のフレーム丸め後と実 MP4 の両方で40秒を超える場合は止める。声を速めて帳尻を合わせない。
- `.github/workflows/soccer_results.yml` は `workflow_dispatch` のみ、`publish=false` が既定。公開するときは未来の予約時刻が必須。種別 `soccer_results` と対象の日本時間日付で既存の重複防止・投稿記録を使う。定時実行・公開・変数切り替えは未実施。
- `data/soccer_results.json` は保存材料の **2026-09-21（日本時間）** の例であり、今日の結果ではない。ワークフローは毎回対象日の材料を作り直す。

## 検査と試作

- `test_soccer_results.py` は `run_checks.py` の自動収集で毎回動く。別プロセスで v3/v4 を検査し、v3 では新しい描画を接続しない。実保存材料の得点・アシスト・途中出場・出場なし、OG、照合不可、移籍、終了日、スコア不一致、40秒上限、全画面の安全域・クラブ札・材料にない数字を検査する。
- fixture はエマ保存の `build/codex/tmp/soccer-material-20261010/espn_scoreboards.json` と `espn_summaries_jp.json` から必要な項目だけを抜き出し、元の SHA256 を `scripts/fixtures/soccer-results/provenance.json` に記録した。元のファイルは変更していない。
- 声つき試作：`build/codex/tmp/soccer-results-preview/collespo_soccer_results.mp4`。全画面：同じ場所の `all-screens.png`。2026-09-21の上田綺世1得点、ニース2–1リールほか、計4選手の材料。実 MP4 **16.33秒**、既存設定の WAV 合計16.27秒。全画面の配置・札・数字を検査し、一覧画像も目視した。
- 再現：この clone で `python -X utf8 scripts/preview_soccer_results.py --out ../soccer-results-preview`。本PCでは指定の Python314 のフルパスを使用する。保存材料を使うため API キーは不要。生成物の `verification.json` に尺と画面の検査記録を残す。

## 未検証・次の一手

ライブ取得、実際の football-data.org 照合、GitHub Actions・予約投稿は未実施。football-data の不一致除外は固定材料で検証した。共通締めを指定どおりそのまま呼んでいるため、締めの紹介文には既存の「毎日のMLB」表記が残る（この枠の表紙・原稿・説明欄はサッカー）。最終全体検査の結果は HANDOFF と試作フォルダの確認記録に残す。エマが取り込み、本人が声つき試作を確認してから公開時刻を決める。
