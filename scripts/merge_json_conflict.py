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
  共通の元・取り込んだ側・この実行の3つから変更を合わせる。
  公開台帳は両方の記録を保持。同じ枠への別動画の同時追加は拒否する。
  使用量は増分を合算。識別子のある話題一覧と字幕イベントは両方の追加を保持。
  識別子のない生成用の配列は、この実行で検算した内容を使う。

使い方:
  取り込みが止まった直後に呼ぶ。解けたら0、解けなければ1を返す。
  0のときは `git rebase --continue` へ進んでよい。
"""

import json
import subprocess
import sys

MISSING = object()
PUBLIC_RECORDS = {'published_assets.json', 'published_videos.json', 'published_tiktok.json'}


def merge_three_way(base, upstream, local, path, keys=()):
    """共通の元からの変更を合わせる。公開台帳の削除・IDの上書きはしない。"""
    if path.startswith('data/publications/'):
        if keys == ('history',) and isinstance(upstream, list) and isinstance(local, list):
            original = base if isinstance(base, list) else []
            if upstream[:len(original)] != original or local[:len(original)] != original:
                raise ValueError('公開履歴の既存部分が変更されています')
            if not all(isinstance(row, dict) and row.get('event_id') for row in upstream + local):
                raise ValueError('公開履歴の識別子がありません')
            seen = {row['event_id'] for row in upstream}
            return upstream + [row for row in local if row['event_id'] not in seen]
        if keys in (('publication_id',), ('domain',), ('kind',), ('key_parts',)):
            if upstream is not MISSING and local is not MISSING and upstream != local:
                raise ValueError('同じ公開ファイルの鍵が異なります')
    if (path.endswith('soccer_flash_receipts.json') and len(keys)==1
            and isinstance(upstream,dict) and isinstance(local,dict)
            and upstream != local and upstream != base and local != base
            and (upstream.get('at'),upstream.get('kind')) != (local.get('at'),local.get('kind'))):
        raise ValueError('同じ試合に別の速報予約があります。上書きせず投稿を停止します')
    public = path.rsplit('/', 1)[-1] in PUBLIC_RECORDS
    if isinstance(upstream, dict) and isinstance(local, dict):
        original = base if isinstance(base, dict) else {}
        return {key: merge_three_way(original.get(key, MISSING),
                                    upstream.get(key, MISSING), local.get(key, MISSING),
                                    path, keys + (key,))
                for key in dict.fromkeys([*upstream, *local])}
    if upstream is MISSING:
        return local
    if local is MISSING:
        return upstream
    # 使用量は各実行の増分を足す。同じ合計値になった場合も二回の使用。
    if path.endswith('token_usage.json') and keys and keys[-1] in {'calls', 'in', 'out', 'usd', 'batch'}:
        if all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in (upstream, local)):
            start = 0 if base is MISSING else base
            if not isinstance(start, (int, float)) or min(upstream, local) < start:
                raise ValueError('使用量が減っているため自動で合わせられません')
            return round(upstream + local - start, 5)
    if upstream == local:
        return local
    if local == base:
        return upstream
    if upstream == base:
        return local
    if public and keys and keys[-1] == 'video_id':
        raise ValueError('同じ枠の動画IDが異なります。両方を控えから確認してください')
    if isinstance(upstream, list) and isinstance(local, list):
        if path.endswith('en_caption_state.json') and keys == ('events',):
            return upstream + [item for item in local if item not in upstream]
        if public:
            raise ValueError('公開台帳の配列は自動で上書きしません')
        # 話題・引用など、識別子のある一覧は別の追加を両方残す。
        for identity in ('key', 'id', 'url'):
            rows = upstream + local
            if rows and all(isinstance(row, dict) and isinstance(row.get(identity), (str, int))
                            for row in rows):
                left = {row[identity]: row for row in upstream}
                right = {row[identity]: row for row in local}
                if len(left) != len(upstream) or len(right) != len(local):
                    continue
                original = {row[identity]: row for row in base
                            if isinstance(row, dict) and identity in row} if isinstance(base, list) else {}
                order = list(left) + [key for key in right if key not in left]
                return [merge_three_way(original.get(key, MISSING), left.get(key, MISSING),
                                        right.get(key, MISSING), path, keys + (str(key),))
                        for key in order]
        # 話題や引用は履歴ではなく再取得する一覧。古い一覧との連結は重複を作る。
        # 同時更新なら、この実行が生成・検算した一覧を採り、公開履歴の保存を妨げない。
        return local
    return local


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


def reconcile(old_head):
    """行単位では競合しなかったJSONも合わせる。同額の使用量増分も失わない。"""
    remote = _run(['git', 'rev-parse', '@{upstream}'])
    if remote.returncode:
        return 1
    upstream = remote.stdout.strip()
    common = _run(['git', 'merge-base', old_head, upstream])
    if common.returncode:
        return 1
    base_ref = common.stdout.strip()
    changed = _run(['git', 'diff', '--name-only', base_ref, old_head])
    if changed.returncode:
        return 1
    plans = []
    try:
        for path in changed.stdout.splitlines():
            if not path.endswith('.json'):
                continue
            values = []
            for ref in (base_ref, upstream, old_head):
                result = _run(['git', 'show', f'{ref}:{path}'])
                values.append(json.loads(result.stdout) if result.returncode == 0 else MISSING)
            plans.append((path, merge_three_way(*values, path)))
    except ValueError as error:
        print(f'[info] JSONを合わせられません: {error}')
        return 1
    for path, value in plans:
        if value is MISSING:
            continue
        import pathlib
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if _run(['git', 'add', '--', path]).returncode:
            return 1
    return 0


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
            base = stage(p, 1)
            plans.append((p, merge_three_way(base if base is not None else MISSING,
                                            ours, theirs, p)))
        except ValueError as e:
            print("[info] %s: %s" % (p, e))
            return 1
    for p, data in plans:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write(chr(10))
        if _run(["git", "add", "--", p]).returncode:
            return 1
        print("[info] 両方を残して解きました: %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(reconcile(sys.argv[2]) if sys.argv[1:2] == ['--reconcile'] else main())
