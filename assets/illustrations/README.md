# 市場の挿絵・写真

ファイルを置くだけでは使わない。SOURCES.jsonのassetsへ登録し、素材を確認してから材料行のillustrationにファイル名を指定する。

必須: filename、source_url（作品の出典ページ）、author、license、terms（確認した利用条件）、checked_on（YYYY-MM-DD）。
typeはillustrationまたはphoto（省略はillustration）。写真はorigin=independentで報道・球団素材でないことも確認する。
licenseは「いらすとや」「CC0」「CC BY」「CC BY-SA」「PD」。写真ではいらすとやは使わない。
license_version、license_url、titleは任意。CC BY/CC BY-SAの作者・ライセンス・出典と縮小の表示、いらすとやのクレジットは説明欄へ自動で入る。

いらすとやは動画内の全行で20点まで。同じファイルの再掲・同じ内容の別名コピーは1点。
台帳に利用条件を書く前に出典ページで確認する。報道写真・球団写真を別サイトから持ってくることも禁止。
台帳の入力が実際の画像の権利を保証するわけではない。写真の由来・作者・条件は登録担当が確認する。

例（本物の出典と利用条件へ置き換える）:

    {"version":1,"assets":[{"filename":"sample.png","source_url":"https://example.com/art","author":"作者名","license":"CC BY","license_version":"4.0","type":"photo","origin":"independent","terms":"CC BY 4.0。作者と出典を表示。報道・球団素材でないことを確認。","checked_on":"2026-11-03"}]}

example.comの行は本番用に使えない。素材なしの市場回では従来の画面を保つ。

## AI生成の手元PNG（2026-11-05）

licenseは「AI生成（OpenAI）」、toolは「Codex image_gen」。filenameはai直下のPNG。
必須欄はgenerated_on、checked_on（YYYY-MM-DD）、prompt、sha256（小文字64桁）、type=illustration、inspection。
inspectionはtext=absent、edges=passed、notesに担当者の目視記録。source_url・download_urlはキー自体を持たない。
画像は1MiB以下、正方形、RGBA PNGで透過と不透明部分を持つ。SHA・寸法・容量はコードで検査する。
文字・ロゴ・数字・人物の同定と輪郭の合否は目視の記録であり、自動OCR判定ではない。
手元にないAI画像は取得せず絵なしへ。破損・容量超過・不正な台帳は検査で止める。
AI画像だけGitへ含め、いらすとやの画像は引き続き再配布しない。従来の取得URL・照合・20点制限は維持。

## 場面の選び方

優先順は材料行のillustration → 回のillustration → market_kind → idの語 → titleの語。
本文の過去の実績から種類を推測しない。種類不明は絵なし。自動選択は最初の確定行だけ。
行に明示済みの絵がある回には自動追加しないため、公開済みの3回はhandshake.pngだけのまま。
回の任意欄market_kindで下表の種類を指定できる。既存dataは変更していない。

| market_kind | id/titleの手掛かり | 素材 |
|---|---|---|
| contract | contract/signing/契約成立/契約合意/契約締結 | ai/contract.png |
| posting | posting/ポスティング | ai/posting.png |
| qo | qo/qualifying/クオリファイング | ai/qo.png |
| fa | fa/free-agent/フリーエージェント | ai/fa.png |
| trade | trade/トレード | ai/trade.png |
| award | award/受賞 | ai/award.png |
| retirement | retirement/retire/引退 | ai/retirement.png |
| injured_list | injured-list/il/負傷者リスト | ai/injured_list.png |

## いらすとやの取得

元画像はGitへ入れない。source_urlは公式の出典ページ、download_urlは確認済み本文画像のHTTPS URL。
いらすとやのdownload_urlはblogger.googleusercontent.comに限定。取得後のSHA-256一致を確認して保存する。
通信失敗・未登録URL・不一致では従来通り絵なしへ戻し、既存ファイルは上書きしない。
