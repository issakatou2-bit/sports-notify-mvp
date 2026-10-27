# 画面と遷移の見た目確認

静的検査と実画面の合否は別々に記録する。画素差で合否を決めない。
公開・購読・通知許可・投稿・購入・連携のボタンは押さない。
撮影ブラウザは外部通信とGET/HEAD以外を遮断する。

## PWA

スマホ390×844/DPR3、タブレット768×1024/DPR2で全HTMLのページ領域を撮る。
ローカルの保存材料による再現。外部の書体・埋込・解析・通知は遮断し、公開中の最新値とは区別する。
リンクと戻るは各種類1経路。日別アーカイブ・選手詳細は代表1件、他は各ページ。
開始前・操作直後・約60ms後・約240ms後を撮る。撮影自体の遅延があり、全フレームは保証しない。
全リンク組合せを網羅したという意味ではない。実行経路はmanifestへ記録する。
以下の基準パスは保存先の規約。合格済みかはBASELINE.mdを正本とし、存在しない画像を合格扱いしない。

|画面名|行き方|期待の見た目|合格画像のパス|
|---|---|---|---|
|`about.html`|`/about.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/about.html.jpg`|
|`archive/2026-07-25.html`|`/archive/2026-07-25.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-07-25.html.jpg`|
|`archive/2026-07-26.html`|`/archive/2026-07-26.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-07-26.html.jpg`|
|`archive/2026-07-27.html`|`/archive/2026-07-27.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-07-27.html.jpg`|
|`archive/2026-07-28.html`|`/archive/2026-07-28.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-07-28.html.jpg`|
|`archive/2026-07-29.html`|`/archive/2026-07-29.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-07-29.html.jpg`|
|`archive/2026-07-30.html`|`/archive/2026-07-30.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-07-30.html.jpg`|
|`archive/2026-07-31.html`|`/archive/2026-07-31.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-07-31.html.jpg`|
|`archive/2026-08-01.html`|`/archive/2026-08-01.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-01.html.jpg`|
|`archive/2026-08-02.html`|`/archive/2026-08-02.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-02.html.jpg`|
|`archive/2026-08-03.html`|`/archive/2026-08-03.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-03.html.jpg`|
|`archive/2026-08-04.html`|`/archive/2026-08-04.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-04.html.jpg`|
|`archive/2026-08-05.html`|`/archive/2026-08-05.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-05.html.jpg`|
|`archive/2026-08-06.html`|`/archive/2026-08-06.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-06.html.jpg`|
|`archive/2026-08-07.html`|`/archive/2026-08-07.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-07.html.jpg`|
|`archive/2026-08-08.html`|`/archive/2026-08-08.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-08.html.jpg`|
|`archive/2026-08-09.html`|`/archive/2026-08-09.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-09.html.jpg`|
|`archive/2026-08-10.html`|`/archive/2026-08-10.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-10.html.jpg`|
|`archive/2026-08-11.html`|`/archive/2026-08-11.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-11.html.jpg`|
|`archive/2026-08-13.html`|`/archive/2026-08-13.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-13.html.jpg`|
|`archive/2026-08-14.html`|`/archive/2026-08-14.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-14.html.jpg`|
|`archive/2026-08-15.html`|`/archive/2026-08-15.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-15.html.jpg`|
|`archive/2026-08-16.html`|`/archive/2026-08-16.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-16.html.jpg`|
|`archive/2026-08-17.html`|`/archive/2026-08-17.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-17.html.jpg`|
|`archive/2026-08-18.html`|`/archive/2026-08-18.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-18.html.jpg`|
|`archive/2026-08-19.html`|`/archive/2026-08-19.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-19.html.jpg`|
|`archive/2026-08-20.html`|`/archive/2026-08-20.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-20.html.jpg`|
|`archive/2026-08-21.html`|`/archive/2026-08-21.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-21.html.jpg`|
|`archive/2026-08-22.html`|`/archive/2026-08-22.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-22.html.jpg`|
|`archive/2026-08-23.html`|`/archive/2026-08-23.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-23.html.jpg`|
|`archive/2026-08-24.html`|`/archive/2026-08-24.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-24.html.jpg`|
|`archive/2026-08-25.html`|`/archive/2026-08-25.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-25.html.jpg`|
|`archive/2026-08-26.html`|`/archive/2026-08-26.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-26.html.jpg`|
|`archive/2026-08-27.html`|`/archive/2026-08-27.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-27.html.jpg`|
|`archive/2026-08-28.html`|`/archive/2026-08-28.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-28.html.jpg`|
|`archive/2026-08-29.html`|`/archive/2026-08-29.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-29.html.jpg`|
|`archive/2026-08-30.html`|`/archive/2026-08-30.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-30.html.jpg`|
|`archive/2026-08-31.html`|`/archive/2026-08-31.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-08-31.html.jpg`|
|`archive/2026-09-01.html`|`/archive/2026-09-01.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-01.html.jpg`|
|`archive/2026-09-02.html`|`/archive/2026-09-02.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-02.html.jpg`|
|`archive/2026-09-03.html`|`/archive/2026-09-03.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-03.html.jpg`|
|`archive/2026-09-04.html`|`/archive/2026-09-04.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-04.html.jpg`|
|`archive/2026-09-05.html`|`/archive/2026-09-05.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-05.html.jpg`|
|`archive/2026-09-06.html`|`/archive/2026-09-06.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-06.html.jpg`|
|`archive/2026-09-07.html`|`/archive/2026-09-07.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-07.html.jpg`|
|`archive/2026-09-08.html`|`/archive/2026-09-08.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-08.html.jpg`|
|`archive/2026-09-09.html`|`/archive/2026-09-09.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-09.html.jpg`|
|`archive/2026-09-10.html`|`/archive/2026-09-10.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-10.html.jpg`|
|`archive/2026-09-11.html`|`/archive/2026-09-11.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-11.html.jpg`|
|`archive/2026-09-12.html`|`/archive/2026-09-12.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-12.html.jpg`|
|`archive/2026-09-13.html`|`/archive/2026-09-13.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-13.html.jpg`|
|`archive/2026-09-14.html`|`/archive/2026-09-14.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-14.html.jpg`|
|`archive/2026-09-15.html`|`/archive/2026-09-15.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-15.html.jpg`|
|`archive/2026-09-16.html`|`/archive/2026-09-16.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-16.html.jpg`|
|`archive/2026-09-17.html`|`/archive/2026-09-17.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-17.html.jpg`|
|`archive/2026-09-18.html`|`/archive/2026-09-18.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-18.html.jpg`|
|`archive/2026-09-19.html`|`/archive/2026-09-19.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-19.html.jpg`|
|`archive/2026-09-20.html`|`/archive/2026-09-20.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-20.html.jpg`|
|`archive/2026-09-21.html`|`/archive/2026-09-21.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-21.html.jpg`|
|`archive/2026-09-22.html`|`/archive/2026-09-22.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-22.html.jpg`|
|`archive/2026-09-23.html`|`/archive/2026-09-23.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-23.html.jpg`|
|`archive/2026-09-24.html`|`/archive/2026-09-24.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-24.html.jpg`|
|`archive/2026-09-25.html`|`/archive/2026-09-25.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-25.html.jpg`|
|`archive/2026-09-26.html`|`/archive/2026-09-26.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-26.html.jpg`|
|`archive/2026-09-27.html`|`/archive/2026-09-27.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-27.html.jpg`|
|`archive/2026-09-28.html`|`/archive/2026-09-28.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-28.html.jpg`|
|`archive/2026-09-29.html`|`/archive/2026-09-29.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-29.html.jpg`|
|`archive/2026-09-30.html`|`/archive/2026-09-30.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-09-30.html.jpg`|
|`archive/2026-10-01.html`|`/archive/2026-10-01.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-01.html.jpg`|
|`archive/2026-10-02.html`|`/archive/2026-10-02.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-02.html.jpg`|
|`archive/2026-10-03.html`|`/archive/2026-10-03.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-03.html.jpg`|
|`archive/2026-10-04.html`|`/archive/2026-10-04.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-04.html.jpg`|
|`archive/2026-10-05.html`|`/archive/2026-10-05.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-05.html.jpg`|
|`archive/2026-10-06.html`|`/archive/2026-10-06.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-06.html.jpg`|
|`archive/2026-10-07.html`|`/archive/2026-10-07.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-07.html.jpg`|
|`archive/2026-10-08.html`|`/archive/2026-10-08.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-08.html.jpg`|
|`archive/2026-10-09.html`|`/archive/2026-10-09.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-09.html.jpg`|
|`archive/2026-10-10.html`|`/archive/2026-10-10.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-10.html.jpg`|
|`archive/2026-10-11.html`|`/archive/2026-10-11.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-11.html.jpg`|
|`archive/2026-10-12.html`|`/archive/2026-10-12.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-12.html.jpg`|
|`archive/2026-10-13.html`|`/archive/2026-10-13.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-13.html.jpg`|
|`archive/2026-10-14.html`|`/archive/2026-10-14.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-14.html.jpg`|
|`archive/2026-10-15.html`|`/archive/2026-10-15.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-15.html.jpg`|
|`archive/2026-10-16.html`|`/archive/2026-10-16.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-16.html.jpg`|
|`archive/2026-10-17.html`|`/archive/2026-10-17.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-17.html.jpg`|
|`archive/2026-10-18.html`|`/archive/2026-10-18.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-18.html.jpg`|
|`archive/2026-10-19.html`|`/archive/2026-10-19.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-19.html.jpg`|
|`archive/2026-10-20.html`|`/archive/2026-10-20.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-20.html.jpg`|
|`archive/2026-10-21.html`|`/archive/2026-10-21.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-21.html.jpg`|
|`archive/2026-10-22.html`|`/archive/2026-10-22.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-22.html.jpg`|
|`archive/2026-10-23.html`|`/archive/2026-10-23.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-23.html.jpg`|
|`archive/2026-10-24.html`|`/archive/2026-10-24.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-24.html.jpg`|
|`archive/2026-10-25.html`|`/archive/2026-10-25.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-25.html.jpg`|
|`archive/2026-10-26.html`|`/archive/2026-10-26.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/2026-10-26.html.jpg`|
|`archive/index.html`|`/archive/index.html` の直開き、安全なリンクと戻る|日付・対戦・出典が読め、前後日へ移れる|`build/visual-baseline/pwa/{phone,tablet}/archive/index.html.jpg`|
|`contact.html`|`/contact.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/contact.html.jpg`|
|`football-competitions.html`|`/football-competitions.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/football-competitions.html.jpg`|
|`glossary.html`|`/glossary.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/glossary.html.jpg`|
|`googled4e966dc0b088ef6.html`|`/googled4e966dc0b088ef6.html` の直開き、安全なリンクと戻る|所有権確認文字列のみ|`build/visual-baseline/pwa/{phone,tablet}/googled4e966dc0b088ef6.html.jpg`|
|`index.html`|`/index.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/index.html.jpg`|
|`lineup.html`|`/lineup.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/lineup.html.jpg`|
|`players/index.html`|`/players/index.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/index.html.jpg`|
|`players/kazuma-okamoto.html`|`/players/kazuma-okamoto.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/kazuma-okamoto.html.jpg`|
|`players/kodai-senga.html`|`/players/kodai-senga.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/kodai-senga.html.jpg`|
|`players/lars-nootbaar.html`|`/players/lars-nootbaar.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/lars-nootbaar.html.jpg`|
|`players/masataka-yoshida.html`|`/players/masataka-yoshida.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/masataka-yoshida.html.jpg`|
|`players/munetaka-murakami.html`|`/players/munetaka-murakami.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/munetaka-murakami.html.jpg`|
|`players/roki-sasaki.html`|`/players/roki-sasaki.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/roki-sasaki.html.jpg`|
|`players/seiya-suzuki.html`|`/players/seiya-suzuki.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/seiya-suzuki.html.jpg`|
|`players/shohei-ohtani.html`|`/players/shohei-ohtani.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/shohei-ohtani.html.jpg`|
|`players/shota-imanaga.html`|`/players/shota-imanaga.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/shota-imanaga.html.jpg`|
|`players/tatsuya-imai.html`|`/players/tatsuya-imai.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/tatsuya-imai.html.jpg`|
|`players/tomoyuki-sugano.html`|`/players/tomoyuki-sugano.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/tomoyuki-sugano.html.jpg`|
|`players/yoshinobu-yamamoto.html`|`/players/yoshinobu-yamamoto.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/yoshinobu-yamamoto.html.jpg`|
|`players/yuki-matsui.html`|`/players/yuki-matsui.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/yuki-matsui.html.jpg`|
|`players/yusei-kikuchi.html`|`/players/yusei-kikuchi.html` の直開き、安全なリンクと戻る|氏名・所属・記録・動画札が読める|`build/visual-baseline/pwa/{phone,tablet}/players/yusei-kikuchi.html.jpg`|
|`privacy.html`|`/privacy.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/privacy.html.jpg`|
|`quiz.html`|`/quiz.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/quiz.html.jpg`|
|`score.html`|`/score.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/score.html.jpg`|
|`services.html`|`/services.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/services.html.jpg`|
|`soccer.html`|`/soccer.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/soccer.html.jpg`|
|`sports-reading.html`|`/sports-reading.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/sports-reading.html.jpg`|
|`standings.html`|`/standings.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/standings.html.jpg`|
|`team-post-guide.html`|`/team-post-guide.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/team-post-guide.html.jpg`|
|`terms.html`|`/terms.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/terms.html.jpg`|
|`threads/callback.html`|`/threads/callback.html` の直開き、安全なリンクと戻る|未認証案内。連携や投稿を実行しない|`build/visual-baseline/pwa/{phone,tablet}/threads/callback.html.jpg`|
|`threads/index.html`|`/threads/index.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/threads/index.html.jpg`|
|`tiktok/callback.html`|`/tiktok/callback.html` の直開き、安全なリンクと戻る|未認証案内。連携や投稿を実行しない|`build/visual-baseline/pwa/{phone,tablet}/tiktok/callback.html.jpg`|
|`tiktok/index.html`|`/tiktok/index.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/tiktok/index.html.jpg`|
|`watch-champions-league.html`|`/watch-champions-league.html` の直開き、安全なリンクと戻る|見出し・本文・表・ボタンが収まり、読みやすい。空/失敗の状態を区別|`build/visual-baseline/pwa/{phone,tablet}/watch-champions-league.html.jpg`|

