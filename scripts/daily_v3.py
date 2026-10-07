"""既存の日次原稿を案Dへ。明示指定時のみ、投稿と有料生成は持たない。"""
import os
from pathlib import Path


def prepare(data, narration, mode):
    comments_on = mode == "voices" and os.environ.get("COLLESPO_COMMENTS_DESIGN", "legacy") == "comments"
    press_on = mode == "press" and os.environ.get("COLLESPO_PRESS_DESIGN", "legacy") == "v3"
    if not comments_on and not press_on:
        return None
    import comment_render as cr
    vd = data.get("voices") or {}
    for seg in narration["segments"]:
        kind = seg["kind"]
        supported = {"intro", "headlines", "reporters", "outro"} if press_on else {"intro", "voices", "thread", "outro"}
        if kind not in supported:
            raise ValueError(f"案Dの未対応画面: {kind}")
        if kind in {"voices", "thread"} and not cr.voices_for_segment(seg, vd):
            raise ValueError("読み上げるコメントが画面の材料にありません")
        if press_on:
            import press_v3
            press_v3.bubbles(seg, data.get("reporters") or {})
    # 検査後に全場面の表示・声・表記をそろえる。旧声を使い回さない。
    for seg in narration["segments"]:
        seg["speaker"] = 2
        seg.setdefault("meta", {})["who"] = "四国めたん"
        if seg['kind']=='outro':
            import review_render_v3 as r3
            seg['text']=r3.OUTRO_TEXT
            seg['meta']['lineup_kind']='morning_press' if press_on else 'morning_voices'
    return {"mode": mode, "voices": vd, "reporters": data.get("reporters") or {}}


def frame(t, seg, design, duration):
    if seg['kind']=='outro':
        import v3_slot_render as common
        closing=common.outro(t,{'heading':'コレスポ','v3':{},'text':seg['text']},'morning_press' if design['mode']=='press' else 'morning_voices')
        if closing is not None:
            return closing
    if design["mode"] == "press":
        import press_v3
        return press_v3.frame(t, seg, design["reporters"], duration)
    import comment_render as cr
    vd = design["voices"]
    if seg["kind"] in {"voices", "thread"}:
        return cr.voices_screen(t, seg, vd, duration)
    if seg["kind"] == "intro":
        rows = vd.get("voices") or []
        index = (seg.get('meta') or {}).get('used_voice')
        chosen = rows[index] if type(index) is int and 0 <= index < len(rows) else {}
        match = cr.jp_matchup(chosen.get('matchup',''))
        voices=cr.voices_for_segment(seg,vd)
        if not voices:
            voices=[{'said':seg['text'],'who':'概要','fact':True}]
        return cr.unified_comments(t,cr.reading_times(voices,seg['text'],duration),None,cr.strip_for_voices(vd),
                                   live=match or '現地のファンの声',source_lines=cr._voices_source(vd))
    return cr.unified_comments(t, [{"said": seg["text"], "who": "コレスポ", "fact": True}],
                       None, "", title="コレスポ", live="",
                       source_lines=("音声：VOICEVOX:四国めたん",))


def mix(audio, segments, durations, design, out_dir):
    import comment_render as cr
    import sound_mix
    if any(s.get("speaker") != 2 for s in segments):
        raise ValueError("案Dの音声を四国めたん（話者2）で作り直してください")
    cues, start = [], 0.0
    for seg, dur in zip(segments, durations):
        speech = float(seg.get('duration') or dur)
        if seg['kind']=='outro':
            import review_render_v3 as r3
            local=r3.outro_cues('morning_press' if design['mode']=='press' else 'morning_voices')
        elif design["mode"] == "press":
            import press_v3
            local = press_v3.cues(seg, design["reporters"], speech)
        else:
            local = (cr.voices_cues(seg, design["voices"], speech)
                 if seg["kind"] in {"voices", "thread"}
                 else [(0.0, "transition", "a", -6)])
        cues.extend((start + at, kind, variant, db) for at, kind, variant, db in local)
        start += dur
    bgm = sound_mix.bgm_path()
    if not bgm.exists():
        raise ValueError("案DのBGMがありません")
    print(f"[info] 案D: BGM {bgm.stem}・効果音{len(cues)}個")
    return sound_mix.mix_file(audio, Path(out_dir) / "narration_mixed.wav", bgm_path=bgm, cues=cues)


def validate_audio(segments, narration):
    expected = narration["segments"]
    if len(segments) != len(expected):
        raise ValueError("新デザインの音声区間数が原稿と合いません")
    for actual, wanted in zip(segments, expected):
        if (actual.get("kind"), actual.get("text"), actual.get("speaker")) != (wanted["kind"], wanted["text"], 2):
            raise ValueError("新デザインの音声・話者が原稿と合いません")
