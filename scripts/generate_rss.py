"""
notable_games.json から RSS 2.0 フィードを生成する。

RSSとは: サイトの更新情報を機械可読な形式(XML)で配信する仕組み。RSSリーダー
アプリ(Feedly等)に登録しておくと、通知を使わない人でも「今日の注目試合」を
自動で受け取れる。検索エンジンにもサイトの更新頻度を示すシグナルになりうる。

使い方:
  python3 scripts/generate_rss.py --input notable_games.json --out public/feed.xml --site-url https://issakatou2-bit.github.io/sports-notify-mvp/
"""

import argparse
import json
import html
from datetime import datetime, timezone


def build_rss(data: dict, site_url: str) -> str:
    games = data.get("games", [])
    notable = [g for g in games if g.get("is_notable")][:5]

    generated_at = data.get("generated_at", datetime.now(timezone.utc).isoformat())
    try:
        pub_date_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        pub_date_dt = datetime.now(timezone.utc)
    pub_date = pub_date_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    if notable:
        top = notable[0]
        title = f"今日の注目: {top['matchup']}"
        description_parts = []
        if top.get("ai_summary"):
            description_parts.append(top["ai_summary"])
        for r in top.get("reasons", []):
            description_parts.append(f"・{r['text']}")
        description = "<br/>".join(html.escape(p) for p in description_parts)

        items.append(
            f"""    <item>
      <title>{html.escape(title)}</title>
      <link>{html.escape(site_url)}</link>
      <guid isPermaLink="false">{html.escape(top['game_id'])}-{pub_date_dt.date().isoformat()}</guid>
      <pubDate>{pub_date}</pubDate>
      <description>{description}</description>
    </item>"""
        )

    items_xml = "\n".join(items)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SPOWatch! - 今日の注目試合</title>
    <link>{html.escape(site_url)}</link>
    <description>MLB・欧州5大リーグの今日の注目試合と、その理由を届けます</description>
    <language>ja</language>
    <lastBuildDate>{pub_date}</lastBuildDate>
{items_xml}
  </channel>
</rss>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="notable_games.json")
    parser.add_argument("--out", default="feed.xml")
    parser.add_argument(
        "--site-url", default="https://issakatou2-bit.github.io/sports-notify-mvp/"
    )
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    rss = build_rss(data, args.site_url)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(rss)

    print(f"RSSフィードを生成しました: {args.out}")


if __name__ == "__main__":
    main()