## 動画

「朝の4本」は現在のファイル名morning_recap.yml、Actions表示は「夕方の4本」。同じ4種類として扱う。
各mp4の頭・中・終わり、場面切替前後、字幕が表や顔に近づく候補を一覧にする。
初回は保存済みサッカー結果1本。他の種類は未撮影・未合格で、基準パスは今後の置き場を示す。

|画面名|行き方|期待の見た目|合格画像のパス|
|---|---|---|---|
|朝4本・選手成績|morning_recap.yml / players の完成mp4|氏名と数字、小さな胸上キャラ|`build/visual-baseline/video/morning-players-contact-*.jpg`|
|朝4本・PS|morning_recap.yml / postseason の完成mp4|全カードと現在地、表と字幕が分離|`build/visual-baseline/video/morning-postseason-contact-*.jpg`|
|朝4本・現地の声|morning_recap.yml / voices の完成mp4|引用と出典が字幕と分離|`build/visual-baseline/video/morning-voices-contact-*.jpg`|
|朝4本・報道|morning_recap.yml / press の完成mp4|見出しと出典を読める|`build/visual-baseline/video/morning-press-contact-*.jpg`|
|夕方の注目試合|daily_notify.yml の完成mp4|対戦・時刻・見どころ|`build/visual-baseline/video/evening-contact-*.jpg`|
|サッカー結果|soccer_results.yml の完成mp4|結果→得点→日本人→名簿|`build/visual-baseline/current-render/{00-intro,01-result,02-roster}.jpg`|
|サッカー予告|soccer_daily.yml の完成mp4|対戦・開始時刻・出典|`build/visual-baseline/video/soccer-preview-contact-*.jpg`|
|サッカー順位|soccer_race.yml の完成mp4|順位・差・時点・出典|`build/visual-baseline/video/soccer-race-contact-*.jpg`|
|サッカー週末|soccer_week.yml の完成mp4|日程と注目カード|`build/visual-baseline/video/soccer-week-contact-*.jpg`|
|サッカー得点ショート|soccer_goal_short.yml の完成mp4|冒頭の得点・得点者・出典|`build/visual-baseline/video/soccer-goal-contact-*.jpg`|
|資産|asset_video.yml の完成mp4|主情報・出典・登録題材|`build/visual-baseline/video/asset-contact-*.jpg`|
|長編|longform.yml の完成mp4|章・表・引用・字幕・キャラの分離|`build/visual-baseline/video/longform-contact-*.jpg`|

