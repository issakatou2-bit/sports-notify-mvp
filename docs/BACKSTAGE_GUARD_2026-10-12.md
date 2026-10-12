# A 楽屋の言葉の防止

- 枝: `hiro/backstage-20261012`。隔離clone: `build/codex/tmp/backstage-20261012`。
- 基点: `bbf007319bf9d6f4e9e31bfdf8b770980fb4d189`。2026-10-11 23時台、GitHubのmainと手元origin/mainの一致をコネクタで確認。通常のHTTPS cloneは接続制限で失敗し、共有コピーのGitオブジェクトから同じコミットを新規cloneへ取得した。共有コピーは変更していない。
- main確認: numbers用の制作事情検査はあったが、全LLM共通の受信検査・一度の訂正・行除外はなかった。

## 変更と理由

`data/backstage_phrases.json`へ禁止する表現・理由のID・共通の生成指示を集約。従来のnumbers専用の曖昧な返答の規則もこの辞書へ移し、適用範囲をnumbersに限定した。「材料費」などを拾う大ざっぱな材料という単語の禁止はしない。

`backstage_guard.create`を、generate_narration / generate_weekly_narration / local_voices / local_buzz / local_reporters / mlb_buzz / soccer_voices / review_board / localize_videos / sanity / notability_engineの呼出しへ接続。generate_dialogueは `_ask` がBatchの受信結果も検査する。Batch訂正は同期の `_create` で一度だけ行い、同じ不採用Batchを再取得しない。モデル・effort・max_tokensは変えない。

検出後は一度だけ訂正。繰り返した場合、番号付き翻訳・論調・対話・箇条書きは問題の行だけを除外する。短い原稿・題・多言語のTITLE/DESC・JSON検査応答は形や意味を保てないため、既存の失敗扱いまたは簡易版への経路へ戻す。全行不採用、訂正時の通信失敗でも危険な初稿を復活させない。検出/訂正/除外/失敗の理由をstderrへ残す。

採用分の費用記録は従来どおり。新たに不採用分も記録し、訂正前に既存の日次上限を確認する。上限で訂正できないときは除外/失敗とし、同じ応答の費用を二重に足さない。Batchの半額記録は維持する。

## 検証

- 追加8件: Joseの実台詞、表記/空白の揺れ、材料費等の誤検出、訂正、行除外、全行失敗、通信失敗、上限、費用の二重計上防止、Batch受信、全本番Messages呼出しのAST走査。通信・課金なし。
- 従来のlongform_editorial 25件、Batch入口4件、報道ガード5件、球団名4件の個別検査を確認。
- 古い模擬応答2か所に本物のAPIと同じ `type=text` を追加。Batch検査は共通指示を含む引数の一致を確認する形へ更新。assertを外していない。
- 全体検査: 最終ログ `build/verification/run_checks-final.log` の末尾「===== すべて通過 =====」を確認。最初の失敗ログ `build/verification/run_checks.log` と区別する。

## 残りと取り込み

手元の検査のみ。CI・実APIの生成結果・公開物は未検証。push/PR/公開/変数切替なし。㉗の枝・成果物・共有コピーの変更なし。

未知の言い回しを完全に理解する仕組みではない。新しい実例は辞書と試験材料へ追加する。内部講評のreview_boardも依頼どおり同じ検査を通す。Aは楽屋の言葉を対象にし、試合時点/得点/人物/会場の事実照合は別枝B。

Claudeはこの枝のcommitを取得して取り込む。Bは同じmainから独立しているため、generate_dialogue / local_voices / mlb_buzz / notability_engine の両変更を保持する。双方のdocs/HANDOFF.md追加は共有の現在地へ要約して調整する。
