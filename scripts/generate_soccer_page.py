#!/usr/bin/env python3
"""
欧州サッカーの案内ページ public/soccer.html を作る。

なぜ静的に書かず生成するのか:
  載せる内容(所属クラブ・開幕日・昨季順位)は、いずれも他の場所に
  既にある。手で書き写すと、移籍や日程変更のたびにサイトだけが
  古くなる。動画と同じ材料から作れば、そこがずれない。

    JP_PLAYERS_SOCCER      … 日本人選手と所属クラブ
    data/soccer_preview.json … 開幕日程・昨季順位(無ければその節を省く)

検索の狙い:
  MLB側は「大谷翔平 今日 試合」のような選手名検索が主だが、
  サッカーは開幕前に「プレミアリーグ 開幕 いつ」「海外組 まとめ」
  のような、日付を持たない調べ物の検索が立つ。開幕してからでは
  遅いので、開幕前に置いておく。

使い方:
  python3 scripts/generate_soccer_page.py --out public/soccer.html
"""

import argparse
import datetime as dt
import html
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import soccer_preview  # noqa: E402
from notability_engine import (  # noqa: E402
    JP_PLAYERS_SOCCER,
    SOCCER_LEAGUE_NAME_JP,
    club_name_jp,
)

SITE_URL = "https://collespo.com/"

# 表示順。2部リーグは5大リーグの後ろへ回す。
LEAGUE_ORDER = ["PL", "PD", "SA", "BL1", "FL1", "ELC", "BL2"]

STYLE = """
  :root {
    color-scheme: dark;
    --bg: #0B0E14; --surface: #12161F; --surface-raised: #171C27;
    --border: #232838; --text: #F2F0E6; --text-dim: #8891A3;
    --accent: #FFB020; --jp: #49C5B6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0 auto; padding: 1.5rem 1.25rem 3rem; max-width: 720px;
    background: var(--bg); color: var(--text); line-height: 1.8;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif;
  }
  a { color: var(--accent); }
  .back { display: inline-block; font-size: 0.85rem; color: var(--text-dim);
          text-decoration: none; margin-bottom: 1.2rem; }
  h1 { font-family: 'Oswald', sans-serif; font-size: 1.6rem;
       color: var(--accent); margin: 0 0 0.3rem; }
  .lead { color: var(--text-dim); font-size: 0.9rem; margin: 0 0 2rem; }
  h2 { font-family: 'Oswald', sans-serif; font-size: 1.2rem; color: var(--text);
       border-bottom: 1px solid var(--border); padding-bottom: 0.4rem;
       margin: 2.4rem 0 1rem; }
  h3 { font-size: 1rem; color: var(--jp); margin: 1.4rem 0 0.5rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem;
          margin: 0.5rem 0 1rem; }
  th, td { text-align: left; padding: 0.5rem 0.6rem;
           border-bottom: 1px solid var(--border); }
  /* クラブ名が長いと列が詰まり、「順位」が「順/位」と縦に割れる。
     見出しだけ折り返さないようにする(クラブ名は折り返してよい)。 */
  th { color: var(--text-dim); font-weight: 500; font-size: 0.8rem;
       white-space: nowrap; }
  td:first-child { white-space: nowrap; }
  td.club { color: var(--text-dim); }
  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: 10px; padding: 0.9rem 1rem; margin: 0.6rem 0; }
  .card .when { color: var(--accent); font-size: 0.8rem; }
  .card .why { color: var(--text-dim); font-size: 0.85rem; }
  .note { color: var(--text-dim); font-size: 0.8rem; margin-top: 0.4rem; }
  dl { margin: 0; }
  dt { font-weight: 600; color: var(--accent); margin-top: 1rem; }
  dd { margin: 0.2rem 0 0; }
  .fixtures { padding-left: 1.2rem; margin: 0.6rem 0 0; }
  .fixtures > li { margin-bottom: 1rem; }
  .fixtures .when { display: block; color: var(--accent); font-size: 0.8rem; }
  .fixtures ul { margin: 0.3rem 0 0; padding-left: 1.1rem;
                 color: var(--text-dim); font-size: 0.85rem; }
  .updated { color: var(--text-dim); font-size: 0.8rem; margin-top: 2.5rem; }
"""

