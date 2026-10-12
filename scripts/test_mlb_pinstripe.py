"""固定材料と変更前の描画による既定画素比較、全枠・30球団の札を検査。"""
import hashlib
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]


def legacy_cards():
    """mainの変更前ソースを凍結。現在の描画から期待値を作らない。"""
    fixture=ROOT/'scripts/fixtures/mlb-pinstripe'
    origin=json.loads((fixture/'legacy-source.json').read_text(encoding='utf8'))
    source=(fixture/origin['fixture']).read_bytes().replace(b'\r\n',b'\n')
    assert hashlib.sha256(source).hexdigest()==origin['sha256'],'legacy source changed'
    namespace={'__file__':str(ROOT/origin['path']),'__name__':'legacy_short_v4_cards'}
    exec(compile(source,namespace['__file__'],'exec'),namespace)
    return {k:v for k,v in namespace.items() if not k.startswith('__')}


def child():
    # CI/Windowsともリポジトリ内の同じフォントを使用。個人のフォントに依存しない。
    import ps_brand_components as brand
    if '--system-fonts' not in sys.argv:
        brand.FONT_CANDIDATES={
            'jp':[str(ROOT/'assets/fonts/soccer-v5/NotoSansJP-VF.ttf')],
            'latin':[str(ROOT/'assets/fonts/Oswald[wght].ttf')],
            'serif':[str(ROOT/'assets/fonts/Oswald[wght].ttf')]}
        brand._cache.clear()
    import mlb_pinstripe_badge as stripe
    import notability_engine as ne
    import short_v4_cards as cards
    import review_render_v3 as r3
    import test_v3_rules as fixtures
    import v3_rules as rules
    from PIL import Image
    baseline=json.loads((ROOT/'scripts/fixtures/mlb-pinstripe/default-pixels.json').read_text(encoding='utf8'))
    cases=fixtures.daily_cases()+fixtures.asset_cases()
    # 保存済みWindows画素hashは環境差を含む。固定のcase/frame一覧だけ利用する。
    saved={(r['case'],r['frame']) for r in baseline['records']}
    legacy=legacy_cards()
    os.environ.pop('COLLESPO_MLB_BADGE',None);count=0;baseline_errors={}
    visited=set()
    for case in cases:
        for i,draw in enumerate(case['frames']):
            key=(case['name'],i);visited.add(key)
            with patch.dict(cards.__dict__,legacy):
                expected=draw(3)
            im=draw(3)
            assert im.mode==expected.mode and im.size==expected.size and im.tobytes()==expected.tobytes(),key
            baseline_errors[(case['name'],i)]=rules.check_layout(im)+rules.check_spacing(im)+rules.check_team_badges(im)
            count+=1
    assert visited==saved,(visited-saved,saved-visited)
    os.environ['COLLESPO_MLB_BADGE']='pinstripe';stamps=0;slots=set()
    for case in cases:
        for i,draw in enumerate(case['frames']):
            im=draw(3);errors=rules.check_layout(im)+rules.check_spacing(im)+rules.check_team_badges(im)
            added=[e for e in errors if e not in baseline_errors[(case['name'],i)]]
            assert not added,(case['name'],i,added)
            inline=[b for b in im.info.get('v4_badges',[]) if b.get('inline')]
            assert all(b.get('style')=='pinstripe' for b in inline),(case['name'],i,inline)
            if inline:slots.add(case['name']);stamps+=len(inline)
    assert all(s in slots for s in ('players','voices','press','forecast','situation')),slots
    for tid in ne.MLB_TEAM_NAME_JP:
        for text_size in (18,28,36,48):
            height=r3.font(text_size).getbbox(ne.MLB_TEAM_NAME_JP[tid])[3]-r3.font(text_size).getbbox(ne.MLB_TEAM_NAME_JP[tid])[1]
            im=stripe.render(tid,cards.inline_badge_width(tid,text_size),height);check=im.info['badge']
            assert check['text_ratio']>=4.5
            assert check['text_box'][0]>check['motif_right']
            assert check['text_box'][2]<=im.width and check['text_box'][3]<=im.height
    r3.LOOK='v3';plain=Image.new('RGB',(200,100));cards.inline_badge(plain,2,2,'119',36,34)
    os.environ.pop('COLLESPO_MLB_BADGE',None);normal=Image.new('RGB',(200,100));cards.inline_badge(normal,2,2,'119',36,34)
    assert plain.tobytes()==normal.tobytes()
    print(json.dumps(dict(default_frames=count,inline_stamps=stamps,slots=sorted(slots),teams=30,sizes=4,v3_unchanged=True,
                          baseline_layout_warnings=sum(len(v) for v in baseline_errors.values()),added_layout_errors=0),ensure_ascii=False))


class Pinstripe(unittest.TestCase):
    def test_saved_forecast_next_line_has_video_layers(self):
        import ps_program as program
        material=json.loads((ROOT/'scripts/fixtures/ps-design/2026-10-07.json').read_text(encoding='utf8'))
        with patch.dict(os.environ,{'COLLESPO_PS_DESIGN':'v3'}):
            plan=program.prepare(material['snapshot'],material['evidence'],'forecast',
                                 datetime.fromisoformat(material['evidence']['retrieved_at']),material['ledger'])
        seg=next(s for s in plan['segments'] if s['meta']['card'].get('next_line'))
        image,manifest,foreground=program.render_segment(seg,layers=True)
        self.assertEqual(manifest['layout'],'next_line')
        self.assertEqual(foreground.mode,'RGBA')
        self.assertEqual(foreground.size,image.size)
        ordinary=program.render_segment(seg)
        self.assertEqual(len(ordinary),2)
        self.assertEqual(ordinary[0].tobytes(),image.tobytes())

    def test_default_pixels_and_all_v4_slots(self):
        env=dict(os.environ,COLLESPO_SHORT_LOOK='v4',COLLESPO_SOCCER_LOOK='v4');env.pop('COLLESPO_MLB_BADGE',None)
        result=subprocess.run([sys.executable,str(Path(__file__)),'--child'],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('"default_frames": 96',result.stdout)
        print(result.stdout.strip())

    def test_workflow_switch_is_optional_in_all_mlb_producers(self):
        import yaml
        names=('asset_video','correct_video','daily_notify','design_preview','morning_design_preview','morning_recap','ps_program_preview','season_review','ps_game_now')
        for name in names:
            env=yaml.safe_load((ROOT/'.github/workflows'/f'{name}.yml').read_text(encoding='utf8'))['env']
            self.assertEqual(env['COLLESPO_MLB_BADGE'],"${{ vars.COLLESPO_MLB_BADGE || '' }}")


if __name__=='__main__':
    if '--child' in sys.argv:child()
    else:unittest.main(argv=[sys.argv[0]])
