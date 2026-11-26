import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metan_tone
import soccer_result_story as story


def test_results_lines_follow_metan_tone():
    # 11/26 朝：尺の補いで足した「得点が入ったのは、…です。」を関門が止めた。
    segments = [dict(kind='followup-detail', text='得点が入ったのは、15分、62分です。', speaker=2,
                     caption_units=['得点が入ったのは、15分、62分です。'], meta={})]
    with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'metan'}):
        story.tone_segments(segments)
    assert metan_tone.problems(segments[0]['text']) == []
    assert segments[0]['caption_units'] == [segments[0]['text']]


def test_ui_solo_keeps_polite_form():
    segments = [dict(kind='followup', text='勝ちました。', speaker=2, meta={})]
    with patch.dict(os.environ, {'COLLESPO_SOLO_HOST': 'ui'}):
        story.tone_segments(segments)
    assert segments[0]['text'] == '勝ちました。'
