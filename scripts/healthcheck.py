#!/usr/bin/env python3
"""
昨日、出るべきものが出たかを確認する。

なぜ要るのか:
  1日で8件の不具合が見つかった日がある。全部ワークフローは成功で
  終わっていた。動画が作られては投稿直前に捨てられ、記録は4日間
  止まり、採点ルールは1つも発火していなかった。どれも「動いている
  ように見えて動いていない」ので、実行ログを見ても気づけない。

  出力が緑かどうかではなく、**結果が残っているか**を見る。
  出るはずのものが出ていなければ、そう言う。

見るもの:
  ・昨日、種類ごとに動画が投稿されたか
  ・材料のデータが更新されているか(古いまま使い回していないか)
  ・記録がコミットされているか(記録が止まると全部が止まる)
  ・週間ランキングの材料が溜まっているか

使い方:
  python3 scripts/healthcheck.py
  python3 scripts/healthcheck.py --date 2026-08-16
"""

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 毎日出るはずのもの。名前は data/published_videos.json の区分に合わせる。
#
# 4つ目の要素は「いつから出しているか」。
# 新しい枠を足した日、それ以前の日を診断すると必ず「出ていない」になる。
# 実際、コメント欄編を足した直後の診断が、前日の分を欠けとして赤くした。
# 存在しなかった日に出ていないのは当たり前で、報せる価値が無い。
SINCE_ALWAYS = "0000-00-00"
EXPECTED_DAILY = [
    ("morning", "日本人選手の成績", "16:30", SINCE_ALWAYS),
    ("morning_player", "今日の1人", "17:00", "2026-08-18"),
    ("morning_voices", "ハイライトのコメント欄", "17:30", "2026-08-17"),
    ("morning_local", "現地での注目度", "18:00", SINCE_ALWAYS),
    ("daily", "明日の注目試合(MLB)", "19:00", SINCE_ALWAYS),
    ("morning_press", "現地の報道", "21:00", SINCE_ALWAYS),
]

# サッカーは試合の無い日があるので、欠けていても異常としない。
OPTIONAL_DAILY = [("daily_soccer", "今夜の注目試合(サッカー)",
                   "20:00", SINCE_ALWAYS)]

# 材料。何時間以内に更新されていれば良しとするか。
FRESH_HOURS = 30
DATA_FILES = [
    ("data/morning_recap.json", "日本人選手の成績"),
    ("data/mlb_buzz.json", "現地の再生回数"),
    ("data/local_buzz.json", "現地の話題"),
    ("data/local_reporters.json", "現地の番記者"),
    ("data/local_voices.json", "現地のファンの声"),
]


def load(path: str):
    p = pathlib.Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def hours_since(iso: str):
    """ISO文字列から、いま何時間前かを返す。読めなければ None。"""
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def check_videos(day: str) -> tuple:
    """その日の動画が投稿されたか。(行, 欠けている数) を返す。"""
    rec = load("data/published_videos.json") or {}
    lines, missing = [], 0
    for kind, label, at, since in EXPECTED_DAILY + OPTIONAL_DAILY:
        if day < since:
            continue  # その枠がまだ無かった日
        entry = (rec.get(kind) or {}).get(day)
        optional = any(kind == k for k, _, _, _ in OPTIONAL_DAILY)
        if entry:
            lines.append(f"| {at} | {label} | 出た | {entry.get('video_id')} |")
        elif optional:
            # 「試合の無い日は欠けてよい」と一律に見逃していたので、
            # サッカーが1本も出ていないことに何週間も気付かなかった。
            # 開催があったかどうかは手元のデータで分かる。
            fixtures = len(((load("data/soccer_games.json") or {})
                            .get("games")) or [])
            if fixtures:
                missing += 1
                lines.append(f"| {at} | {label} | **出ていない** | "
                             f"{fixtures}試合あった日 |")
            else:
                lines.append(f"| {at} | {label} | — | 試合が無い日 |")
        else:
            missing += 1
            lines.append(f"| {at} | {label} | **出ていない** | |")
    return lines, missing


def check_data() -> tuple:
    lines, stale = [], 0
    for path, label in DATA_FILES:
        d = load(path)
        if d is None:
            stale += 1
            lines.append(f"| {label} | **ファイルが無い** | |")
            continue
        h = hours_since(d.get("updated_at") or d.get("generated_at"))
        if h is None:
            lines.append(f"| {label} | 時刻が読めない | |")
        elif h > FRESH_HOURS:
            stale += 1
            lines.append(f"| {label} | **{h:.0f}時間前** | 古い |")
        else:
            lines.append(f"| {label} | {h:.0f}時間前 | |")
    return lines, stale


def check_history() -> tuple:
    """週間ランキングの材料。7日分そろって初めて出せる。"""
    d = pathlib.Path("data/recap_history")
    n = len(list(d.glob("*.json"))) if d.exists() else 0
    if n >= 7:
        return f"| 週間ランキングの材料 | {n}日分 | 出せる |", 0
    return f"| 週間ランキングの材料 | {n}日分 | あと{7 - n}日 |", 0


def check_playlists() -> tuple:
    d = load("data/playlists.json")
    if not d:
        return "| 再生リスト | **記録が無い** | 権限を確認 |", 1
    total = sum(len(v.get("videos") or []) for v in d.values())
    return f"| 再生リスト | {len(d)}個 / {total}本 | |", 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="確認する日 (既定は昨日のJST)")
    args = ap.parse_args()

    now = datetime.now(JST)
    day = args.date or (now - timedelta(days=1)).strftime("%Y-%m-%d")

    video_lines, missing = check_videos(day)
    data_lines, stale = check_data()
    hist_line, _ = check_history()
    pl_line, pl_bad = check_playlists()

    out = [f"# コレスポの健康診断  ({day} 分 / {now:%m-%d %H:%M} JST 時点)", ""]
    if missing or stale or pl_bad:
        out.append(f"**要確認: 動画の欠け {missing}件 / データの古さ {stale}件**")
    else:
        out.append("**問題なし**")
    out += ["", "## 動画", "",
            "| 時刻 | 種類 | 状態 | 動画ID |", "|---|---|---|---|"]
    out += video_lines
    out += ["", "## 材料と記録", "",
            "| 対象 | 状態 | |", "|---|---|---|"]
    out += data_lines + [hist_line, pl_line]

    text = "\n".join(out)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    # 欠けていたら赤で終わる。緑のまま欠けているのが、いちばん困る。
    return 1 if (missing or stale or pl_bad) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
