#!/usr/bin/env python3
"""
名前を照合しているところが、正規化を通しているかを見る。

なぜ要るのか:
  Edwin Díaz を見落とした事例を一般化する。

  起きたこと: アクセントを落とさずに姓を数えたので、
  Díaz が Diaz(1人) と Díaz(5人) に割れ、前者が「同姓なし」に見えた。
  コメントの "diaz" に、別球団の別人の成績が付くところだった。

  この形が怖いのは、壊れても静かなこと。照合が外れるだけなら
  「該当なし」で済むが、割れて一意に見えると誤った情報が出る。
  そして出たあとでないと気付けない。

  同じ形は、名前を辞書のキーにしているところ全部にある:
    ・コメントから選手を引く      (mentioned)
    ・読み上げのカタカナを引く    (generate_narration)
    ・クラブ名から日本人選手を引く (notability_engine)

見るもの:
  1. 正規化すると同じになるキーが、別々に登録されていないか
  2. 実在の名前で引けるか(アクセントの有無どちらでも)

使い方:
  python3 scripts/test_keys.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import textkey as tk  # noqa: E402

fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok' if ok else 'NG'}  {label}: {got}")


def split_keys(keys) -> dict:
    """正規化すると同じになるのに、別々に登録されているキー。"""
    seen = {}
    for k in keys:
        seen.setdefault(tk.key(k), []).append(k)
    return {k: v for k, v in seen.items() if len(v) > 1}


def main() -> int:
    print("--- 綴り違いで割れているキー ---")

    from generate_narration import _kana_table, _surname_kana, speech_name
    check("カタカナ表(フルネーム)", split_keys(_kana_table()), {})
    check("カタカナ表(姓)", split_keys(_surname_kana()), {})

    import notability_engine as ne
    check("人気クラブ", split_keys(ne.SOCCER_MARQUEE_CLUBS), {})
    check("クラブ名の日本語", split_keys(ne.SOCCER_CLUB_NAME_JP), {})
    check("外国人選手の読み", split_keys(ne.MLB_NAME_READINGS), {})

    print("\n--- アクセントの有無で結果が変わらないか ---")
    for a, b in (("Edwin Díaz", "Edwin Diaz"),
                 ("Yandy Díaz", "Yandy Diaz"),
                 ("Andrés Chaparro", "Andres Chaparro")):
        check(f"{a} と {b} が同じ読み", speech_name(a), speech_name(b))

    print("\n--- 同姓を一意と誤認していないか ---")
    import mentioned as mn
    by_last, _ = mn._roster()
    # 名簿にある全員の姓を数え直して、2人以上いる姓が
    # 照合表に残っていないことを確かめる
    import json
    rows = []
    for path in ("data/best_of_day.json", "data/roster_stats.json"):
        try:
            d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for grp in ("everyone", "players", "league"):
            rows += [r.get("name", "") for r in (d.get(grp) or [])]
    counts = {}
    for name in rows:
        s = tk.key(tk.surname(name))
        if s:
            counts.setdefault(s, set()).add(tk.key(name))
    dupes = {s for s, names in counts.items() if len(names) > 1}
    leaked = sorted(s for s in by_last if tk.key(s) in dupes)
    check("同姓が複数いる姓が照合表に残っていない", leaked, [])

    print("\nALL OK" if not fails else f"\n{fails} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
