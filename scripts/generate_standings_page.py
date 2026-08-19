#!/usr/bin/env python3
"""
MLBの順位表をサイトに出す。

なぜ要るのか:
  YouTubeの検索で来た人が打った語を見たら、いちばん多いのが
  「mlb順位表」だった(11回)。次が選手名で7回ずつ。
  つまり、いちばん探されているものを1つも用意していなかった。

  検索から来た人は平均102秒見ている。フィードから流れてきた人の
  21秒に対して5倍で、いちばん濃い流入がそこだった。
  その入口が空いている。

何を出すか:
  MLB公式APIの数字だけ。勝敗・勝率・ゲーム差・直近の連勝連敗。
  順位の解釈(「まだ間に合う」など)は書かない。
  ワイルドカードの数字もAPIにあるので、そのまま並べる。

出力: public/standings.html

使い方:
  python3 scripts/generate_standings_page.py --out public/standings.html
"""

import argparse
import html
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from notability_engine import MLB_TEAM_NAME_JP  # noqa: E402

import generate_archive_pages as ga  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}
JST = timezone(timedelta(hours=9))

# 地区IDと日本語名。APIは division.id でしか返さない。
DIVISION_JP = {
    200: "ア・リーグ西地区", 201: "ア・リーグ東地区", 202: "ア・リーグ中地区",
    203: "ナ・リーグ西地区", 204: "ナ・リーグ東地区", 205: "ナ・リーグ中地区",
}
ORDER = [201, 202, 200, 204, 205, 203]

STYLE_EXTRA = """
  .std-table { width:100%; border-collapse:collapse; margin:.4rem 0 1.6rem; }
  .std-table th, .std-table td { padding:.42rem .3rem; text-align:right;
    border-bottom:1px solid var(--border); font-size:.86rem; }
  .std-table th { color:var(--text-dim); font-weight:500; font-size:.74rem; }
  .std-table td.team, .std-table th.team { text-align:left; }
  .std-table tr.lead td { color:var(--accent); font-weight:600; }
  .std-note { font-size:.78rem; color:var(--text-dim); margin:.2rem 0 1.4rem; }
  .std-streak { font-family:'JetBrains Mono',monospace; font-size:.78rem; }
"""


def fetch(season: int) -> dict:
    r = requests.get(f"{API}/standings",
                     params={"leagueId": "103,104", "season": season,
                             "standingsTypes": "regularSeason"},
                     headers=UA, timeout=30)
    r.raise_for_status()
    out = {}
    for rec in r.json().get("records", []):
        did = (rec.get("division") or {}).get("id")
        if did:
            out[did] = rec.get("teamRecords") or []
    return out


def streak_jp(t: dict) -> str:
    """連勝・連敗。APIの streakCode は W3 / L1 の形。"""
    s = t.get("streak") or {}
    n = s.get("streakNumber") or 0
    if not n:
        return ""
    if s.get("streakType") == "wins":
        return f"{n}連勝"
    return f"{n}連敗"


def table_html(rows: list) -> str:
    out = ['<table class="std-table">',
           "<tr><th class='team'>チーム</th><th>勝</th><th>負</th>"
           "<th>勝率</th><th>ゲーム差</th><th>直近</th></tr>"]
    for t in rows:
        tid = str((t.get("team") or {}).get("id"))
        name = MLB_TEAM_NAME_JP.get(tid) or (t.get("team") or {}).get("name", "")
        lead = ' class="lead"' if t.get("divisionRank") == "1" else ""
        gb = t.get("gamesBack") or "-"
        out.append(
            f"<tr{lead}><td class='team'>{html.escape(name)}</td>"
            f"<td>{t.get('wins', 0)}</td><td>{t.get('losses', 0)}</td>"
            f"<td>{html.escape(str(t.get('winningPercentage', '')))}</td>"
            f"<td>{html.escape(str(gb))}</td>"
            f"<td class='std-streak'>{streak_jp(t)}</td></tr>")
    out.append("</table>")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public/standings.html")
    ap.add_argument("--season", type=int,
                    default=datetime.now(JST).year)
    args = ap.parse_args()

    try:
        data = fetch(args.season)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 順位表を取れませんでした: {e}", file=sys.stderr)
        return 0
    if not data:
        print("[warn] 順位表が空でした", file=sys.stderr)
        return 0

    now = datetime.now(JST)
    stamp = now.strftime("%-m月%-d日 %H:%M") if sys.platform != "win32" \
        else now.strftime("%m月%d日 %H:%M").lstrip("0")
    desc = (f"MLB全30球団の順位表。6地区それぞれの勝敗・勝率・ゲーム差・"
            f"直近の連勝連敗を、MLB公式データから毎日更新しています"
            f"（{stamp}時点）。")

    head = ga.HEAD_TMPL.format(
        title=f"MLB順位表 {args.season}｜6地区の勝敗・ゲーム差 | コレスポ",
        description=html.escape(desc),
        canonical=f"{ga.SITE_URL}standings.html",
        root="",
        style=ga.STYLE + STYLE_EXTRA,
        extra_head="",
    )
    body = [head, f"<h1>MLB順位表 {args.season}</h1>",
            f'<p class="std-note">{html.escape(desc)}</p>']
    for did in ORDER:
        rows = data.get(did) or []
        if not rows:
            continue
        rows = sorted(rows, key=lambda t: int(t.get("divisionRank") or 99))
        body.append(f"<h2>{DIVISION_JP.get(did, '')}</h2>")
        body.append(table_html(rows))
    body.append('<p class="std-note">数字はMLB公式データをそのまま並べた'
                'ものです。ゲーム差の「-」は首位を表します。</p>')
    body.append('<p><a class="back" href="./">← コレスポのトップへ</a></p>')
    body.append("</body></html>")

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(body), encoding="utf-8")
    n = sum(len(v) for v in data.values())
    print(f"[info] {len(data)}地区 / {n}球団の順位表を書き出しました -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
