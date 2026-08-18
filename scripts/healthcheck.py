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


CHANNEL_ID = "UCpZ_j8X8uOex5VvKwwTJj3Q"
FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"


def published_on(day: str) -> int:
    """
    その日にチャンネルへ実際に公開された本数。取れなければ -1。

    なぜ記録だけを信じないのか:
      8/17は7本すべて公開されているのに、健康診断は5本欠けと言った。
      投稿の記録を data/published_videos.json から読んでいるが、
      その日は5つのワークフローが同じブランチへ押し合って、記録の側が
      失われていた。動画はある。記録が無いだけ。

      記録が消えるのは直したが、それでも「記録が真実の唯一の写し」で
      ある限り、同じ形の誤報はまた起きる。誤報を出す見張りは、
      見張りが無いより悪い。実物を見に行く。

      RSSなので鍵も枠も要らない。取れなければ -1 を返して、
      記録だけの判断に戻る(取得できないことを異常とは言わない)。
    """
    import re
    import urllib.request
    try:
        req = urllib.request.Request(FEED, headers={"User-Agent": "collespo/1.0"})
        xml = urllib.request.urlopen(req, timeout=20).read().decode("utf-8",
                                                                   "replace")
    except Exception:  # noqa: BLE001
        return -1
    n = 0
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        m = re.search(r"<published>(.*?)</published>", e)
        if not m:
            continue
        try:
            when = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.astimezone(JST).strftime("%Y-%m-%d") == day:
            n += 1
    return n


def check_videos(day: str, only_past: bool = False) -> tuple:
    """
    その日の動画が投稿されたか。(行, 欠けている数) を返す。

    only_past を立てると、まだ公開時刻が来ていない枠は見ない。
    当日の途中で走らせるとき、これから出るものを「欠け」と言われても
    毎回赤くなるだけで意味が無い。
    """
    rec = load("data/published_videos.json") or {}
    now_hm = datetime.now(JST).strftime("%H:%M")
    lines, missing = [], 0
    for kind, label, at, since in EXPECTED_DAILY + OPTIONAL_DAILY:
        if day < since:
            continue  # その枠がまだ無かった日
        if only_past and at > now_hm:
            continue  # まだその時刻になっていない
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
    ap.add_argument("--today", action="store_true",
                    help="今日を、公開時刻が過ぎた枠だけ見る(日中の見張り用)")
    args = ap.parse_args()

    now = datetime.now(JST)
    if args.today:
        day = now.strftime("%Y-%m-%d")
    else:
        day = args.date or (now - timedelta(days=1)).strftime("%Y-%m-%d")

    video_lines, missing = check_videos(day, only_past=args.today)

    # 記録が欠けていても、実際に公開されていれば異常ではない。
    # 記録の押し合いで記録だけが失われることがあり、そのとき
    # 見張りが「出ていない」と嘘をつく。実物の本数と突き合わせる。
    actual = published_on(day)
    expect = len(video_lines)
    if missing and actual >= expect:
        video_lines.append(f"| — | 実際の公開 | {actual}本ありました | "
                           "記録が欠けているだけです |")
        missing = 0
    # 当日の途中では、材料が古いのは当たり前(朝の回がまだ走っていない)。
    # 動画が出たかどうかだけを見る。
    data_lines, stale = check_data()
    if args.today:
        stale = 0
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
