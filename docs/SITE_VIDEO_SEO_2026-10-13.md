# サイトの動画導線と訪問数の計測準備（2026-10-13）

- 基点 origin/main `11035100`。隔離clone `build/codex/tmp/site-video-seo-20261013`、枝 `hiro/site-video-seo-20261013`。commitまで、push/PR/公開はClaude。共有コピー・HANDOFFは変更しない。
- 日付ページは台帳の同日キーにある全枠の動画を掲載。選手ページは台帳の題・説明・明示した選手情報に本人の名前がある動画を掲載し、球団所属だけでは紐づけない。同じページの同じIDは重複させない。
- 公開判定は既存 `video_visibility.is_public` に統一。保留・非公開・限定公開・削除・失敗・未来の予約・不正な予約日時を除外。台帳外のYouTube手動変更の実確認は今回の範囲外。
- `youtube-nocookie.com` の埋め込みは `loading=lazy`、大きさを指定して表示時のずれを抑える。YouTubeで見るリンクも併記。
- VideoObjectのnameは台帳のtitle、uploadDateは台帳のpublished_at（アップロード記録）、embedUrlはvideo_idから確定できる埋め込みURL。description/thumbnailUrl/contentUrlは台帳に値がある場合だけ出す。YouTube視聴ページのurlを動画ファイルのcontentUrlに流用しない。
- 基点の台帳370本にはdescription/thumbnailUrl/contentUrlがない。推測で補っていないため、現状のJSON-LDはGoogle動画検索の必須情報が揃っていない。検索掲載・流入増加は未確認。次の改善候補はYouTubeの取得済みメタ情報を台帳へ正確に保存すること。参考: [Google VideoObject](https://developers.google.com/search/docs/appearance/structured-data/video)。
- canonical・題・説明は既存の個別値を保持し、OGとの一致を検査。既存sitemap生成は日付ページと生成済みの全選手ページを含む。両サイトworkflowは選手→日付/sitemapの順。robots.txtのSitemap行も既存処理で生成する。

## GoatCounterを本人が登録したあと

1. [GoatCounter](https://www.goatcounter.com/)で登録し、サイトURLを `https://collespo.com` にする。希望のコード名を選ぶ（例 `collespo`、使用済みなら別名）。
2. 登録後のURLが `https://コード名.goatcounter.com` なら、`data/site_analytics.json` の `goatcounter` にコード名だけを書く。URLや秘密鍵は書かない。空文字は無効。
3. Claudeが設定を取り込みサイトを再生成・公開する。両サイトworkflowの最後で全HTMLへ非同期の解析スクリプトを追加する。空に戻して再生成すると追加分を除去する。不正設定時はサイトの公開を止め、日次動画とは分ける。
4. 公開サイトを開いて管理画面に訪問数が届くか確認する。広告ブロックで計測が止まる場合がある。個別閲覧の収集は既定の無効のままにする。

Cookieを使わない解析を導入する場合の説明をprivacy.htmlに追加。IP等を一時的に処理する点も説明し、サイト全体がCookieを使わないとは表現していない。参考: [導入](https://www.goatcounter.com/help/start) / [情報の扱い](https://www.goatcounter.com/help/privacy)。

## 手元の確認

- 固定資料の関連検査29件（SEO 8、archive 8、player 4、visibility 9）が通過。
- 保存先 `build/codex/tmp/site-seo-preview/`。実台帳で日付79件＋一覧、選手14件＋一覧を生成。例 `archive/2026-10-12.html` / `players/shohei-ohtani.html`。privacy.htmlも保存。
- 全95生成HTMLのcanonicalをsitemapと照合。日付370件・選手306件のVideoObjectと埋め込みが対応。GoatCounter読み込み0件。詳細 `verification.json`。
- Nodeがこの環境に見つからず、既存 `test_web_*.cjs` は未実施（今回の変更はPython生成とprivacy本文）。
- `scripts/run_checks.py` は終了コード0・「すべて通過」。結果は `run_checks.log` に保存。CI・実YouTube公開状態・公開サイト・実GoatCounter受信は未検証。
