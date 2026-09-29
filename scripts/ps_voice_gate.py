"""Check the engine's pronunciation of the reported padded-hour incident."""
import json
from pathlib import Path
import re
import requests
from ps_program import spoken_start
from notability_engine import apply_readings


def main():
    phrase='初戦は日本時間'+spoken_start('09/30 06:00')+'です。'
    response=requests.post('http://127.0.0.1:50021/audio_query',
                           params={'text':phrase,'speaker':2},timeout=20)
    response.raise_for_status()
    kana=response.json()['kana']
    sounds=re.sub('[^ァ-ヶー]','',kana)
    if 'ゼロ' in sounds or 'ロクジ' not in sounds:
        raise ValueError('6時の読みが自然な日本語として確認できません: '+kana)
    rounds=[]
    for abbreviation, expected in (('WCS','ワイルドカードシリーズ'), ('DS','チクシリーズ'),
                                   ('LCS','リーグユウショウケッテイシリーズ'), ('WS','ワールドシリーズ')):
        spoken=apply_readings(abbreviation+'第1戦です。')
        reply=requests.post('http://127.0.0.1:50021/audio_query',
                            params={'text':spoken,'speaker':2},timeout=20)
        reply.raise_for_status()
        round_kana=reply.json()['kana']
        if expected not in re.sub('[^ァ-ヶー]','',round_kana):
            raise ValueError('PS回戦名の正式な読みを確認できません: '+round_kana)
        rounds.append(dict(display=abbreviation,spoken=spoken,engine_kana=round_kana))
    out=Path('build/ps_voice_check.json');out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'text':phrase,'engine_kana':kana,'rounds':rounds,'passed':True},ensure_ascii=False,indent=2),encoding='utf-8')
    print('[info] 6時のエンジン読みを確認: '+kana)


if __name__=='__main__':main()
