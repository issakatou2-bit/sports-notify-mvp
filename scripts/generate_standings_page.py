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
  地区順位とワイルドカード争いを分け、読み方と出典を添える。
  進出確率や未確認の前日差は作らない。欠測は0と区別する。

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
LEAGUES = [("al", "ア・リーグ", ORDER[:3]), ("nl", "ナ・リーグ", ORDER[3:])]

STYLE_EXTRA = """
  body { max-width:960px; }
  .std-hero { padding:.6rem 0 .7rem; border-bottom:2px solid var(--accent); }
  .std-kicker { font-size:.75rem; color:var(--jp); font-weight:700; letter-spacing:.1em; }
  .std-hero h1 { color:var(--text); font-family:inherit; font-size:clamp(1.8rem,5vw,2.8rem); line-height:1.35; }
  .std-hero p { max-width:680px; }
  .std-nav { display:flex; flex-wrap:wrap; gap:.55rem; margin:1.2rem 0; }
  .std-nav a { padding:.45rem .8rem; border:1px solid var(--border); border-radius:4px; font-size:.85rem; text-decoration:none; }
  .std-nav a:hover { background:var(--surface-raised); }
  .std-scroll { overflow-x:auto; margin-bottom:1.7rem; }
  .std-table { width:100%; min-width:520px; border-collapse:collapse; margin:.4rem 0; font-variant-numeric:tabular-nums; }
  .std-table caption { text-align:left; font-weight:700; font-size:1.05rem; padding:.7rem 0; }
  .std-table th, .std-table td { padding:.42rem .3rem; text-align:right;
    border-bottom:1px solid var(--border); font-size:.86rem; }
  .std-table th { color:var(--text-dim); font-weight:500; font-size:.74rem; }
  .std-table .team { text-align:left; font-size:.86rem; color:var(--text); min-width:125px; }
  .std-table thead th:nth-child(2) { text-align:left; }
  .std-table tr.lead { background:var(--surface-raised); }
  .std-table tr.lead .team { color:var(--accent); font-weight:700; }
  .std-table .cutoff > * { border-bottom:2px solid var(--accent); }
  .std-note { font-size:.78rem; color:var(--text-dim); margin:.2rem 0 1.4rem; }
  .std-streak { font-family:'JetBrains Mono',monospace; font-size:.78rem; }
  .std-guide { background:var(--surface); border:1px solid var(--border); padding:1.2rem; border-radius:8px; }
  .std-guide h2 { margin-top:0; }
  .std-guide dt { font-weight:700; margin-top:1rem; }
  .std-guide dd { margin:.3rem 0; font-size:.9rem; }
  .std-next { display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin:2rem 0; }
  .std-next a { background:var(--surface); border-top:3px solid var(--jp); padding:1rem; text-decoration:none; font-weight:700; }
  .std-next span { display:block; color:var(--text-dim); font-size:.8rem; font-weight:400; }
  section { scroll-margin-top:1rem; }
  @media(max-width:560px) { .std-next { grid-template-columns:1fr; } }
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
    validate_data(out, season)
    return out


def validate_data(data: dict, season: int) -> None:
    """Do not replace a full published table with a partial/wrong-season response."""
    if set(data) != set(ORDER) or any(len(data[d]) != 5 for d in ORDER):
        raise ValueError("全6地区・各5球団の順位データが揃っていません")
    teams = [t for rows in data.values() for t in rows]
    ids = [(t.get("team") or {}).get("id") for t in teams]
    if None in ids or len(set(ids)) != 30:
        raise ValueError("球団IDに欠落または重複があります")
    if any(str(t.get("season")) != str(season) for t in teams):
        raise ValueError("要求したシーズンと順位データが一致しません")


def cell(value) -> str:
    return "未取得" if value is None or value == "" else html.escape(str(value))


def team_name(t: dict) -> str:
    team = t.get("team") or {}
    return html.escape(MLB_TEAM_NAME_JP.get(str(team.get("id"))) or team.get("name", "球団名未取得"))


def rank_number(value) -> int:
    try:
        n = int(value)
        return n if n > 0 else 99
    except (ValueError, TypeError):
        return 99


def remaining(t: dict, season: int) -> str:
    """A reference calculation, not a promise that every game will be played."""
    played = t.get("gamesPlayed")
    if season < 2022 or type(played) is not int or not 0 <= played <= 162:
        return "未取得"
    return str(162 - played)


def wildcard_rows(data: dict, divisions: list) -> list:
    rows = [t for did in divisions for t in data[did]
            if t.get("divisionLeader") is not True
            and rank_number(t.get("divisionRank")) != 1]
    return sorted(rows, key=lambda t: rank_number(t.get("wildCardRank")))


def streak_jp(t: dict) -> str:
    """連勝・連敗。APIの streakCode は W3 / L1 の形。"""
    s = t.get("streak") or {}
    n = s.get("streakNumber")
    if type(n) is not int or n < 1:
        return "未取得"
    if s.get("streakType") == "wins":
        return f"{n}連勝"
    if s.get("streakType") == "losses":
        return f"{n}連敗"
    return "未取得"


def table_html(rows: list, caption: str, season: int, wildcard: bool = False) -> str:
    columns = ["WC順位" if wildcard else "地区順位", "チーム", "勝", "負", "勝率",
               "WC差" if wildcard else "ゲーム差", "残り目安", "直近"]
    out = [f'<div class="std-scroll" role="region" aria-label="{html.escape(caption)}、横にスクロールできます" tabindex="0">',
           '<table class="std-table">', f'<caption>{html.escape(caption)}</caption>',
           '<thead><tr>' + ''.join(f'<th scope="col">{c}</th>' for c in columns) + '</tr></thead><tbody>']
    for t in rows:
        rank = rank_number(t.get("wildCardRank" if wildcard else "divisionRank"))
        mark = ' class="cutoff"' if wildcard and rank == 3 and season >= 2022 else ""
        if not wildcard and rank == 1:
            mark = ' class="lead"'
        gb = t.get("wildCardGamesBack" if wildcard else "gamesBack")
        out.append(
            f"<tr{mark}><td>{rank if rank != 99 else '未取得'}</td>"
            f"<th scope='row' class='team'>{team_name(t)}</th>"
            f"<td>{cell(t.get('wins'))}</td><td>{cell(t.get('losses'))}</td>"
            f"<td>{cell(t.get('winningPercentage'))}</td><td>{cell(gb)}</td>"
            f"<td>{remaining(t, season)}</td>"
            f"<td class='std-streak'>{streak_jp(t)}</td></tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def source_dates(data: dict) -> str:
    stamps = []
    missing = 0
    for rows in data.values():
        for t in rows:
            try:
                stamp = datetime.fromisoformat(t["lastUpdated"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("timezone missing")
                stamps.append(stamp.astimezone(JST))
            except (KeyError, ValueError, AttributeError, TypeError):
                missing += 1
    if not stamps:
        return "球団データの更新日時：未取得"
    first, last = min(stamps), max(stamps)
    text = f"球団データの更新範囲：{first:%Y/%m/%d %H:%M}〜{last:%m/%d %H:%M}（日本時間）"
    return text + (f"。{missing}球団は更新日時未取得" if missing else "")


def render_page(data: dict, season: int, now: datetime) -> str:
    validate_data(data, season)
    desc = (f"MLB {season}の地区順位とワイルドカード争い。全30球団の勝敗・ゲーム差・"
            "残り試合の目安を、数字の読み方とあわせて確認できます。")
    head = ga.HEAD_TMPL.format(
        title=f"MLB順位表 {season}｜ワイルドカード争い・残り試合 | コレスポ",
        description=html.escape(desc), canonical=f"{ga.SITE_URL}standings.html", root="./",
        style=ga.STYLE + STYLE_EXTRA,
        extra_head='<script src="/site-theme.js"></script><link rel="stylesheet" href="/site-theme.css">'
                   '<link rel="icon" href="/favicon.ico" sizes="any">',
    )
    body = [head, '<main><header class="std-hero"><p class="std-kicker">観戦前に、いまの位置を。</p>',
            f'<h1>MLB順位表 {season}<br>ポストシーズンへの距離</h1>',
            '<p>地区首位との差と、ワイルドカードの位置を確認。'
            '次の観戦前に、応援する球団の現在地をつかめます。</p>',
            f'<p class="std-note">取得：<time datetime="{now.astimezone(JST).isoformat()}">{now.astimezone(JST):%Y/%m/%d %H:%M} 日本時間</time><br>'
            f'{source_dates(data)}<br>試合中のリアルタイム順位ではありません。球団ごとに更新時刻が異なります。</p></header>',
            '<nav class="std-nav" aria-label="順位表の目次"><a href="#wildcard">ワイルドカード争い</a>'
            '<a href="#divisions">6地区の順位</a><a href="#reading">数字の読み方</a></nav>',
            '<section id="wildcard"><h2>ワイルドカード争い</h2>']
    if season >= 2022:
        body.append('<p>地区首位を除いた公式順位です。線は3位の区切りで、進出確定ではありません。</p>')
    else:
        body.append('<p>当該年の進出枠は現在と異なる場合があります。公式の当該年の制度をご確認ください。</p>')
    body.append('<p class="std-note">WC差は公式値です。「＋」は圏内からのリード、符号なしは圏内までの差。'
                '同じゲーム差でも順位は異なる場合があります。狭い画面では表を横に動かせます。</p>')
    for slug, name, divisions in LEAGUES:
        body.append(table_html(wildcard_rows(data, divisions), name, season, wildcard=True))
    body.append('</section><section id="divisions"><h2>6地区の順位</h2>'
                '<p class="std-note">背景色のある行は現在の地区首位。優勝確定を意味しません。</p>')
    for did in ORDER:
        rows = sorted(data[did], key=lambda t: rank_number(t.get("divisionRank")))
        body.append(table_html(rows, DIVISION_JP[did], season))
    body.append('</section><section id="reading" class="std-guide"><h2>数字の読み方</h2><dl>'
                '<dt>地区順位とワイルドカード順位</dt><dd>まず所属地区の表で首位との差を確認。'
                '地区首位でない球団は、別地区の球団とも競うワイルドカード表へ進むと位置が分かります。</dd>'
                '<dt>ゲーム差と「未取得」</dt><dd>地区のゲーム差は首位からの距離です。「−」は公式データの表記を保持。'
                '数字が届いていない場合は「未取得」と表示し、0差とは区別しています。</dd>'
                '<dt>残り試合の目安</dt><dd>2022年以降は162試合から公式の消化試合数を引いた参考値です。'
                '中止や未消化により実際に行われる試合数と異なる場合があります。</dd>'
                '<dt>同じ成績・ゲーム差でも並びが違うとき</dt><dd>掲載順は公式APIの順位に従います。'
                '最終的な同率順位にはタイブレークの規則があります。'
                '<a href="https://www.mlb.com/news/mlb-playoff-tiebreaker-rules">同率時の公式ルール</a></dd></dl></section>')
    if season >= 2022:
        body.append('<p class="std-note">現在の制度では、各リーグの地区優勝3球団とワイルドカード3球団が進出します。'
                    '<a href="https://www.mlb.com/news/mlb-playoff-format-faq">制度の公式説明</a></p>')
    body.append('<nav class="std-next" aria-label="次に読む"><a href="./#today">次の注目試合を読む'
                '<span>現在地が分かったら、次の対戦へ。</span></a><a href="players/">日本人選手の記録を見る'
                '<span>応援する選手から、試合をたどる。</span></a></nav>')
    body.append(f'<p class="std-note">出典：<a href="https://www.mlb.com/standings/">MLB公式順位表</a> / '
                f'<a href="{API}/standings?leagueId=103%2C104&amp;season={season}&amp;standingsTypes=regularSeason">MLB公式データ</a>。'
                '<a href="about.html#corrections">誤りの連絡・掲載方針</a></p></main></body></html>')
    return "\n".join(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public/standings.html")
    ap.add_argument("--season", type=int,
                    default=datetime.now(JST).year)
    args = ap.parse_args()

    try:
        data = fetch(args.season)
        page = render_page(data, args.season, datetime.now(JST))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 順位表を取れませんでした: {e}", file=sys.stderr)
        return 1

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    n = sum(len(v) for v in data.values())
    print(f"[info] {len(data)}地区 / {n}球団の順位表を書き出しました -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