## 手順

```powershell
python scripts/visual_prepare_site.py --fetch-standings
python scripts/visual_capture.py pwa --site build/visual/site
python scripts/visual_capture.py video --video build/example.mp4
python scripts/visual_capture.py compare --current build/visual/20261027
python scripts/visual_capture.py layout --input scripts/fixtures/visual/example-layout.json
python scripts/run_checks.py
```

PWAのみ `pip install playwright` と `python -m playwright install chromium` が必要。
PWA用の依存一覧は `scripts/requirements-visual.txt`。
既存ブラウザは `--browser`。動画にはPATH上のffmpeg/ffprobeが必要。共通動画依存にPlaywrightを追加しない。
撮影は1つずつ。出力はbuild/visual/日付/。比較は左が前回、右が今回。
review.jsonのdifference欄に違い・理由・対象画像を書き、verdictに合格/不合格/未確認を記録。
合格した画像だけ同じ相対パスで基準へ写す。自動昇格しない。サイズ・材料・外部通信条件も合わせる。

`--timeline` は `{"scenes":[{"start":0,"end":3}],"proximity_times":[1.2]}`。
正確な場面境界・接近時刻を制作側から渡せる。未指定時は縮小場面差＋10秒区間と、字幕・顔・表の境界帯のエッジ密度最大の1秒刻み候補を各区間から採る。
候補は意味認識ではない。緩い切替や1秒未満の接近は目視/明示時刻で補う。
抽出画像はメモリ上で逐次縮小し、ディスクに一切保存しない。Actionsで個別画像を消す必要自体をなくす。
一覧は24コマずつ分割し、上限で切り捨てない。

