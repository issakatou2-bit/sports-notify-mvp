# 保存記録から動画検査の入力を作る

```powershell
python scripts/av_check_inputs.py --video build/episode/video.mp4 --render-timeline build/episode/video/render_timeline.json --voice-manifest build/episode/video/voice_manifest.json --review build/episode/review.json --out build/episode/inputs-new
python C:/Users/issak/Tools/heavy-guard/heavy_wait.py --minutes 5 -- python scripts/gemini_av_check.py --video build/episode/video.mp4 --script build/episode/inputs-new/timeline.json --provenance build/episode/inputs-new/provenance.json --out build/episode/preflight-new --dry-run
```

変換は音声の長さを使わない。完成動画と記録の指紋・尺、行/画面/字幕の実フレームと秒の一致、全区間の連続性、元行番号と保存音声本文を照合する。抜け・重なり・不一致は補間せず拒否する。意図した合唱は単一行の`source_line_ids`を維持する。声の行を分割せず、字幕ページを`subtitle_pages`と`subtitles`に保存し、`cuts`を字幕切替でも分ける。`source_cut_id`が元の画面番号。声開始/終了の予定差は音声durationから推測しない。

`--review`の省略時は時刻の変換まで行い、出所は「送れない」とする。#269の記録は素材一覧や画像の権利を証明しない。文字札かロゴかを名前だけで判断せず、描画コードとその依存物・全画面を確認する。[ASSET_PROVENANCE.md](ASSET_PROVENANCE.md)の公式・混在・不明を自作に読み替えない。現在の道具は`assets/`の素材を保守的に拒否する。フォントを含む描画コードの依存物も確認対象。レビューJSONの形は以下。安全だと推測して欄を埋めない。

```json
{
  "video_sha256": "完成mp4の指紋",
  "render_timeline_sha256": "使用するrender_timeline.jsonの指紋",
  "all_assets_accounted_for": true,
  "reviewed_cut_ids": [1, 2],
  "drawing_code": [{"path": "描画コード.py", "sha256": "コードの指紋", "evidence": "版・描画経路・依存素材・ロゴ/色札/名前/引用の具体的な確認結果"}],
  "review": {"evidence": "この完成版の全画面と音源・コードを確認した根拠", "official_art": false, "personal_information": false, "secrets": false, "poster_names": false, "unreleased_private_material": false},
  "assets": [{"kind": "rendered_screen", "classification": "self_created", "self_created": true, "path": "cut.png", "sha256": "画面の指紋", "evidence": "描画コードと全画面の出所確認"}]
}
```

`reviewed_cut_ids`は変換後の全`cuts`の番号。画面・BGM・効果音の全素材を`assets`へ記載する。音声は元manifestから自動追加し、WAV/FLACの存在と保存指紋を照合する。レビュー内のpathはレビューJSON基準で、出所JSONには絶対パスを保存する。人の確認内容の真偽を機械だけで証明する仕組みではない。

レビューが無い・禁止の印がある・素材が足りない場合、`conversion.json`に理由を保存して終了1となり、`provenance.json`を作らない。時刻の変換まで成功した場合は`timeline.json`が残る。元の予定雨衣/代役/受領記録は除去しない。毎回新しい空の出力先を指定する。

変換自体はネットワーク・ASR・Gemini・音声抽出・復号を行わない。ffprobeでmp4の尺を読む。送信前の全フレーム復号は既存の`gemini_av_check.py --dry-run`をheavy_wait内で実行する。`preflight_only`は動画内容の合格や公開許可ではない。
