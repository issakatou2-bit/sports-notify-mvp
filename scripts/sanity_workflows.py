"""公開経路の点検契約。新しい呼出しや迂回もrun_checksで検出する。"""
from pathlib import Path
import re

# 原稿を作る経路ごとの必要数。消えた点検と別原稿への誤接続を検出する。
NARRATIONS = {
    'asset_video': ['"build/narr_$t.json"'],
    'correct_video': ['build/corr/narr.json'],
    'daily_notify': ['public/narration.json'],
    'design_preview': ['"build/narr_$T.json"'],
    'longform': ['build/lf/dialogue.json'],
    'morning_design_preview': ['build/preview-narration.json'],
    'morning_recap': ['"build/mr_narration_${mode}.json"'],
    'player_story': ['build/player_story/narration.json'],
    'ps_game_now': ['"build/narr_$t.json"'],
    'season_review': ['"build/narr_$t.json"'],
    'soccer_daily': ['build/soccer_narration.json'],
    'soccer_race': ['build/race_narration.json'],
    'soccer_results': ['build/soccer_results/narration.json'],
    'soccer_voices': ['build/soccer_voices/narration.json'],
    'soccer_week': ['build/week_narration.json'],
    'weekly_summary': ['build/weekly_narration.json', 'build/vs_narration.json'],
}
KINDS = {
    'asset_video': 'asset', 'correct_video': 'asset', 'daily_notify': 'daily',
    'design_preview': 'asset', 'longform': 'longform', 'morning_design_preview': 'morning_preview',
    'player_story': 'player_story', 'ps_game_now': 'asset', 'season_review': 'asset',
    'soccer_daily': 'daily_soccer', 'soccer_race': 'soccer_race', 'soccer_results': 'soccer_results',
    'soccer_voices': 'soccer_voices', 'soccer_week': 'soccer_week',
}
PUBLISHER = re.compile(r'scripts/(?:upload_youtube|soccer_results_upload|soccer_week_publish)\.py'
                      r'|scripts/ps_daily_entry\.py\s+--stage\s+upload')


def errors(root):
    import yaml
    root = Path(root)
    bad, seen = [], {}
    for path in sorted((root/'.github/workflows').glob('*.yml')):
        try:
            workflow = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except yaml.YAMLError:
            bad.append(f'{path.name}: YAMLを読めないため共通点検を検査できません')
            continue
        found = []
        for job in (workflow.get('jobs') or {}).values():
            prior = []
            for index, step in enumerate(job.get('steps') or []):
                run = (step.get('run') or '').replace('\\\n', ' ')
                calls = re.findall(r'python(?:3)? scripts/sanity\.py[^\n]*', run)
                for call in calls:
                    flags = re.findall(r'--[a-z-]+', call)
                    expected = ['--general', '--strict', '--narration', '--out', '--hold-record', '--kind']
                    if flags != expected:
                        bad.append(f'{path.name}: 共通引数・順序と不一致: {call}')
                    signature = re.search(r'--narration\s+(.+?)\s+--out\s+(.+?)\s+--hold-record\s+(.+?)\s+--kind\s+(.+)', call)
                    if not signature or any(v.startswith('--') for v in signature.groups()):
                        bad.append(f'{path.name}: 原稿・出力・hold・種類の値が不足しています')
                    kind = KINDS.get(path.stem)
                    if path.stem == 'weekly_summary':
                        kind = 'verdict' if 'build/vs_narration.json' in call else 'weekly'
                    if kind and not re.search(r'--kind\s+'+re.escape(kind)+r'(?=\s|;|$)', call):
                        bad.append(f'{path.name}: 種類が{kind}と一致しません')
                    match = re.search(r'--narration\s+(.*?)\s+--out\s+', call)
                    if match:
                        found.append(match[1].strip())
                    if '|| true' in call:
                        bad.append(f'{path.name}: 点検失敗を無視しています')
                    prior.append((index, step, call))
                publication = PUBLISHER.search(run)
                if publication:
                    eligible = [g for g in prior if g[0] <= index]
                    if not eligible:
                        bad.append(f'{path.name}: 投稿より前の共通点検がありません')
                    elif eligible[-1][0] == index:
                        # set +e のループ内は && または if ! ... continue で1本だけ止める。
                        gate_call = eligible[-1][2]
                        if 'set +e' in run and not (gate_call.rstrip().endswith('&&') or
                                ('if ! '+gate_call in run and re.search(r';?\s*then.*?continue', run, re.S))):
                            bad.append(f'{path.name}: ループの点検失敗で投稿を止められません')
                    elif eligible[-1][1].get('continue-on-error'):
                        ident = eligible[-1][1].get('id')
                        if f"steps.{ident}.outcome == 'success'" not in str(step.get('if') or ''):
                            bad.append(f'{path.name}: 投稿の点検成功条件がありません')
                    published = re.search(r'--kind\s+(\w+)', run[publication.end():])
                    checked = re.search(r'--kind\s+(\w+)', eligible[-1][2]) if eligible else None
                    if published and checked:
                        actual = published[1]
                        if actual == 'daily' and re.search(r'--sport\s+soccer\b', run[publication.end():]):
                            actual = 'daily_soccer'
                        if actual != checked[1]:
                            bad.append(f'{path.name}: 保留記録の種類{checked[1]}と投稿の種類{actual}が不一致')
        if found:
            seen[path.stem] = found
            if 'Save sanity gate records' not in path.read_text(encoding='utf-8'):
                bad.append(f'{path.name}: 点検履歴のartifact保存がありません')
    for name, expected in NARRATIONS.items():
        if seen.get(name) != expected:
            bad.append(f'{name}.yml: 必要な原稿の点検が不一致 {seen.get(name, [])} != {expected}')
    # Pythonの中で投稿する速報も、同じCLIの成功を要求する。
    script = (root/'scripts/soccer_now.py').read_text(encoding='utf-8')
    if not re.search(r'subprocess\.run\(sanity\.command\(kind,.*?check=True\)', script, re.S):
        bad.append('soccer_now.py: soccer_now/goal_shortの共通点検がありません')
    return bad


def main():
    bad = errors(Path(__file__).resolve().parents[1])
    for error in bad:
        print('NG', error)
    print(f'共通点検: {len(NARRATIONS)} workflows / 問題 {len(bad)}件')
    return bool(bad)


if __name__ == '__main__':
    raise SystemExit(main())
