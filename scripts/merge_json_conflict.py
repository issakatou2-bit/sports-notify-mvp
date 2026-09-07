#!/usr/bin/env python3
"""取り込みでぶつかった記録ファイルを、両方残す形で解く。

なぜ要るのか:
  1日に5つのワークフローが同じブランチへ押す。`commit_data.sh` は
  ぶつかったら取り込んでやり直すが、**同じJSONの同じあたりを
  両方が書き換えていると、取り込み自体が止まる。**
  そのときは記録を捨てて終わっていた。

  実害が2回出ている。
    8/17 サッカーの動画は20:00に出ているのに投稿記録だけ残らず、
         見張りが「出ていない」と誤って赤くした
    9/6  週次2本が出ているのに記録が残らず、`weekly` は8/30で止まった

  記録が消えると、二重投稿の防止も健康診断も、その分だけ効かない。

  ぶつかる中身は「別の枠・別の日が増えた」だけのことがほとんどで、
  **両方を残せば正しい。**辞書として混ぜれば済む。

どこまでやるか:
  混ぜられると言い切れる形だけ扱う。**辞書の入れ子だけ。**
  同じ鍵で値が食い違うときは、いま押そうとしている側を採る
  (作ったばかりの記録のほうが新しい)。
  配列がぶつかったら諦める。並びの意味が分からないまま混ぜると、
  記録を残すために記録を壊すことになる。

使い方:
  取り込みが止まった直後に呼ぶ。解けたら0、解けなければ1を返す。
  0のときは `git rebase --continue` へ進んでよい。
"""

import json
import subprocess
import sys


def _run(args):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8")


def conflicted() -> list:
    r = _run(["git", "diff", "--name-only", "--diff-filter=U"])
    return [p for p in r.stdout.splitlines() if p.strip()]


def stage(path: str, num: int):
    """ぶつかった片方を読む。2=取り込んだ側 / 3=いま押そうとしている側。"""
    r = _run(["git", "show", ":%d:%s" % (num, path)])
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def merge(base, mine):
    """辞書を深く混ぜる。mine を優先する。

    混ぜられない形なら ValueError。**呼ぶ側で諦めるため。**
    """
    if isinstance(base, dict) and isinstance(mine, dict):
        out = dict(base)
        for k, v in mine.items():
            out[k] = merge(base[k], v) if k in base else v
        return out
    if isinstance(base, list) or isinstance(mine, list):
        if base == mine:
            return mine
        raise ValueError("配列は混ぜません")
    return mine


def main() -> int:
    paths = conflicted()
    if not paths:
        print("[info] ぶつかっているファイルがありません")
        return 1
    plans = []
    for p in paths:
        if not p.endswith(".json"):
            print("[info] JSONではないので混ぜられません: %s" % p)
            return 1
        theirs, ours = stage(p, 3), stage(p, 2)
        if theirs is None or ours is None:
            print("[info] 片方を読めませんでした: %s" % p)
            return 1
        try:
            plans.append((p, merge(ours, theirs)))
        except ValueError as e:
            print("[info] %s: %s" % (p, e))
            return 1
    for p, data in plans:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write(chr(10))
        _run(["git", "add", p])
        print("[info] 両方を残して解きました: %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
