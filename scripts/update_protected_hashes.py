#!/usr/bin/env python3
"""見本づくりで「本番のコードを変えていない」ことを見張る指紋（scripts/fixtures/**/*protected-source*.json）を確かめる・更新する。

10/13、意図した本番の直し（#145 short_v4_cards・#147 characters・#155 generate_morning_short）のたびに、
この指紋の試験が CI で赤になり、手で値を書き換えていた。手で直さず、この道具で更新する。

  python scripts/update_protected_hashes.py          # ずれている所を表示（終了コード1）
  python scripts/update_protected_hashes.py --write  # いまの中身（Git に入る改行 LF の形）で書き直す

記録の形は2つ。平らな {ファイル: 指紋}（mlb-badge）と、{"files": {ファイル: 指紋}, "functions": {ファイル: {関数: 指紋}}}
（soccer-slots/v5）。ファイルは改行を LF にした中身の sha256、関数は ast.get_source_segment の sha256（test_soccer_v5 と同じ）。
意図しない変更でないかは、更新の前に差分を見て確かめること。
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


def function_digest(path, name):
    value = (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")
    nodes = {n.name: n for n in ast.parse(value).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if name not in nodes:
        return None
    return hashlib.sha256(ast.get_source_segment(value, nodes[name]).encode()).hexdigest()


def entries(table):
    """(表示名, ファイル, 今の値, 書き戻し先の辞書, キー, 計算) を並べる。"""
    if "files" in table or "functions" in table:
        # 2段の形でも、上の段に平らな {ファイル: 指紋} が混ざっていれば一緒に見る
        for path, want in table.items():
            if path not in ("files", "functions") and isinstance(want, str):
                yield path, path, want, table, path, (lambda p=path: digest(p))
        for path, want in (table.get("files") or {}).items():
            yield path, path, want, table["files"], path, (lambda p=path: digest(p))
        for path, funcs in (table.get("functions") or {}).items():
            for name, want in funcs.items():
                yield f"{path}:{name}", path, want, funcs, name, (lambda p=path, n=name: function_digest(p, n))
    else:
        for path, want in table.items():
            yield path, path, want, table, path, (lambda p=path: digest(p))


def main(argv):
    write = "--write" in argv
    stale = 0
    for fixture in sorted((ROOT / "scripts" / "fixtures").glob("**/*protected-source*.json")):
        table = json.loads(fixture.read_text(encoding="utf-8"))
        changed = False
        for label, path, want, holder, key, compute in list(entries(table)):
            if not isinstance(want, str) or len(want) != 64 or not (ROOT / path).exists():
                continue
            have = compute()
            if have and have != want:
                stale += 1
                print(f"{'更新' if write else 'ずれ'} {fixture.relative_to(ROOT)}: {label}")
                if write:
                    holder[key] = have
                    changed = True
        if changed:
            fixture.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if not stale:
        print("指紋はすべて一致しています")
    return 0 if (write or not stale) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
