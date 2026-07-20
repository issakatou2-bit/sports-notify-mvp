# 注目試合ナビ PWA — セットアップ手順

## 動作確認済み / 未確認の範囲(正直に)

- ✅ `scripts/generate_vapid_keys.py` — このまま実行して鍵が生成できることを確認済み
- ✅ `notability_engine.py --mock` — JSON生成のロジックは動作確認済み
- ✅ `notability_engine.py --source all`(APIキー未設定時) — MLB/サッカーのどちらか、または両方が失敗・未設定でもクラッシュせず、警告を出して空JSONまたは部分的な結果を出力することを確認済み
- ⚠️ MLB Stats API・football-data.orgへの実際のリクエスト(認証成功時の正常系) — この開発環境はネットワークが許可リスト制のため、実際に統計データが取れることまでは検証できていません。エンドポイント・パラメータ名は実在確認済みですが、フィールド名の細部は初回実行時に要確認
- ⚠️ Web Push送信・GitHub Pagesへのデプロイ・ブラウザでの購読フロー — 同様の理由で未検証。標準的な構成なので動くはずだが、実際にGitHubリポジトリ上で試して調整が必要
- ✅ ワークフロー — `PUSH_SUBSCRIPTION`が未設定でも通知送信ステップはスキップされ、Pagesのデプロイまでは完了する設計に変更済み(初回セットアップの詰まりを回避)

## 手順

### 1. GitHubリポジトリを作る
このフォルダ一式を新しいリポジトリにpushする。

### 2. GitHub Pagesを有効にする
リポジトリの Settings > Pages > Source を **GitHub Actions** に設定する。

### 3. VAPID鍵を生成する
```
python3 scripts/generate_vapid_keys.py
```
出力された `VAPID_PUBLIC_KEY` と `VAPID_PRIVATE_KEY` をメモしておく。

### 4. 公開鍵をindex.htmlに埋め込む
`web/index.html` 内の

```js
const VAPID_PUBLIC_KEY = 'REPLACE_WITH_YOUR_VAPID_PUBLIC_KEY';
```

を、手順3で生成した `VAPID_PUBLIC_KEY` に差し替える。

### 5. GitHub Secretsを登録する
リポジトリの Settings > Secrets and variables > Actions で以下を登録:

| Secret名 | 値 | 無くても動くか |
|---|---|---|
| `VAPID_PRIVATE_KEY` | 手順3で生成した秘密鍵 | 通知送信ステップが自動スキップされる |
| `VAPID_SUBJECT` | `mailto:自分のメールアドレス` | 同上 |
| `PUSH_SUBSCRIPTION` | 手順6で取得する購読情報 | 未設定ならPagesのデプロイまでは正常に完了する(通知送信だけスキップ) |
| `FOOTBALL_DATA_API_KEY` | football-data.orgで取得したキー | 未設定ならサッカー分だけスキップし、MLBのみで続行する |

**つまり、最初は何も登録しなくてもワークフローは(mockデータで)最後まで通ります。** 1つずつ揃えながら本番データに寄せていけばよい。

### 6. サイトにアクセスして購読する
1. GitHub Actionsを一度手動実行(workflow_dispatch)してPagesを公開する
2. 公開されたURLに **iPhoneのSafari** でアクセス
3. 共有ボタン → 「ホーム画面に追加」
4. ホーム画面のアイコンからPWAとして起動(Safariの中で開くと通知が動かないので注意)
5. 「通知を有効にする」ボタンをタップ → 通知を許可
6. 画面に表示されたJSONをコピー
7. GitHub Secretsの `PUSH_SUBSCRIPTION` をこの値で更新する

### 7. テスト送信する
Actionsタブから `Daily notable games` ワークフローを手動実行(Run workflow)。
19時を待たずにその場でテストできる。

### 8. 本番の19時通知を待つ
`cron: '0 10 * * *'` によりUTC 10:00(JST 19:00)に自動実行される。
GitHub Actionsのcronは指定時刻ちょうどに実行される保証がなく、数分〜十数分遅れることがある。

## 今後やるべきこと

- `notability_engine.py` の `fetch_mlb_schedule_today()` を完成させ、`--mock` ではなく実データで動かす
- football-data.org 等サッカー側のデータ取得を追加する
- 購読が失効した場合(410 Gone)の再購読フローを用意する
- 十分安定して動くようになったら、ネイティブアプリ化を検討する
