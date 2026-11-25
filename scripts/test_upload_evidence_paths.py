"""短い合成フレームで本番の描画入口から投稿用の記録まで通す。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont
import pytest
import yaml

import sample_evidence
import voice_manifest


ROOT = Path(__file__).resolve().parents[1]
SIZE = (1080, 1920)
FONT = ImageFont.load_default()


@pytest.mark.parametrize(('workflow', 'kind', 'narration'), [
    ('asset_video', 'asset', 'build/narr_$t.json'),
    ('correct_video', 'asset', 'build/corr/narr.json'),
    ('ps_game_now', 'asset', 'build/narr_$t.json'),
    ('weekly_summary', 'weekly', 'build/weekly_narration.json'),
    ('weekly_summary', 'verdict', 'build/vs_narration.json'),
])
def test_upload_command_passes_the_saved_narration(workflow, kind, narration):
    flow = yaml.safe_load((ROOT / '.github/workflows' / f'{workflow}.yml').read_text(encoding='utf-8'))
    steps = [step.get('run', '') for job in flow['jobs'].values() for step in job.get('steps', [])]
    script = '\n'.join(steps).replace('\\\n', ' ')
    uploads = [shlex.split(line) for line in re.findall(r'python scripts/upload_youtube\.py[^\n]*', script)]
    matching = [args for args in uploads if args[args.index('--kind') + 1] == kind]
    assert len(matching) == 1
    assert matching[0][matching[0].index('--narration') + 1] == narration
    assert any(re.search(r'--(?:narration-out|out)\s+["\']?' + re.escape(narration), step)
               for step in steps)


def layout_image():
    im = Image.new('RGB', SIZE, 'navy')
    sample_evidence.LayoutDraw(im).text((80, 180), 'Evidence', font=FONT, fill='white', role='source')
    return im


def assert_evidence(video, expected_text='Evidence'):
    evidence = json.loads(video.with_suffix('.sample-check.json').read_text(encoding='utf-8'))
    assert evidence['size'] == list(SIZE)
    assert evidence['video_sha256'] == voice_manifest.sha256(video)
    assert [frame['frame'] for frame in evidence['frames']] == [0, 1]
    assert all(any(expected_text in row.get('text', '') for row in frame['layout'])
               for frame in evidence['frames'])
    return evidence


@pytest.fixture
def episode(tmp_path, monkeypatch):
    import host_split
    import motion
    import preview_unified_v3
    import short_common
    import short_content
    import sound_mix
    import video_common

    for key in ('COLLESPO_BUBBLE', 'COLLESPO_MOTION', 'GITHUB_STEP_SUMMARY'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(host_split, 'enabled', lambda: False)
    monkeypatch.setattr(host_split, 'bind_video', lambda *a: None)
    monkeypatch.setattr(motion, 'enabled', lambda: False)
    monkeypatch.setattr(Image.Image, 'save', lambda *a, **k: None)
    monkeypatch.setattr(preview_unified_v3, 'sheet', lambda *a, **k: None)
    monkeypatch.setattr(short_content, 'require', lambda *a, **k: None)
    monkeypatch.setattr(sound_mix, 'verify_short_video', lambda *a: None)
    monkeypatch.setattr(video_common, 'build_narration_track', lambda *a, **k: tmp_path / 'voice.wav')
    monkeypatch.setattr(short_common, 'add_audio', lambda track, *a, **k: track)
    (tmp_path / 'voice.wav').touch()

    videos = {}

    class Encoder:
        def __init__(self, command, **kwargs):
            option = '-framerate' if '-framerate' in command else '-r'
            self.rate = int(command[command.index(option) + 1])
            self.video = Path(command[-1])
            self.stdin = SimpleNamespace(write=self.write, close=lambda: None)
            self.returncode = 0
            self.digest = hashlib.sha256()
            self.count = 0

        def write(self, raw):
            assert len(raw) == SIZE[0] * SIZE[1] * 3
            self.digest.update(raw)
            self.count += 1
            return len(raw)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def wait(self):
            assert self.count == 2
            self.video.write_bytes(self.digest.digest())
            videos[str(self.video)] = self.rate
            return 0

    def probe(command, **kwargs):
        if command[0] == 'ffprobe':
            return SimpleNamespace(stdout=json.dumps({'streams': [
                dict(nb_frames='2', avg_frame_rate=f'{videos[command[-1]]}/1')]}))
        assert command[0] == 'ffmpeg' and command[1] == '-hide_banner'
        return SimpleNamespace(stderr='Duration: 00:00:00.08')

    monkeypatch.setattr(subprocess, 'Popen', Encoder)
    monkeypatch.setattr(subprocess, 'run', probe)
    # CI の機械には ffmpeg が無い（imageio_ffmpeg だけ）。描画器の「ffmpeg があるか」の確認も偽の道具へ向ける。
    which = shutil.which
    monkeypatch.setattr(shutil, 'which', lambda name, *a, **k: f'/fake/{name}' if name in ('ffmpeg', 'ffprobe') else which(name, *a, **k))

    def write_audio(segment):
        audio = dict(segment, file=str(tmp_path / 'voice.wav'), duration=0.08)
        voice_manifest.write_json(tmp_path / 'audio/manifest.json', dict(segments=[audio]))
        return audio

    return tmp_path, write_audio


def test_mlb_daily_writes_sample_evidence(episode, monkeypatch):
    import generate_video as daily
    import short_common

    folder, audio = episode
    audio(dict(speaker=2, text='試合よ。', kind='intro', meta={}))
    games = folder / 'games.json'
    voice_manifest.write_json(games, dict(games=[dict(is_notable=True)]))
    monkeypatch.setattr(sys, 'argv', ['daily', '--games', str(games), '--audio-dir', str(folder/'audio'),
                                    '--out', str(folder/'out'), '--require-audio'])
    monkeypatch.setattr(short_common, 'duration', lambda *a: 2/daily.FPS)
    monkeypatch.setattr(daily, 'render_intro', lambda *a: layout_image())
    monkeypatch.setattr(daily.video_common, 'anim_step', lambda *a: (1, True))
    daily.main()
    assert_evidence(folder/'out/collespo_short.mp4')


def test_soccer_daily_routes_to_existing_sample_evidence(episode, monkeypatch):
    monkeypatch.setenv('COLLESPO_SHORT_LOOK', 'v4')
    monkeypatch.setenv('COLLESPO_SOCCER_LOOK', 'v6')
    import generate_video as daily
    import soccer_slots_v4 as slots

    folder, audio = episode
    segment = dict(speaker=2, text='試合よ。', kind='preview', meta={})
    audio(segment)
    games = folder / 'games.json'
    voice_manifest.write_json(games, {})
    narration = dict(title='試合', segments=[segment], duration_budget=dict(limit=60))
    monkeypatch.setattr(sys, 'argv', ['daily', '--sport', 'soccer', '--games', str(games),
                                    '--audio-dir', str(folder/'audio'), '--out', str(folder/'out')])
    monkeypatch.setattr(slots.r3, 'LOOK', 'v4')
    monkeypatch.setattr(slots, 'program', lambda mode, data: dict(mode=mode, narration=narration))
    monkeypatch.setattr(slots, 'fit_preview', lambda *a: None)
    monkeypatch.setattr(slots, 'video_times', lambda *a: [2/30])
    monkeypatch.setattr(slots, 'check_frame', lambda *a: [])
    monkeypatch.setattr(slots, 'frame', lambda *a: layout_image())
    assert daily.main() == 0
    assert_evidence(folder/'out/collespo_short.mp4')


def test_player_story_writes_sample_evidence(episode, monkeypatch):
    import ps_brand_components
    import review_render_v3
    import short_common
    import synthesize_narration

    # 選手の描画器は単独起動時の書体を import で設定する。他の試験へ持ち越さない。
    monkeypatch.setenv('COLLESPO_SHORT_LOOK', 'v4')
    monkeypatch.setattr(ps_brand_components, 'FONT_CANDIDATES', dict(ps_brand_components.FONT_CANDIDATES))
    monkeypatch.setattr(review_render_v3, 'font', review_render_v3.font)
    spec = importlib.util.spec_from_file_location('player_story_render_fixture', ROOT/'scripts/player_story_render.py')
    player = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(player)

    folder, audio = episode
    segment = dict(speaker=2, voice_host='ui', text='試合です。', kind='intro', meta={})
    narr = dict(segments=[segment], can_make=True, direction='fixture', player=dict(name_jp='選手'))
    monkeypatch.setattr(player.story, 'validate', lambda *a: None)
    monkeypatch.setattr(player.story, 'RULES', dict(max_story_seconds=60, fixture=dict(face='', effect='')))
    monkeypatch.setattr(synthesize_narration, 'audio_duration', lambda *a: .08)
    monkeypatch.setattr(short_common, 'duration', lambda *a: 2/24)
    monkeypatch.setattr(player, 'frame', lambda *a: layout_image())
    player.render(narr, [audio(segment)], folder/'out')
    evidence = assert_evidence(folder/'out/collespo_player_story.mp4')
    assert evidence['segments'][0]['voice_host'] == 'ui'


def test_soccer_voices_writes_sample_evidence(episode, monkeypatch):
    monkeypatch.setenv('COLLESPO_SHORT_LOOK', 'v4')
    monkeypatch.setenv('COLLESPO_SOCCER_LOOK', 'v6')
    import soccer_voices_render as voices

    folder, audio = episode
    segment = dict(speaker=2, text='試合よ。', kind='intro', meta={})
    narr = dict(segments=[segment])
    monkeypatch.setattr(voices.sv, 'validate_data', lambda *a: None)
    monkeypatch.setattr(voices.sv, 'narration', lambda *_: narr)
    monkeypatch.setattr(voices.slots, 'durations', lambda *a: [2/voices.FPS])
    monkeypatch.setattr(voices, 'clubs_for', lambda *_: {})
    monkeypatch.setattr(voices, 'check_frame', lambda *a: [])
    monkeypatch.setattr(voices, 'frame', lambda *a: layout_image())
    voices.render_video(dict(title='試合', sample_fictional=True), narr, [audio(segment)], folder/'out')
    assert_evidence(folder/'out/collespo_soccer_voices.mp4')


def test_weekly_verdict_writes_sample_evidence(episode, monkeypatch):
    import generate_verdict_short as verdict
    import sanity_sources

    folder, audio = episode
    segment = dict(speaker=2, text='試合よ。', kind='intro', meta={})
    audio(segment)
    monkeypatch.setattr(sys, 'argv', ['verdict', '--audio-dir', str(folder/'audio'), '--out', str(folder/'out')])
    monkeypatch.setattr(verdict.ws, 'load_week', lambda *a: [('2026-11-20', {}), ('2026-11-21', {})])
    monkeypatch.setattr(verdict.ws, 'compute_verdict', lambda *a: dict(streaks=[{}]))
    monkeypatch.setattr(verdict, 'career_streaks', lambda *a: {})
    monkeypatch.setattr(verdict, 'build_narration', lambda *a: dict(segments=[segment]))
    monkeypatch.setattr(sanity_sources, 'attach', lambda value, *_: value)
    monkeypatch.setattr(verdict, 'plan_durations', lambda *a: [2/verdict.FPS])
    monkeypatch.setattr(verdict, 'build_narration_track', lambda *a: folder/'voice.wav')
    monkeypatch.setattr(verdict, 'render_intro', lambda *a: layout_image())
    monkeypatch.setattr(verdict.video_common, 'anim_step', lambda *a: (1, True))
    verdict.main()
    assert_evidence(folder/'out/collespo_verdict.mp4')


def test_ps_dedicated_preview_records_its_existing_source(episode, monkeypatch):
    import check_sample
    import generate_ps_preview as ps
    import short_common

    folder, audio = episode
    segment = dict(speaker=2, text='試合よ。', kind='ps_preview', meta=dict(view='pending'))
    audio(segment)
    monkeypatch.setattr(short_common, 'duration', lambda *a: 2/ps.FPS)
    monkeypatch.setattr(ps.vc, 'font', lambda *a: FONT)
    ps.movie(dict(date_jst='2026-11-25'), dict(segments=[segment]), folder/'audio', folder/'out', True)
    evidence = assert_evidence(folder/'out/collespo_morning_postseason.mp4', '出典：MLB公式日程')
    source = next(row for row in evidence['frames'][0]['layout'] if row['role'] == 'source')
    assert source['box'][1] >= 1735
    assert any('安全域外 source' in issue for issue in check_sample.geometry_issues(evidence['frames'][0], SIZE))


@pytest.mark.parametrize(('kind', 'style', 'filename'), [
    ('daily', 'stadium', 'collespo_short.mp4'),
    ('morning', 'stadium', 'collespo_morning_postseason.mp4'),
    ('morning', 'v3', 'collespo_morning_postseason.mp4'),
])
def test_ps_program_writes_sample_evidence(episode, monkeypatch, kind, style, filename):
    import fan_events
    import ps_program as ps
    import ps_unified_v3 as unified
    import sound_mix

    folder, audio = episode
    card = dict(layout='facts', visual_style=style)
    segment = dict(speaker=2, text='試合よ。', kind='cover', meta=dict(card=card))
    audio(segment)
    monkeypatch.setattr(ps, 'render_segment', lambda *a, **k: (layout_image(), {}, layout_image().convert('RGBA')))
    monkeypatch.setattr(ps, 'background_team', lambda *a: None)
    monkeypatch.setattr(ps.motion, 'background', lambda *a, **k: Image.new('RGB', SIZE))
    monkeypatch.setattr(ps, 'focus_plan', lambda *a: [])
    monkeypatch.setattr(ps, 'check_program', lambda *a: {})
    monkeypatch.setattr(ps.short_common, 'duration', lambda *a: 2/30)
    monkeypatch.setattr(fan_events, 'prepare', lambda *a, **k: None)
    monkeypatch.setattr(fan_events, 'event_cues', lambda: [])
    monkeypatch.setattr(unified, 'lead_card', lambda *a: card)
    monkeypatch.setattr(unified, 'program_ticker', lambda *a: 'Ticker')
    monkeypatch.setattr(unified, 'cues', lambda *a, **k: [])
    monkeypatch.setattr(unified, 'frame', lambda *a, **k: layout_image())
    monkeypatch.setattr(unified.r3, '_single_ticker', lambda *_: Image.new('RGB', (120, 44)))
    monkeypatch.setattr(sound_mix, 'bgm_path', lambda: folder/'voice.wav')
    monkeypatch.setattr(sound_mix, 'mix_short_file', lambda *a, **k: folder/'voice.wav')
    ps.movie(dict(kind=kind, segments=[segment]), folder/'audio', folder/'out')
    evidence = assert_evidence(folder/'out'/filename)
    if style == 'v3':
        assert any(row['role'] == 'ticker' for row in evidence['frames'][-1]['layout'])


def test_layout_draw_and_the_ps_motion_record_actual_coordinates(monkeypatch):
    import ps_motion_template as motion

    recorded = Image.new('RGB', SIZE)
    original = recorded.copy()
    args = ((100, 250), 'Box')
    kwargs = dict(fill='white', font=FONT, anchor='lt')
    draw = ImageDraw.Draw(original)
    draw.text(*args, **kwargs)
    sample_evidence.LayoutDraw(recorded).text(*args, **kwargs)
    box = draw.textbbox(*args, font=FONT, anchor='lt')
    assert recorded.tobytes() == original.tobytes()
    assert recorded.info['v3_layout'][0]['box'] == list(box)
    foreground = recorded.convert('RGBA')
    monkeypatch.setattr(motion, 'background', lambda **_k: Image.new('RGB', SIZE))
    layers = motion.prepare(foreground, dict(layout='facts'))
    settled = motion.frame(layers, 3)
    entering = motion.frame(layers, .1)
    assert settled.info['v3_layout'][0]['box'] == list(box)
    x0, y0, x1, y1 = entering.info['v3_layout'][0]['box']
    assert x0 < box[0] and x1 - x0 == box[2] - box[0] and (y0, y1) == (box[1], box[3])


def test_bubble_keeps_layout_for_actually_resized_content(monkeypatch):
    import bubble_styles

    monkeypatch.setattr(bubble_styles, 'selected', lambda: 'slant')
    monkeypatch.setattr(bubble_styles, 'page_lines', lambda *_: [['']])
    im = layout_image()
    out = bubble_styles.narration_frame(im, dict(text='', speaker=2), 0, 1)
    content_x, _, right, bottom = out.info['narrated_content_box']
    x0, y0, x1, y1 = im.info['v3_layout'][0]['box']
    assert out.info['v3_layout'][0]['box'] == [
        content_x + round(x0 * (right-content_x) / SIZE[0]), round(y0 * bottom / SIZE[1]),
        content_x + round(x1 * (right-content_x) / SIZE[0]), round(y1 * bottom / SIZE[1]),
    ]


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
