# 順位表の検索入口を明確化

- 基点: origin/main 4b3779ac。枝: hiro/standings-ctr-20261013。
- 依頼時のSearch Console直近28日: standings.html 表示319・クリック5（本人/Claude提供。独立取得なし）。検索語にMLB順位・2026MLB順位表など。
- 生成元のtitleを「2026 MLB 順位表（最新）｜ア・リーグ ナ・リーグ 地区別・ワイルドカード」へ（年は生成時の対象年）。40文字。
- meta descriptionは両リーグ・地区別・WC・勝敗/勝率/ゲーム差を明示し、JSTのページ更新日時を入れる。固定試作で112文字。OG/Twitterも既存テンプレート経由で同期。
- 冒頭h1・紹介文も現在の順位をすぐ確認できる表記へ。ページ更新時刻と球団データ更新範囲を区別する従来表示を維持。表・順位取得・lineup.htmlは変更なし。
- 手元: 順位表8試験成功。固定30球団材料と日付境界の2時刻でtitle/description長、検索語、更新日時を検査。API/フォント/過去commit不要。build/standings-preview.htmlは固定材料の確認用で実順位ではない。
- 手元の全体検査: scripts/run_checks.py「すべて通過」。ログ build/checks-standings-ctr.log。
- CI・実データ生成・公開物は未検証。push/PR/公開はClaude担当。
