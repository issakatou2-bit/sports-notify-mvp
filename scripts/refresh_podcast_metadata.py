"""公開済みRSSの番組紹介を更新する。音声・回のID・配信日時は維持する。"""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

from generate_podcast import DESCRIPTION, LEGACY_DESCRIPTION, TITLE

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")


def refresh_metadata(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    channels = root.findall("channel")
    if root.tag != "rss" or len(channels) != 1:
        raise ValueError("Podcast RSSのchannelを一意に確認できません")
    channel = channels[0]
    # 不完全な持ち越しデータを正常な番組として公開しない。
    updates = {"title": TITLE, "description": DESCRIPTION,
               f"{{{ITUNES}}}summary": DESCRIPTION}
    targets = []
    for tag, value in updates.items():
        nodes = channel.findall(tag)
        if len(nodes) != 1:
            raise ValueError(f"Podcastの{tag}を一意に確認できません")
        targets.append((nodes[0], value))
    for node, value in targets:
        node.text = value
    for description in channel.findall("item/description"):
        if description.text == LEGACY_DESCRIPTION:
            description.text = DESCRIPTION
    # 検証を通ったものだけ置き換え、失敗時は取得済みの原本を残す。
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True)
    args = parser.parse_args()
    refresh_metadata(args.feed)
    print("[info] Podcast紹介文を更新しました（音声・回のID・配信日時は維持）")


if __name__ == "__main__":
    main()
