# Cloud-01 B. PSの話題の回に足せる情報源の洗い出し

作成: 2026-10-03 クラウドのClaude（指示書 `docs/Cloud/Cloud-01.md` の B）。

## 読む順番

1. **まず「おすすめの順番」**（いちばん下）: どれから足すかの提案と理由
2. **次に「情報源の表」**: 1行が1つの情報源
3. 気になる行があれば「各情報源の補足」と「確かめ方の記録」

## 前提

- いまの話題の回（`scripts/ps_story.py`）が使っているのは2つだけ:
  1. MLB公式の成績表（`https://statsapi.mlb.com/api/v1` の `schedule` と `game/{gamePk}/boxscore`）
  2. 番記者のBlueskyの投稿（`data/ps_quotes.json`。`scripts/ps_quotes.py` が `data/local_reporters.json` から10日ぶん貯めたもの）
- 例に使う対戦: **カブス対パドレスのワイルドカードシリーズ**（米国 9/29〜9/30）。Gitの材料 `data/postseason.json` では `F:112-135`、パドレスが **2勝0敗**（`played: 2`, `winner: 135`）。日本人選手はパドレスの松井裕樹、カブスの今永昇太・鈴木誠也（同じファイルの `players`）。
- **このクラウドの環境からは外部のサイトに直接つながらなかった**（`statsapi.mlb.com`・`www.mlb.com`・`reddit.com`・`baseballsavant.mlb.com`・`espn.com`・`youtube.com`・`news.google.com`・`public.api.bsky.app` はすべて通信を止められた。2026-10-03 13:57 UTC ごろ）。そのため「確認できたか」は次の3段階で書く:
  - **確認（Git）**: Gitにある材料・コードで確かめた
  - **題だけ確認（検索）**: Web検索の結果に、その記事・ページの題とURLが出た（本文は開けていない）
  - **未確認**: 確かめられなかった。URLの形だけ示す

## 情報源の表

