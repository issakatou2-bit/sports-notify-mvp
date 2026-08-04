"""
archive/*.json から、日付ごとの静的HTMLページを生成する。

なぜ静的ページにするのか:
  これまでアーカイブは archive.html が JavaScript で JSON を読み込んで
  表示する作りだった。この方式だとURLが1つしか存在しないため、
  何日分データが溜まっても検索エンジンからは「1ページのサイト」に見える。
  日付ごとに独立したURL(/archive/2026-07-28.html)を持たせることで、
  「ホワイトソックス アストロズ 7/28」のような検索に個別にヒットしうる
  状態を作る。AdSenseが求める「コンテンツの厚み」の観点でも効いてくる。

生成物:
  public/archive/YYYY-MM-DD.html  … 各日のページ(JSON-LD構造化データ入り)
  public/archive/index.html       … 日付一覧ページ
  public/archive/index.json       … 日付一覧(既存のarchive.htmlが参照する)

使い方:
  python3 scripts/generate_archive_pages.py --archive-dir archive --out-dir public/archive
"""

import argparse
import html
import json
import pathlib
import re
from datetime import datetime

SITE_URL = "https://collespo.com/"

# archive/2026-07-28.json のような命名だけを対象にする(index.json等を除外するため)
DATE_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.json$")

STYLE = """
  :root {
    color-scheme: dark;
    --bg: #0B0E14;
    --surface: #12161F;
    --surface-raised: #171C27;
    --border: #232838;
    --text: #F2F0E6;
    --text-dim: #8891A3;
    --accent: #FFB020;
    --jp: #49C5B6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0 auto;
    padding: 1.5rem 1.25rem 3rem;
    max-width: 720px;
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif;
    line-height: 1.8;
  }
  a { color: var(--accent); }
  .home-link {
    display: inline-block;
    font-size: 0.85rem;
    color: var(--text-dim);
    text-decoration: none;
    margin-bottom: 1.2rem;
  }
  h1 {
    font-family: 'Oswald', sans-serif;
    font-size: 1.5rem;
    color: var(--accent);
    margin: 0 0 0.3rem;
  }
  .lead { color: var(--text-dim); font-size: 0.85rem; margin: 0 0 2rem; }
  .game {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.1rem 1.2rem;
    margin-bottom: 1.5rem;
  }
  .game h2 {
    font-size: 1.15rem;
    margin: 0 0 0.4rem;
  }
  .time {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: var(--text-dim);
  }
  .result {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.95rem;
    color: var(--text);
    background: var(--surface-raised);
    border-radius: 6px;
    padding: 0.5rem 0.8rem;
    margin: 0.6rem 0;
  }
  .result .winner { color: var(--accent); font-family: 'Inter', sans-serif; font-size: 0.8rem; }
  .badges { margin: 0.5rem 0 0.8rem; }
  .badge {
    display: inline-block;
    font-size: 0.72rem;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--surface-raised);
    color: var(--text-dim);
    margin-right: 6px;
  }
  .badge.jp { color: var(--jp); border-color: var(--jp); }
  .summary { font-size: 0.95rem; margin: 0 0 0.9rem; }
  mark { background: linear-gradient(transparent 58%, rgba(255,176,32,0.32) 58%);
         color: var(--text); font-weight: 600; padding: 0 1px; }
  ul.reasons { padding-left: 1.1rem; margin: 0; }
  ul.reasons li { font-size: 0.87rem; color: var(--text-dim); }
  .video { margin-top: 1rem; }
  .video iframe {
    width: 100%;
    aspect-ratio: 16 / 9;
    border: 0;
    border-radius: 8px;
  }
  .video p { font-size: 0.78rem; color: var(--text-dim); margin: 0.4rem 0 0; }
  nav.pager {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-top: 2.5rem;
    font-size: 0.85rem;
  }
  nav.pager span { color: var(--text-dim); }
  ul.datelist { list-style: none; padding: 0; }
  ul.datelist li {
    border-bottom: 1px solid var(--border);
    padding: 0.7rem 0;
  }
  ul.datelist .sub { display: block; font-size: 0.8rem; color: var(--text-dim); }
"""

HEAD_TMPL = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<meta name="description" content="{description}" />
<link rel="canonical" href="{canonical}" />
<link rel="apple-touch-icon" href="{root}icons/icon-192.png" />
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-3009257813842371"
     crossorigin="anonymous"></script>
