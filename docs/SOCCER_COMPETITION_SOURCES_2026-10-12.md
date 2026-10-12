# 大会と取得元（㉝）

確認日: 2026-10-12。現在の取得コードはfootball-data.orgの無料対象5大リーグ＋CL。結果のESPN取得経路も既存。以下は公式の対象表と、今回用意した追加経路を分けた一覧。

|大会|football-data無料枠|今回の追加ESPN経路|実取得の段階|代替案|
|---|---|---|---|---|
|プレミアリーグ|対象 PL|eng.1|既存保存材料あり。今回の再取得は通信制限|既存のfootball-data|
|ラ・リーガ|対象 PD|esp.1|同上|同上|
|ブンデスリーガ|対象 BL1|ger.1|同上|同上|
|セリエA|対象 SA|ita.1|同上|同上|
|リーグ・アン|対象 FL1|fra.1|同上|同上|
|CL|対象 CL|uefa.champions|公式無料対象、追加経路の今回実取得は未確認|既存のfootball-data|
|EL|対象外|uefa.europa|優先して確認を試みたが通信/閲覧制限。経路の実取得は未確認|UEFA公式日程・API-Footballの対象確認|
|カンファレンスL|対象外|uefa.europa.conf|同上|UEFA公式日程・API-Football|
|FA杯|対象外|eng.fa|今回の実取得は未確認|football-data有料の対象/契約確認・API-Football|
|英リーグ杯|対象外|eng.league_cup|同上|同上|
|コパ・デル・レイ|対象外|esp.copa_del_rey|同上|同上|
|DFBポカール|対象外|ger.dfb_pokal|同上|同上|
|コッパ・イタリア|対象外|ita.coppa_italia|同上|同上|
|クープ・ドゥ・フランス|対象外|fra.coupe_de_france|同上|同上|

football-dataの[公式対象](https://www.football-data.org/coverage)と[料金/資料の種類](https://www.football-data.org/pricing)を確認。無料は12大会・日程/順位・遅延スコア。EL/カンファレンス/国内杯は無料一覧に無い。全提供大会一覧にはあるが、現在の鍵/契約が使えることは確かめていない。新規契約・支払い・鍵/変数の変更は行わない。

代替の入口: [UEFA EL公式日程](https://www.uefa.com/uefaeuropaleague/fixtures-results/)、[カンファレンス公式日程](https://www.uefa.com/uefaconferenceleague/fixtures-results/)、[API-Football公式対象表](https://www.api-football.com/coverage)。別のAPIを既に導入した/契約したとは扱わない。

今回のコードはdata/soccer_competitions.jsonの14大会をESPNへ問い合わせ、ホーム/アウェーと時刻を正規化する。EL/カンファレンスを先に問い合わせる。成功した空のeventsと取得失敗を区別。日時とクラブが同じカードは重ねない。正式なラウンド表記があった場合だけ決勝トーナメント加点を付ける。

この環境の直接取得は全14大会URLError。build/coverage-probe.jsonへ記録。ブラウザでのESPN API閲覧も承認審査が「本人が許可を拒否した」として拒否したため、別経路では回避していない。実取得の成功とは報告しない。追加大会の実取得は残り。

登録済みのクラブ名/読みが無い対戦は候補から外してログへ。既存103クラブ（5大リーグ96＋追加7）の外まで名前を推測して付けない。他の有効なカードがあれば動画を続ける。追加する大会の参加クラブが全部対応済みとは扱わない。

新しい経路は取得と正規化の準備・固定材料の検査まで。公開を行っていない。Claude側の通常環境で実取得を確認し、欠けるクラブ名は辞書へ戻してから大会の対応範囲を拡げる。
