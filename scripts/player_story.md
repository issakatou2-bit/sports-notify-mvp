# 日本人選手のいまの流れ

既存の夕方4本を変えず、独立した `player_story.yml` で17:10 JSTに判定する。
`COLLESPO_PLAYER_STORY=on` のときだけ生成し、さらに `PLAYER_STORY_PUBLISH=true` のときだけ投稿する。どちらも既定オフ。
手動実行でも両変数が必要。投稿処理自身にも同じガードがあり、日付ごとの重複投稿を既存台帳で防ぐ。

基準・締め・表情は `player_story.py:RULES`、安全に訳せる報道の型は `REPORT_RULES` が決定元。
直近5試合中、最低3試合・12打数で判定。3試合連続無安打/複数安打、または今季100打数以上の打率との0.120差を拾う。
投手は最低3登板・9回、今季30回以上との防御率差2.00以上を拾う。投球回は整数のアウト数に変換し、被安打を安打と混同しない。
公式APIの試合別記録はレギュラーシーズンとPSを集め、重複試合を除き日付順で直近を使う。比較水準は今季レギュラーシーズンと明記する。

数字の流れか本人に関する現地報道がなければ出さない。球団の言及数・gist、ファンの声だけでは出さない。
保存材料の時刻から48時間まで、未来の報道は除外。試合日も古ければ数字の流れを採用しない。
現地報道は現在、休養協議と先発予定の明示を対象とする。未対応の言い回し・疑問・否定・複数日本人選手への言及は安全側で見送る。
取得不能は警告を残し、数字をゼロに置き換えない。今後の報道の型は固定試験材料と一緒に増やす。
続報がある場合は古い協議→最新の同じ試合番号の先発報道を順に出す。
型訳は「報じられています」を必ず保つ。保存された日本語訳やLLMで原因・けが・心理を補わない。
ファンの声は本人名が明示される短い感想/応援だけ最大2件。原因・けが・心理・断定的な予測は除外し、感想と明記する。一般の投稿者名を原稿・画面・説明に渡さない。

声は既存VOICEVOXと音声結合、画面は既存v4の背景・札・字幕・胸上の下隅キャラを使う。
不調は既存の `jitome`（困り眉）と `sweat`、好調は `pose-smile` と `sparkle`。
表情を実際に変えるのは既存仕様通り `COLLESPO_EXPR=fan` のときだけ。新しい顔素材は作らない。
書体は同梱のNoto Sans JPとOswaldだけを使用。声なし・音声と原稿の不一致・60秒超・文字の欠落/はみ出しは停止する。

保存試作（本番投稿なし）:

```powershell
$env:COLLESPO_PLAYER_STORY='on'
$env:COLLESPO_EXPR='fan'
& C:/Users/issak/AppData/Local/Programs/Python/Python314/python.exe scripts/player_story.py --recap scripts/fixtures/player_story/recap_20261013.json --reporters scripts/fixtures/player_story/reporters_20261014.json --voices scripts/fixtures/player_story/voices_20261014.json --as-of 2026-10-14T04:00:00Z --out ../player-story-preview/narration.json
& C:/Users/issak/AppData/Local/Programs/Python/Python314/python.exe scripts/synthesize_narration.py --narration ../player-story-preview/narration.json --out-dir ../player-story-preview/audio
& C:/Users/issak/AppData/Local/Programs/Python/Python314/python.exe scripts/player_story_render.py --narration ../player-story-preview/narration.json --audio-dir ../player-story-preview/audio --out ../player-story-preview
```

試作の入力は10/14にmainへ保存されていた記者/見出しと10/13取得の成績から固定した。
「休ませることを協議」のあとに「第3戦も先発予定」という続報が保存されているため、両方扱う。
不調の締めはCBS Sportsの保存見出しの `despite struggles` が根拠（説明欄にも原文/時点/URL）。休養検討だけなら中立の応援にする。
当日の保存材料から大谷の打席への匿名の感想を1件使う。最後の復調を願う言葉はチャンネルの応援として区別する。
実データのライブ取得、CI、本人の試作採用、公開結果は手元の検査と別段階。
