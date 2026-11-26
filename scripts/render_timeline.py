"""描いた字幕と実際にpipeへ書いたフレームを観測する。"""
import json
from pathlib import Path
import subprocess

from voice_manifest import sha256, write_json


def subtitle(image, text, visible=True):
    if visible and text:
        image.info.setdefault('timeline_subtitles', []).append(str(text))


def scene(image, key):
    image.info['timeline_scene'] = key


def opening_card_lines(layout):
    return [str(row['text']) for row in layout if row.get('text')
            and row.get('role') not in ('header', 'caption', 'source', 'ticker')]


def _append(rows, signature, frame, fields):
    if rows and rows[-1]['_key'] == signature and rows[-1]['end_frame'] == frame:
        rows[-1]['end_frame'] = frame + 1
    else:
        rows.append(dict(fields, _key=signature, start_frame=frame, end_frame=frame + 1))


class Recorder:
    def __init__(self, fps, segments, narration=None, *, landscape=False):
        self.fps = fps
        self.segments = segments
        original = (narration or {}).get('segments', [])
        self.object_ids = {id(s): s.get('index', i) + 1 for i, s in enumerate(segments)}
        self.sources = {s.get('index', i) + 1: dict(text=s.get('text', original[i].get('text', '') if i < len(original) else ''), speaker=s.get('speaker'))
                        for i, s in enumerate(segments)}
        self.frames = 0
        self.lines, self.cuts, self.subtitles = [], [], []
        self.overlaps = []
        self.last_subtitle = self.previous_subtitle = None
        self.last_image = None
        self.current = None
        self.broken = None
        self.first_source = None
        self.opening_card = []
        self.sample_size = (1920, 1080) if landscape else (1080, 1920)
        self.sample_stride = 12 if landscape else 3
        self.sample_rows = []
        self.sample_last = None
        self.sample_error = None
        sample_source = (narration or {}).get('segments') or segments
        self.sample_segments = [
            dict(text=row.get('text', ''), speaker=row.get('speaker'),
                 **({'voice_host': row['voice_host']} if row.get('voice_host') else {}),
                 meta={key: row.get('meta', {})[key] for key in ('quote_rows', 'duo')
                       if key in (row.get('meta') or {})})
            for row in sample_source
        ]

    def select(self, segment, index, page=None):
        self.previous_subtitle = self.last_subtitle
        ids = segment.get('_source_line_ids') or [self.object_ids.get(id(segment), segment.get('index', index) + 1)]
        meta = segment.get('meta') or {}
        self.current = dict(source_line_ids=ids, text='\n'.join(dict.fromkeys(self.sources.get(i, {}).get('text', '') for i in ids)),
                            screen=meta.get('screen', index), kind=segment.get('kind'), page=page)

    def write(self, stream, raw, image, overlap=False):
        """成功したwriteだけ数える。キャッシュ画像も同じmetadataを持つ。"""
        result = stream.write(raw)
        if result is not None and result != len(raw):
            raise OSError('フレームの書込みが途中で終わりました')
        if self.broken:
            return result
        if image.size == self.sample_size and not self.sample_error:
            try:
                self._observe_sample(image, raw, overlap)
            except (ValueError, TypeError, OSError) as exc:
                self.sample_error = str(exc)
        try:
            self._observe(image, overlap)
        except Exception as exc:
            # 記録は確認用。記録の失敗で動画の書き出しを止めない。
            self.broken = f'{type(exc).__name__}: {exc}'
        return result

    def _observe_sample(self, image, raw, overlap):
        import sample_evidence
        layout = image.info.get('v3_layout', [])
        badges = image.info.get('v4_badges', [])
        if badges:
            recorded = {tuple(row['box']) for row in layout if row['role'] in ('badge', 'team_badge')}
            layout = layout + [dict(role='badge', box=badge['box'], text=badge.get('abbr', ''))
                               for badge in badges if tuple(badge['box']) not in recorded]
        portraits = sample_evidence.portraits(image.info)
        transition = bool(overlap or image.info.get('v2_slide'))
        self.sample_last = (image, raw, self.frames, layout, portraits, transition)
        if self.frames % self.sample_stride == 0:
            self.sample_rows.append(sample_evidence.record(*self.sample_last))

    def _observe(self, image, overlap):
        info = image.info
        self.last_image = image
        current = self.current
        ids = current['source_line_ids']
        if self.first_source is None:
            self.first_source = tuple(ids)
        if not self.opening_card and tuple(ids) == self.first_source:
            self.opening_card = opening_card_lines(info.get('v3_layout', []))
        _append(self.lines, tuple(ids), self.frames, dict(source_line_ids=ids, text=current['text']))
        card = (info.get('timeline_scene') or info.get('press_hook') or info.get('asset_v4')
                or info.get('v4_quote') or {})
        if isinstance(card, dict):
            card = {k: card[k] for k in ('kind', 'head', 'body', 'name', 'row', 'item', 'page', 'said') if k in card}
        screen = dict(screen=current['screen'], kind=current['kind'], page=current['page'], rendered=card)
        if 'readable_page' in info:
            screen['rendered_page'] = info['readable_page']
        _append(self.cuts, json.dumps(screen, ensure_ascii=False, sort_keys=True), self.frames,
                dict(screen=json.dumps(screen, ensure_ascii=False, sort_keys=True),
                     intentional='既存の切替・重ねを維持。開始は次の画面を描いて出力した最初のフレーム'))
        texts = list(dict.fromkeys(info.get('timeline_subtitles', []) +
                                 [e['text'] for e in info.get('v3_layout', [])
                                  if e.get('role') == 'caption' and e.get('text')]))
        if info.get('timeline_subtitle_visible') is False:
            texts = []
        _append(self.subtitles, (tuple(ids), tuple(texts)), self.frames,
                dict(source_line_ids=ids, subtitle='\n'.join(texts)))
        self.last_subtitle = dict(source_line_ids=ids, subtitle='\n'.join(texts))
        if overlap and self.previous_subtitle and self.previous_subtitle['subtitle']:
            old = self.previous_subtitle
            _append(self.overlaps, (tuple(old['source_line_ids']), old['subtitle']), self.frames,
                    dict(old, intentional='前画面の字幕が既存のクロスフェードで重なる'))
        self.frames += 1

    def repeat(self, stream, raw, overlap=False):
        if self.last_image is None:
            self.broken = self.broken or '最初の描画より前にキャッシュを書いた'
            return stream.write(raw)
        return self.write(stream, raw, self.last_image, overlap=overlap)

    def save(self, video, audio_dir):
        """記録を保存する。失敗しても警告だけにし、動画の書き出しは成功のまま。"""
        if (Path(video).parent / 'audio_mix.json').exists():
            # 音量不合格は時刻表の警告処理へ飲み込ませない。
            __import__('sound_mix').verify_short_video(video)
        if self.broken:
            print(f'::warning::字幕とカットの時刻の記録を保存しませんでした（{self.broken}）')
            return None
        try:
            video = Path(video)
            frames = self._video_frames(video)
            if self.sample_last or self.sample_error:
                self._save_sample(video, frames)
            return self._save(video, audio_dir, frames)
        except Exception as exc:
            print(f'::warning::字幕とカットの時刻の記録を保存できませんでした（{type(exc).__name__}: {exc}）')
            return None

    def _video_frames(self, video):
        result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                 '-show_entries', 'stream=nb_frames,avg_frame_rate', '-of', 'json', str(video)],
                                capture_output=True, text=True, check=True)
        stream = json.loads(result.stdout)['streams'][0]
        frames = int(stream['nb_frames'])
        numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
        if numerator / denominator != self.fps or frames > self.frames:
            raise ValueError('完成動画と観測したフレームが一致しません')
        return frames

    def save_sample(self, video):
        """描画記録だけを保存し、完成動画のフレーム数で末尾を切る。"""
        video = Path(video)
        try:
            self._save_sample(video, self._video_frames(video))
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
            print(f'::warning::見本検査の記録を保存できませんでした（{exc}）')

    def _save(self, video, audio_dir, frames):
        def timed(rows):
            out = []
            for row in rows:
                if row['start_frame'] >= frames:
                    continue
                row = {k: v for k, v in row.items() if k != '_key'}
                row['end_frame'] = min(row['end_frame'], frames)
                row.update(start=row['start_frame'] / self.fps, end=row['end_frame'] / self.fps)
                out.append(row)
            return out

        subtitles = sorted(timed(self.subtitles) + timed(self.overlaps), key=lambda r: r['start_frame'])
        lines = timed(self.lines)
        used_ids = set()
        next_id = max(self.sources, default=0) + 1
        for line in lines:
            ident = line['source_line_ids'][0]
            if ident in used_ids:
                ident, next_id = next_id, next_id + 1
            used_ids.add(ident)
            line['line_id'] = ident
            if len(line['source_line_ids']) > 1:
                line['intentional'] = '複数の元行を同時に重ねる合唱。対応はsource_line_ids'
            related = [r for r in subtitles if r['source_line_ids'] == line['source_line_ids'] and r['subtitle']]
            line['subtitle'] = '\n'.join(dict.fromkeys(r['subtitle'] for r in related))
            line['subtitle_start'] = related[0]['start'] if related else None
            line['subtitle_end'] = max(r['end'] for r in related) if related else None
        cuts = timed(self.cuts)
        for i, cut in enumerate(cuts, 1):
            cut['cut_id'] = i
        voice = Path(audio_dir) / 'voice_manifest.json'
        if not voice.is_file():
            # 過去素材をspeaker番号だけでVOICEVOXと認定しない。
            import voice_manifest
            voice_manifest.save(audio_dir, self.segments, default_engine=None, status='unverified_source')
        record_dir = video.with_suffix('')
        saved_voice = json.loads(voice.read_text(encoding='utf-8'))
        for row in saved_voice['segments']:
            self.sources.setdefault(row['line_id'], dict(text=row.get('text', ''), speaker=row.get('source_speaker')))
        import os
        for row in saved_voice['segments']:
            if row.get('file'):
                source = (voice.parent / row['file']).resolve()
                row['file'] = Path(os.path.relpath(source, record_dir.resolve())).as_posix()
        write_json(record_dir / 'voice_manifest.json', saved_voice)
        used = {n for r in lines for n in r['source_line_ids']}
        payload = dict(version=1, fps=self.fps, frame_count=frames, written_frame_count=self.frames,
                       video_sha256=sha256(video), lines=lines, cuts=cuts, subtitles=subtitles,
                       opening_card=self.opening_card,
                       source_lines=[dict(line_id=n, **r, rendered=n in used) for n, r in self.sources.items()],
                       voice_manifest_sha256=sha256(record_dir / 'voice_manifest.json'),
                       provenance_review='未実施。素材の送信許可を意味しない',
                       observation='描画metadataと実writeのフレーム。字幕本文は描画したページの文。フェード中は両画面が重なる')
        # 共用のoutでも前の動画の記録を失わない。すべてJSONだけ。
        write_json(record_dir / 'render_timeline.json', payload)
        write_json(video.parent / 'render_timeline.json', payload)
        return payload

    def _save_sample(self, video, frames):
        import sample_evidence
        try:
            if self.sample_error:
                raise ValueError(self.sample_error)
            if not self.sample_rows:
                raise ValueError('描画記録にコマがありません')
            observed = [row for row in self.sample_rows if row['frame'] < frames]
            if frames == self.frames and observed and observed[-1]['frame'] != frames - 1:
                observed.append(sample_evidence.record(*self.sample_last))
            sample_evidence.save(video, self.fps, self.sample_segments, observed,
                                 size=self.sample_size, stride=self.sample_stride)
        except (ValueError, TypeError, OSError) as exc:
            print(f'::warning::見本検査の記録を保存できませんでした（{exc}）')
