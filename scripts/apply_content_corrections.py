"""Keep published corrections when rebuilding the site and podcast feed."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ITUNES = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ET.register_namespace('itunes', ITUNES)
ET.register_namespace('content', 'http://purl.org/rss/1.0/modules/content/')


def apply(site, catalog=Path('content/corrections/published.json')):
    for correction in json.loads(catalog.read_text(encoding='utf-8')):
        games_path = site / 'games.json'
        if games_path.exists():
            payload = json.loads(games_path.read_text(encoding='utf-8'))
            replacements = {g['game_id']: g for g in json.loads(
                Path(correction['games']).read_text(encoding='utf-8'))['games']}
            # Exact fixture IDs only: never restore an old edition over a new one.
            payload['games'] = [replacements.get(g.get('game_id'), g) for g in payload['games']]
            games_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        feed = site / 'podcast/feed.xml'
        if not feed.exists():
            continue
        tree = ET.parse(feed)
        matches = [item for item in tree.findall('./channel/item')
                   if item.findtext('guid') == correction['guid']]
        if not matches:
            continue  # The normal retention policy may have removed this edition.
        if len(matches) != 1:
            raise ValueError('Correction target must be one podcast episode')
        media = site / correction['audio']
        if hashlib.sha256(media.read_bytes()).hexdigest() != correction['sha256']:
            raise ValueError('The corrected podcast audio is missing or changed')
        item = matches[0]
        for field, value in [('title', correction['title']), ('description', correction['description']),
                             (f'{{{ITUNES}}}duration', correction['duration'])]:
            node = item.find(field)
            if node is None:
                node = ET.SubElement(item, field)
            node.text = value
        enclosure = item.find('enclosure')
        if enclosure is None:
            raise ValueError('Podcast enclosure is missing')
        enclosure.set('url', correction['guid'] + '?v=' + correction['sha256'][:12])
        enclosure.set('length', str(media.stat().st_size))
        # Keep GUID and pubDate: it is a correction of the same episode.
        tree.write(feed, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=Path('public'))
    args = parser.parse_args()
    apply(args.site)
