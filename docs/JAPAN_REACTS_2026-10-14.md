# 日本の反応を英語字幕で届ける（D）

本人の10/13夜方針を適用。枝 `hiro/japan-reacts-20261014`。元の基点9de21222から、#160の `022e39fb` をfast-forwardで取り込み、この字幕処理を再利用。**エマの統合は#160を先に**。共有コピー/HANDOFFへの変更なし。push/PR/公開・変数変更なし。

## 採るもの・採らないもの

対象はMLBとプレミアリーグ。日本語の発言だからといって発言者の国籍を推測しない。選んだ数件を「日本全体の総意」と説明しない。短い引用と解説・翻訳を結び、媒体/記者/公式と元のリンクを示す。映像・画像・記事本文を転載しない。

| 取得元 | 取得方法・出典 | 実装と今回の状態 |
|---|---|---|
| SPOTV NOW日本向け公式ハイライトのコメント（MLB） | YouTube Data API。運営会社の[公式案内](https://prtimes.jp/main/html/rd/p/000000026.000075946.html)にhandle `SPOTVNOW_JP`・ID `UCJ-l-sMQFHogSy8KXRyMIRA`を確認 | uploads→ハイライト→commentThreads。handle/ID・動画のチャンネルを照合、短い日本語の声3件まで。一般コメントの名前は保存/表示しない。元動画＋コメントへのリンク。今回はAPIキー未設定で実取得なし |
| DAZN・ABEMA・U-NEXT（プレミア） | 公式チャンネルのData API。DAZNの[運営会社によるリンク](https://dazngroup.com/press-room/0424/)、[ABEMA公式](https://www.youtube.com/channel/UCVjvtweGM-Kak2D53AvfNOA)、[U-NEXTの認証済み投稿例](https://www.youtube.com/watch?v=NfE37gixgyQ) | ハイライトかつプレミアの表記を要する。ABEMAのIDは確認済み。DAZN/U-NEXTのhandle解決と実コメント取得は本番キーで未検証。取れない候補を他のチャンネルと取り違えて補わない |
| 日本のスポーツ紙の見出し | 既存local_reportersと同じGoogleニュースRSSの見出し解析を日本語検索で使用。スポニチ/スポーツ報知/サンスポ/デイリースポーツの媒体名を限定 | 短い見出しのみ、媒体とリンクつき。長い見出しは無理に切らず除外。今回はWebで元記事を開けたスポニチの本物の見出しを保存試作へ。日刊スポーツの直接RSSは[個人/営利等の制限](https://www.nikkansports.com/rss/)があるため、このRSSを使わない。新聞全部を禁止した以前の設計は撤回 |
| 日本語の記者/公式アカウント | local_reporters.fetch_author（Bluesky公開API）を再利用。名前・公式サイト等で確認できた名簿だけ | reporter/officialの役割と確認元を要する。本人の投稿のみ、リポスト・返信を除外。日本語の確認済みBluesky名簿は今回まだ未登録。取得元全体を禁止する設計ではなく、名簿が揃えば同じ経路で取れる |
| Yahoo!ニュースコメント・5ちゃんねる | 使わない（本人方針） | 入力のsource kindでも拒否 |
| 一般の人のSNS投稿を名前つきで引用 | 使わない（本人方針） | 記者/公式以外のSNS登録を拒否。YouTubeの短い声は名前を取らず匿名で紹介 |

APIで取れることを再利用権の包括許諾と説明しない。本人が定めた既存の「ファンコメント/現地報道/番記者」枠と同じ、少数の引用・出典・訳・解説の扱い。APIデータは[YouTubeの保存規則](https://developers.google.com/youtube/terms/developer-policies)に従い30日以内の更新/削除、Artifactの保持は7日。定期の自動公開へはまだ接続しない。

## 音声と英語字幕

**今回はVOICEVOX:四国めたん（話者2）の日本語音声。英語音声は作らない。** v4の同梱書体・札・下隅キャラ・吹き出し・進行線を再利用し、画面の本文/吹き出しを英語にする。ずんだもん/きりたんは本人が後で声を選ぶ場合の候補、今回の実装はめたんに限定。

#160の `english_captions.translate` を本番英訳に、`captions.build_cues/render_srt` を日本語の実測音声に合わせたja/en SRTへ再利用。訳はllm_modelsのtranslate役＋楽屋の見張り・正式名/数字検査。さらに別のreview役で意味・話者・悪口を照合し、原文/訳のhashを検査。保存試作の英訳はCodexが元記事と照らして書いたもので、実LLM呼出しが成功したとは扱わない。

英語の題/説明に、訳した選択例であり全員の意見ではないこと、出典の日付、元のリンク、日本語音声と英語字幕、VOICEVOXクレジットを記す。SRTの時間は音声だけでなく、動画の最低表示時間とフレーム丸めを含む実際の画面長へ合わせる。

## 本物の保存試作

[2026-05-14のスポニチ記事](https://www.sponichi.co.jp/baseball/news/2026/05/14/articles/20260514s00001007251000c.html)を10/13にWebで確認。大谷の7回無失点・8奪三振・今季3勝目を同紙が伝え、見出しに本人の「防御率はまだ気にする段階ではない」という言葉を置いたことを紹介。発言者は大谷本人であり「ファンの声」「新聞社の採点」と混同しない。解説はコレスポの読み取りとして記録。数字は同紙に帰属させ、独立したMLBスコア照合はしていない。

**架空の材料ではないが、5月の記事を使った保存試作であり10/13の速報ではない。** 画面/題/説明に `2026-05-14 / SAVED SOURCE` を表示。本文や写真は保存せず短い見出し抜粋・出典と制作台本だけを同梱。

```powershell
& C:/Users/issak/AppData/Local/Programs/Python/Python314/python.exe scripts/test_japan_reacts.py
& C:/Users/issak/AppData/Local/Programs/Python/Python314/python.exe scripts/japan_reacts.py --saved scripts/fixtures/japan-reacts/sponichi-saved.json --out C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/japan-reacts-preview
```

`preview.mp4`・全画面/一覧・日本語原稿/英語字幕・`ja.srt/en.srt`・題/説明・音声manifest・verification.jsonを保存。同梱NotoSansJPをWindows/Linux共通で使用。新規7検査と#160の11検査は外部通信なしで通過。日本語の読点で複数の字幕候補になる場合も、同じ画面の完全な英訳を1区間に結び、日英の開始/終了を一致させる検査を追加。英語は毎秒3語を目安に最低表示時間を取る（音声は速めない）。全体検査の一括実行は容量停止で中断したため成功とは報告せず、構造検査と関連検査を分けて記録する。CI・聴感は未確認。CIはエマのpush後。

## 動かす条件と未検証

最終試作は23.70秒・全5画面。音声21.312秒、VOICEVOX:四国めたん。実動画の尺・音声トラック・全編の読み出し・配置を検査し、全5画面を目視確認。関連3スクリプト（新規7検査/#160の11検査/楽屋検査）成功。構造16項目のうち初回の依存記載1件はworkflow修正後に再検査0件。記録は試作フォルダのrelated-tests.log/structural-checks.log/dependency-final.log。

`COLLESPO_JAPAN_REACTS=on`で手動制作を有効化。`JAPAN_REACTS_PUBLISH`は既定false。今回のworkflowには投稿処理を接続しない。保存材料の試作は `--saved` で指定できる。

実取得は `--sport MLB --player 大谷翔平` または `--sport PL --player 三笘薫`。本環境のYOUTUBE_API_KEY/ANTHROPIC_API_KEYは未設定、隔離CLIから外部HTTPS接続も拒否。実際のコメント/API翻訳、新聞RSSの実行結果、日本語記者の名簿、当日制作は未検証。取得に失敗した理由はfetch-report.jsonへ残し、声を作り物で埋めない。

本人に決めてほしいこと：めたんの日本語＋英語字幕の見本がこの形でよいか。きりたんへ替える場合は108と `VOICEVOX:東北きりたん` を使う別の見比べへ。取得元の包括禁止や英語音声の選択を再度求めることはしない。
