#!/usr/bin/env python3
"""
選手名のカタカナ表記を集める。

なぜ要るのか:
  MLB公式APIは英語名しか返さない。画面に "Pete Crow-Armstrong" と
  出しても、日本の視聴者には読みにくい。読み上げも、辞書に無い綴りは
  1文字ずつ読まれる。

どこから取るか:
  Wikidataの日本語ラベル。英語名で検索して、説明に baseball を含む
  項目の日本語ラベルを引く。9人試して9人とも正しく引けた
  (ピート・クロウ＝アームストロング、ザック・ソーントンのような
   知名度の低い選手まで)。

  SPOTV NOW など日本語チャンネルのタイトルから拾う案もあったが、
  そちらは表記が揺れる。実際に検索結果を見ると、同じ選手が
  「ピート・クルーアームストロング」「ピート・クロウ‐アームストロング」
  「PCA」と3通りで書かれていた。Wikidataは記事名なので1つに定まる。

  認証も割り当ても無く、球団名や球場名にも同じ方法が使える。

使い方:
  python3 scripts/player_kana.py --names "Pete Crow-Armstrong,Blake Snell"
  python3 scripts/player_kana.py --from-recap    # その日出た選手ぶん
"""

import argparse
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

import requests

API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}
OUT = "data/player_kana.json"

# 説明文にこれが入っている項目だけを採る。同姓同名の別人を避ける。
WANT = ("baseball", "野球")


def load(path: str = OUT) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated_at": "", "names": {}}


def lookup(name: str, timeout: int = 20) -> str:
    """英語名から日本語表記。見つからなければ空。"""
    try:
        r = requests.get(API, headers=UA, timeout=timeout,
                         params={"action": "wbsearchentities", "search": name,
                                 "language": "en", "format": "json",
                                 "limit": 3, "type": "item"}).json()
    except Exception:  # noqa: BLE001
        return ""
    for hit in r.get("search", []):
        desc = (hit.get("description") or "").lower()
        if not any(w in desc for w in WANT):
            continue
        q = hit.get("id")
        try:
            e = requests.get(API, headers=UA, timeout=timeout,
                             params={"action": "wbgetentities", "ids": q,
                                     "props": "labels", "languages": "ja",
                                     "format": "json"}).json()
        except Exception:  # noqa: BLE001
            return ""
        lab = ((e.get("entities", {}).get(q, {}).get("labels", {})
                .get("ja") or {}).get("value"))
        if lab:
            return _strip_disambiguator(lab)
    return ""


def _strip_disambiguator(label: str) -> str:
    """Wikidataの曖昧さ回避を落とす。「ミッチェル (野球)」→「ミッチェル」

    同名の人物がいると、日本語ラベルに「(野球)」「(野球選手)」が
    付いてくる。そのまま読み上げに渡すと「かっこ やきゅう」と読む。
    実際 Garrett Mitchell がそうなっていた。
    """
    import re
    out = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", label).strip()
    return out or label


def names_from_recap() -> list:
    """その日の採点に出た選手。ここに出る名前だけ引ければ足りる。"""
    out = []
    for path in ("data/best_of_day.json", "data/morning_recap.json"):
        try:
            d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key in ("players", "pitchers"):
            for row in d.get(key) or []:
                if row.get("name"):
                    out.append(row["name"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default="", help="カンマ区切りの英語名")
    ap.add_argument("--from-recap", action="store_true",
                    help="その日の採点に出た選手ぶんを引く")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    want = [x.strip() for x in args.names.split(",") if x.strip()]
    if args.from_recap:
        want += names_from_recap()
    # 重複を除く。順序は保つ。
    seen, uniq = set(), []
    for n in want:
        if n not in seen:
            seen.add(n)
            uniq.append(n)

    store = load(args.out)
    known = store.get("names") or {}
    todo = [n for n in uniq if n not in known]
    if not todo:
        print(f"[info] 引く名前がありません(既知 {len(known)}件)")
        return 0

    print(f"[info] {len(todo)}件を引きます(既知 {len(known)}件)")
    got = 0
    for n in todo:
        kana = lookup(n)
        # 見つからなかったことも覚える。毎日同じ名前で問い合わせ直さない。
        known[n] = kana
        if kana:
            got += 1
            print(f"   {n:28s} -> {kana}")
        time.sleep(args.sleep)

    store["names"] = known
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    print(f"\n[info] {got}/{len(todo)}件引けました -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
