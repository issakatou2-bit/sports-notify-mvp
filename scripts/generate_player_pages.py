"""
日本人選手ごとのページを archive/*.json から生成する。

なぜ選手ページを作るのか:
  日本語圏でのMLB関連の検索は、「MLB 注目試合」のような一般語よりも
  「大谷翔平 今日 試合」「鈴木誠也 結果」のような、選手名を起点にした
  検索が圧倒的に多い。日付ごとのアーカイブページだけでは、この最大の
  検索需要を取りこぼしてしまう。
  選手名でページを持ち、その選手が絡んだ試合を日々自動で積み上げることで、
  蓄積したアーカイブをそのまま検索流入に変える狙い。

生成物:
  public/players/{slug}.html … 選手ごとのページ
  public/players/index.html  … 選手一覧

使い方:
  python3 scripts/generate_player_pages.py --archive-dir archive --out-dir public/players
"""

import argparse
import html
import json
import pathlib
import re
import unicodedata

SITE_URL = "https://collespo.com/"
DATE_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.json$")

# 選手ページに載せる直近試合の件数。多すぎると読み物として散漫になるため絞る。
MAX_GAMES_PER_PLAYER = 20

# 日本語名 -> URLに使うスラッグ。name_enから機械的に作ると表記ゆれが出るため、
# ここで明示的に対応させる(notability_engine.pyのJP_PLAYERS_MLBと対応)。
PLAYER_SLUGS = {
    "大谷翔平": "shohei-ohtani",
    "ダルビッシュ有": "yu-darvish",
    "佐々木朗希": "roki-sasaki",
    "山本由伸": "yoshinobu-yamamoto",
    "菅野智之": "tomoyuki-sugano",
    "菊池雄星": "yusei-kikuchi",
    "今永昇太": "shota-imanaga",
    "鈴木誠也": "seiya-suzuki",
    "千賀滉大": "kodai-senga",
    "松井裕樹": "yuki-matsui",
    "吉田正尚": "masataka-yoshida",
    "岡本和真": "kazuma-okamoto",
    "村上宗隆": "munetaka-murakami",
    "小笠原慎之介": "shinnosuke-ogasawara",
    "今井達也": "tatsuya-imai",
    "ヌートバー": "lars-nootbaar",
}

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
  h1 { font-family: 'Oswald', sans-serif; font-size: 1.6rem; color: var(--accent); margin: 0 0 0.3rem; }
  .lead { color: var(--text-dim); font-size: 0.9rem; margin: 0 0 2rem; }
  .team-line { background: var(--surface); border: 1px solid var(--border);
               border-radius: 10px; padding: 0.9rem 1.1rem; margin-bottom: 2rem; font-size: 0.95rem; }
  h2 { font-family: 'Oswald', sans-serif; font-size: 1.15rem;
       border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; margin: 2rem 0 1rem; }
  .game { background: var(--surface); border: 1px solid var(--border);
          border-radius: 10px; padding: 0.9rem 1.1rem; margin-bottom: 1rem; }
  .game .date { font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: var(--text-dim); }
  .game .match { font-size: 1rem; font-weight: 600; margin: 0.2rem 0 0.4rem; }
  .game .result { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: var(--accent); }
  .game .why { font-size: 0.87rem; color: var(--text-dim); margin: 0.4rem 0 0; }
  ul.playerlist { list-style: none; padding: 0; }
  ul.playerlist li { border-bottom: 1px solid var(--border); padding: 0.7rem 0; }
  ul.playerlist .sub { display: block; font-size: 0.8rem; color: var(--text-dim); }
"""

HEAD = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<meta name="description" content="{description}" />
<link rel="canonical" href="{canonical}" />
<link rel="apple-touch-icon" href="../icons/icon-192.png" />
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-3009257813842371"
     crossorigin="anonymous"></script>
<style>{style}</style>
{extra_head}
</head>
<body>
<a class="back" href="../">&larr; コレスポ トップへ</a>
"""


def collect_player_games(archive_dir: pathlib.Path) -> dict:
    """
    アーカイブを走査し、選手名 -> その選手が絡んだ試合のリスト を作る。
    新しい日付が先頭に来るようにする。
    """
    by_player: dict = {}
    entries = []
    for p in sorted(archive_dir.glob("*.json")):
        m = DATE_FILE_RE.match(p.name)
        if m:
            entries.append((m.group(0)[:10], p))
    entries.sort(key=lambda x: x[0], reverse=True)

    for date_str, path in entries:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for g in data.get("games", []):
            if not g.get("is_notable"):
                continue
            for name in g.get("jp_players") or []:
                if name not in PLAYER_SLUGS:
                    continue
                by_player.setdefault(name, [])
                if len(by_player[name]) < MAX_GAMES_PER_PLAYER:
                    by_player[name].append((date_str, g))
    return by_player


