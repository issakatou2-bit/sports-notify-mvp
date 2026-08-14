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
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import post_common  # noqa: E402
import html
from datetime import datetime, timezone


def build_rss(sources: list, site_url: str) -> str:
    """
    競技ごとに1件ずつ出す。

    以前は全部を1つにまとめて先頭1件だけを出していた。MLBとサッカーを
    混ぜるとそれでは片方しか出ない。しかも点数は競技ごとに別の物差しで
    付いているので、合わせて並べ替えると常に同じ競技が勝ってしまう。
    """
    generated = next((d.get("generated_at") for d in sources
                      if d.get("generated_at")), "")
    try:
        pub_date_dt = datetime.fromisoformat(
            (generated or datetime.now(timezone.utc).isoformat()
             ).replace("Z", "+00:00"))
    except ValueError:
        pub_date_dt = datetime.now(timezone.utc)
    pub_date = pub_date_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for data in sources:
        notable = [g for g in data.get("games", []) if g.get("is_notable")]
        if not notable:
            continue
        top = notable[0]
        # 「今日」か「今夜」かは試合開始時刻から決める。欧州の試合は
        # 日本時間の未明に始まるので、暦どおりだと実感とずれる。
        label = post_common.when_label(top.get("start_time_jst") or "") or "次"
        title = f"{label}の注目: {top['matchup']}"
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
    <title>コレスポ - 今日の注目試合</title>
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
    # 複数指定できるようにしてある。MLBとサッカーで別ファイルに
    # 分かれているが、購読者にとっては1つのフィードで届く方がよい。
    # 無いファイルは黙って飛ばす(サッカーは試合の無い日がある)。
    parser.add_argument("--input", action="append", default=None,
                        help="注目試合のJSON。複数回指定できる")
    parser.add_argument("--out", default="feed.xml")
    parser.add_argument(
        "--site-url", default="https://issakatou2-bit.github.io/sports-notify-mvp/"
    )
    args = parser.parse_args()

    loaded = []
    for path in (args.input or ["notable_games.json"]):
        p = pathlib.Path(path)
        if not p.exists():
            print(f"[info] {path} が無いため飛ばします")
            continue
        try:
            loaded.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] {path} を読めませんでした: {e}")

    rss = build_rss(loaded, args.site_url)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(rss)

    print(f"RSSフィードを生成しました: {args.out}")


if __name__ == "__main__":
    main()
