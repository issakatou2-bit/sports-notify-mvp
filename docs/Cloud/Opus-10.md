# Opus-10: サイト（collespo.com）に「ポストシーズンの勝ち上がり」ページを足す生成コードの下書き

作成: 2026-10-06 コレスポのPCのClaude（エマ）。

> **コレスポのコードとデータ**: このリポジトリの `collespo/src/` にある写し（説明は `collespo/src/README.md`）。指示書の中の「`scripts/…`」「`data/…`」「`docs/…`」は `collespo/src/` の下のパスとして読む。`collespo/src/` は書き換えない。成果物は `collespo/` の下（`src/` の外）に作り、PRで出す。秘密は書かない。

## 背景
サイトは `web/`（手で書いたページ）と、`scripts/generate_archive_pages.py`（日ごとのアーカイブを作る）などで出来ていて、`.github/workflows/deploy_site.yml` で公開している（写しには workflows は入っていない。`scripts/` と `data/postseason.json` を見る）。PSの勝ち上がり（ワイルドカード→地区→リーグ優勝決定→ワールドシリーズ）を1ページで見られるようにしたい。ずっと見られる型のページで、検索からも来やすい。

## 作るもの（`collespo/`）
1. `collespo/generate_ps_bracket_page.py`: `data/postseason.json` から `ps-bracket.html` を作る下書き。各シリーズの球団（日本語名）・勝敗・勝ち上がり・決まっていない枠は「未定」。日本人選手の名前（`players`）を球団の下に小さく。次の試合の日本時間（材料にあれば）。スマホで横にはみ出さない。サイトの見た目（`web/site-theme.css`・`web/home-base.css` など）に合わせる。
2. 構造化データ（`SportsEvent` など、既存の `generate_archive_pages.py` の `build_jsonld` の書き方に合わせる）とページの説明文（検索向け、盛らない）。
3. `collespo/test_generate_ps_bracket_page.py`: 固定の `postseason.json` で、全シリーズが出る・勝敗が材料と一致・未定の扱い・日本人選手の名前、を確かめる。
4. 見本: `collespo/samples/ps-bracket.html`（いまの `data/postseason.json` で作ったもの）。
5. `collespo/README_ps_bracket_page.md`: サイトへのつなぎ方（どのワークフローのどこで作るか、トップページからのリンク）。

## 終わったら
作業一覧のメモに成果物とPRのリンク。質問は「やりとり」に、やさしい日本語で。
