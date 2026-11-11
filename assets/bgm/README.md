# ショートのBGM

`scripts/make_bgm.py` で組み立てた（2026-10-06、エマ）。生成AIは使っていない。

- 材料: 数式の合成と、自由に使える録音 VSCO 2 CE（CC0）・Growlybass（CC0）。表記の要る録音は使っていない。
- どれも16小節で継ぎ目なくループする。平均 -14dB。声の帯域（1.5〜4kHz）を少し下げてある。
- 本番では `scripts/sound_mix.py` が声より20dB小さく重ね、声の間はさらに6dB下げる。

| ファイル | 名前 | 向き |
|---|---|---|
| everyday.mp3 | 日常（104 BPM・マリンバと鉄琴の旋律、ハ長調） | 既定（10/6 本人「軽い音がメロディを奏でる、あっさりした長調」） |
| scoreboard.mp3 | スコアボード（112 BPM・軽い電子音） | 試合の話題・2勝0敗の話題 |
| nighter.mp3 | ナイター（84 BPM・ピアノのローファイ） | シーズンまとめ・コメントの回 |
| dugout.mp3 | ダッグアウト（100 BPM・オルガンと手拍子） | 予告・情勢 |
| comeback.mp3 | 逆襲（96 BPM・弦の刻み） | どん底からの話 |

材料（topics の JSON）の `"bgm": "nighter"` で回ごとに選べる。

## 11/10〜 Google Lyria で作った曲（新しい見た目用）

本人 11/10「BGMもそろそろ刷新したい」、Vertex の Lyria 3 Pro（lyria-3-pro-preview）を上限5ドルで了承（11/10）。
Google Cloud の生成AIプレビューの追加規約（2026/9/24 版、https://cloud.google.com/terms/genai-preview-products）で、
Lyria 3 Pro は「評価目的に限る・第三者に出さない」の制限の対象外の一覧に入っている（11/11 Claude が原文で確認）。

| ファイル | 名前 | 向き |
|---|---|---|
| briefing.mp3 | ブリーフィング（108 BPM・落ち着いた電子音、声なし） | 新しい見た目の数字の回（代表から）。24小節53.3秒で1周 |

声が入っていないことは Demucs（声を分けて伴奏比 -20dB 超の秒を数える）と Gemini で確かめた。
作り直すときは「stadium」など歓声を呼ぶ語を使わず、「no vocals, no crowd, no sound effects」と書く。
