# 変更ファイルから読む桜井スキルの節

1. 作る前に `py -3 scripts/sakurai_map.py scripts/soccer_national_topics.py web/index.html` を実行し、出た節を読む。
2. `--about 冒頭,音` で目印を絞り、`--body` を付けると節の本文も読める。
3. 作った後は右列を完成した画面・音・操作で確かめる。対応表自体は `py -3 scripts/sakurai_map.py --selftest` で点検する。

| パターン | 目印 | #節 | 作った後に見る所 |
| --- | --- | --- | --- |
| `scripts/*_render.py`、`scripts/short_common.py`、`scripts/video_common.py`、`scripts/render_timeline.py` | 描画、冒頭、止め、切替、札、字幕 | #003、#033、#036、#079、#093、#148、#184、#244、#250、#252 | 0秒と1.6秒に主役が読めるか。説明中の静止、切替直後、字幕と出典の重なりを実コマで見る。 |
| `scripts/sound_mix.py`、`scripts/sfx.py`、`scripts/short_common.py` | 音、声、BGM、効果音、鳴る時刻 | #025、#032、#054、#089、#165、#183、#255 | 完成音をスマホ内蔵とイヤホンで聞く。核心の札で鳴る時刻と、声が埋もれないかを見る。 |
| `scripts/upload_youtube.py`、`scripts/generate_thumbnail.py`、`scripts/shorts_thumbnail.sh`、`scripts/video_titles.py`、`scripts/opening_alignment.py` | 題、説明欄、サムネ、冒頭 | #033、#101、#150、#184、#224 | 確定題・縮小サムネ・最初の2区間・説明欄冒頭で、対象と数字が同じかを見る。 |
| `scripts/soccer_national_topics.py`、`scripts/soccer_national.py`、`scripts/generate_morning_short.py`、`scripts/generate_narration.py`、`scripts/generate_asset_video.py`、`scripts/generate_dialogue.py`、`scripts/short_renewal.py`、`scripts/ps_program.py` | 台本、冒頭の事実、見どころ、根拠、締め | #009、#012、#017、#101、#105、#149、#185、#233、#248 | 誰の何かが早く分かるか。予告の見る理由と結果で変わった点が、確認した事実から伝わるか。 |
| `web/**` | ホーム、案内、読み込み、通知、操作、文字 | #018、#033、#055、#078、#104、#141、#145、#167、#212、#227 | スマホで注目試合に着けるか。失敗表示と通知の再試行、キーボード操作、文字拡大を確かめる。 |
