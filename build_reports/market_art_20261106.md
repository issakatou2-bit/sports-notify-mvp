# 移籍市場の自前挿絵（2026-11-06向け）

担当：Codex。開始は2026-11-05 23:19 JST頃。生成・検査時間は今回の道具応答と保存ログによる。
目的：既存v4の静かな挿絵に使える透過PNG、台帳検査、種類の選択表を用意する。
作業場：`build/wt-market-art`、枝 `claude/market-art`。共有コピーの取得済み `refs/remotes/origin/main` = `b9a991ef5c18642d5266a925afa6129be2638fa3` が起点。
共有の.gitは書込禁止のためworktree作成は失敗し、指定の別クローン方式を採用。オブジェクト共有のsparse clone、管理領域は `build/codex/tmp/market-art-git`。git fetchはしていない。
HANDOFF・共有コピーの未コミット変更・dataの実績台帳・変数や通信設定は変更していない。push・PR・公開・動画生成・VoiSona要求なし。

## 完成素材

内蔵 `image_gen` を使用。8場面、9回生成（ポスティングのみ1回再生成）。最終PNGは各640×640のRGBA、透過あり、1,000,000 bytes未満。縮小とPNG最適化だけを行い、色の塗り直し・輪郭の切除はしていない。
各生成時間はimage_gen呼出直前〜応答完了の実測。トークン数・費用は道具から返らず取得不可（推定値を実測として記載しない）。

| 場面 | ファイル（assets/illustrations/） | bytes | 生成秒 | 点検 |
|---|---|---:|---:|---|
| 契約成立（握手） | ai/contract.png | 195,452 | 33.732 | 合格 |
| ポスティング | ai/posting.png | 182,560 | 35.271 | 合格 |
| QO | ai/qo.png | 154,586 | 32.649 | 合格 |
| FA | ai/fa.png | 132,324 | 32.294 | 合格 |
| トレード | ai/trade.png | 166,451 | 36.328 | 合格 |
| 受賞 | ai/award.png | 156,727 | 32.055 | 合格 |
| 引退 | ai/retirement.png | 285,039 | 34.292 | 合格 |
| 負傷者リスト | ai/injured_list.png | 169,872 | 34.552 | 合格 |

生成時間合計：297.182秒（不採用1回を含む）。生成日：2026-11-05。生成原本は道具の既定保存先に保持し、別の原本コピーは増やしていない。

## 自分で確認したこと

最終保存版をcontact.png（紺と明るい背景）とedges.png（上部輪郭を4倍）で点検。初回応答の全画像でも輪郭・隙間・下端を確認。文字・ロゴ・数字・実在人物・実在球場・球団識別は見当たらない。帽子は無地の灰色。救急箱にもマークなし。採用8枚に赤いにじみや淡い外光は見当たらない。これはCodexの目視記録であり、自動OCRや法的な権利保証ではない。
日本の島形は象徴的な概形。正確な地図としては使わない。トロフィー・扉などの意味は見出しと併せて読む。
ポスティング初回は横長1536×1024で、輪郭外に大きな淡い光が残ったため不採用。再生成1回で正方形・外光なしを確認。ほかの再生成・不採用はなし。
他担当の過去報告は今回の検証に数えていない。前回READMEは指示作成の注意点として参照した。

## 選び方と既存経路

材料行のillustrationを最優先。次に回のillustration、market_kind、id、titleの順。種類の表はassets/illustrations/README.mdとmarket_art.pyのSCENE_FILES/SCENE_WORDS。本文の過去の実績から推測しない。
自動選択は最初の確定行に1点。行に明示済みの絵がある回には自動追加しない。公開済み3回はhandshake.pngだけのままで、data/offseason_market.jsonは変更なし。
AI行はURLのキー自体を禁止し、resolve_aiで直接手元PNGだけを照合。必須項目・生成日/点検日・目視記録・sha256・1MiB上限・PNG/正方形/alphaを検査する。未配置なら絵なし、破損ならエラー。いらすとや3行、取得URL/HTTPS制約、SHA照合、20点制限、クレジットは維持。
描画は既存generate_asset_video.py → asset_v4_cards.py → market_art_render.pyを再利用。generate_asset_video.pyと描画の位置・字サイズは変更していない。

## 比較見本

材料：保存済み `data/offseason_market.json` の `ito-posting-open-20261105`、最初の確定行、v4、時刻2秒。日付・本文・54px文字・立ち絵・描画条件は同じ。
- `market_art_20261106/irasutoya.png`：既存handshake.png。
- `market_art_20261106/ai.png`：メモリ上だけai/posting.pngを明示した比較。元のdataは変更していない。
- `market_art_20261106/preview.json`：使用素材、配置、文字サイズ。
- `market_art_20261106/contact.png`、`edges.png`：全素材の点検画像。
いらすとや画像は通信制限で取得失敗。プロジェクト内の保存済み `build/codex/tmp/wt-market/assets/illustrations/handshake.png` を1枚だけコピーし、既存台帳のSHA一致をresolveで自分で確認して使用。元のPNGはGitに含めない。
描画試験・見本では共有コピーの既存立ち絵を読み取り参照し、大きな素材コピーを避けた。自分で2枚とも開いて、挿絵と本文・キャラが重ならないことを確認。字幕・出典は従来の描画のまま。動画・実公開は未検証。

