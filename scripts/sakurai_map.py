"""変更したファイルから読む桜井スキルの節を引く。

元は ai-sanpo の tools/sakurai_map.py。対応は docs/review/sakurai_map.md の表を使う。
"""
import argparse
import fnmatch
import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'docs/review/sakurai_map.md'
REF = Path('C:/Users/issak/.claude/skills/sakurai/references')


def rows():
    """対応表を読み込む。"""
    text = TABLE.read_text(encoding='utf-8')
    out = []
    for ln in text.splitlines():
        if not ln.startswith('| `'):
            continue
        c = [x.strip() for x in ln.strip('|').split('|')]
        if len(c) != 4:
            raise ValueError(f'対応表は4列で指定してください: {ln}')
        pats = re.findall(r'`([^`]+)`', c[0])
        ids = re.findall(r'#(\d{3})\b', c[2])
        if not pats or not ids:
            raise ValueError(f'パターンまたは節が空です: {ln}')
        out.append((pats, c[1], ids, c[3]))
    return out


def hit(path, pat):
    p = posixpath.normpath(path.replace('\\', '/')).casefold()
    root = ROOT.as_posix().casefold() + '/'
    if p.startswith(root):
        p = p[len(root):]
    return fnmatch.fnmatchcase(p, pat.casefold())


def sections(reference_dir=REF):
    """節の番号 → (参照ファイル, 見出し, 本文)。"""
    sec = {}
    for f in sorted(reference_dir.glob('*.md')):
        cur = None
        for ln in f.read_text(encoding='utf-8').splitlines():
            m = re.match(r'## (\d{3}) (.*)', ln)
            if m:
                cur = m.group(1)
                sec[cur] = [f.stem, m.group(2), []]
            elif ln.startswith('## '):
                cur = None
            elif cur:
                sec[cur][2].append(ln)
    return sec


def find(paths, about):
    table = rows()
    got = []
    for path in paths:
        mine = [r for r in table if any(hit(path, p) for p in r[0])]
        if about:
            mine = [r for r in mine if any(a in r[1] or a in r[3] for a in about)] or mine
        got.append((path, mine))
    return got


def selftest(reference_dir):
    cases = [('scripts/soccer_national_topics_render.py', '003'),
             ('scripts/short_common.py', '032'), ('scripts/video_common.py', '244'),
             (str(ROOT / 'scripts/sound_mix.py'), '054'), (r'scripts\sfx.py', '165'),
             ('scripts/upload_youtube.py', '101'), ('scripts/generate_thumbnail.py', '150'),
             ('scripts/shorts_thumbnail.sh', '184'), ('scripts/soccer_national_topics.py', '185'),
             ('scripts/generate_morning_short.py', '233'), ('web/index.html', '145'),
             ('web/players/index.html', '104')]
    ng = 0
    for path, want in cases:
        ids = {i for _, rs in find([path], []) for r in rs for i in r[2]}
        ok = want in ids
        ng += not ok
        print('OK' if ok else 'NG', path, '→', want)
    sec = sections(reference_dir)
    miss = sorted({i for r in rows() for i in r[2] if i not in sec})
    if miss:
        print('NG スキルに無い節', miss)
        ng += 1
    if find(['unmapped.py'], [])[0][1]:
        print('NG 対象外のパスが一致')
        ng += 1
    print('全件 OK' if not ng else f'{ng} 件 NG')
    return 1 if ng else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--about', default='', help='目印で絞る（カンマ区切り。例 冒頭,音）')
    ap.add_argument('--body', action='store_true', help='節の本文も出す')
    ap.add_argument('--references', type=Path, default=REF, help='桜井スキルの references フォルダ')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    if a.selftest:
        return selftest(a.references)
    if not a.paths:
        ap.error('変更したファイルのパスを指定してください')
    sec = sections(a.references)
    if not sec:
        ap.error('桜井スキルの参照節が見つかりません。--references で場所を指定してください')
    about = [x.strip() for x in a.about.split(',') if x.strip()]
    seen = set()
    for path, rs in find(a.paths, about):
        print(f'■ {path}')
        if not rs:
            print('  該当なし')
        for _, mark, ids, look in rs:
            print(f'  目印：{mark}')
            print(f'  作った後に見る所：{look}')
            for i in ids:
                stem, title, body = sec.get(i, ('?', '（スキルに無い節）', []))
                print(f'   #{i} {title}（{stem}.md）' + ('　…上に出した' if i in seen else ''))
                if a.body and i not in seen:
                    txt = '\n'.join(x for x in body if x.strip())
                    print('      ' + txt.replace('\n', '\n      '))
                seen.add(i)
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
