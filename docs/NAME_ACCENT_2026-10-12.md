# 氏名の高低 2026-10-12

完了: ヒロ。基点main 2f86ba3f、隔離clone name-accent-20261012、枝 hiro/name-accent-20261012。HANDOFFへの追記なし。
対象: 共通高低関数の取り込み、共通辞書の写し、氏名queryの補正/検査、聞き比べ。原本yomi-sharedには本人指定の鎌田大地だけを追加する。
確認済みの高低だけ補正し、残る氏名は未確認として本人へ戻す。

## 辞書と共通道具

- 共通原本 `C:/Users/issak/Tools/yomi-shared/yomi.csv` に鎌田大地/カマダダイチ/LHHHHHを1行追加。出所は「コレスポ 加藤さん10/12」。同じ行をリポジトリのdata/yomi_shared.csvへ同期し、他の一般語の既存の写しは更新しない。
- 高低の唯一の決定元はこの共通CSVの写し。player_kana.jsonは読みと対象名簿のまま。日本人氏名60呼称のうち確認済み1、未確認59（表記別名を含む）。未確認の高低を辞書へ推定登録しない。
- `voice_accent_common.py` はAPSCのvoicevox_dict.py（モーラ数/LH→型）、accent_analysis.py（カナ/モーラ/型→LH）、check_accent.py（queryの型/LH）の必要関数だけを変更せず取り込んだ。元ファイル・関数名・SHA256はdocs/verification/name-accent-sources-2026-10-12.json。標準ライブラリだけでCIでも使える。必要関数を再同期するときは元ファイルとの差を確認し、この出所記録と試験を更新する。
- 手元の実query検査と音声見本はaccent-toolsのvenvで実行。原本のAPSCファイル、VOICEVOX利用者辞書、ほかのプロジェクトは変更していない。

## 補正と検査

氏名を1句にする既存のprepare_queryの後で、name_accent_guardが確認済みの氏名の開始位置を合わせる。句頭に別の文言がある場合だけ氏名の前を分け、pauseは足さない。氏名の内部は1句のまま。LHHHHHは平板0なのでqueryでは氏名＋後続助詞を含めた句長をaccentにして、/mora_dataで高低を再計算する。先頭のaccentを継承するだけだった既存の結合に、本人の辞書を優先する段を加えた。

既存validate_queryにも辞書LHとqueryの氏名範囲LHの照合を追加。読みのPASSと高低の確認済み/未確認を区別し、name_accentsとunverified_accentsを音声のreading.jsonへ保存する。未知の高低はUNVERIFIEDであり、高低の合格数へ入れない。

- 新しい8試験：鎌田の頭高/型4を検出、本人指定の型と助詞を補正、文中の開始位置、英語別名・繰り返し、再計算が型を戻したとき停止、未確認は補正しない。
- 60呼称×話者2/3の120query。確認済み一致2、未確認118、確認済みの不一致0。全員の読み・1句は既存検査でも照合。鎌田の単独/文中/助詞の型を補正する。
- 元エンジンの「鎌田大地です」は型4（LHHHLL）、補正後はLHHHHH。本人の指摘を、どの文脈でも同じ型の誤りだったと一般化しない。

## 聞き比べ

`C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/name-accent-samples/`。index.html、samples.json、all-queries.json、78WAVと各query.json。鎌田はめたん/ずんだもんの修正前後。他の59呼称の現在音声を全員分保存し、最初の15人だけ現在/平板の仮案を並べる（名前順で、頻度順ではない）。仮案は正解と宣言せず、本番と辞書には入れない。

APSCの少数聞き比べにならい「いま/案/保留」の判定をJSON保存できる。次は本人の判定JSONを原音声・queryと照合し、選ばれた氏名のLHだけを共通原本と写しへ戻して試験へ足す。保留・未回答は正解にも採用率にも入れない。型を他の選手へまとめて一般化しない。

原本accent_analysis.pyの実声測定もvenvで実行し、鎌田の修正前後のF0を保存。修正後の0.60秒に8.41半音の跳び候補が出た（目安）。語内の位置を合わせた検査ではなく、無声化/測定誤りかは未確認なので、これを氏名の高低の合否に使わない。本人の聴き比べで確認する。

再現: `accent-tools/venv/Scripts/python.exe scripts/check_name_accents.py --out ../name-accent-samples/all-queries.json`（`--narration`でコレスポの保存台本にも使える）、`scripts/preview_name_accents.py --out ../name-accent-samples`。

残り: 59呼称の本人の判定、Claudeのpush/CI/取込。共有原本への鎌田の1行は追加済み。

run_checksは終了コード0、123試験ファイルNG0、末尾「===== すべて通過 =====」。ログはname-accent-samples/run_checks.log。共有の知恵の入口READMEにも仕組みへの案内1行を追加。今回の共通原本の変更はyomi-shared/yomi.csvとshared-knowhow/README.mdのみで、プロジェクトのGit対象外。辞書の写しと出所・検証要約はこの枝にコミットする。

Claudeの取得元: `C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/name-accent-20261012` の `refs/heads/hiro/name-accent-20261012`。CI/公開音声の効果は未確認。
