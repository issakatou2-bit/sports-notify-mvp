"""Route the existing daily workflow, preserving the regular-season producer."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import ps_program as ps

STATUS = Path('build/ps_forecast_status.json')
PROGRAM = Path('build/ps_program_forecast.json')


def option(argv, name, fallback):
    return argv[argv.index(name) + 1] if name in argv else fallback


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stage', choices=['narration', 'video', 'thumbnail', 'cover', 'upload'], required=True)
    args, rest = p.parse_known_args()
    legacy = dict(narration='generate_narration.py', video='generate_video.py',
                  thumbnail='generate_thumbnail.py', cover='render_shorts_cover.py', upload='upload_youtube.py')
    if args.stage == 'narration':
        STATUS.unlink(missing_ok=True)
        snapshot = ps.read('data/postseason.json')
        if ps.desired(snapshot) and ps.layout() != 'legacy':
            out = Path(option(rest, '--out', 'public/narration.json'))
            out.unlink(missing_ok=True)
            PROGRAM.unlink(missing_ok=True)
            ps.write(STATUS, dict(state='blocked', reason='Preparation has not succeeded'))
            now = datetime.now(timezone.utc)
            year = now.astimezone(ps.JST).year
            url = ps.pe.API + f'schedule?sportId=1&season={year}&startDate={year}-09-01&endDate={year}-11-15&gameType=F,D,L,W&hydrate=team,probablePitcher'
            if ps.layout() == 'hold':
                program = None
            else:
                evidence = dict(retrieved_at=now.isoformat(), source_url=url, schedule=ps.pe.fetch(url))
                ps.write('build/ps_forecast_source.json', evidence)
                ledger = ps.read('data/published_videos.json')
                program = ps.prepare(snapshot, evidence, 'forecast', now, ledger)
            if program:
                ps.check_program(program)
                ps.write(PROGRAM, program); ps.write(out, ps.script(program))
                ps.write(STATUS, dict(state='v2', edition=program['edition_key']))
            else:
                ps.write(STATUS, dict(state='skipped', reason='No PS games tomorrow or hold'))
                Path('build/narration_skipped.txt').write_text('PS対象なし/保留', encoding='utf-8')
            return
    elif STATUS.exists():
        state = ps.read(STATUS)['state']
        if state == 'blocked':
            raise ValueError('PS新版の準備に失敗したため旧版を公開しません')
        if state == 'skipped':
            print('[info] PS予告は正常省略/保留'); return
        if state == 'v2':
            program = ps.read(PROGRAM)
            if args.stage == 'video':
                ps.movie(program, option(rest, '--audio-dir', 'build/audio'), option(rest, '--out', 'build/video'))
            elif args.stage in ('thumbnail', 'cover'):
                image, _ = ps.render_segment(program['segments'][0])
                path = Path(option(rest, '--out', 'build/video/short.png'))
                path.parent.mkdir(parents=True, exist_ok=True); image.save(path)
            else:
                ps.upload(program, rest)
            return
    raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).with_name(legacy[args.stage])), *rest]))


if __name__ == '__main__':
    main()