## 観点と失敗の還元

- 文字の欠け・重なり・はみ出し、色崩れ、大きな空き、ボタン位置、遷移の暗転/ちらつき。
- 出典と字幕、記号/札と顔、キャラの内向き、生の値、数字の最大幅予約、画面途中の体の切れ目。
- fixtures/visual/failures.jsonは各失敗の矩形・向き・数字最大幅を保存。layoutコマンドは指定した避ける組の重なり・はみ出し・空きを検査する。
- DOMの候補抽出は別に記録する。意図したスクロール/装飾には誤検出もある。静的合格だけでは目視合格にしない。
- 完成mp4から意味付き領域を復元できたとは扱わない。制作側が領域を出せる時に同形式で渡す。見つけた実崩れは画像・矩形・修正後をfixturesへ戻す。

## CI

soccer_resultsとmorning_recapの書出し後へ撮影を追加。時間超過/失敗は公開を止めない。
新しいartifactは一覧JPEGのみ、7日保存。元の動画artifact・公開条件は維持。
checks.ymlのPWA撮影追加は今回行わず、初回報告の実測を基に案だけとする。

## 操作状態の一覧

`python scripts/visual_capture.py pwa --site build/visual/site --states-only` も両端末で実行する。
基準画像の先頭は `build/visual-baseline/states/pwa-states/{phone,tablet}/`。
クリック前・途中3枚も同じ所へ保存する。静的候補と目視判定は別記録。

