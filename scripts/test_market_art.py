"""素材登録・点数・説明欄・実寸配置。通信・実績台帳書込なし。"""
import copy
import hashlib
import io
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image
import market_art as art
import offseason_market as market


class ArtTest(unittest.TestCase):
    def setUp(self):
        art._ATTEMPTS.clear()
        self.root = Path(tempfile.mkdtemp(prefix='market-art-test-'))
        self.root_patch = patch.object(art, 'DIRECTORY', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.table = []
        self.entry = json.loads(Path('scripts/fixtures/offseason-market/example.json').read_text(encoding='utf-8'))['entries'][0]

    def add(self, name='diagram.png', license_name='CC0', **extra):
        Image.new('RGBA', (80,60), (40+len(self.table),130,180,255)).save(self.root/name)
        row = dict(filename=name, source_url='https://example.com/art', author='試験図の作者',
                   license=license_name, terms='動作試験の単色図', checked_on='2026-11-03', **extra)
        row['sha256']=hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        row['download_url']='https://blogger.googleusercontent.com/test/'+name
        if license_name == 'いらすとや':
            row['source_url'] = 'https://www.irasutoya.com/test/' + name
        self.table.append(row)
        self.save()
        return row

    def save(self):
        (self.root/'SOURCES.json').write_text(json.dumps(dict(version=1,assets=self.table),ensure_ascii=False),encoding='utf-8')

    def spec(self):
        return market.topic(self.entry,date(2026,11,3),sample=True)

    def test_optional_art_and_original_pixels(self):
        import asset_v4_cards as cards
        spec = self.spec()
        source = subprocess.run(['git','show','HEAD:scripts/asset_v4_cards.py'],capture_output=True,check=True).stdout
        baseline = types.ModuleType('market_art_baseline')
        baseline.__file__ = cards.__file__
        exec(compile(source,'market_art_baseline','exec'),baseline.__dict__)
        with patch.object(art,'ledger',side_effect=AssertionError('素材なしで台帳を読んだ')):
            head,body = spec['items'][0]
            self.assertEqual(cards.item(2,spec,'MLB',head,body).tobytes(), baseline.item(2,spec,'MLB',head,body).tobytes())

    def test_unregistered_missing_fields_unknown_license_and_paths_stop(self):
        self.save()
        with self.assertRaises(ValueError): art.resolve('missing.png',sample=True)
        for name in ('../x.png','C:\\x.png','/x.png','x/../x.png','SOURCES.json'):
            with self.assertRaises(ValueError): art.filename(name)
        row = self.add()
        for field in ('source_url','author','license','terms','checked_on','sha256'):
            original=row.pop(field);self.save()
            with self.assertRaises((ValueError,KeyError)):art.resolve('diagram.png',sample=True)
            row[field]=original
        row['license']='報道用途のみ';self.save()
        with self.assertRaises(ValueError):art.resolve('diagram.png',sample=True)

    def test_photo_license_origin_and_attribution(self):
        row=self.add(license_name='CC BY',type='photo',origin='independent',license_version='4.0')
        self.entry['facts'][0]['illustration']='diagram.png'
        for license_name in ('CC0','CC BY','CC BY-SA','PD'):
            row['license']=license_name;self.save()
            spec=self.spec()
            credit='\n'.join(art.credits(spec))
            if license_name.startswith('CC BY'):
                self.assertIn(row['author'],credit);self.assertIn(license_name,credit);self.assertIn(row['source_url'],credit)
        for origin in ('news','team',''):
            row['origin']=origin;self.save()
            with self.assertRaises(ValueError):self.spec()
        row['origin']='independent';row['source_url']='https://www.mlb.com/news/photo';self.save()
        with self.assertRaises(ValueError):self.spec()

    def test_irastoya_twenty_unique_and_duplicate_once(self):
        for index in range(21):self.add(f'art{index}.png','いらすとや')
        entry=dict(facts=[dict(illustration=f'art{i}.png') for i in range(20)],reports=[])
        self.assertEqual(len(art.entry_rows(entry,sample=True)),20)
        entry['facts'].append(dict(illustration='art20.png'))
        with self.assertRaises(ValueError):art.entry_rows(entry,sample=True)
        entry['facts'][-1]['illustration']='art0.png'
        self.assertEqual(len(art.entry_rows(entry,sample=True)),20)
        (self.root/'art20.png').write_bytes((self.root/'art0.png').read_bytes())
        self.table[-1]['sha256']=self.table[0]['sha256'];self.save()
        entry['facts'][-1]['illustration']='art20.png'
        self.assertEqual(len(art.entry_rows(entry,sample=True)),21)  # 21ファイル・内容は20点

    def test_download_verified_before_write_and_reuse(self):
        row=self.add()
        data=(self.root/'diagram.png').read_bytes()
        row['filename']='fetched.png';self.save()
        response=io.BytesIO(data)
        response.geturl=lambda:row['download_url']
        with patch.object(art,'urlopen',return_value=response) as fetch:
            self.assertTrue(art.resolve('fetched.png',sample=True)['available'])
            self.assertEqual((self.root/'fetched.png').read_bytes(),data)
            self.assertTrue(art.resolve('fetched.png',sample=True)['available'])
            self.assertEqual(fetch.call_count,1)

    def test_network_hash_and_missing_url_fallback_to_original_pixels(self):
        import asset_v4_cards as cards
        row=self.add()
        plain=self.spec();head,body=plain['items'][0]
        baseline=cards.item(2,plain,'MLB',head,body).tobytes()
        self.entry['facts'][0]['illustration']='unavailable.png'
        row['filename']='unavailable.png';self.save()
        with patch.object(art,'urlopen',side_effect=OSError('offline')) as fetch:
            spec=self.spec()
            self.assertEqual(cards.item(2,spec,'MLB',head,body).tobytes(),baseline)
            self.assertEqual(art.credits(spec),[])
            self.assertEqual(fetch.call_count,1)
        art._ATTEMPTS.clear()
        response=io.BytesIO(b'wrong hash');response.geturl=lambda:row['download_url']
        with patch.object(art,'urlopen',return_value=response):
            self.assertFalse(art.resolve('unavailable.png',sample=True)['available'])
        self.assertFalse((self.root/'unavailable.png').exists())
        art._ATTEMPTS.clear();row['download_url']=None;self.save()
        with patch.object(art,'urlopen',side_effect=AssertionError('URLなしで取得')):
            self.assertFalse(art.resolve('unavailable.png',sample=True)['available'])

    def test_bad_local_hash_is_never_used_or_overwritten(self):
        row=self.add();row['sha256']='0'*64;self.save()
        original=(self.root/'diagram.png').read_bytes()
        with patch.object(art,'urlopen',side_effect=OSError('offline')):
            self.assertFalse(art.resolve('diagram.png',sample=True)['available'])
        self.assertEqual((self.root/'diagram.png').read_bytes(),original)

    def test_download_urls_must_be_official_for_irasutoya(self):
        row=self.add(license_name='いらすとや')
        for url in ('http://blogger.googleusercontent.com/a','https://evil.example/a','https://user:secret@blogger.googleusercontent.com/a'):
            row['download_url']=url;self.save()
            with self.assertRaises(ValueError):art.resolve('diagram.png',sample=True)

    def test_unknown_author_and_team_aliases_are_rejected(self):
        row=self.add(type='photo',origin='independent')
        for author in ('不明','unknown','anonymous'):
            row['author']=author;self.save()
            with self.assertRaises(ValueError):art.resolve('diagram.png',sample=True)
        row['author']='試験図の作者'
        for url in ('https://www.dodgers.com/photo','https://img.mlbstatic.com/photo','https://hanshintigers.jp/photo'):
            row['source_url']=url;self.save()
            with self.assertRaises(ValueError):art.resolve('diagram.png',sample=True)

    def test_saved_narration_path_is_validated_before_drawing(self):
        import generate_asset_video as g
        spec=self.spec();self.save()
        spec['offseason']['entry']['facts'][0]['illustration']='not_registered.png'
        with patch.dict(g.LIST_TOPICS,{spec['key']:spec}), \
             patch.object(sys,'argv',['generate_asset_video','--topic',spec['key'],'--narration','not_read.json']):
            with self.assertRaisesRegex(ValueError,'素材台帳'):
                g.main()

    def test_irastoya_description_and_full_material_roundtrip(self):
        import offseason_public
        import generate_asset_video as g
        self.add(license_name='いらすとや')
        self.entry['facts'][0]['illustration']='diagram.png'
        spec=self.spec()
        self.assertIn('イラスト：いらすとや',offseason_public.metadata(spec)['lead'])
        with patch.dict(g.LIST_TOPICS,{spec['key']:spec}):doc=g.build_narration(spec['key'])
        self.assertEqual(market.check(doc),[])
        changed=copy.deepcopy(doc);changed['offseason']['events'][0]['illustration']='other.png'
        self.assertTrue(market.check(changed))

    def test_static_placement_fade_and_long_text_pages(self):
        import asset_v4_cards as cards
        import market_art_render
        import review_render_v3 as r3
        import v3_rules
        self.add()
        self.entry['facts'][0]['illustration']='diagram.png'
        self.entry['facts'][0]['text']='佐藤輝明の交渉期限について所属球団が発表した内容を確認しています。'*4
        spec=self.spec();head,body=spec['items'][0]
        boxes=[];fades=[]
        with patch.object(r3,'LOOK','v4'):
            import generate_asset_video as g
            g.set_asset_caption(dict(kind='list',text=body,speaker=2,meta={}),10,30,spec)
            for t in (0,.35,.8,3):
                for page in range(cards.item_pages(spec,head,body)):
                    im=cards.item(t,spec,'MLB',head,body,page)
                    self.assertEqual(v3_rules.check_layout(im),[])
                    self.assertEqual(market_art_render.check_layout(im),[])
                    boxes.append(im.info['market_art']['box']);fades.append(im.info['market_art']['fade'])
                    self.assertEqual(im.info['asset_v4']['font_size'],54)
            self.assertGreaterEqual(cards.item_pages(spec,head,body),2)
        self.assertEqual(len({tuple(b) for b in boxes}),1)
        self.assertLess(min(fades),max(fades))


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
