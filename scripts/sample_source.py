"""元実行のartifactを照会し、見本を後続へ伝える。"""
import argparse
import json
import os
from pathlib import Path
import urllib.request
from sample_only import source_is_sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True)
    parser.add_argument('--github-output', type=Path, required=True)
    args = parser.parse_args()
    if args.source_run:
        if not args.source_run.isdigit() or not args.github_output:
            parser.error('source-runには実行IDとgithub-outputが必要です')
        artifacts = []
        for page in range(1, 101):
            url = (f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
                   f'{args.source_run}/artifacts?per_page=100&page={page}')
            request = urllib.request.Request(url, headers={
                'Authorization': 'Bearer '+os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(request, timeout=30) as response:
                rows = json.load(response)['artifacts']
            artifacts.extend(rows)
            if len(rows) < 100:
                break
        else:
            raise ValueError('元実行の全成果物を確認できません')
        allowed = not source_is_sample(artifacts)
        if not allowed:
            marker = Path('build/sample_only.json')
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(dict(sample_only=True, inherited=True))+'\n', encoding='utf-8')
        with args.github_output.open('a', encoding='utf-8') as output:
            output.write('allowed='+str(allowed).lower()+'\n')
        print('見本のためSNS配信を省略します' if not allowed else '通常の制作実行です')


if __name__ == '__main__':
    main()