|画面名|行き方|期待の見た目|合格画像のパス（上記を先頭に付ける）|
|---|---|---|---|
|メニュー|開く→Escape|メニューと閉じる印、戻った本文|`home-menu.jpg`|
|サッカー|欧州サッカータブ|選択中の線と当該競技|`home-soccer.jpg`|
|MLB|MLBタブ|MLBへ戻る|`home-mlb.jpg`|
|ダーク|表示→ダーク|背景・文字・ボタンが読める|`home-dark.jpg`|
|ライト|表示→ライト|背景・文字・ボタンが読める|`home-light.jpg`|
|端末の配色|表示→端末に合わせる|端末の配色で読める|`home-system.jpg`|
|取得失敗|games取得を遮断して再読込|失敗案内、崩れない本文|`home-fetch-failed.jpg`|
|取得復旧|取得を復旧して再読込|試合一覧が戻る|`home-fetch-recovered.jpg`|
|検索一致|MLBを入力|一致する日付|`archive-found.jpg`|
|検索0件|一致しない語を入力|0件の案内|`archive-empty.jpg`|
|検索解除|検索欄を空にする|一覧が戻る|`archive-cleared.jpg`|
|クイズ問題|クイズを開く|問題と4選択肢|`quiz-question.jpg`|
|クイズ誤答|不正解を選ぶ|赤い回答、正解と補足|`quiz-wrong.jpg`|
|クイズ次問|次の問題|次の番号と選択肢|`quiz-next.jpg`|
|クイズ正解|正解を選ぶ|緑の正解と補足|`quiz-correct.jpg`|
|クイズ結果|8問進める|得点と再挑戦|`quiz-result.jpg`|
|クイズ再挑戦|もう一度挑戦|1問目に戻る|`quiz-retry.jpg`|
|編成の未取得|成績がない状態で開く|未取得案内、保存編成を保持|`lineup-missing-data.jpg`|
|選手候補|明示した架空材料で枠を選ぶ|ダイアログと候補|`lineup-picker.jpg`|
|選手を選択|候補を選ぶ|枠と値が表示される|`lineup-selected.jpg`|
|おまかせ|おまかせ編成|各枠が収まる|`lineup-random.jpg`|
|編成解除|クリア|空の枠に戻る|`lineup-cleared.jpg`|
|配色を保った遷移|ライトのトップ→日本人選手|ライトを保持|10/27改修後：`build/visual-fixes/themes-final/pwa-states/{phone,tablet}/theme-light-to-players.png`。旧失敗例はfixturesに保持|