| 情報源 | 何が取れるか | 取り方（API・RSS・URLの形） | 使ってよいかの注意（規約・引用の範囲） | 確認できたか |
|---|---|---|---|---|
| ① MLB公式YouTubeのハイライトのコメント | その試合を見た直後のファンの声（原文・いいね数・返信） | YouTube Data API v3 `commentThreads`（`part=snippet,replies`, `videoId=…`, `order=relevance`。キーが要る）。動画IDは `scripts/mlb_buzz.py` がMLB公式チャンネル（`UCoLrcjPV5PbUrUyXq5mjc_A`）から取っている。仕組みは `scripts/local_voices.py` に既にある | YouTube API サービスの規約に従う（キーとクォータ。`commentThreads` は1回1ユニット）。コメントは投稿者の著作物なので、**短く・出典（MLB公式ハイライトのコメント欄）と「翻訳」を明示**。今の `local_voices.py` も原文の併記と出典を必須にしている | 確認（Git）: 形は下の補足。カブス対パドレスの回のコメントは**未確認**（`data/local_voices.json` は今はフィリーズ対ブレーブスの4件だけで、Gitの履歴も浅く9/30以前が見えない） |
| ② MLB.com の記事 | シリーズの総括・試合の記事の見出しと本文（番記者の書いたもの） | ニュースのRSS `https://www.mlb.com/feeds/news/rss.xml`（`scripts/local_buzz.py` が既に読んでいる）。記事のURLの形は `https://www.mlb.com/news/{slug}`（球団版は `https://www.mlb.com/{team}/news/{slug}`） | MLB Advanced Media の著作物。**見出しの要約と出典で使い、本文の長い引用はしない**（今の `local_reporters.py` も「見出しだけを使い、本文は取りに行かない」方針）。細かい規約は未確認 | 題だけ確認（検索）: 「Padres get revenge with commanding sweep of Cubs in Wild Card Series」`https://www.mlb.com/news/padres-win-nl-wild-card-series-2026`、「Postseason FAQ: What's next for Padres?」`…/news/padres-2026-postseason-faq`、「cubs padres 2026 nlwc position by position breakdown」`…/news/cubs-padres-2026-nlwc-position-by-position-breakdown` |
| ③ 各球団の公式発表 | シリーズの出場選手登録（ロースター）、故障者の入れ替え、監督・GMの談話を含む記事 | 球団のニュース `https://www.mlb.com/padres/news`・`https://www.mlb.com/cubs/news`。数字で取れるのは公式API `https://statsapi.mlb.com/api/v1/teams/{teamId}/roster?rosterType=active&date=YYYY-MM-DD`（パドレス135・カブス112）。球団のSNS（X・Bluesky）もあるが、ここでは扱っていない | 球団サイトは②と同じ（MLB Advanced Media）。APIの応答には「個人・非商用・大量でない利用」に限る旨の著作権表示が付く（**推測**: 内容は記憶による。応答の `copyright` の欄で要確認）。今のコレスポも同じAPIを本番で使っている | 題だけ確認（検索）: 地元局の記事「san diego padres announce roster for national league wild card series against chicago cubs」`https://www.10news.com/sports/padres/san-diego-padres-announce-roster-for-national-league-wild-card-series-against-chicago-cubs`（URLに年が無く、2025年の同じ対戦の記事か判別できない。球団の発表そのものは未確認）。2026年と分かるのはMLB.com「Padres lock up No. 4 seed, will host Cubs in Wild Card Series」`https://www.mlb.com/astros/news/padres-secure-home-field-in-nl-wild-card-series`（本拠で開催＝2026年の形） |
| ④ Reddit r/baseball の試合後スレッド | 「Post Game Thread」の題（スコアの要約）と、そのスレッドのコメント | 板の新着RSS `https://www.reddit.com/r/baseball/.rss`（`local_buzz.py`・`local_voices.py` が既に読む）。スレッドのコメントは `https://www.reddit.com/r/baseball/comments/{id}/.rss`（**推測**: RSSの形は未確認）。検索は `https://www.reddit.com/r/baseball/search.rss?q=…&restrict_sr=1&sort=new`（未確認） | Redditのデータ利用の規約は2023年に厳しくなり、商用の利用は別の契約が要る（**推測**: 収益化したチャンネルが当たるかは不明）。コメントは投稿者の著作物。**レート制限が厳しい**（`local_buzz.py` の注記: 球団別の板は3つ中2つが429で取れなかった） | 未確認: 検索でも 2026年のカブス対パドレスの「Post Game Thread」は見つからなかった |
| ⑤ Baseball Savant のシリーズ単位の数字 | 1球ずつの計測（打球速度・角度・飛距離・球速・回転数）。シリーズの全試合ぶんを足せば「シリーズで最も強い打球」「平均球速」などが言える | `https://baseballsavant.mlb.com/statcast_search/csv?…`（`scripts/statcast.py` が既に日付指定で読んでいる。キー不要）。ポストシーズンに絞る指定は `hfGT=F%7C`（ワイルドカード。**推測**: 引数名は未確認）、球団は `team=SD` 等、期間は `game_date_gt` / `game_date_lt`。試合ごとは `https://baseballsavant.mlb.com/gamefeed?gamePk={gamePk}`（未確認） | MLB Advanced Media のデータ。②③と同じ扱い。**数字なので引用の問題は小さい**。出典「MLB公式の計測（Statcast）」 | 未確認（通信できず）。検索ではSavantの検索画面に「Wild Card」などポストシーズンの絞り込みがあることだけ出た |
| ⑥ ESPN 等の見出し | 試合の見出し・総括記事の見出し（ESPN・AP系の配信・地元紙） | ESPNのRSS `https://www.espn.com/espn/rss/mlb/news`（`local_buzz.py` が既に読む）。試合のページは `https://www.espn.com/mlb/game/_/gameId/{id}`。まとめて引くならGoogleニュースのRSS `https://news.google.com/rss/search?q={選手名や球団名} when:1d&hl=en-US&gl=US&ceid=US:en`（`local_reporters.py` が選手名で使っている） | ESPNのRSSは個人・非商用の利用に限る旨の規約がある（**推測**: 要確認）。Googleニュースは各社の見出しの集まりで、規約の扱いは**不明**。**見出しだけを訳して出典を付ける**今の方針なら引用の範囲は小さい | 題だけ確認（検索）: Yahoo Sports「Padres beat Cubs 4-1, sweep series, advance to NLDS against Brewers」`https://sports.yahoo.com/articles/padres-beat-cubs-4-1-050129867.html`、theScore「Padres to play Brewers in NLDS after eliminating Cubs」`https://www.thescore.com/mlb/news/3612976/padres-to-play-brewers-in-nlds-after-eliminating-cubs`。ESPNの試合ページは2026年の回か判別できず未確認 |
| ⑦ （参考）MLB公式の試合経過 | 1打席ごとの結果・得点の場面（先制・逆転など） | `https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live`（`scripts/clutch.py` が同じAPIで場面を取っている） | ③と同じ | 確認（Git）: 同じAPIを `clutch.py`・`ps_focus.py` が使っている。この対戦の中身は未確認 |