## 試験

- `test_market_art.py`：19件成功。AI必須項目、目視記録、URL禁止、SHA、不足時の通信なし、1MiB上限、PNG/正方形/透過、選択表、明示優先、既存3回維持、原稿添付往復、従来のいらすとや取得・上書き防止・20点・配置を検証。
- 関係試験：market_art / offseason_market / offseason_public / offseason_outro、合計50件、5.090秒、成功。`market_art_20261106/related_tests.log`。
- `scripts/run_checks.py --section static`：191.3秒、すべて通過（重大0、既存の軽微警告63）。`market_art_20261106/static.log` / `static_timings.json`。
- `git diff --check`：成功。
上記は全てheavy_waitを通した。試験の初回は疎なクローンに立ち絵がなく描画3件で失敗し、共有の既存素材を読み取り参照してから通過。staticは一度だけ。CIはpushしていないため未実施。

再現（作業場をcwd、pythonはこのPCのPython314）：

```powershell
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 5 -- python build_reports/market_art_20261106/run_related_tests.py
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 8 -- python scripts/run_checks.py --section static
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 3 -- python build_reports/market_art_20261106/render_preview.py
```

## 変更ファイルと行

- `.gitignore:61`
- `scripts/market_art.py:16`
- `scripts/market_art.py:163`
- `scripts/market_art.py:204`
- `scripts/offseason_market.py:37`
- `scripts/offseason_market.py:54`
- `scripts/offseason_market.py:111`
- `scripts/test_market_art.py:203`
- `assets/illustrations/README.md:20`
- `assets/illustrations/SOURCES.json:47`
- `assets/illustrations/ai/*.png`：8枚（バイナリにつき行なし）。
- `build_reports/market_art_20261106/`：見本・点検・ログ・再現用スクリプト。

## 実際に送った指示文

### 1. 契約成立（握手）（33.732秒、採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: two generic hands shaking to symbolize an agreed contract, with simple plain sleeves, no people or faces. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

### 2. ポスティング（26.009秒、不採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: a plain ivory baseball travelling over a short band of ocean waves away from a small Japanese island silhouette toward an open horizon; one simple curved arrow points across the water. The islands are only a symbolic silhouette, no precise map, no other country or flag.. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

不採用理由：非正方形、輪郭外の広い淡い光を目視で確認。不採用

### 3. ポスティング（35.271秒、採用）

Square 1:1 transparent PNG, isolated flat editorial cutout. Japanese baseball posting: a baseball above a tiny symbolic Japanese island shape and two short ocean waves, a solid curved arrow travelling right. Compact centered composition with empty transparent margins. Muted teal, ivory, ochre and charcoal bold outlines; matches calm flat news illustration. Each shape solid opaque flat fill. Background strictly alpha zero immediately outside the outlines, including all spaces between objects. Absolutely NO glow, halo, haze, shadows, translucent atmosphere, gradients or lighting effects. No text, logos, digits, flags, people, stadiums or team references. Not photographic.

### 4. QO（32.649秒、採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: a blank ivory document with a folded corner and a small round analog deadline clock beside it; clock face has hands only, absolutely no tick marks or numerals; no writing or lines on paper. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

### 5. FA（32.294秒、採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: one open freestanding teal door in an ivory doorframe to symbolize free agency and open opportunities, no wall, no room, no light coming through, no floor, no person. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

### 6. トレード（36.328秒、採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: two plain neutral gray baseball caps exchanging places, with two opposite curved arrows in muted teal and ochre; caps have NO badges, logos, letters, contrasting team color panels or recognizable team styling, no people. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

### 7. 受賞（32.055秒、採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: one simple ochre trophy cup with two handles on a short teal plinth, no plaque writing, no emblem, no engraved marks, no confetti, no sparkles. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

### 8. 引退（34.292秒、採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: a single well-kept ochre baseball glove set down palm-up beside a plain ivory baseball, peaceful retirement symbol, no hand, no person, no floor or cast shadow, no brand stitching or emblem. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

### 9. 負傷者リスト（34.552秒、採用）

Use case: illustration-story. One square transparent PNG editorial illustration for a baseball transfer news video on a dark navy background. Subject: a plain teal first-aid kit with a blank ivory front panel, beside one ivory rolled bandage with a short unrolled end, no cross symbol, no writing, no person or injury. Flat calm cut-paper shapes, muted teal, warm ivory, soft ochre, charcoal outlines, minimal hard-edged shading. Centered compact silhouette, generous transparent margin on all sides. Opaque solid interior; only thin antialiasing at edges. No glow, blur, shadow outside silhouette, texture, haze, fringe, gradient or photography. No text, letters, digits, logos, watermark, real people, stadiums, team identifiers or uniform numbers. Exactly one scene. Save the output for local project use.

## 容量と残ること

報告作成時の作業場 86,018,429 bytes、別Git管理領域 486,902 bytes、生成原本9枚 6,238,819 bytes。合計 92.74MB。作業用スクリプトは小容量。200MB以内。
残ること：枝のレビュー・push/取込・本番での採用判断は依頼元へ。今回のローカルコードでは新しい明示なしの回を自動選択できるが、共有コピー・本番への切替は行っていない。動画の書き出しと公開は依頼対象外。生成トークン数は取得不可。
