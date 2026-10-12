# 96クラブの表示案と読み 2026-10-12

本人の㉜（10/12）で、この表を案どおり採用。現在の決定はSOCCER_V5_FINISH_2026-10-12.md参照。

本人指定のアストンヴィラを優先。各リーグのスポーツ紙の短い表記と中継の呼称を基準に、画面で使う表示案/狭い欄の短名/読みを1クラブずつ表に固定した。媒体ごとの差があるため、唯一の公式日本語表記とは扱わない。所属・順位・色はこの表で決めない。

`data/club_display_names.json` の96クラブ＋既存名簿の対象外7クラブが入口。v5の5枠のクラブラベル/字幕生成時のclub_name_jp/音声が参照する。APIのクラブIDと引用原文は保ち、原文の英語表記を日本語へ書き換えない。旧legacy/v4は以前の画素を保持する。

読みのexpectedとVOICEVOXへ渡すspokenは通常同じ。アストンヴィラだけはspoken=あすとんゔぃら（VOICEVOXがカタカナのヴィをビへ置き換えるため）。画面の名前と辞書の正解はアストンヴィラ。

| リーグ | 今の名前 | 表示案 | 狭い欄 | 読み | 理由 |
|---|---|---|---|---|---|
| PL | マンチェスター・シティ | マンチェスターC | マンC | マンチェスターシティ | 新聞の短縮表記を基準にC/Uを区別。狭い欄だけさらに短くする。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | アーセナル | アーセナル | アーセナル | アーセナル | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | ブライトン | ブライトン | ブライトン | ブライトン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | ブレントフォード | ブレントフォード | ブレントフォード | ブレントフォード | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | リーズ | リーズ | リーズ | リーズ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | リバプール | リバプール | リバプール | リバプール | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | エバートン | エバートン | エバートン | エバートン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | ハル・シティ | ハル・シティ | ハル | ハルシティ | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | ニューカッスル | ニューカッスル | ニューカッスル | ニューカッスル | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | チェルシー | チェルシー | チェルシー | チェルシー | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | イプスウィッチ | イプスウィッチ | イプスウィッチ | イプスウィッチ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | マンチェスター・ユナイテッド | マンチェスターU | マンU | マンチェスターユナイテッド | 新聞の短縮表記を基準にC/Uを区別。狭い欄だけさらに短くする。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | ノッティンガム・フォレスト | ノッティンガムF | ノッティンガムF | ノッティンガムフォレスト | 新聞のF略記を採用。音声はフォレストまで読む。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | サンダーランド | サンダーランド | サンダーランド | サンダーランド | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | クリスタル・パレス | クリスタルパレス | パレス | クリスタルパレス | 冠詞と名を続ける新聞表記を採用。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | アストン・ビラ | アストンヴィラ | アストンヴィラ | アストンヴィラ | 本人指定「アストンヴィラ」を優先。ビラ/ヴィラの揺れも別名で吸収。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | ボーンマス | ボーンマス | ボーンマス | ボーンマス | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | コベントリー | コベントリー | コベントリー | コベントリー | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | フラム | フラム | フラム | フラム | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PL | トッテナム | トッテナム | トッテナム | トッテナム | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/premier/data/standings/) |
| PD | バルセロナ | バルセロナ | バルセロナ | バルセロナ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | アトレティコ・マドリード | アトレティコ・マドリード | アトレティコ | アトレティコマドリード | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | レアル・ベティス | ベティス | ベティス | ベティス | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | レアル・マドリード | レアル・マドリード | Rマドリード | レアルマドリード | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | セビージャ | セビージャ | セビージャ | セビージャ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | アラベス | アラベス | アラベス | アラベス | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | デポルティボ | デポルティボ | デポルティボ | デポルティボ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | レアル・ソシエダ | レアル・ソシエダ | ソシエダ | レアルソシエダ | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | ビジャレアル | ビジャレアル | ビジャレアル | ビジャレアル | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | アスレティック・ビルバオ | アスレティック・ビルバオ | ビルバオ | アスレティックビルバオ | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | ヘタフェ | ヘタフェ | ヘタフェ | ヘタフェ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | ラージョ・バジェカーノ | ラージョ・バジェカーノ | ラージョ | ラージョバジェカーノ | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | オサスナ | オサスナ | オサスナ | オサスナ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | セルタ | セルタ | セルタ | セルタ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | エスパニョール | エスパニョール | エスパニョール | エスパニョール | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | ラシン・サンタンデール | ラシン・サンタンデール | ラシン | ラシンサンタンデール | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | レバンテ | レバンテ | レバンテ | レバンテ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | エルチェ | エルチェ | エルチェ | エルチェ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | バレンシア | バレンシア | バレンシア | バレンシア | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| PD | マラガ | マラガ | マラガ | マラガ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/spain/data/standings/) |
| SA | ローマ | ローマ | ローマ | ローマ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | インテル | インテル | インテル | インテル | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ラツィオ | ラツィオ | ラツィオ | ラツィオ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | カリアリ | カリアリ | カリアリ | カリアリ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ACミラン | ACミラン | ミラン | エーシーミラン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | フロジノーネ | フロジノーネ | フロジノーネ | フロジノーネ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ユベントス | ユベントス | ユベントス | ユベントス | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | コモ | コモ | コモ | コモ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ナポリ | ナポリ | ナポリ | ナポリ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | サッスオーロ | サッスオーロ | サッスオーロ | サッスオーロ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | アタランタ | アタランタ | アタランタ | アタランタ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | レッチェ | レッチェ | レッチェ | レッチェ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ウディネーゼ | ウディネーゼ | ウディネーゼ | ウディネーゼ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | トリノ | トリノ | トリノ | トリノ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | パルマ | パルマ | パルマ | パルマ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | モンツァ | モンツァ | モンツァ | モンツァ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | フィオレンティーナ | フィオレンティーナ | フィオレンティーナ | フィオレンティーナ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ボローニャ | ボローニャ | ボローニャ | ボローニャ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ジェノア | ジェノア | ジェノア | ジェノア | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| SA | ベネツィア | ベネツィア | ベネツィア | ベネツィア | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/italy/data/standings/) |
| BL1 | ドルトムント | ドルトムント | ドルトムント | ドルトムント | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | バイエルン | バイエルン | バイエルン | バイエルン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | フライブルク | フライブルク | フライブルク | フライブルク | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | アウクスブルク | アウクスブルク | アウクスブルク | アウクスブルク | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | レバークーゼン | レバークーゼン | レバークーゼン | レバークーゼン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | マインツ | マインツ | マインツ | マインツ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | エルバースベルク | エルフェアスベルク | エルフェアスベルク | エルフェアスベルク | 現在のスポーツ紙・配信の表記を採用。旧表記も別名として認識。 [媒体例](https://www.nikkansports.com/soccer/world/news/202505270000273.html) |
| BL1 | ブレーメン | ブレーメン | ブレーメン | ブレーメン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | ライプツィヒ | ライプツィヒ | ライプツィヒ | ライプツィヒ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | フランクフルト | フランクフルト | フランクフルト | フランクフルト | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | シャルケ | シャルケ | シャルケ | シャルケ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | パーダーボルン | パーダーボルン | パーダーボルン | パーダーボルン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | ケルン | ケルン | ケルン | ケルン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | ホッフェンハイム | ホッフェンハイム | ホッフェンハイム | ホッフェンハイム | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | シュツットガルト | シュツットガルト | シュツットガルト | シュツットガルト | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | ハンブルガーSV | ハンブルガーSV | ハンブルク | ハンブルガーエスブイ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | ウニオン・ベルリン | ウニオン・ベルリン | ウニオン | ウニオンベルリン | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| BL1 | ボルシアMG | ボルシアMG | ボルシアMG | ボルシアメンヒェングラートバッハ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/germany/data/standings/) |
| FL1 | モナコ | モナコ | モナコ | モナコ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | リヨン | リヨン | リヨン | リヨン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | パリFC | パリFC | パリFC | パリエフシー | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | リール | リール | リール | リール | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | レンヌ | レンヌ | レンヌ | レンヌ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | パリ・サンジェルマン | パリ・サンジェルマン | PSG | パリサンジェルマン | 長い正式形は中黒を保持。狭い欄の短縮名を別に指定。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | アンジェ | アンジェ | アンジェ | アンジェ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | ストラスブール | ストラスブール | ストラスブール | ストラスブール | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | ル・マン | ルマン | ルマン | ルマン | 冠詞と名を続ける新聞表記を採用。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | オセール | オセール | オセール | オセール | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | ブレスト | ブレスト | ブレスト | ブレスト | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | ロリアン | ロリアン | ロリアン | ロリアン | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | トゥールーズ | トゥールーズ | トゥールーズ | トゥールーズ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | ニース | ニース | ニース | ニース | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | ランス | ランス | ランス | ランス | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | トロワ | トロワ | トロワ | トロワ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | マルセイユ | マルセイユ | マルセイユ | マルセイユ | 一般的な短い呼称を維持。中黒を機械的に足さない。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |
| FL1 | ル・アーブル | ルアーブル | ルアーブル | ルアーブル | 冠詞と名を続ける新聞表記を採用。 [媒体例](https://www.nikkansports.com/soccer/world/france/data/standings/) |

ラ・リーガのフル表記の例は [WOWOW](https://www.wowow.co.jp/detail/113938/189) も参照。表示名は既存の呼称を出発点に媒体の短名を併用し、中黒の一律削除はしない。長い名前は短名へ、さらに必要なら最小18pxまで縮小。BREのような異なるクラブで共有される略称だけからはクラブを決めない。

## 96クラブの外にある既存名簿の呼称

- バーンリー → バーンリー（短名 バーンリー、読み バーンリー）。既存のJP_PLAYERS_SOCCERから。今の所属を新しく確認した意味ではない。
- サウサンプトン → サウサンプトン（短名 サウサンプトン、読み サウサンプトン）。既存のJP_PLAYERS_SOCCERから。今の所属を新しく確認した意味ではない。
- QPR → QPR（短名 QPR、読み QPR）。既存のJP_PLAYERS_SOCCERから。今の所属を新しく確認した意味ではない。
- ブラックバーン → ブラックバーン（短名 ブラックバーン、読み ブラックバーン）。既存のJP_PLAYERS_SOCCERから。今の所属を新しく確認した意味ではない。
- ボルトン → ボルトン（短名 ボルトン、読み ボルトン）。既存のJP_PLAYERS_SOCCERから。今の所属を新しく確認した意味ではない。
- バーミンガム → バーミンガム（短名 バーミンガム、読み バーミンガム）。既存のJP_PLAYERS_SOCCERから。今の所属を新しく確認した意味ではない。
- ブリストル・シティ → ブリストル・シティ（短名 ブリストル・シティ、読み ブリストルシティ）。既存のJP_PLAYERS_SOCCERから。今の所属を新しく確認した意味ではない。
