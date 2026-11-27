"""今の見た目の値の一覧と、旧い見た目の値を止める確かめ。

本人 11/25「旧デザインは削除して2度と使えなくして」・11/27「旧デザインが出てこないようにして」。
流れ（.github/workflows）は今の値に固定してある（PR #429）。ここでは、
変数や流れが旧い値に戻されても、投稿の前で止める。
"""
import os
import re
from pathlib import Path

# 今の本番の値。SHORT_LOOK はサッカーの日次と順位争いが v6、ほかは v4。
CURRENT = {
    'COLLESPO_STYLE': ('v2',),
    'COLLESPO_SHORT_LOOK': ('v4', 'v6'),
    'COLLESPO_SOCCER_LOOK': ('v6',),
    'COLLESPO_SOCCER_FOCUS': ('on',),
    'COLLESPO_LONGFORM_STYLE': ('v3',),
}


def problems(env=None):
    env = os.environ if env is None else env
    out = []
    for name, allowed in CURRENT.items():
        value = env.get(name)
        if value is None or value == '':
            continue
        if value not in allowed:
            out.append(f'{name}={value} は旧い見た目（使えるのは {"・".join(allowed)}）')
    return out


def check(env=None):
    found = problems(env)
    if found:
        raise SystemExit('旧い見た目の指定があるので止めます：' + '、'.join(found))


ASSIGN = re.compile(r'^\s*(?:export\s+)?(COLLESPO_(?:STYLE|SHORT_LOOK|SOCCER_LOOK|SOCCER_FOCUS|LONGFORM_STYLE))\s*[:=]\s*(.*?)\s*$')


def workflow_problems(path):
    """流れの中の見た目の指定が、今の値の書き込みかを確かめる（変数の切替や旧い値を通さない）。"""
    out = []
    for no, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if line.lstrip().startswith('#'):
            continue
        if re.search(r'vars\.COLLESPO_(?:STYLE|SHORT_LOOK|SOCCER_LOOK|SOCCER_FOCUS|LONGFORM_STYLE)\b', line):
            out.append(f'{Path(path).name}:{no} 見た目を変数で切り替えている')
            continue
        m = ASSIGN.match(line)
        if not m:
            continue
        name, raw = m.groups()
        value = raw.split(';')[0].strip().strip('"\'')
        if value.startswith('$'):
            # season_review の「元の値に戻す」だけ通す（元の値は上の固定の行で確かめる）
            if value in ('$BASE_SHORT_LOOK', '${BASE_SHORT_LOOK}'):
                continue
            out.append(f'{Path(path).name}:{no} {name} を式で決めている')
            continue
        if value not in CURRENT[name]:
            out.append(f'{Path(path).name}:{no} {name}={value} は旧い見た目')
    return out
