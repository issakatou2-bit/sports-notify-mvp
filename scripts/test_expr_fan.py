#!/usr/bin/env python3
"""日本人選手寄りの表情（COLLESPO_EXPR=fan）の検査。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from PIL import Image
import characters as c

def main():
    ok=True
    def check(name,cond):
        nonlocal ok
        print(('ok  ' if cond else 'NG  ')+name);ok=ok and cond
    c.EXPR=''
    check('未設定なら何もしない',c.fan_mood('山本由伸が先発します') is None)
    c.EXPR='fan'
    check('先発の予告は笑顔とキラキラ',c.fan_mood('山本由伸がきょう先発します')[:2]==('smile','sparkle'))
    check('名字でも分かる',c.fan_mood('大谷は4打数無安打')[:2]==('sad',None))
    check('記録は驚き',c.fan_mood('村上が自己最多の36号本塁打')[:2]==('surprise','burst'))
    check('活躍は大きい笑顔',c.fan_mood('鈴木誠也が決勝の本塁打')[:2]==('pose-smile','sparkle'))
    check('日本人選手の名前が無ければ普通のまま',c.fan_mood('ブリュワーズが先発を発表、本塁打で勝利') is None)
    check('理由を残す',c.fan_mood('山本由伸がきょう先発します')[2]=='山本由伸・先発')
    check('ジト目の組み合わせは使わない（困り眉）',c.FACE_PARTS['jitome'][1]!='ジト')
    im=Image.new('RGB',(1080,1920),(20,24,40));before=im.tobytes()
    c.fan_effect(im,'sparkle',[600,900,1000,1400],0.2)
    check('キラキラが描かれる',im.tobytes()!=before)
    im2=Image.new('RGB',(1080,1920),(20,24,40));c.fan_effect(im2,'none',[600,900,1000,1400],0.2)
    check('知らない効果は何も描かない',im2.tobytes()==Image.new('RGB',(1080,1920),(20,24,40)).tobytes())
    c.EXPR=''
    print('ALL OK' if ok else 'FAILED')
    return 0 if ok else 1

if __name__=='__main__':
    raise SystemExit(main())
