# 氏名の平板採用と未確認の聞き比べ

- 基点: origin/main 4b3779ac。枝: hiro/name-accent-flat-20261013。
- 本人が10/13に採用した15人を data/yomi_shared.csv と共通原本 C:/Users/issak/Tools/yomi-shared/yomi.csv に各1行追記。出所は「コレスポ 加藤さん10/13」。既存の鎌田大地と同じ補正経路で、姓名を一つの句にし、後続助詞まで高くする。
- 確認済み16呼称、未確認44呼称。未確認を推測登録しない。
- 再生成: `scripts/preview_name_accents_pending.py --out <保存先> --url http://127.0.0.1:50121`。両話者のいま/平板を全44呼称（同じ型も含む）に用意。選択はブラウザ内に保存し、全44件を name-accent-picks2.json に書き出す。未選択と保留は別。辞書の自動変更なし。
- 保存先: C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/name-accent-samples2/index.html。samples.json、176 WAV、各 synthesis query を保存。
- 手元: 関連32試験成功。新しい試験材料は同梱辞書と固定の擬似queryのみ（Windowsフォント・保存音声・過去commit不要）。既存の読み/句結合の試験材料も、本人採用の上田綺世の平板に更新。
- 実エンジン: 60呼称×2話者＝120query、失敗0。build/confirmed-live-queries.json。共通辞書15行と同梱辞書15行の一致、176音声の存在・非空・リンク先を確認。平板案のqueryは生成時に期待LHと照合。
- 手元の全体検査: scripts/run_checks.py「すべて通過」。ログ build/checks-name-flat.log。
- ブラウザ: localhost:8766が自動承認レビューで「ユーザーが許可を拒否した」と却下。画面とJSON書き出し操作・本人の聴感は未検証。CI・公開も未検証。push/PR/公開はClaude担当。
