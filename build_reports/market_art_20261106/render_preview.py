"""保存済み材料を同一条件で静止画比較。入力JSON・公開台帳は書かない。"""
import copy
from datetime import date
import json
from pathlib import Path
import sys
sys.path[:0]=['scripts','.']
import market_art as art
import offseason_market as market
import review_render_v3 as r3
import characters
import asset_v4_cards as cards
import generate_asset_video as g
shared=Path.cwd().parents[1]
r3.ROOT=shared
r3.LOOK='v4'
characters.PORTRAIT_DIR=str(shared/'assets/portraits')
out=Path('build_reports/market_art_20261106')
entries=json.loads(Path('data/offseason_market.json').read_text(encoding='utf-8'))['entries']
entry=next(e for e in entries if e['id']=='ito-posting-open-20261105')
metadata=[]
for variant in ('irasutoya','ai'):
    material=copy.deepcopy(entry)
    if variant=='ai':material['facts'][0]['illustration']='ai/posting.png'
    spec=market.topic(material,date.fromisoformat(material['checked_on']))
    head,body=spec['items'][0]
    row=art.for_item(spec,head,body)
    if row is None:raise RuntimeError('比較素材が取得できない: '+variant)
    g.set_asset_caption(dict(kind='list',text=body,speaker=2,meta={}),10,30,spec)
    im=cards.item(2,spec,'MLB',head,body)
    im.save(out/(variant+'.png'),optimize=True)
    metadata.append(dict(variant=variant,material_id=material['id'],illustration=row['filename'],layout=im.info.get('market_art'),font_size=im.info.get('asset_v4',{}).get('font_size')))
(out/'preview.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('saved 2 still images')
