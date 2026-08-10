"""
サイトの各ページへ、関連するYouTube動画へのリンクを差し込む。

なぜ必要か:
  これまでサイトからYouTubeへの導線が一つも無かった。動画の説明文には
  サイトのURLを載せていたので、YouTube→サイトは繋がっていたが、
  逆向きが完全に切れていた。サイトを見に来た人は、同じ内容を
  動画で見られることを知らないまま帰っていたことになる。

  用語集はとくに相性が良い。「OPSとは」を調べに来た人に、
  同じ説明の動画を出せる。検索から来た人が次に触れるものを用意できる。

差し込む先:
  ・用語集 … 用語ごとに、その用語を扱った資産動画へ
  ・トップと各ページ … チャンネル全体へのリンク

動画IDは data/published_assets.json から読む。まだ投稿していない
トピックのリンクは出さない(存在しないURLを踏ませないため)。

使い方(サイトを public/ へ組み立てた後に実行する):
  python3 scripts/inject_video_links.py --site public
"""

import argparse
import json
import pathlib
import re
import sys

CHANNEL_URL = "https://www.youtube.com/@collespo_jp"

# 用語集の見出し(dt)と、それを扱っている資産動画のトピック。
# 見出しの文字列に、ここのキーが含まれていれば対応づける。
TERM_TO_TOPIC = {
    "OPS": "mlb_stats",
    "ERA": "mlb_stats",
    "防御率": "mlb_stats",
    "WHIP": "mlb_stats",
    "RBI": "mlb_stats",
    "打点": "mlb_stats",
    "打率": "mlb_stats",
    "ゲーム差": "mlb_terms",
    "ワイルドカード": "mlb_terms",
    "地区": "mlb_league",
    "ア・リーグ": "mlb_league",
    "ナ・リーグ": "mlb_league",
    "インターリーグ": "mlb_league",
    "ポストシーズン": "mlb_postseason",
    "ワールドシリーズ": "mlb_postseason",
    "DH": "mlb_position",
    "指名打者": "mlb_position",
    "先発": "mlb_position",
}

STYLE = """
<style>
  .yt-link { display:inline-flex; align-items:center; gap:.35rem;
    margin-top:.4rem; font-size:.8rem; color:var(--accent);
    text-decoration:none; border:1px solid var(--accent-dim);
    border-radius:6px; padding:.2rem .5rem; }
  .yt-link:hover { background:var(--accent-dim); }
  .yt-channel { margin:2rem 0; padding:1rem; border:1px solid var(--border);
    border-radius:10px; background:var(--surface); }
  .yt-channel a { color:var(--accent); }
  .yt-channel p { margin:.3rem 0 0; font-size:.85rem; color:var(--text-dim); }
</style>
"""

CHANNEL_BLOCK = f"""
<div class="yt-channel">
  <a href="{CHANNEL_URL}" target="_blank" rel="noopener">
    YouTube「コレスポ」で動画も配信しています</a>
  <p>その日の注目試合、日本人選手の成績、球場や用語の解説を動画にしています。</p>
</div>
"""


def load_published(path: str) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("assets") or {}
    except (json.JSONDecodeError, OSError):
        return {}


def inject_glossary(html: str, published: dict) -> tuple:
    """用語ごとに、その用語を扱った動画へのリンクを <dd> の末尾へ足す"""
    count = 0

    def repl(m):
        nonlocal count
        term, dd_open, body, dd_close = m.groups()
        topic = None
        for key, t in TERM_TO_TOPIC.items():
            if key in term:
                topic = t
                break
        if not topic or topic not in published:
            return m.group(0)
        url = published[topic].get("url")
        if not url:
            return m.group(0)
        count += 1
        link = (f'<a class="yt-link" href="{url}" target="_blank" '
                f'rel="noopener">▶ 動画で見る</a>')
        return f"{term}{dd_open}{body}{link}{dd_close}"

    html = re.sub(r"(<dt>[^<]*</dt>\s*)(<dd[^>]*>)(.*?)(</dd>)",
                  repl, html, flags=re.S)
    return html, count


def add_channel_block(html: str) -> str:
    """チャンネルへの導線を、本文の末尾(戻るリンクの手前)へ置く"""
    if "yt-channel" in html:
        return html
    if "</head>" in html and "yt-link" not in html:
        html = html.replace("</head>", STYLE + "</head>", 1)
    m = re.search(r'<a class="back"', html)
    if m:
        return html[:m.start()] + CHANNEL_BLOCK + html[m.start():]
    return html.replace("</body>", CHANNEL_BLOCK + "</body>", 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="public")
    parser.add_argument("--published", default="data/published_assets.json")
    args = parser.parse_args()

    site = pathlib.Path(args.site)
    if not site.exists():
        print(f"[info] {site} が無いためスキップします")
        return

    published = load_published(args.published)
    print(f"[info] 投稿済みの資産動画: {len(published)}本")

    # 用語集: 用語ごとのリンク
    g = site / "glossary.html"
    if g.exists() and published:
        html = g.read_text(encoding="utf-8")
        if "</head>" in html and "yt-link" not in html:
            html = html.replace("</head>", STYLE + "</head>", 1)
        html, n = inject_glossary(html, published)
        html = add_channel_block(html)
        g.write_text(html, encoding="utf-8")
        print(f"[info] 用語集に{n}件の動画リンクを差し込みました")

    # 主要ページ: チャンネルへの導線
    added = []
    for name in ("about.html", "quiz.html", "lineup.html"):
        p = site / name
        if not p.exists():
            continue
        html = p.read_text(encoding="utf-8")
        new = add_channel_block(html)
        if new != html:
            p.write_text(new, encoding="utf-8")
            added.append(name)
    if added:
        print(f"[info] チャンネル導線を追加: {', '.join(added)}")


if __name__ == "__main__":
    main()
