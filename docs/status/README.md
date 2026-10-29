# 毎朝の状況とアナリティクス

`morning_report.yml` が毎朝9:30 JSTとmainの手動実行で、実行要約とこの場所の日付ファイルに同じ報告を保存する。Actionsの混雑による遅延はあり得る。変更するのは報告だけで、公開設定・変数・動画・コメントには触れない。

- 前日・当日はJST。台帳の予約時刻を優先し、未保存なら登録時刻と明記する。2台帳は動画IDで重複を除く。
- YouTubeへの照合は1動画1回のoEmbed。Data APIの割当を使わない。200は視聴可能という意味で、限定公開との区別はできない。非200・通信失敗を非公開の確定とは扱わない。未公開の題・ID・コメント本文・投稿者名は報告へ渡さない。
- Actionsは前日JSTに開始したmainの実行、ジョブ単位で数える。skippedは除外し、成功した実行内の失敗段も調べる。失敗したジョブだけログを読む。最初のerror行の定型終了コードは掲載し、それ以外の本文は秘密・未発表情報保護のため伏せ、段の名前と実行リンクを残す。取得できない項目は未収録とする。
- 日別Analyticsの暦日はPacific Time。直前7日と前7日を表示し、欠測のある合計・増減は未収録にする。再生が連続14日そろう最後の期間も補足する。旧sourcesの重複期間は足さず、再生だけに使い、旧日付のタイムゾーン不明も明記する。
- 日別の視聴時間（分）・登録獲得・解除は既存healthcheckの取得に1照会だけ追加。少なくとも直近28日を毎回再取得し、後日計上された値を埋め直す。日別は120日、従来の動画別スナップショットは90回を保持する。取得失敗やAPI応答にない日を0にせず、既存の観測値を保持する。
- 9:30の報告は保存済みAnalyticsを使う。既存の10時healthcheckより前なので当朝の取得は翌朝の報告に反映される。追加のAnalytics取得やLLM利用はしない。
- 種類の強弱は最新の動画別照会期間における収録動画の再生中央値。週の増減とは区別し、上位200本・公開台帳publicとの結合・観測時間の違いを明記する。
- A/Bは実験名別の有効ラベル付き台帳本数。予約前・保留を除き、未ラベルをAに含めない。実公開本数・変数の状態とは区別する。

手元の見本: `python scripts/morning_report.py --offline --out build_reports/morning-report-example.md`。外部照合を行わず未確認と記す。固定試験: `python scripts/test_morning_report.py`。

API仕様の根拠: [YouTube Analyticsのチャンネル日別レポート](https://developers.google.com/youtube/analytics/channel_reports)、[日付の定義](https://developers.google.com/youtube/analytics/dimensions#day)、[GitHub実行一覧](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository)。
