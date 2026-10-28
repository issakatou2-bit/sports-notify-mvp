"""音声生成を使うjobが2つのJSONをartifactに残すか検査する。"""
from fnmatch import fnmatch
from pathlib import Path

PRODUCERS = ('synthesize_narration.py', 'generate_morning_short.py', 'generate_asset_video.py',
             'generate_longform.py', 'ps_program.py', 'generate_ps_preview.py')
RECORDS = ('voice_manifest.json', 'render_timeline.json')


def errors(root):
    import yaml
    result = []
    for workflow in sorted((Path(root) / '.github/workflows').glob('*.yml')):
        data = yaml.safe_load(workflow.read_text(encoding='utf-8')) or {}
        for name, job in data.get('jobs', {}).items():
            steps = job.get('steps', [])
            if not any(any(p in str(s.get('run', '')) for p in PRODUCERS) for s in steps):
                continue
            saved = set()
            for step in steps:
                if not str(step.get('uses', '')).startswith('actions/upload-artifact@'):
                    continue
                if 'always()' not in str(step.get('if', '')):
                    continue
                patterns = str(step.get('with', {}).get('path', '')).splitlines()
                for record in RECORDS:
                    example = 'build/episode/' + record
                    included = False
                    for pattern in patterns:
                        pattern = pattern.strip()
                        if not pattern:
                            continue
                        exclusion = pattern.startswith('!')
                        if fnmatch(example, pattern.lstrip('!')):
                            included = not exclusion
                    if included:
                        saved.add(record)
            for record in set(RECORDS) - saved:
                result.append(f'{workflow.name}/{name}: {record} をalways()のartifactに残していません')
    return result
