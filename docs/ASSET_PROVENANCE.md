# assets の出所一覧

2026-10-29、`origin/main c42da5dc` の追跡ファイル・README・コミット履歴と、共有コピーの既存docsを調査した。出所の分類であり、Geminiその他への送信許可ではない。**全項目の送信可否は未判断。Claudeと本人が個別に決める。** 出所を追えない物は不明とする。

| フォルダ（配下に適用） | 分類 | 確認した根拠・限界 |
|---|---|---|
| `assets/` | 混在 | 下記のBGM・フォント・立ち絵。背景画像専用フォルダはこの版に無い。外部指定の画像や私的な素材置場は調査対象外 |
| `assets/bgm/` | 自作（外部のCC0録音を含む） | `assets/bgm/README.md`、`scripts/make_bgm.py`。数式とVSCO 2 CE / Growlybassの録音で組立て。生成AI不使用との保存記録。録音の外部素材を含むため「全て自作音だけ」とはしない |
| `assets/fonts/` | 公式配布物（書体） | `Oswald-OFL.txt`、Oswald Project Authors、SIL OFL 1.1。導入履歴 `ee7d1926`。画像素材ではない |
| `assets/fonts/soccer-v5/` | 公式配布物（書体） | `BarlowCondensed-OFL.txt` / `NotoSansJP-OFL.txt`、SIL OFL 1.1。導入履歴 `6a7b9e1e`。画像素材ではない |
| `assets/portraits/` | 混在 | 作者配布PSDの加工と、生成線画に着彩した別系列が共存。フォルダ全体を自作とはしない |
| `assets/portraits/ずんだもん/` | 公式配布物（作者配布素材の加工） | `assets/portraits/README.md` に坂本アヒル「ずんだもん立ち絵素材改1.1.1」のPSDから合成・抽出と明記。`parts.json` / `common.parts.json` も同系統 |
| `assets/portraits/ずんだもん/上向き/` | 公式配布物（同PSDの差分抽出） | 同READMEの全差分抽出、`export_all_portrait_parts.py` と索引。自前で抽出したことは原画の出所を変えない |
| `assets/portraits/四国めたん/` | 公式配布物（作者配布素材の加工） | 同READMEに坂本アヒル「四国めたん立ち絵素材2.1」のPSD由来と明記。全差分・共通形式は同じ出所 |
| `assets/portraits/collespo-20260923/` | 生成・コード着彩（混在の詳細は下記） | 共有docs `PORTRAIT_AND_SCOPE_REVIEW_2026-09-23.md` は生成線画＋コード着彩と説明。人間の手描きとはしない。生成元の全参照画像・入力条件をこの調査で独立に再確認していない |
| `assets/portraits/collespo-20260923/metan/` | 生成・コード着彩 | 同共有docs、共有 `CHANNEL_AND_ART_REVIEW_2026-09-23.md`。眉周辺の分類・局所補正・表情生成の記録。採用履歴 `ab2a3677` / `59a68be7` / `6b363870` |
| `assets/portraits/collespo-20260923/metan/3-white/` | 生成・コード着彩・局所編集 | `ab2a3677` がbase.pngを導入、`6b363870` が表情を追加。元絵の条件まで「確認済み」とはしない |
| `assets/portraits/collespo-20260923/metan/3-black/` | 生成・コード着彩・局所編集 | `59a68be7`、`6b363870`。共有docsは白T/黒Tの衣装差分と説明。生成/局所加工の許可とAI入力の許可を同一視しない |
| `assets/portraits/collespo-20260923/zundamon/` | 生成・コード着彩 | 上記9/23共有docsのA/B/C候補とCの表情生成の記録。親フォルダに原画の利用条件を証明する文書は無い |
| `assets/portraits/collespo-20260923/zundamon/C-cheer/` | 生成・コード着彩・局所編集 | `ab2a3677` がbase-brow-candidate.pngを導入。共有docsのC目閉じ生成・眉修正の記録。全ファイルの生成時入力は未確認 |
| `assets/portraits/collespo-20260923/zundamon/C-black/` | 生成・コード着彩・局所編集 | 同フォルダ `README-duo.md`、`e2743782`。C-cheerの写しと10/9の口・眉・まぶたの局所変更。今回の導入時に再生成していないという記録であり、元絵の生成出所を変更しない |

共有docsの2文書は共有コピーだけに存在し、対象版のGit追跡には入っていない。ここには調査に使った文書名と要旨を記した。元文書を新たに公開したり、本文・未発表素材を外部へ送ったりしていない。

この版の全14ディレクトリ（`assets/`を除く）を列挙した。今後追加される未分類フォルダは**不明**として扱う。動的に指定される雨衣の立ち絵、外部から読む画像、`build/` 内の試作や参照画像はこの一覧で確認済みにならない。背景がコード描画でも、重なる立ち絵・引用・フォント・画像を含む完成画面の送信可否は別途確認が必要。

## 共有コピーだけにある追加フォルダ

同日の共有 `C:/Users/issak/Desktop/pwa-mvp/assets/` のディレクトリ名も照合した。下記22フォルダは上記の対象版に無い。名称が「候補」「検証」でも画像全体の出所を確定できないため、すべて**不明・送信可否未判断**とする。9/23の候補の説明があっても、個別ファイルとの対応・参照元・条件を未照合のまま「生成物なので送ってよい」とはしない。画像や非公開の検証記録はコピー・送信していない。

| 共有assets内の追加フォルダ | 分類 |
|---|---|
| `portraits/exports/` | 不明 |
| `portraits/collespo-20260923/expression-candidates/` | 不明 |
| `portraits/collespo-20260923/expression-candidates/metan/` | 不明 |
| `portraits/collespo-20260923/expression-candidates/zundamon/` | 不明 |
| `portraits/collespo-20260923/metan/1-black/` | 不明 |
| `portraits/collespo-20260923/metan/1-white/` | 不明 |
| `portraits/collespo-20260923/metan/D1-candidates/` | 不明 |
| `portraits/collespo-20260923/metan/D1-candidates/M1/` | 不明 |
| `portraits/collespo-20260923/metan/D1-candidates/M2/` | 不明 |
| `portraits/collespo-20260923/zundamon/A-wave/` | 不明 |
| `portraits/collespo-20260923/zundamon/B-guide/` | 不明 |
| `portraits/collespo-20260923/zundamon/D-candidates/` | 不明 |
| `portraits/collespo-20260923/zundamon/D-candidates/D1/` | 不明 |
| `portraits/collespo-20260923/zundamon/D-candidates/D2/` | 不明 |
| `portraits/collespo-20260923/zundamon/D-candidates/D3/` | 不明 |
| `portraits/collespo-20260923/zundamon/C-black/rejected-20261009/` | 不明 |
| `portraits/collespo-20260923/verification-20261009/` | 不明 |
| `portraits/collespo-20260923/verification-20261009/masks/` | 不明 |
| `portraits/collespo-20260923/verification-20261009-metan-D1/` | 不明 |
| `portraits/collespo-20260923/verification-20261009-metan-D1/rejected/` | 不明 |
| `portraits/collespo-20260923/verification-20261009-redesign/` | 不明 |
| `portraits/collespo-20260923/verification-20261009-v2/` | 不明 |

対象版と共有コピーの和集合は36フォルダ。対象版の14と、共有だけの22を混同しない。