<style>{style}</style>
{extra_head}
</head>
<body>
<a class="home-link" href="{root}">&larr; コレスポ トップへ</a>
"""


def parse_date_files(archive_dir: pathlib.Path) -> list:
    """archive配下の YYYY-MM-DD.json を、日付の新しい順に並べて返す。"""
    entries = []
    for p in sorted(archive_dir.glob("*.json")):
        m = DATE_FILE_RE.match(p.name)
        if not m:
            continue  # index.json など、日付形式でないものは対象外
        entries.append((f"{m.group(1)}-{m.group(2)}-{m.group(3)}", p))
    entries.sort(key=lambda x: x[0], reverse=True)
    return entries


def game_datetime_iso(archive_date: str, start_time_jst: str):
    """
    'MM/DD HH:MM'(JST) と アーカイブ日付から ISO8601(+09:00) を組み立てる。
    アーカイブ日付は「生成日」であり、試合日は基本その翌日になる。年末年始に
    年をまたぐケース(12月生成→1月の試合)があるため、月が巻き戻っていたら
    翌年として扱う。組み立てられない場合はNoneを返す(構造化データ側で省略)。
    """
    if not start_time_jst or " " not in start_time_jst:
        return None
    try:
        md, hm = start_time_jst.split(" ", 1)
        month, day = (int(x) for x in md.split("/"))
        hour, minute = (int(x) for x in hm.split(":"))
        year, arc_month, _ = (int(x) for x in archive_date.split("-"))
        if month < arc_month:  # 12月生成 → 1月の試合
            year += 1
        return datetime(year, month, day, hour, minute).strftime(
            "%Y-%m-%dT%H:%M:00+09:00"
        )
    except (ValueError, TypeError):
        return None


def build_jsonld(games: list, archive_date: str) -> str:
    """
    試合ごとの SportsEvent 構造化データを組み立てる。
    データとして確実に持っている項目(名称・開始日時・対戦チーム)だけを書き、
    会場など保持していない情報は捏造せず省略する。
    """
    events = []
    for g in games:
        iso = game_datetime_iso(archive_date, g.get("start_time_jst"))
        event = {
            "@context": "https://schema.org",
            "@type": "SportsEvent",
            "name": g.get("matchup", ""),
            "sport": "Baseball" if g.get("league") == "MLB" else "Soccer",
            "competitor": [
                {"@type": "SportsTeam", "name": g.get("home_team_name", "")},
                {"@type": "SportsTeam", "name": g.get("away_team_name", "")},
            ],
        }
        if iso:
            event["startDate"] = iso
        events.append(event)
    if not events:
        return ""
    return (
        '<script type="application/ld+json">'
        + json.dumps(events, ensure_ascii=False)
        + "</script>"
    )


def render_badges(g: dict) -> str:
    badges = []
    for p in g.get("jp_starters") or []:
        badges.append(
            f'<span class="badge jp">JP先発: {html.escape(p.get("name", ""))}</span>'
        )
    if g.get("same_division"):
        badges.append('<span class="badge">同地区対決</span>')
    if g.get("rivalry_type") == "historic":
        badges.append('<span class="badge">伝統の好カード</span>')
    if g.get("rivalry_type") == "city":
        badges.append('<span class="badge">同都市対決</span>')
    badges.append(f'<span class="badge">{html.escape(g.get("league", ""))}</span>')
    return '<div class="badges">' + "".join(badges) + "</div>"


def team_badge_html(abbr, color) -> str:
    if not abbr or not color:
        return ""
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    fg = "#111" if luminance > 0.6 else "#fff"
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f'width:26px;height:18px;border-radius:4px;background:{color};color:{fg};'
        f"font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;"
        f'margin-right:4px;">{html.escape(abbr)}</span>'
    )


def render_game(g: dict) -> str:
    parts = ['<article class="game">']
    home_badge = team_badge_html(g.get("home_abbr"), g.get("home_color"))
    away_badge = team_badge_html(g.get("away_abbr"), g.get("away_color"))
    parts.append(
        f'<h2>{home_badge}{html.escape(g.get("home_team_name", ""))} vs '
        f'{away_badge}{html.escape(g.get("away_team_name", ""))}</h2>'
    )
    if g.get("start_time_jst"):
        parts.append(
            f'<div class="time">{html.escape(g["start_time_jst"])} (JST)</div>'
        )

    final_score = g.get("final_score")
    if final_score:
        home_name = g.get("home_team_name", "")
        away_name = g.get("away_team_name", "")
        winner_name = home_name if final_score.get("winner") == "home" else away_name
        parts.append(
            '<div class="result">'
            f'{html.escape(home_name)} {final_score.get("home")} - '
            f'{final_score.get("away")} {html.escape(away_name)}'
            f'　<span class="winner">{html.escape(winner_name)}勝利</span>'
            "</div>"
        )

    parts.append(render_badges(g))

    if g.get("ai_summary"):
        # AIが【】で囲んだ要点だけをマーカー表示にする。
        # 先にエスケープしてからタグを差し込むことで、生成文が
        # そのままHTMLとして解釈されることを防いでいる。
        summary = re.sub(
            r"【([^】]{1,40})】", r"<mark>\\1</mark>", html.escape(g["ai_summary"])
        )
        parts.append(f'<p class="summary">{summary}</p>')

    visible_reasons = [
        r for r in g.get("reasons", []) if r.get("visible", True) and r.get("text")
    ]
    if visible_reasons:
        parts.append('<ul class="reasons">')
        for r in visible_reasons:
            parts.append(f'<li>{html.escape(r["text"])}</li>')
        parts.append("</ul>")

    # MLB公式ハイライト動画。試合終了後の生成でのみIDが入るため、
    # 無ければ何も出さない(過去日のページほど埋まりやすい)。
    video_id = g.get("highlight_video_id")
    if video_id:
        parts.append('<div class="video">')
        parts.append(
            f'<iframe src="https://www.youtube.com/embed/{html.escape(video_id)}" '
            f'title="{html.escape(g.get("matchup", ""))} ハイライト" '
            'loading="lazy" allowfullscreen></iframe>'
        )
        parts.append("<p>MLB公式チャンネルのハイライト映像</p>")
        parts.append("</div>")

    detail_query = f'{g.get("home_team_name", "")} {g.get("away_team_name", "")} 速報'
    detail_url = "https://search.yahoo.co.jp/search?p=" + detail_query.replace(" ", "+")
    parts.append(
        f'<p><a href="{html.escape(detail_url)}" target="_blank" rel="noopener">'
        "試合経過・詳細を検索(スポナビ等)</a></p>"
    )

    parts.append("</article>")
    return "\n".join(parts)


def render_day_page(archive_date: str, data: dict, prev_date, next_date) -> str:
    games = [g for g in data.get("games", []) if g.get("is_notable")]
    y, m, d = archive_date.split("-")
    jp_date = f"{y}年{int(m)}月{int(d)}日"

    if games:
        top = games[0].get("matchup", "")
        description = (
            f"{jp_date}にコレスポが選んだ注目試合。{top}ほか、"
            "なぜ注目なのかの理由つきで振り返ります。"
        )
    else:
        description = f"{jp_date}の注目試合の記録です。"

    head = HEAD_TMPL.format(
        title=f"{jp_date}の注目試合 | コレスポ",
        description=html.escape(description),
        canonical=f"{SITE_URL}archive/{archive_date}.html",
        root="../",
        style=STYLE,
        extra_head=build_jsonld(games, archive_date),
    )

    body = [head]
    body.append(f"<h1>{jp_date}の注目試合</h1>")
    body.append(
        f'<p class="lead">コレスポが選んだこの日の注目カードです。'
        f'<a href="./">アーカイブ一覧へ</a></p>'
    )

    if games:
        for g in games:
            body.append(render_game(g))
    else:
        body.append('<p class="lead">この日は注目試合がありませんでした。</p>')

    # 前後の日へのリンク。クローラーが日付ページを辿れるようにする狙いもある
    body.append('<nav class="pager">')
    if prev_date:
        body.append(f'<a href="{prev_date}.html">&larr; {prev_date}</a>')
    else:
        body.append("<span></span>")
    if next_date:
        body.append(f'<a href="{next_date}.html">{next_date} &rarr;</a>')
    else:
        body.append("<span></span>")
    body.append("</nav>")
    body.append("</body></html>")
    return "\n".join(body)


def render_index_page(entries: list, summaries: dict) -> str:
    head = HEAD_TMPL.format(
        title="注目試合アーカイブ | コレスポ",
        description="コレスポがこれまでに選んだ日ごとの注目試合を、"
        "理由つきで振り返れるアーカイブです。",
        canonical=f"{SITE_URL}archive/",
        root="../",
        style=STYLE,
        extra_head="",
    )
    body = [head]
    body.append("<h1>注目試合アーカイブ</h1>")
    body.append(
        '<p class="lead">日付ごとに、その日の注目カードと注目理由を振り返れます。</p>'
    )
    body.append('<ul class="datelist">')
    for date_str, _ in entries:
        y, m, d = date_str.split("-")
        label = f"{y}年{int(m)}月{int(d)}日"
        sub = summaries.get(date_str, "")
        body.append(
            f'<li><a href="{date_str}.html">{label}</a>'
            + (f'<span class="sub">{html.escape(sub)}</span>' if sub else "")
            + "</li>"
        )
    body.append("</ul>")
    body.append("</body></html>")
    return "\n".join(body)


def render_sitemap(entries: list, site_root: pathlib.Path = None) -> str:
    """
    sitemap.xml を組み立てる。日付ページは数が増えていく一方で、トップから
    直接リンクされているわけではないため、クローラーに存在を伝える手段として
    用意する。lastmodにはその日付を入れる。
    """
    urls = [
        (SITE_URL, None),
        (f"{SITE_URL}archive/", None),
        (f"{SITE_URL}glossary.html", None),
        (f"{SITE_URL}about.html", None),
        (f"{SITE_URL}privacy.html", None),
        (f"{SITE_URL}quiz.html", None),
        (f"{SITE_URL}lineup.html", None),
        (f"{SITE_URL}players/", None),
    ]
    # 選手ページ(generate_player_pages.pyが生成する分)もsitemapに含める。
    # パスは site_root から導出する(固定文字列にすると、実行時の
    # カレントディレクトリ次第で見つからず、静かに漏れてしまうため)。
    players_dir = (site_root or pathlib.Path("public")) / "players"
    if players_dir.exists():
        for f in sorted(players_dir.glob("*.html")):
            if f.name != "index.html":
                urls.append((f"{SITE_URL}players/{f.name}", None))
    urls += [(f"{SITE_URL}archive/{d}.html", d) for d, _ in entries]

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, lastmod in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{html.escape(loc)}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--out-dir", default="public/archive")
    parser.add_argument(
        "--site-root",
        default="public",
        help="sitemap.xmlを書き出す先(サイトのルートに相当するディレクトリ)",
    )
    args = parser.parse_args()

    archive_dir = pathlib.Path(args.archive_dir)
    out_dir = pathlib.Path(args.out_dir)
    if not archive_dir.exists():
        print(f"[warn] {archive_dir} が見つからないため、アーカイブ生成をスキップします")
        return

    entries = parse_date_files(archive_dir)
    if not entries:
        print("[warn] アーカイブ対象のJSONが見つかりませんでした")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # entriesは新しい順。prev/nextは日付の前後で結びたいので、日付昇順の配列も作る
    asc = list(reversed(entries))
    date_to_index = {d: i for i, (d, _) in enumerate(asc)}

    summaries = {}
    generated = 0
    for date_str, path in entries:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] {path} の読み込みに失敗したためスキップします: {e}")
            continue

        i = date_to_index[date_str]
        prev_date = asc[i - 1][0] if i > 0 else None
        next_date = asc[i + 1][0] if i + 1 < len(asc) else None

        page = render_day_page(date_str, data, prev_date, next_date)
        (out_dir / f"{date_str}.html").write_text(page, encoding="utf-8")
        generated += 1

        notable = [g for g in data.get("games", []) if g.get("is_notable")]
        if notable:
            summaries[date_str] = notable[0].get("matchup", "")

    (out_dir / "index.html").write_text(
        render_index_page(entries, summaries), encoding="utf-8"
    )
    # 既存のarchive.html(JSで一覧を描画する方)が参照するため、日付一覧も出力する
    (out_dir / "index.json").write_text(
        json.dumps([d for d, _ in entries], ensure_ascii=False), encoding="utf-8"
    )

    print(f"[info] アーカイブページを{generated}件生成しました -> {out_dir}")

    site_root = pathlib.Path(args.site_root)
    site_root.mkdir(parents=True, exist_ok=True)
    (site_root / "sitemap.xml").write_text(
        render_sitemap(entries, site_root), encoding="utf-8"
    )
    (site_root / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n", encoding="utf-8"
    )
    print(f"[info] sitemap.xml / robots.txt を出力しました -> {site_root}")


if __name__ == "__main__":
    main()