### カブス対パドレス（9/29〜9/30）で何が取れそうか（1行ずつ）

- ① YouTubeのコメント: MLB公式の「CUBS vs. PADRES: Wild Card Full Game 1 Highlights (September 29) | 2026 MLB Season」のような動画のコメント（**推測**: 題の形は `data/mlb_buzz.json` にある「PHILLIES vs. BRAVES: Wild Card Full Game 3 Highlights (October 1) | 2026 MLB Season」から）。松井裕樹・鈴木誠也の名前が出たコメントは `jp_players` で拾える。
- ② MLB.com: シリーズ総括の記事（上の題）。「なぜカブスの打線が止まったか」を記者がどう書いたかの見出し。
- ③ 球団の公式発表: シリーズの出場選手登録（パドレスは松井裕樹を含むか、カブスは今永昇太・鈴木誠也）。APIの `roster` なら日付つきで確かめられる。
- ④ Reddit: 2試合ぶんの「Post Game Thread」の題とコメント（未確認）。
- ⑤ Savant: 2試合ぶんの1球ずつの計測。鈴木誠也の打球の速さ、松井裕樹の球速などをシリーズ単位で言える。
- ⑥ 見出し: 「Padres beat Cubs 4-1, sweep series…」のような各社の見出し（上の題は検索で確認）。
- ⑦ 試合経過: 2試合の得点の場面（ps_story の「打線の沈黙」を、何回にどう点が入ったかで補える）。

> **数字について**: Web検索の要約には「第1戦8-0・第2戦4-1、2試合で12-1」と出たが、本文を開けていないので**未確認**。Gitの材料（`data/postseason.json`）で確かなのは「パドレスが2勝0敗」まで。

## 各情報源の補足

### ① `data/local_voices.json` の形（Gitで確認、2026-10-03 06:02 UTC 更新の版）

```
{
  "updated_at": "…",
  "source": "MLB公式ハイライトのコメント",
  "source_url": "https://www.youtube.com/@MLB",
  "voices": [                       ← コメント1件が1要素
    {
      "at": "…",                    コメントの日時
      "video_published_at": "…",    動画の公開日時
      "title": "…",                 コメントの原文（名前は title だが中身はコメント本文）
      "url": "https://www.youtube.com/watch?v=…",
      "likes": 342, "replies": 54,  いいね数・返信数
      "reply_texts": ["…", …],      返信の原文（上位3件）
      "author": "@…",
      "source": "MLB公式ハイライトのコメント",
      "matchup": "PHILLIES vs. BRAVES",  どの試合の動画か
      "is_thread": true,
      "ja": "…",                    日本語訳
      "tone": "称賛",               口調の分類
      "reply_ja": [{"ja": "…", "tone": "…", "original": "…"}],
      "jp_players": []              名前が出た日本人選手
    }
  ],
  "jp_praise": []                   日本人選手への声（17:00の「現地の声」の画面で使う）
}
```

