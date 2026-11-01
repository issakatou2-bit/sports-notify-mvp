#!/usr/bin/env python3
"""引用の上の小さな行が、長い英語の題で回を落とさないことを確かめる（10/12 の 17:30 の失敗）。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import short_v4_cards as s4

def main():
    ok=True
    def check(name,cond):
        nonlocal ok
        print(('ok  ' if cond else 'NG  ')+name);ok=ok and cond
    im=s4.canvas(0,'現地のファンの声')
    raw='Shohei Ohtani vs Jacob Misiorowski! (Both plate appearances in 2026 NLCS Game 1) | MLB Highlights'
    check('日本語の無い長い題は省いて落ちない',s4.live_line(im,raw) is False)
    check('長すぎる日本語の題も省いて落ちない',s4.live_line(im,'大谷翔平'*40) is False)
    check('ふつうの日本語の題は描く',s4.live_line(im,'ドジャース 対 ブリュワーズ 第1戦') is True)
    check('空なら何もしない',s4.live_line(im,'') is False)
    print('ALL OK' if ok else 'FAILED')
    return 0 if ok else 1

if __name__=='__main__':
    raise SystemExit(main())
