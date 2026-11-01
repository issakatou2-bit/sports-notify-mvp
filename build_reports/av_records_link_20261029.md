# 保存記録とGemini動画検査の接続（2026-10-29）

**press.mp4は送れない。ASR・Gemini・外部送信・鍵の読取・pushは行っていない。**

## 作業場所と変更

- worktree: `C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/wt-av-records-link`
- 枝: `hiro/av-records-link-20261029`、起点は取得済み`origin/main 63764ba392d1c97ca5b2107c7d0221fca8dcf994`（#272）。ネットワークからmainを更新していない。
- 元の`.git`は書込不可だったため、既存objectsを参照する専用`build/codex/tmp/av-records-repository.git`でworktreeを管理。cloneしていない。共有コピーの他担当の未コミット差分は変更していない。
- `scripts/av_check_inputs.py`: 動画・記録・保存音声manifestの指紋、実フレーム/秒、末尾、元行と本文を照合。抜け・重なり・不明は補間しない。字幕ページの切替をcutsへ追加する。声の長さから時刻・台詞の分割・予定差を推測しない。
- 出所はコード・全画面・全素材の確認JSONを要求。公式・混在・不明の素材と保存された予定雨衣/代役の印は拒否する。音声manifestを加工して禁止の印を取り除かない。WAVの存在と保存指紋も必須。
- `scripts/gemini_av_check.py --dry-run`: 出所・時刻・全フレーム復号まで。ASR/Gemini/CLIの前で終了。`preflight_only`は内容の合格ではない。
- 使い方: `docs/AV_CHECK_INPUTS.md`、`docs/GEMINI_AV_CHECK.md`。出所の安全性を機械だけで証明したとは扱わない。

## pressの実データで自分で確認した結果

対象は依頼のrun `40834429940`から取り寄せ済みの材料。動画指紋は`f8099210a9d7bc6fc7916b7fdf51c574477ea2f4686572e5a7b52ce99d3b622e`。手元のファイルと描画記録の一致を確認した。GitHub上のrunや公開ページの再確認は行っていない。

- `build/press-inputs-verified/timeline.json`を作成。30fps・1750フレーム、先頭0秒から58.333333秒。6行、元画面6区間、字幕17ページを保持し、全17カットへ変換した。字幕なしの締めも保存。
- `build/press-inputs-verified/conversion.json`は`blocked / provenance`、終了1。「VoiSona経路の入力はASR・Geminiとも禁止」。`provenance.json`は存在しない。
- 保存manifestの全6行は`voice_engine=voicevox, speaker=2`だが、同じ行に`planned_host=ui, planned_engine=voisona`がある。`host_assignment`と`host_delivery.previous_attempt`にも予定雨衣の記録が残る。音声はめたんへの作り直しという記録だが、#267の入口は予定雨衣の代役回も保守的に拒否する。この条件を緩めていない。
- `gemini_av_check.py --dry-run`も実行。`build/press-preflight-verified/result.json`は`blocked`、終了1。「出所JSONがありません。変換の拒否理由を確認してください」。復号・ASR・Geminiより前に止まった。実動画の復号や内容検査が通ったとは扱わない。

## 描画コードから確認した出所の問題

対象版の`press_v3.frame`→`comment_render.unified_comments`→v4引用札の経路を読んだ。

- `short_v4_cards.tag`はpanelとtextで描く色札。球団名・媒体名のある札を、その名前だけで公式ロゴとは判定していない。`team_badge`/`mini_badge`にもコード描画の札がある。動画全体に公式の絵が無いという証明にはしない。
- `press_v3.bubbles`は`outlet`と`author`を組み合わせ、v4では`author`等も引き継ぐ。`short_v4_cards.metadata`/`quotes`は記者名を札として描ける。今回のrender_timelineには本文とページしか残らず、author/全属性札が無い。元の報道材料も同梱されておらず、投稿者名が画面に無いと確定できない。
- `short_v4_cards.finish`から`review_render_v3.presenter`へ進み、`_portrait_v4`は`assets/portraits/collespo-20260923/metan/3-black`等を読む。この系統は`ASSET_PROVENANCE.md`では「生成・コード着彩・局所編集、元の入力条件は未確認」。自作として自動許可しない。
- 入力一式はmp4とJSONだけで、保存WAV、全画面の根拠画像、BGM/SFXを含む完全な素材一覧と出所確認が無い。予定雨衣の印が無くても現材料だけではprovenanceを作れない。

**次の判断:** このpressについて禁止の印を削って送らない。最初から許可対象の声で生成し、描画コード・名前・立ち絵・全音源の出所が確定した別の完成版と、その版の保存記録/音声/レビューを用意する必要がある。今回の道具や報告は送信許可を与えない。

## 自分で確認した試験

- `test_av_check_inputs.py` 20件、既存`test_gemini_av_check.py` 35件、計55件成功。偽素材・偽CLIだけ。抜け/重なり/秒とフレームの矛盾/指紋/元行/公式・不明/投稿者名/予定雨衣/音声欠落/再利用出力/出所不足/正常なdry-runを確認。
- dry-runで出所不備ならsubprocessを呼ばず、正常な偽素材では復号のみを呼び、ASR/Geminiを一切呼ばないことをmockで確認。
- `heavy_wait.py --minutes 5`内で試験と実データ確認を実行。ログは`build/av-link-verification/`。`summary.json`のpress変換/送信前検査は期待どおり終了1。
- `scripts/update_protected_hashes.py --write`: 全指紋一致、書換え不要。`git diff --check`通過。
- 全体run_checks・リモートCI・実ASR・実Gemini・公開結果の確認は未実施。

## Claudeが実行するコマンド（送信しない再確認）

PowerShellで作業場所をworktreeにする。出力先は毎回新しい名前にする。このpressでは変換が終了1で止まり、出所JSONは作られない。レビューを推測して追加しない。

```powershell
Set-Location C:/Users/issak/Desktop/pwa-mvp/build/codex/tmp/wt-av-records-link
$env:PYTHONUTF8='1'
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 5 -- python scripts/av_check_inputs.py --video ../av-press-20261029/shorts/press.mp4 --render-timeline ../av-press-20261029/records/morning/collespo_morning_press/render_timeline.json --voice-manifest ../av-press-20261029/records/morning/collespo_morning_press/voice_manifest.json --out build/press-inputs-claude-new
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 5 -- python scripts/gemini_av_check.py --video ../av-press-20261029/shorts/press.mp4 --script build/press-inputs-claude-new/timeline.json --provenance build/press-inputs-claude-new/provenance.json --out build/press-preflight-claude-new --dry-run
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 5 -- python -m unittest discover -s scripts -p test_av_check_inputs.py -v
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 5 -- python -m unittest discover -s scripts -p test_gemini_av_check.py -v
python scripts/update_protected_hashes.py --write
```

安全な別の完成版が揃った時の`--review`の形は`docs/AV_CHECK_INPUTS.md`。ASR/Geminiを呼ぶコマンドは今回実行していない。
