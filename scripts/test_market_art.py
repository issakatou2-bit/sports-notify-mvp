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
        self.entry['title'] = '佐藤輝明 市場の動き'

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


class AiArtTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='market-ai-test-'))
        (self.root/'ai').mkdir()
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        image.paste((60, 130, 120, 255), (10, 10, 50, 50))
        self.path = self.root/'ai/contract.png'
        image.save(self.path)
        self.row = dict(filename='ai/contract.png', license=art.AI_LICENSE,
                        type='illustration', tool='Codex image_gen', generated_on='2026-11-05',
                        checked_on=str(date.today()), prompt='無地の握手。文字・数字・ロゴなし。',
                        inspection=dict(text='absent', edges='passed', notes='目視した試験材料'),
                        sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())

    def resolve(self, row=None):
        row = self.row if row is None else row
        return art.resolve(row['filename'], self.root, catalog={row['filename']: row})

    def test_ai_local_only_missing_or_bad_hash_never_downloads(self):
        with patch.object(art, 'urlopen', side_effect=AssertionError('AI画像を取得した')):
            self.assertTrue(self.resolve()['available'])
            missing = dict(self.row, filename='ai/missing.png')
            self.assertFalse(self.resolve(missing)['available'])
            with self.assertRaisesRegex(ValueError, 'sha256'):
                self.resolve(dict(self.row, sha256='0'*64))

    def test_ai_required_fields_and_manual_review(self):
        for key in ('tool', 'generated_on', 'checked_on', 'prompt', 'sha256', 'inspection', 'type'):
            with self.subTest(key=key):
                row = copy.deepcopy(self.row);row.pop(key)
                with self.assertRaises(ValueError):self.resolve(row)
        for inspection in ({'text':'present','edges':'passed','notes':'文字あり'},
                           {'text':'absent','edges':'failed','notes':'光あり'}):
            with self.assertRaises(ValueError):self.resolve(dict(self.row, inspection=inspection))
        for key in ('source_url','download_url'):
            for value in (None, 'https://example.com/image'):
                with self.assertRaises(ValueError):self.resolve(dict(self.row, **{key:value}))
        with self.assertRaises(ValueError):self.resolve(dict(self.row, tool='other'))
        with self.assertRaises(ValueError):self.resolve(dict(self.row, generated_on='2099-01-01'))

    def test_ai_size_format_alpha_and_nested_paths(self):
        for name in ('ai/../bad.png','ai/ai/bad.png','ai/x.jpg','ai/../../x.png'):
            with self.assertRaises(ValueError):art.filename(name)
        for image in (Image.new('RGBA',(64,48)), Image.new('RGB',(64,64)),
                      Image.new('RGBA',(64,64),(60,130,120,255))):
            image.save(self.path)
            self.row['sha256']=hashlib.sha256(self.path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):self.resolve()
        self.path.write_bytes(b'x'*(art.AI_MAX_BYTES+1))
        self.row['sha256']=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'1MiB'):self.resolve()

    def test_scene_table_and_unknown(self):
        for kind, file in art.SCENE_FILES.items():
            entry=dict(market_kind=kind, facts=[{}], reports=[])
            self.assertEqual(art.selected_name(entry, entry['facts'][0]),file)
        for text, expected in [('x-posting-open','posting'),('x-qo-decline','qo'),
                ('x-fa-open','fa'),('x-contract-sign','contract'),('x-trade','trade'),
                ('x-award','award'),('x-retire','retirement'),('x-injured-list','injured_list')]:
            self.assertEqual(art.scene(dict(id=text,title='前年の受賞')) ,expected)
        self.assertIsNone(art.scene(dict(id='unclassified',title='動き')))
        self.assertEqual(art.scene(dict(title='FAの手続き')), 'fa')
        with self.assertRaises(ValueError):art.scene(dict(market_kind='unregistered'))

    def test_explicit_priority_and_first_fact_only(self):
        entry=dict(market_kind='posting', illustration='contract_sign.png', facts=[{},{}], reports=[{}])
        self.assertEqual(art.selected_name(entry,entry['facts'][0]),'contract_sign.png')
        entry['facts'][0]['illustration']='handshake.png'
        self.assertEqual(art.selected_name(entry,entry['facts'][0]),'handshake.png')
        self.assertIsNone(art.selected_name(entry,entry['facts'][1]))
        self.assertIsNone(art.selected_name(entry,entry['reports'][0]))
        entry.pop('illustration');entry['facts'][0].pop('illustration')
        self.assertEqual(art.selected_name(entry,entry['facts'][0]),'ai/posting.png')
        entry['facts'][1]['illustration']='handshake.png'
        self.assertIsNone(art.selected_name(entry,entry['facts'][0]))

    def test_shipped_assets_and_published_entries(self):
        with patch.object(art,'urlopen',side_effect=AssertionError('通信した')):
            catalog=art.ledger()
            for file in art.SCENE_FILES.values():
                row=art.resolve(file,catalog=catalog)
                self.assertTrue(row['available'])
                self.assertLessEqual(row['path'].stat().st_size,1_000_000)
        entries=json.loads(Path('data/offseason_market.json').read_text(encoding='utf-8'))['entries']
        # 回は毎日増える。絵を明示して公開済みの回だけ、絵が変わらないことを見る（11/6 件数の決め打ちで落ちた）。
        explicit=[e for e in entries if any(r.get('illustration') for g in ('facts','reports') for r in e[g])]
        self.assertGreaterEqual(len(explicit),3)
        for entry in explicit:
            names=[art.selected_name(entry,r) for group in ('facts','reports') for r in entry[group]]
            self.assertEqual([n for n in names if n],['handshake.png'])

    def test_automatic_event_roundtrip_without_mutating_material(self):
        entry=json.loads(Path('scripts/fixtures/offseason-market/example.json').read_text(encoding='utf-8'))['entries'][0]
        original=copy.deepcopy(entry)
        spec=market.topic(entry,date(2026,11,3),sample=True)
        self.assertEqual(entry,original)
        self.assertEqual(spec['offseason']['events'][0]['illustration'],'ai/posting.png')
        head,body=spec['items'][0]
        self.assertEqual(art.for_item(spec,head,body)['filename'],'ai/posting.png')
        self.assertEqual(art.credits(spec),[])
        import generate_asset_video as g
        with patch.dict(g.LIST_TOPICS,{spec['key']:spec}):doc=g.build_narration(spec['key'])
        self.assertEqual(market.check(doc),[])


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
