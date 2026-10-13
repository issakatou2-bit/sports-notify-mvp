#!/usr/bin/env python3
"""見本づくりで「本番のコードを変えていない」ことを見張る指紋（scripts/fixtures/**/*protected-source*.json）を確かめる・更新する。

10/13、意図した本番の直し（#145 short_v4_cards・#147 characters）のたびに、この指紋の試験が CI で赤になり、
手で値を書き換えていた（同じ形が2回）。手で直さず、この道具で更新する。

  python scripts/update_protected_hashes.py          # ずれている所を表示（終了コード1）
  python scripts/update_protected_hashes.py --write  # いまの中身（Git に入る改行 LF の形）で書き直す

指紋は CI と同じく、改行を LF にした中身の sha256。意図しない変更でないかは、更新の前に差分を見て確かめること。
"""
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def main(argv):
    write = "--write" in argv
    stale = 0
    for fixture in sorted((ROOT / "scripts" / "fixtures").glob("**/*protected-source*.json")):
        table = json.loads(fixture.read_text(encoding="utf-8"))
        changed = False
        entries = [(table,path,want,digest(path)) for path,want in table.items()
                   if isinstance(want,str) and len(want)==64 and (ROOT/path).is_file()]
        for path,want in table.get('files',{}).items():
            entries.append((table['files'],path,want,digest(path)))
        for path,functions in table.get('functions',{}).items():
            value=(ROOT/path).read_text(encoding='utf-8').replace('\r\n','\n')
            nodes={n.name:n for n in ast.parse(value).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
            for name,want in functions.items():
                source=ast.get_source_segment(value,nodes[name])
                entries.append((functions,name,want,hashlib.sha256(source.encode()).hexdigest()))
        for container,path,want,have in entries:
            if not isinstance(want, str) or len(want) != 64:
                continue
            if have != want:
                stale += 1
                print(f"{'更新' if write else 'ずれ'} {fixture.relative_to(ROOT)}: {path}")
                if write:
                    container[path] = have
                    changed = True
        if changed:
            fixture.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if not stale:
        print("指紋はすべて一致しています")
    return 0 if (write or not stale) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