def latest_team_of(name: str, games: list):
    """直近の試合データから、その選手が所属していると思われる球団名を推定する"""
    for _, g in games:
        for side in ("home", "away"):
            team_name = g.get(f"{side}_team_name")
            # jp_playersは両チーム合算なので、チーム別フラグで絞り込む
            if g.get(f"{side}_has_jp") and team_name:
                # 同一試合で両チームに日本人がいる場合は特定できないため、
                # 片方だけの場合に限って所属チームとみなす
                other = "away" if side == "home" else "home"
                if not g.get(f"{other}_has_jp"):
                    return team_name
    return None


def render_game(date_str: str, g: dict) -> str:
    parts = ['<div class="game">']
    parts.append(f'<div class="date">{html.escape(date_str)}</div>')
    parts.append(f'<p class="match">{html.escape(g.get("matchup", ""))}</p>')

    fs = g.get("final_score")
    if fs:
        winner = (
            g.get("home_team_name") if fs.get("winner") == "home" else g.get("away_team_name")
        )
        parts.append(
            f'<p class="result">{html.escape(g.get("home_team_name",""))} '
            f'{fs.get("home")} - {fs.get("away")} '
            f'{html.escape(g.get("away_team_name",""))}　{html.escape(winner or "")}勝利</p>'
        )

    reasons = [r["text"] for r in g.get("reasons", []) if r.get("visible", True) and r.get("text")]
    if reasons:
        parts.append(f'<p class="why">{html.escape(reasons[0])}</p>')

    parts.append(
        f'<p class="why"><a href="../archive/{html.escape(date_str)}.html">'
        "この日の詳細を見る</a></p>"
    )
    parts.append("</div>")
    return "\n".join(parts)


def render_player_page(name: str, games: list) -> str:
    slug = PLAYER_SLUGS[name]
    team = latest_team_of(name, games)
    team_part = f"{team}所属の" if team else ""
    description = (
        f"{team_part}{name}選手が出場する試合を、コレスポが注目試合として"
        f"取り上げた記録です。試合の見どころと結果を日付ごとに振り返れます。"
    )
    head = HEAD.format(
        title=f"{name} | 注目試合の記録 | コレスポ",
        description=html.escape(description),
        canonical=f"{SITE_URL}players/{slug}.html",
        style=STYLE,
        extra_head="",
    )
    body = [head]
    body.append(f"<h1>{html.escape(name)}</h1>")
    body.append(f'<p class="lead">{html.escape(description)}</p>')
    if team:
        body.append(
            f'<p class="team-line">直近の掲載時点での所属: <strong>{html.escape(team)}</strong></p>'
        )
    body.append(f"<h2>取り上げた試合({len(games)}件)</h2>")
    for date_str, g in games:
        body.append(render_game(date_str, g))
    body.append('<p class="lead"><a href="./">ほかの選手を見る</a></p>')
    body.append("</body></html>")
    return "\n".join(body)


def render_index(by_player: dict) -> str:
    head = HEAD.format(
        title="日本人選手一覧 | コレスポ",
        description="MLBでプレーする日本人選手ごとに、コレスポが注目試合として"
        "取り上げた記録をまとめています。",
        canonical=f"{SITE_URL}players/",
        style=STYLE,
        extra_head="",
    )
    body = [head]
    body.append("<h1>日本人選手から探す</h1>")
    body.append(
        '<p class="lead">選手ごとに、その選手が出場した注目試合の記録をまとめています。</p>'
    )
    body.append('<ul class="playerlist">')
    for name in sorted(by_player, key=lambda n: -len(by_player[n])):
        games = by_player[name]
        team = latest_team_of(name, games)
        sub = f"{team} / {len(games)}試合を掲載" if team else f"{len(games)}試合を掲載"
        body.append(
            f'<li><a href="{PLAYER_SLUGS[name]}.html">{html.escape(name)}</a>'
            f'<span class="sub">{html.escape(sub)}</span></li>'
        )
    body.append("</ul>")
    body.append("</body></html>")
    return "\n".join(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--out-dir", default="public/players")
    args = parser.parse_args()

    archive_dir = pathlib.Path(args.archive_dir)
    if not archive_dir.exists():
        print(f"[warn] {archive_dir} が見つからないため、選手ページ生成をスキップします")
        return

    by_player = collect_player_games(archive_dir)
    if not by_player:
        print("[warn] 対象となる選手の試合が見つかりませんでした")
        return

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, games in by_player.items():
        (out_dir / f"{PLAYER_SLUGS[name]}.html").write_text(
            render_player_page(name, games), encoding="utf-8"
        )
    (out_dir / "index.html").write_text(render_index(by_player), encoding="utf-8")

    print(f"[info] 選手ページを{len(by_player)}件生成しました -> {out_dir}")


if __name__ == "__main__":
    main()