# 指標の説明。資産動画(soccer_terms)と同じ内容にしてある。
# 片方だけ直すと説明が食い違うので、変えるときは両方を見ること。
TERMS = [
    ("xG（期待ゴール）",
     "そのシュートが決まる確率を、位置や状況から見積もった数字。0.8なら"
     "「8割方入る場面」。試合のxGを足すと、本来何点入ってもおかしくなかったか"
     "が見えます。"),
    ("xA（期待アシスト）",
     "そのパスがアシストになる確率。得点に結びつかなくても、"
     "良い形を作れていたかが分かります。"),
    ("ポゼッション率",
     "ボールを保持していた時間の割合。ただし高いほど強いとは限らず、"
     "あえて相手に持たせて守る戦い方もあります。"),
    ("PPDA",
     "相手が何本パスを通すごとに守備を仕掛けたかを表す数字。"
     "小さいほど前から激しく追っている、という読み方をします。"),
    ("クリーンシート",
     "無失点で試合を終えること。守備陣とGKの評価によく使われます。"),
]

LEAGUE_NOTES = [
    ("プレミアリーグ（イングランド）", "20クラブ。放映権収入が最も大きく、"
     "資金力の面で世界最高峰とされます。日本人選手が多く在籍するリーグでもあります。"),
    ("ラ・リーガ（スペイン）", "20クラブ。技術と戦術を重んじる作りで、"
     "レアル・マドリードとバルセロナの2強が長く中心にいます。"),
    ("セリエA（イタリア）", "20クラブ。守備の組織を重視する伝統があり、"
     "戦術的な駆け引きが見どころとされます。"),
    ("ブンデスリーガ（ドイツ）", "18クラブ。観客動員が多く、"
     "若手が出場機会を得やすいリーグとして知られます。"),
    ("リーグ・アン（フランス）", "18クラブ。育成に定評があり、"
     "ここから他リーグへ移る選手が多く出ます。"),
    ("チャンピオンズリーグ", "各国リーグの上位クラブが集まる大会。"
     "火曜と水曜に開催されるので、週末のリーグ戦と合わせるとほぼ毎日試合があります。"),
]


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def load_preview(path: str) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def jp_day(date_str) -> str:
    if not date_str:
        return ""
    try:
        t = dt.datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{t.year}年{t.month}月{t.day}日"


def jp_datetime(utc) -> str:
    """欧州の夜の試合は日本時間では翌朝になるので、日本時間へ直して出す。"""
    if not utc:
        return ""
    try:
        t = dt.datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ""
    t = t.replace(tzinfo=dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=9))
    )
    return f"{t.month}月{t.day}日 {t.hour}:{t.minute:02d}"


def players_section() -> str:
    by_league: dict = {}
    for p in JP_PLAYERS_SOCCER:
        by_league.setdefault(p["league"], []).append(p)

    order = [c for c in LEAGUE_ORDER if c in by_league]
    order += [c for c in by_league if c not in order]

    out = [f"<h2>欧州でプレーする日本人選手（{len(JP_PLAYERS_SOCCER)}人）</h2>"]
    for code in order:
        members = by_league[code]
        name = SOCCER_LEAGUE_NAME_JP.get(code, code)
        out.append(f"<h3>{esc(name)}（{len(members)}人）</h3>")
        out.append("<table><tr><th>選手</th><th>所属クラブ</th></tr>")
        for p in members:
            out.append(
                f"<tr><td>{esc(p['name_jp'])}</td>"
                f"<td class=\"club\">{esc(p['team_jp'])}</td></tr>"
            )
        out.append("</table>")
    out.append('<p class="note">所属は移籍市場の動きで変わります。'
               '移籍市場は9月上旬まで開いています。</p>')
    return "\n".join(out)


