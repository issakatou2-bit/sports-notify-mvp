import json
import sys
from unittest.mock import patch

import pytest

import upload_gate


CREDITS = '音声: VOICEVOX:四国めたん / VOICEVOX:ずんだもん'


def row(role, text, box):
    return dict(role=role, text=text, box=box)


@pytest.fixture
def episode(tmp_path, monkeypatch):
    video = tmp_path / 'sato.mp4'
    video.touch()
    narration = tmp_path / 'narration.json'
    narration.write_text(json.dumps({'segments': [
        dict(speaker=2, text='カブスに移るわ。'),
        dict(speaker=3, text='次の試合はいつなのだ？'),
    ]}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(upload_gate, 'probe_size', lambda _: (1080, 1920))
    return video, narration


def save_layout(video, *frames):
    (video.parent / 'layout_checks.json').write_text(
        json.dumps([dict(frame=i, layout=rows) for i, rows in enumerate(frames)], ensure_ascii=False),
        encoding='utf-8')


def safe_layout():
    return [row('caption', 'カブスに移るわ。', [64, 1100, 900, 1220]),
            row('source', CREDITS, [72, 1370, 797, 1411])]


def test_sato_regression_checks_all_frames_and_tone(episode, monkeypatch):
    video, narration = episode
    narration.write_text('{"segments":[{"speaker":2,"text":"カブスとの契約です。"}]}',
                         encoding='utf-8')
    monkeypatch.setenv('COLLESPO_SOLO_HOST', 'ui')
    save_layout(video, safe_layout(), [
        row('caption', 'カブスとの契約です。', [64, 1660, 940, 1860]),
        row('source', '出典・音声', [72, 1880, 797, 1911]),
    ])
    status, issues = upload_gate.check(video, narration, CREDITS, 'mlb_market_topic')
    assert status == 1
    assert any('めたんの語尾' in issue and 'です' in issue for issue in issues)
    assert any('コマ1 安全域外 caption' in issue and '[64, 1660, 940, 1860]' in issue for issue in issues)
    assert any('コマ1 安全域外 source' in issue and '[72, 1880, 797, 1911]' in issue for issue in issues)


@pytest.mark.parametrize(('description', 'missing'), [
    ('音声: VOICEVOX:四国めたん', 'ずんだもん'),
    ('音声: 四国めたん / ずんだもん', 'VOICEVOX'),
    ('音声: VOICEVOX:ずんだもん', '四国めたん'),
])
def test_missing_voice_credit(episode, description, missing):
    save_layout(episode[0], safe_layout())
    assert upload_gate.check(*episode, description, 'asset') == (
        1, [f'説明欄に「{missing}」の表記がありません'])


@pytest.mark.parametrize('explicit', [True, False])
def test_solo_ui_uses_ui_credit_and_allows_polite_speech(episode, monkeypatch, explicit):
    video, narration = episode
    segment = dict(speaker=2, text='今日の試合です。')
    if explicit:
        segment['voice_host'] = 'ui'
        monkeypatch.setenv('COLLESPO_SOLO_HOST', 'metan')
    else:
        monkeypatch.setenv('COLLESPO_SOLO_HOST', 'ui')
    narration.write_text(json.dumps(dict(segments=[segment])), encoding='utf-8')
    save_layout(video, safe_layout())
    assert upload_gate.check(*episode, 'VoiSona Talk 雨衣', 'asset') == (0, [])
    status, issues = upload_gate.check(*episode, 'VOICEVOX:四国めたん', 'asset')
    assert status == 1 and '説明欄に「雨衣」の表記がありません' in issues


def test_mixed_ui_and_zundamon_still_require_voicevox(episode):
    video, narration = episode
    narration.write_text(json.dumps(dict(segments=[
        dict(speaker=2, voice_host='ui', text='今日の試合です。'),
        dict(speaker=3, text='いつなのだ？'),
    ])), encoding='utf-8')
    save_layout(video, safe_layout())
    assert upload_gate.check(*episode, 'VoiSona Talk 雨衣 / ずんだもん', 'asset') == (
        1, ['説明欄に「VOICEVOX」の表記がありません'])
    assert upload_gate.check(*episode, 'VoiSona Talk 雨衣 / VOICEVOX:ずんだもん', 'asset') == (0, [])


@pytest.mark.parametrize(('role', 'lines', 'name'), [
    ('source', ['VOICEVOX:ず', 'んだもん'], 'ずんだもん'),
    ('source', ['VOI', 'CE', 'VOX:四国めたん'], 'VOICEVOX'),
    ('source', ['VOICEVOX:四国', 'めたん'], '四国めたん'),
    ('caption', ['カ', 'ブスに移るわ。'], 'カブス'),
])
def test_name_split_inside_stacked_rows(episode, role, lines, name):
    save_layout(episode[0], [row(role, line, [72, y, 797, y + 25])
                            for y, line in zip(range(1300, 1440, 30), lines)])
    assert upload_gate.check(*episode, CREDITS, 'asset') == (
        1, [f'コマ0 {role} の「{name}」が行の途中で折り返されています'])


def test_safe_episode_passes(episode):
    save_layout(episode[0], safe_layout(), [
        row('caption', 'カブス', [72, 1300, 200, 1325]),
        row('caption', 'に移るわ。', [72, 1330, 300, 1355]),
        row('source', 'VOICEVOX:ず', [72, 1370, 500, 1400]),
        row('source', 'んだもん', [520, 1370, 660, 1400]),
    ])
    assert upload_gate.check(*episode, CREDITS, 'asset') == (0, [])


def test_missing_record_and_exemptions(episode, monkeypatch):
    status, issues = upload_gate.check(*episode, CREDITS, 'asset')
    assert status == 1 and '描画の記録が無い' in issues[0]
    monkeypatch.setitem(upload_gate.EXEMPT, 'asset', ' ')
    assert upload_gate.check(*episode, CREDITS, 'asset')[0] == 1
    monkeypatch.setitem(upload_gate.EXEMPT, 'asset', '記録の形式を確認した試験用の例外')
    assert upload_gate.check(*episode, CREDITS, 'asset') == (0, [])
    assert upload_gate.check(*episode, 'VOICEVOX:四国めたん', 'asset')[0] == 1
    save_layout(episode[0], [row('caption', 'カブス', [64, 1660, 940, 1860])])
    assert upload_gate.check(*episode, CREDITS, 'asset')[0] == 1


def test_all_exemptions_have_a_reason():
    assert all(isinstance(reason, str) and reason.strip() for reason in upload_gate.EXEMPT.values())


def test_sample_preferred_and_checked_for_split(episode):
    video, _ = episode
    save_layout(video, safe_layout())
    evidence = dict(frames=[dict(frame=4, layout=[
        row('source', 'ず', [72, 1300, 200, 1325]),
        row('source', 'んだもん', [72, 1330, 200, 1355]),
    ])])
    video.with_suffix('.sample-check.json').write_text(json.dumps(evidence), encoding='utf-8')
    with patch.object(upload_gate.check_sample, 'video_issues', return_value=['動画と描画記録の指紋が違う']) as check:
        status, issues = upload_gate.check(*episode, CREDITS, 'asset')
    check.assert_called_once_with(video, evidence)
    assert status == 1 and issues == [
        '動画と描画記録の指紋が違う', 'コマ4 source の「ずんだもん」が行の途中で折り返されています']


def test_landscape_checks_credits_without_requiring_layout(episode, monkeypatch):
    monkeypatch.setattr(upload_gate, 'probe_size', lambda _: (1920, 1080))
    assert upload_gate.check(*episode, CREDITS, 'weekly') == (0, [])
    assert upload_gate.check(*episode, 'VOICEVOX:四国めたん', 'weekly')[0] == 1


def test_cli_json_and_exit_codes(episode, capsys):
    video, narration = episode
    description = video.parent / 'description.txt'
    description.write_text(CREDITS, encoding='utf-8')
    argv = [str(video), '--segments', str(narration), '--description-file', str(description),
            '--kind', 'asset', '--json']
    for expected in (1, 0, 2):
        assert upload_gate.main(argv) == expected
        result = json.loads(capsys.readouterr().out)
        assert result['status'] == expected and result['passed'] == (expected == 0)
        if expected == 1:
            save_layout(video, safe_layout())
        if expected == 0:
            narration.write_text('{"segments":[]}', encoding='utf-8')


def test_uploader_holds_private_video_before_building_youtube(episode, monkeypatch, capsys):
    import upload_youtube

    video, narration = episode
    save_layout(video, safe_layout())
    monkeypatch.setattr(sys, 'argv', ['upload', '--video', str(video), '--narration', str(narration),
                                    '--privacy', 'private'])
    output = video.parent / 'github-output'
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    for key in ('YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN'):
        monkeypatch.setenv(key, 'test')
    with patch.object(upload_youtube, 'published_video', return_value={}), \
            patch.object(upload_youtube, 'build_metadata', return_value={
                'snippet': {'title': '試験', 'description': 'VOICEVOX:四国めたん'}}), \
            patch('opening_alignment.before_upload'), patch.object(upload_youtube, 'build') as build, \
            pytest.raises(SystemExit) as exc:
        upload_youtube.main()
    build.assert_not_called()
    assert exc.value.code == 1
    hold = upload_gate.read_json(video.with_suffix('.upload-hold.json'))
    assert hold['status'] == 'held' and hold['reasons'] == ['説明欄に「ずんだもん」の表記がありません']
    assert 'ずんだもん' in capsys.readouterr().err and output.read_text() == 'uploaded=false\n'
    upload_youtube.require_upload_gate(video, narration, CREDITS, 'daily')
    assert upload_gate.read_json(video.with_suffix('.upload-hold.json'))['status'] == 'passed'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
