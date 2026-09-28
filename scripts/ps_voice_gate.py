"""Check the engine's pronunciation of the reported padded-hour incident."""
import json
from pathlib import Path
import re
import requests
from ps_program import spoken_start


def main():
    phrase='初戦は日本時間'+spoken_start('09/30 06:00')+'です。'
    response=requests.post('http://127.0.0.1:50021/audio_query',
                           params={'text':phrase,'speaker':2},timeout=20)
    response.raise_for_status()
    kana=response.json()['kana']
    sounds=re.sub('[^ァ-ヶー]','',kana)
    if 'ゼロ' in sounds or 'ロクジ' not in sounds:
        raise ValueError('6時の読みが自然な日本語として確認できません: '+kana)
    out=Path('build/ps_voice_check.json');out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'text':phrase,'engine_kana':kana,'passed':True},ensure_ascii=False,indent=2),encoding='utf-8')
    print('[info] 6時のエンジン読みを確認: '+kana)


if __name__=='__main__':main()
