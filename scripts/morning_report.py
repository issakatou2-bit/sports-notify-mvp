#!/usr/bin/env python3
"""朝の状況を1枚へ。YouTube Data API/LLMは呼ばず、保存値と公開GETだけ使う。"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
from statistics import median
import urllib.error
import urllib.request
from urllib.parse import urlsplit

JST = timezone(timedelta(hours=9))
METRICS = ("views", "estimatedMinutesWatched", "subscribersGained", "subscribersLost")
LABELS = {"daily": "MLB注目試合", "daily_soccer": "サッカー注目試合",
          "morning": "MLB当日成績", "morning_voices": "現地コメント",
          "morning_press": "現地報道", "morning_postseason": "PS情勢",
          "soccer_results": "サッカー結果", "soccer_race": "サッカー順位",
          "soccer_week": "サッカー週末", "longform": "長編",
          "asset:season_player": "選手まとめ", "asset:season_team": "球団まとめ",
          "asset:season_game": "試合直後", "asset:venue": "球場",
          "asset:legend": "歴史・名選手", "asset:other": "その他の資産動画"}


def kind_label(kind):
    return cell(LABELS.get(kind, kind))


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def stamp(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(JST) if dt.tzinfo else None
    except (ValueError, AttributeError):
        return None


def cell(value):
    return re.sub(r"[\r\n|<>`\[\]]", " ", str(value))[:160]


def records(data):
    """2台帳をIDで統合。assetsの登録時刻より動画台帳の予約時刻を優先。"""
    out = {}
    assets = load(data / "published_assets.json").get("assets", {})
    videos = load(data / "published_videos.json")
    for key, rec in assets.items():
        if isinstance(rec, dict) and rec.get("video_id"):
            kind = "asset:" + ("season_player" if key.startswith("season_player_")
                              else "season_team" if key.startswith("season_team_")
                              else "season_game" if key.startswith("season_game_")
                              else "legend" if key.startswith("legend_")
                              else "venue" if key.startswith("venue_") else "other")
            out[rec["video_id"]] = {**rec, "kind": kind}
    for kind, days in videos.items():
        if isinstance(days, dict):
            for rec in days.values():
                if isinstance(rec, dict) and rec.get("video_id"):
                    vid = rec["video_id"]
                    resolved = out.get(vid, {}).get("kind", "asset:other") if kind == "asset" else kind
                    out[vid] = {**out.get(vid, {}), **rec, "kind": resolved}
    return out


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urlsplit(newurl).hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


def get_url(url, token=None):
    headers = {"User-Agent": "collespo-morning-report", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(SafeRedirect())
    with opener.open(urllib.request.Request(url, headers=headers), timeout=20) as res:
        return res.read()


def oembed(video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return "未確認（ID形式）"
    try:
        get_url("https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v=" + video_id)
        return "200"
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except (OSError, TimeoutError):
        return "未確認（通信）"


def public_error(log):
    """最初のerrorだけ。任意のログ本文は秘密/未発表情報を含み得るので公開しない。"""
    for line in log.splitlines():
        match = re.search(r"(?:\[error\]|##\[error\]|::error(?::|\s))", line, re.I)
        if match:
            text = line[match.end():].strip()
            if re.fullmatch(r"Process completed with exit code \d+\.?", text):
                return "[error] " + text
            return "[error] 本文非掲載（秘密・未発表情報保護。実行ログで確認）"
    return "[error] 行は未収録"


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("repository must be owner/repo")
        self.base = "https://api.github.com/repos/" + repository
        self.token = token

    def get(self, path):
        return json.loads(get_url(self.base + path, self.token))

    def pages(self, path, key):
        out = []
        for page in range(1, 11):
            obj = self.get(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            chunk = obj.get(key, [])
            out.extend(chunk)
            if len(chunk) < 100:
                return out
        raise ValueError("pagination limit")


def actions_report(api, day):
    """前日JSTに開始したmainの処理。skippedは段もジョブも数えない。"""
    start = datetime.combine(day, time(), JST).astimezone(timezone.utc)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    query = f"/actions/runs?branch=main&created={start:%Y-%m-%dT%H:%M:%SZ}..{end:%Y-%m-%dT%H:%M:%SZ}"
    counts, failures, missing = Counter(), [], 0
    try:
        runs = api.pages(query, "workflow_runs")
    except (OSError, ValueError):
        return ["前日の自動処理：未収録（GitHub取得失敗）"]
    for run in runs:
        if run.get("event") == "pull_request" or run.get("conclusion") == "skipped":
            continue
        try:
            jobs = api.pages(f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
        except (OSError, ValueError, KeyError):
            missing += 1
            continue
        for job in jobs:
            if job.get("conclusion") == "skipped":
                continue
            failed_steps = [s for s in job.get("steps", []) if s.get("conclusion") in ("failure", "timed_out", "cancelled")]
            result = "failure" if failed_steps else job.get("conclusion") or "実行中"
            counts[result] += 1
            if result not in ("success", "neutral", "実行中"):
                try:
                    # GitHubの署名付きログURLへ認証ヘッダを転送しない。
                    log = get_url(api.base + f"/actions/jobs/{job['id']}/logs", api.token).decode("utf-8", "replace")
                    error = public_error(log)
                except (OSError, ValueError):
                    error = "[error] 行は未収録（ログ取得失敗）"
                steps = " / ".join(cell(s["name"]) for s in failed_steps) or "段は未収録"
                failures.append(f"- [実行 {run['id']}](https://github.com/{api.base.split('/repos/')[1]}/actions/runs/{run['id']})：{cell(run['name'])} / {cell(job['name'])} / {steps}：`{error}`")
    return ["ジョブ単位（既定オフ等の skipped 除外）: " + (", ".join(f"{cell(k)} {v}" for k, v in sorted(counts.items())) or "対象なし"),
            f"ジョブ取得の未収録: {missing}実行", *failures]


def daily_values(analytics):
    """古いsourcesは再生だけ救済。重なる取得期間を足し合わせない。"""
    out = {}
    for acquired, snapshot in sorted(analytics.get("days", {}).items()):
        for day, sources in snapshot.get("sources", {}).items():
            if sources and all(isinstance(v, (int, float)) for v in sources.values()):
                out[day] = {"views": sum(sources.values()),
                            "fetched_at": snapshot.get("fetched_at", acquired + "（保存日・取得時刻未収録）")}
    for day, row in analytics.get("daily", {}).items():
        out[day] = {**out.get(day, {}), **row}
    return out


def week(daily, end):
    dates = [(end - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    values = {}
    for metric in METRICS:
        rows = [daily.get(d, {}).get(metric) for d in dates]
        values[metric] = sum(rows) if all(isinstance(v, (int, float)) for v in rows) else None
    values["net"] = (values["subscribersGained"] - values["subscribersLost"]
                     if values["subscribersGained"] is not None and values["subscribersLost"] is not None else None)
    return dates, values


def number(value):
    return "未収録" if value is None else f"{value:,.1f}" if isinstance(value, float) else f"{value:,}"


def report(data, now, check=oembed, actions=None):
    today = now.date()
    yesterday = today - timedelta(days=1)
    ledger = records(data)
    analytics = load(data / "analytics.json")
    daily = daily_values(analytics)
    dates1, prev = week(daily, yesterday - timedelta(days=7))
    dates2, current = week(daily, yesterday)
    lines = [f"# 状況とアナリティクス {today}", "", f"取得・確認日: {now:%Y-%m-%d %H:%M JST}", "",
             "出典: 公開台帳2種、data/analytics.json、GitHub Actions API、YouTube oEmbed。", "",
             "## 前日〜当日の予約・公開", "",
             "未公開の題・IDは非掲載。oEmbed 200は視聴可能の確認で、限定公開と一般公開は判別できない。台帳publicだけで実公開と断定しない。", "",
             "| JST日時 | 種類 | 台帳 | 実際の確認 |", "|---|---|---|---|"]
    selected = []
    for vid, rec in ledger.items():
        dt = stamp(rec.get("publish_at") or rec.get("published_at"))
        if dt and yesterday <= dt.date() <= today:
            selected.append((dt, vid, rec))
    for dt, vid, rec in sorted(selected, key=lambda item: (item[0], item[1])):
        state = "保留" if rec.get("held") else "予約時刻前" if dt > now else "公開時刻到来"
        actual = check(vid)
        actual = "oEmbed 200（視聴可）" if actual == "200" else f"公開未確認（oEmbed {cell(actual)}）"
        suffix = "" if rec.get("publish_at") else "（登録時刻）"
        lines.append(f"| {dt:%m/%d %H:%M}{suffix} | {kind_label(rec['kind'])} | {state} / {cell(rec.get('privacy', '未収録'))} | {actual} |")
    if not selected:
        lines.append("| — | — | 台帳記録なし（制作予定の欠如とは限らない） | 未確認 |")
    lines += ["", f"## 自動処理（{yesterday} JST開始・main）", "", *(actions or ["未収録（接続なし）"]), "",
              "## チャンネルの7日比較", "", "日付はYouTube AnalyticsのPacific Time。旧sources由来の日付のタイムゾーンは未収録。欠測を0にせず、当日・計上待ちを含む直前7日をそのまま示す。", "",
              f"| 指標 | {dates1[0]}〜{dates1[-1]} | {dates2[0]}〜{dates2[-1]} | 増減 |", "|---|---:|---:|---:|"]
    for metric, label in zip((*METRICS, "net"), ("再生", "視聴時間（分）", "登録獲得", "登録解除", "登録純増")):
        a, b = prev[metric], current[metric]
        delta = "未収録" if a is None or b is None else number(b - a) + (f"（{(b-a)/a:+.1%}）" if a else "（前期間0・率算出不可）")
        lines.append(f"| {label} | {number(a)} | {number(b)} | {delta} |")
    acquisitions = sorted({str(daily[d].get("fetched_at", "未収録")) for d in dates1 + dates2 if d in daily})
    lines += ["", "日別値の取得日: " + (", ".join(cell(a) for a in acquisitions) or "未収録")]
    missing = [d for d in dates1 + dates2 if any(daily.get(d, {}).get(m) is None for m in METRICS)]
    lines += ["日別の欠測（いずれかの指標）: " + (", ".join(missing) or "なし"), "", "## 強い種類・弱い種類", ""]
    # 計上遅れで直前週が空でも、最後の連続14日を別表として読めるようにする。
    candidates = sorted((d for d in daily if d < today.isoformat()), reverse=True)
    for candidate in candidates:
        last = datetime.fromisoformat(candidate).date()
        d1, v1 = week(daily, last - timedelta(days=7))
        d2, v2 = week(daily, last)
        if v1["views"] is not None and v2["views"] is not None:
            if last != yesterday:
                extra = ["", f"補足・最後の連続14日（再生が収録済み）: {d1[0]}〜{d1[-1]} / {d2[0]}〜{d2[-1]}。",
                         "", "| 指標 | 前の7日 | 後の7日 | 増減 |", "|---|---:|---:|---:|"]
                for m, label in zip((*METRICS, "net"), ("再生", "視聴時間（分）", "登録獲得", "登録解除", "登録純増")):
                    a, b = v1[m], v2[m]
                    diff = "未収録" if a is None or b is None else number(b-a) + (f"（{(b-a)/a:+.1%}）" if a else "")
                    extra.append(f"| {label} | {number(a)} | {number(b)} | {diff} |")
                acquired = sorted({str(daily[d].get("fetched_at", "未収録")) for d in d1 + d2})
                extra += ["", "補足値の取得日: " + ", ".join(cell(a) for a in acquired)]
                lines[-3:-3] = extra
            break
    snapshots = analytics.get("days", {})
    snapshot = snapshots[max(snapshots)] if snapshots else {}
    period = snapshot.get("range", ["未収録", "未収録"])
    lines += [f"動画別の期間合計: {cell(period[0])}〜{cell(period[-1])}。取得日: {cell(snapshot.get('fetched_at', max(snapshots) + '（保存日・取得時刻未収録）' if snapshots else '未収録'))}。上位200本の保存値、公開台帳publicとの結合。観測期間は動画ごとに異なり、週の増減や因果効果ではない。", ""]
    buckets = defaultdict(list)
    seen = set()
    for row in snapshot.get("videos", []):
        vid = row.get("video")
        rec = ledger.get(vid, {})
        if vid not in seen and rec.get("privacy") == "public" and isinstance(row.get("views"), (int, float)):
            buckets[rec["kind"]].append(row["views"])
            seen.add(vid)
    ranked = sorted(((median(v), k, len(v)) for k, v in buckets.items()), reverse=True)
    if ranked:
        lines += ["| 種類 | 収録本数 | 再生中央値 |", "|---|---:|---:|"]
        for med, kind, count in ranked:
            lines.append(f"| {kind_label(kind)} | {count} | {number(med)} |")
        if len(ranked) > 1:
            lines += ["", f"再生中央値の上位: {kind_label(ranked[0][1])}、下位: {kind_label(ranked[-1][1])}（少数・未収録に注意）。"]
    else:
        lines.append("未収録")
    ab = Counter()
    for rec in ledger.values():
        dt = stamp(rec.get("publish_at") or rec.get("published_at"))
        if rec.get("ab_enabled") is True and rec.get("ab_variant") in ("A", "B") and dt and dt <= now and not rec.get("held"):
            ab[(str(rec.get("ab_test", "未収録")), rec["ab_variant"])] += 1
    lines += ["", "## A/Bの本数", "", f"対象: 取得時点までの台帳のラベル付き動画（ID重複除外、予約前・保留を除外）。取得日: {now:%Y-%m-%d}。実公開本数とは区別する。"]
    for test in sorted({test for test, _ in ab}):
        lines.append(f"- {cell(test)}: A {ab[(test, 'A')]}本 / B {ab[(test, 'B')]}本")
    if not ab:
        lines.append("- ラベル付き A 0本 / B 0本。未ラベルをAに数えない。実運用・設定の有効/停止は未確認。")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--offline", action="store_true", help="保存材料の見本。外部接続なし")
    args = parser.parse_args()
    now = datetime.now(JST)
    actions = None
    if not args.offline and os.getenv("GITHUB_REPOSITORY"):
        actions = actions_report(GitHub(os.environ["GITHUB_REPOSITORY"], os.getenv("GH_TOKEN")), now.date() - timedelta(days=1))
    text = report(args.data, now, (lambda _: "未確認（見本・接続なし）") if args.offline else oembed, actions)
    out = args.out or Path("docs/status") / (now.date().isoformat() + ".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"report_path={out.as_posix()}\n")
    print(out)


if __name__ == "__main__":
    main()
