"""関数の中の条件の中で、外でも使う名前を import し直していないか。

関数内のどこかで import すると、その名前は関数全体で局所の名前になる。
条件に入らない回は値が無く、外側の行で UnboundLocalError になる
（10/28 夕方の4本の voices・press が generate_morning_short の
post_common で止まった）。
"""
import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent


def risky(source):
    tree = ast.parse(source)
    # 外の名前を隠す時だけ危ない。モジュール直下で読み込んだ名前に限る
    top = {(a.asname or a.name).split('.')[0] for n in tree.body
           if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parent = {}
        for node in ast.walk(func):
            for child in ast.iter_child_nodes(node):
                parent[child] = node
        for node in ast.walk(func):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or parent.get(node) is func:
                continue
            block = parent[node]
            inside = {id(n) for n in ast.walk(block)}
            for alias in node.names:
                name = (alias.asname or alias.name).split('.')[0]
                # try で読み、失敗時は名前を入れるか関数を抜けるなら、外で使っても値がある
                if isinstance(block, ast.Try) and node in block.body and block.handlers and all(
                        isinstance(h.body[-1], (ast.Return, ast.Raise)) or any(
                            isinstance(t, ast.Name) and t.id == name
                            for s in h.body if isinstance(s, ast.Assign) for t in s.targets)
                        for h in block.handlers):
                    continue
                if name in top and any(isinstance(n, ast.Name) and n.id == name and id(n) not in inside
                       for n in ast.walk(func)):
                    found.append((node.lineno, func.name, name))
    return found


class LocalImportScope(unittest.TestCase):
    def test_finds_import_used_outside_its_branch(self):
        source = "import m\ndef f(x):\n    if x:\n        import m\n        m.a()\n    return m.b()\n"
        self.assertEqual(risky(source), [(4, 'f', 'm')])

    def test_allows_import_used_only_inside_its_branch(self):
        source = "import m\nfrom m import b\ndef f(x):\n    if x:\n        import m\n        return m.a()\n    try:\n        from m import b\n    except ImportError:\n        b = None\n    return b\n"
        self.assertEqual(risky(source), [])

    def test_scripts_have_no_branch_import_used_outside(self):
        bad = []
        for path in sorted(ROOT.glob('*.py')):
            for line, func, name in risky(path.read_text(encoding='utf-8-sig')):
                bad.append(f'{path.name}:{line} {func} の {name}')
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])  # run_checks は一時置場を引数で渡す
