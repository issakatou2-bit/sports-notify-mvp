# 氏名をつなげる読み 2026-10-12

担当: ヒロ。基点 main e4140012、隔離 clone name-phrase-20261012、枝 hiro/name-phrase-20261012。
対象: player_kana.json、name_reading_guard、synthesize_narration、読み検査と試験。HANDOFFは編集しない。

完了: ローカルrun_checks終了コード0、試験ファイル122本NG0、末尾「===== すべて通過 =====」。中断した旧検査を成功扱いにせず再実行。既存の軽微pyflakes警告50件は残るが重大0件。検証の要約はdocs/verification/name-phrase-2026-10-12.json。

本人の「鎌田大地を一つなぎで」という指摘を試験材料へ戻す。辞書の氏名は区切りなしのカタカナに統一し、エンジンの句の補正と検査は name_reading_guard に集約する。

## 原因と規則

10/12、ローカルVOICEVOX 0.25.2の実audio_queryで確認。旧辞書は「カマダ、ダイチ」「ウエダ、アヤセ」「オオタニ、ショウヘイ」で、姓の最後の句にpause_moraがあった。読点を削るだけで鎌田・上田は1句になったが、大谷は内部のpauseなしでも2句に分かれた。

- player_kana.json の readings に日本人氏名を区切りなしのカタカナで書く（空白/読点/中黒なし）。表示名と英語の別名はそのまま。日本人名簿＋読みの表を唯一の対象/正解とし、監督や一般語は氏名結合の対象にしない。
- name_reading_guard.prepare_query が、正しい読みを先に確認した上で、氏名内の句境界だけを結合する。文や列挙の句読点、氏名前後のpauseは保持。結合した句だけ /mora_data に渡し音の長さ/高低を再計算する。最初の句のaccentを継承し、後続句のaccentは重ねない。全文や利用者辞書は変更しない。
- 長音のオー/オオ、エー/エイなどを既存の読み検査と同じ方法で扱う。名簿の日本人氏名と英語の別名、姓名間の空白/中黒、複数人/繰り返しにも同じ処理を使う。
- validate_query は実際に合成へ送るqueryで「氏名が1句の中にある」を検査。姓と名の間にpauseを置くには句の境界が必要なので、pauseなしの複数句も不合格にする。句末のpauseは氏名内の間と区別する。
- 本番の synthesize_narration と登録名の check_name_queries が同じprepare_queryを参照。エンジン生応答と補正後を混同しない。補正後のkana欄は空にし、accent_phrasesを検査証拠とする。

## 確認と見本

- 既存読み試験16件＋姓名の境界試験6件：鎌田/上田/大谷、pauseあり/なしの2句、列挙の間の保持、繰り返しの2回目、合成が補正済みqueryを受け取ること。
- 登録名207件（選手呼称62/クラブ103/監督42）の話者2のquery：読みと氏名の句検査PASS。60の日本人氏名のうち43呼称はエンジンが分けた句を補正。
- 日本人氏名60呼称の文中query＋3人の列挙/同一名の繰り返しを話者2/3で計124件：PASS。contexts.jsonに生/補正後queryを保存。
- 見本は5人（鎌田大地/上田綺世/大谷翔平/山本由伸/三笘薫）×話者2/3、修正後10WAV＋以前10WAV。20WAVのフレーム数が0でないことを確認。音声全体や高低の聴取合格とは区別する。

保存先: `C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/name-phrase-samples/`。入口index.html、cause.json、all-name-queries.json、contexts.json、samples.json、各reading.json、run_checks.log。

再現: `python scripts/check_name_queries.py --url http://127.0.0.1:50121 --out ../name-phrase-samples/all-name-queries.json`、`python scripts/preview_name_phrases.py --out ../name-phrase-samples`。

残り: 本人の聴き比べ、Claudeのpush/CI/取込。公開音声の差し替えは行っていない。

Claudeの取得元: `C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/name-phrase-20261012` の `refs/heads/hiro/name-phrase-20261012`。隔離clone内だけでコミット、共有コピーの枝や未コミット変更は変更しない。

他案件向け共有入口の追記案（共有READMEは今回の書込権限外なので原本は未変更）:
`VOICEVOXの日本人氏名を1句にする / pwa-mvp/scripts/name_reading_guard.py・docs/NAME_PHRASE_2026-10-12.md / 読み照合後に氏名内だけ結合しmora_data再計算、句とpauseを検査`。
