#!/usr/bin/env python3
"""きょうの状況を1画面に。

なぜ要るのか:
  作業を再開するたび、git の状態・ワークフローの一覧・落ちたものの
  実行ログ・きょう出た動画を、別々に取っていた。実行ログは zip を
  落として展開して検索する。毎回1万字を超えて、そのほとんどが
  「成功した」という行だった。

  **調べる量は減らさない。選んで出す。**
  落ちた理由はここで拾って、1行にして返す。理由が分かれば、
  実行ログを開く回数そのものが減る。

使い方:
    py -3 scripts/status.py             直近24時間
    py -3 scripts/status.py --hours 72  期間を広げる
    py -3 scripts/status.py --quiet     落ちた理由を調べない（速い）
"""

import argparse
import io
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = "issakatou2-bit/sports-notify-mvp"
JST = timezone(timedelta(hours=9))
WIDTH = 100          # 1行の長さ。これを超えたら切る


def sh(*args, **kw):
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       cwd=str(ROOT), **kw)
    return (r.stdout or "").strip()


def token() -> str:
    """GitHub の合言葉。手元の git が覚えているものを使う。"""
    r = subprocess.run(["git", "credential", "fill"], input=
                       "protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, cwd=str(ROOT))
    for line in (r.stdout or "").splitlines():
        if line.startswith("password="):
            return line[9:]
    return ""


def api(path: str, tok: str):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/%s" % (REPO, path),
        headers={"Authorization": "Bearer " + tok,
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def why(run_id: int, tok: str) -> str:
    """落ちた理由を1行で。

    実行ログの中から、この順で探す:
      1. 検査が出した NG の行
      2. 例外の最後の行（TypeError: ... など）
      3. ##[error] の行
    """
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/actions/runs/%d/logs" % (REPO, run_id),
        headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return "（実行ログを取れない）"

    ng, exc, err = [], [], []
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                if "/" in name:            # 各段の詳細は親の方に入っている
                    continue
                for raw in z.read(name).decode("utf-8", "replace").splitlines():
                    line = re.sub(r"^\S+Z ", "", raw).strip()
                    if line.startswith("NG "):
                        ng.append(line)
                    elif re.match(r"^[\w.]*(Error|Exception)\b.*:", line):
                        exc.append(line)
                    elif line.startswith("##[error]"):
                        err.append(line[9:])
    except zipfile.BadZipFile:
        return "（実行ログが読めない）"

    for group in (ng, exc, err):
        if group:
            s = group[0]
            return s if len(s) <= WIDTH else s[:WIDTH] + "…"
    return "（理由の行が見つからない）"


def git_line() -> str:
    head = sh("git", "rev-parse", "--short", "HEAD")
    dirty = len([x for x in sh("git", "status", "--short").splitlines()
                 if x and not x.startswith("??")])
    sh("git", "fetch", "origin", "main", "-q")
    ahead = sh("git", "rev-list", "--count", "origin/main..HEAD")
    behind = sh("git", "rev-list", "--count", "HEAD..origin/main")
    bits = ["HEAD=%s" % head]
    if ahead != "0":
        bits.append("未push %s件" % ahead)
    if behind != "0":
        bits.append("取り込み待ち %s件" % behind)
    if dirty:
        bits.append("手元の変更 %d件" % dirty)
    if len(bits) == 1:
        bits.append("リモートと同じ")
    return "git    " + " / ".join(bits)


def published(days: int = 2) -> list:
    """どの枠が、どの日に出たか。"""
    path = ROOT / "data" / "published_videos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    today = datetime.now(JST).date()
    out = []
    for back in range(days):
        day = str(today - timedelta(days=back))
        kinds = sorted(k for k, v in data.items()
                       if isinstance(v, dict) and day in v)
        out.append((day, kinds))
    return out


def handoffs() -> list:
    """共有メモの置き場。**共有コピー側の1つだけ。**

    枝（build/wt-*）で動かしても、読むのは2つ上の共有コピー側。
    以前は枝側にも同じ名前のファイルがあり中身が違っていたので、
    9/23に1つへまとめた。リポジトリは公開なので、メモはコミットしない。
    """
    shared = ROOT.parent.parent / "docs" / "HANDOFF.md"
    here = ROOT / "docs" / "HANDOFF.md"
    for p in (shared, here):
        if p.exists():
            return [p]
    return []


def working() -> list:
    """共有メモの「作業中」。他の担当と重ならないために見る。"""
    out = []
    for path in handoffs():
        on = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                on = "作業中" in line
                continue
            # 見出しの下の箇条書きは全部拾う。**「作業中」という語を
            # 行に求めない。**Codexは9/22に見出しを「## 作業中」へ
            # 変えていて、行の方にはその語が無い。
            if on and line.startswith("- "):
                s = re.sub(r"\*\*", "", line[2:])
                out.append(s if len(s) <= WIDTH else s[:WIDTH] + "…")
    return out[:4]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--quiet", action="store_true",
                    help="落ちた理由を調べない")
    a = ap.parse_args()

    now = datetime.now(JST)
    print("== コレスポ %s ==" % now.strftime("%Y-%m-%d %H:%M JST"))
    print(git_line())

    tok = token()
    if not tok:
        print("CI     （GitHub の合言葉を取れないので調べていない）")
    else:
        since = now.astimezone(timezone.utc) - timedelta(hours=a.hours)
        try:
            runs = api("actions/runs?per_page=60", tok)["workflow_runs"]
        except Exception as e:                       # noqa: BLE001
            runs = []
            print("CI     （取れない: %s）" % e)
        recent = [r for r in runs
                  if datetime.fromisoformat(
                      r["created_at"].replace("Z", "+00:00")) >= since]
        bad = [r for r in recent if r["conclusion"] == "failure"]
        if recent:
            print("CI     直近%d時間 %d件 / 失敗 %d件"
                  % (a.hours, len(recent), len(bad)))
        for r in bad:
            at = datetime.fromisoformat(
                r["created_at"].replace("Z", "+00:00")).astimezone(JST)
            # 名前は切らない。全角が混ざるので、桁を揃えると崩れる。
            print("  NG %s  %s" % (at.strftime("%m-%d %H:%M"), r["name"]))
            if not a.quiet:
                print("     " + why(r["id"], tok))

    for day, kinds in published():
        print("公開   %s  %s" % (day, " ".join(kinds) if kinds else "（なし）"))

    now_lines = working()
    if now_lines:
        print("作業中")
        for s in now_lines:
            print("  " + s)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