def schedule_section(preview: dict) -> str:
    comps = preview.get("competitions", [])
    rows = []
    for c in comps:
        # APIがまだ次シーズンへ切り替えていない競技会は載せない。
        # 終わったシーズンの日程を「今シーズン」として出すことになる。
        if soccer_preview.is_stale(c):
            continue
        season = c.get("season") or {}
        start, end = jp_day(season.get("start")), jp_day(season.get("end"))
        if not start:
            continue
        rows.append((c.get("name_jp", c.get("code")), start, end))
    if not rows:
        return ""

    out = ["<h2>今シーズンの日程</h2>",
           "<table><tr><th>リーグ</th><th>開幕</th><th>最終節</th></tr>"]
    for name, start, end in rows:
        out.append(f"<tr><td>{esc(name)}</td><td>{esc(start)}</td>"
                   f"<td class=\"club\">{esc(end)}</td></tr>")
    out.append("</table>")
    out.append('<p class="note">日程は変更されることがあります。'
               '正式な情報は各リーグの公式発表をご確認ください。</p>')
    return "\n".join(out)


def highlights_section(preview: dict) -> str:
    picks = []
    for c in preview.get("competitions", []):
        if soccer_preview.is_stale(c):
            continue
        for m in c.get("highlights", []):
            picks.append((c.get("name_jp", c.get("code")), m))
    picks.sort(key=lambda x: -x[1].get("score", 0))

    # 動画と同じく1リーグ2件まで。点順のまま並べると1リーグで埋まる。
    per_league: dict = {}
    limited = []
    for league, m in picks:
        if per_league.get(league, 0) >= 2:
            continue
        per_league[league] = per_league.get(league, 0) + 1
        limited.append((league, m))
    if not limited:
        return ""

    out = ["<h2>序盤の注目カード</h2>",
           '<p class="note">昨シーズンの最終順位と、日本人選手の所属クラブから'
           '機械的に選んでいます。時刻は日本時間です。</p>']
    for league, m in limited[:8]:
        home = club_name_jp(m.get("home") or "")
        away = club_name_jp(m.get("away") or "")
        when = jp_datetime(m.get("utc") or "")
        why = "、".join(m.get("reasons", []))
        out.append(
            f'<div class="card"><strong>{esc(home)} 対 {esc(away)}</strong>'
            f'<div class="when">{esc(league)}'
            + (f" / {esc(when)}" if when else "")
            + "</div>"
            + (f'<div class="why">{esc(why)}</div>' if why else "")
            + "</div>"
        )
    return "\n".join(out)


def last_season_section(preview: dict) -> str:
    out = []
    for c in preview.get("competitions", []):
        if soccer_preview.is_stale(c):
            continue
        table = c.get("last_season") or []
        if not table:
            continue
        year = c.get("last_season_year")
        label = c.get("name_jp", c.get("code"))
        if year:
            label += f"（{year}-{str(year + 1)[-2:]}）"
        out.append(f"<h3>{esc(label)}</h3>")
        out.append("<table><tr><th>順位</th><th>クラブ</th>"
                   "<th>勝点</th><th>得失点</th></tr>")
        for r in table[:5]:
            gf, ga = r.get("gf"), r.get("ga")
            diff = f"{gf - ga:+d}" if isinstance(gf, int) and isinstance(ga, int) else ""
            out.append(
                f"<tr><td>{esc(r.get('position'))}</td>"
                f"<td>{esc(club_name_jp(r.get('team') or ''))}</td>"
                f"<td>{esc(r.get('points'))}</td>"
                f"<td class=\"club\">{esc(diff)}</td></tr>"
            )
        out.append("</table>")
    if not out:
        return ""
    return "<h2>昨シーズンの結果</h2>\n" + "\n".join(out)


def fixtures_section(games: list) -> str:
    """
    その日の注目試合。20時のサッカー動画と同じ選定・同じ理由を出す。

    ここが無いと、動画は出ているのにサイト側に着地点が無い。
    MLBは日次のたびにアーカイブページができて、それが検索の入口に
    なっているが、サッカーには対応するページが1つも無かった。
    「プレミアリーグ 今日 試合」で入ってくる導線を作る。
    """
    if not games:
        return ""
    out = ["<h2>今夜の注目試合</h2>",
           '<p class="note">コレスポが選んだ、その日の注目カードです。'
           '選んだ理由も添えています。時刻は日本時間です。</p>',
           '<ol class="fixtures">']
    for g in games[:3]:
        home = esc(g.get("home_team_name") or "")
        away = esc(g.get("away_team_name") or "")
        when = jp_datetime(g.get("start_time_utc") or g.get("game_date") or "")
        league = esc(SOCCER_LEAGUE_NAME_JP.get(g.get("league"), g.get("league") or ""))
        reasons = [r.get("text") for r in (g.get("reasons") or [])
                   if r.get("visible", True) and r.get("text")][:3]
        out.append("<li>")
        out.append(f"<strong>{home} vs {away}</strong>")
        meta = " ".join(x for x in (when, league) if x)
        if meta:
            out.append(f'<span class="when">{esc(meta)}</span>')
        if reasons:
            out.append("<ul>"
                       + "".join(f"<li>{esc(r)}</li>" for r in reasons)
                       + "</ul>")
        out.append("</li>")
    out.append("</ol>")
    return "\n".join(out)