初版の比較JPEGはCSS幅へ縮小。DPR3/2の原寸PNGはbuild側に保持する。
公式順位表を取れない場合は、明示的に `visual_prepare_site.py --standings-fixture` で架空材料を使える。
既存rendererのverification.jsonにv3_layoutがあれば、動画撮影時にその範囲の重なり・はみ出し・空きを静的候補として別記録する。

サッカー結果の初版は現行main既定v4の停止後の静止画3枚だけ。締めの体の切れ目を目視で不合格としたため、完成動画の合格とは区別する。詳細は初回報告。

## 10/27の不合格2点の修正確認

生成headは `site_theme.THEME_HEAD` で静的ページと同じ `/site-theme.js` と
`/site-theme.css` を読む。CSSはページ固有のstyleより後、スクリプトは初回描画前に実行する。
一覧・詳細・日別アーカイブ・score/soccer/standingsと連携案内も同じ保存値を使用する。
履歴から戻ったページもpageshowで保存値を読み直す。所有確認用の一行HTMLは表示ページの対象外。

`--states-only --state-groups theme-nav` は両サイズでライト、ダーク、端末連動の明暗を撮る。
トップで選択→選手一覧→選手詳細→戻る→アーカイブ一覧→score→soccer→standings→日別へ進む。
手動の明暗は端末設定と逆にして優先順位を確かめ、各到着の保存値・適用値・背景色をmanifestに残す。
連携・投稿のボタンは押さない。撮影先の日付は保存材料のPOSIX相対パスから取り出す。

`python scripts/preview_visual_fixes.py` は保存ESPN材料（2026-09-20）から
v6とv4それぞれの冒頭・結果・名簿・締めを3秒地点の静止画として描く。
字幕がない締めは共通の立ち絵を画面下端へ、v6通常場面は切れ目を字幕の箱の下へ置く。
既存の札・字幕幅・字サイズ・表情素材は維持する。
実描画の立ち絵矩形は `visual_capture.renderer_layout` で締めのbody-cut検査に渡す。
`test_visual_fixes.py` は失敗fixtureの検出と、v6/v4の実描画の合格・再び浮かせた時の不合格を確認する。
日本語を含む判定文の生成処理はUTF-8の.pyへ保存して実行し、PowerShellのパイプに直接流さない。
同試験で差し替え一覧の見出し・inventoryの「合格」表記と`???`への文字化けも検査する。

今回の撮影・目視の範囲、基準126枚の差し替え一覧と検査結果は
`build_reports/visual_fixes_20261027.md` を参照する。完成動画・音声・実公開の合格とは区別する。