- 取れなかった日は r/baseball のRSSの題に落ちる（`local_voices.py` の `build`）。
- PSの話題の回に足すなら、**`matchup` でシリーズの対戦に絞り、そのシリーズの全試合の動画を読む**形になる（今は直近30時間の最も見られた動画が中心）。

### 引っかかりやすい点: 2025年にも同じ対戦がある

**2025年のワイルドカードシリーズもカブス対パドレス**（そのときはカブスが2勝1敗、リグレー・フィールド）。今回のWeb検索でも、2025年の記事（鈴木誠也の本塁打、カブスの3-1の勝ちなど）が2026年の記事と混ざって出た。②④⑥のように**題や見出しで探す情報源は、日付（2026-09-29以降）か gamePk で必ず絞る**必要がある。①⑤⑦は gamePk・動画ID・日付で引くので混ざりにくい。

## 確かめ方の記録

- 通信: `curl` と WebFetch で上の各URLを試し、すべて「通信を止められた」（環境の制限）。
- 検索: Web検索（2026-10-03）で「Padres sweep Cubs Wild Card Series」「Padres press release Wild Card Series roster Cubs 2026」「reddit r/baseball Post Game Thread Padres Cubs」「baseballsavant postseason」などを引き、題とURLを書き写した。本文は開いていない。
- Git: `scripts/ps_story.py`・`local_voices.py`・`local_buzz.py`・`local_reporters.py`・`statcast.py`・`mlb_buzz.py`、`data/postseason.json`・`local_voices.json`・`local_reporters.json`・`ps_quotes.json`・`mlb_buzz.json`。

## おすすめの順番（3つ）

1. **⑤ Baseball Savant のシリーズ単位の数字**
   - 足す価値: ps_story は「公式の数字で何が起きたかを言う」回なので、いちばん合う。「打線の沈黙」に「シリーズで95マイル以上の打球が○本」のような裏づけを足せる。日本人選手の「どんな1本・どんな1球だったか」も言える。
   - 手間: 小さい。`statcast.py` がキー無しで同じCSVを既に読んでいるので、期間と試合の種類を変えるだけ（引数名の確認は要る）。
   - 規約: 数字なので引用の問題が小さい。今の本番と同じ扱い。
2. **② MLB.com の記事の見出し（シリーズ総括）**
   - 足す価値: 公式の記者が「何が起きたか」をどう要約したかを、見出し1行と出典で添えられる。番記者のBluesky（今の引用）より事実寄りで、カタカナにできない名前の問題も少ない。
   - 手間: 小さい。ニュースのRSSを `local_buzz.py` が既に読んでいる。シリーズの両球団名と日付で絞るだけ。2025年の記事が混ざらないよう日付で切る。
   - 規約: 見出しだけ・出典つきなら今の `local_reporters.py` と同じ線。
3. **① MLB公式YouTubeのハイライトのコメント（シリーズの全試合ぶん）**
   - 足す価値: 本人の言う「ハイライトのコメントを拾って」にそのまま当たる。数字では出ない温度が伝わる。
   - 手間: 中くらい。`local_voices.py` と `mlb_buzz.py` の仕組みはあるが、「直近30時間の動画」ではなく「そのシリーズの試合の動画」を探す処理と、翻訳（API代）が増える。決着の翌日に古い試合の動画を探す必要がある。
   - 規約: コメントは投稿者のもの。今と同じく原文併記・翻訳の明示・出典で、短く。

見送り: ④ Reddit は、レート制限で取れない日がある（`local_buzz.py` の実測）うえ、データ利用の規約が商用に厳しい（推測）ので後回し。⑥ は②と重なり、規約が不明なものが多い。③ は「誰が登録されたか」の確認には便利だが、話題の中身は増えにくい。