def render(preview: dict, games: list = None) -> str:
    sections = [
        fixtures_section(games or []),
        schedule_section(preview),
        highlights_section(preview),
        players_section(),
        last_season_section(preview),
    ]

    leagues = ["<h2>5大リーグとチャンピオンズリーグ</h2>", "<dl>"]
    for name, note in LEAGUE_NOTES:
        leagues.append(f"<dt>{esc(name)}</dt><dd>{esc(note)}</dd>")
    leagues.append("</dl>")
    sections.append("\n".join(leagues))

    terms = ["<h2>知っておくと見やすくなる指標</h2>", "<dl>"]
    for name, note in TERMS:
        terms.append(f"<dt>{esc(name)}</dt><dd>{esc(note)}</dd>")
    terms.append("</dl>")
    terms.append(f'<p class="note">野球の用語も含めた一覧は'
                 f'<a href="glossary.html">用語集</a>にあります。</p>')
    sections.append("\n".join(terms))

    generated = preview.get("generated_at", "")[:10]
    body = "\n\n".join(s for s in sections if s)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
<title>欧州サッカー 開幕ガイド | コレスポ</title>
<meta name="description" content="欧州5大リーグの開幕日程、序盤の注目カード、日本人選手の所属クラブ、xGなどの指標の見方をまとめています。" />
<link rel="canonical" href="{SITE_URL}soccer.html" />
<meta property="og:title" content="欧州サッカー 開幕ガイド | コレスポ" />
<meta property="og:description" content="開幕日程・注目カード・日本人選手の所属クラブ・指標の見方。" />
<meta property="og:url" content="{SITE_URL}soccer.html" />
<meta property="og:type" content="article" />
<link rel="apple-touch-icon" href="icons/icon-192.png" />
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{STYLE}</style>
</head>
<body>
  <a class="back" href="index.html">&larr; コレスポ トップへ</a>
  <h1>欧州サッカー 開幕ガイド</h1>
  <p class="lead">開幕日程、序盤に見ておきたいカード、日本人選手の所属クラブ、
  そして中継で出てくる指標の見方をまとめています。</p>

{body}

  <p class="updated">{esc("更新: " + generated if generated else "")}</p>
  <a class="back" href="index.html">&larr; コレスポ トップへ</a>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", default="data/soccer_preview.json")
    ap.add_argument("--out", default="public/soccer.html")
    ap.add_argument("--games", default="data/soccer_games.json",
                    help="その日の注目試合。無ければその節を省く")
    args = ap.parse_args()

    preview = load_preview(args.preview)
    if not preview:
        # 名簿と解説だけでもページとしては成立する。日程が無いことを
        # 理由にページごと落とすと、開幕前の検索需要を丸ごと逃す。
        print(f"[info] {args.preview} が無いため、日程と昨季順位は省きます")

    # その日の試合。開幕前やオフの日は無いので、無ければ節ごと省く。
    games = []
    gp = pathlib.Path(args.games)
    if gp.exists():
        try:
            data = json.loads(gp.read_text(encoding="utf-8"))
            games = [g for g in data.get("games", []) if g.get("is_notable")]
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] {args.games} を読めませんでした: {e}")
    else:
        print(f"[info] {args.games} が無いため、今夜の注目試合は省きます")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(preview, games), encoding="utf-8")

    n_comp = len(preview.get("competitions", []))
    print(f"[done] {out} (選手{len(JP_PLAYERS_SOCCER)}人 / 競技会{n_comp} /"
          f" 今夜の試合{len(games)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

