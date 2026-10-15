"""めたんだけの回の任意の雨衣試作。素材・認証をコードに含めない。

speaker=2は既存の進行役キーとして保ち、実際の声はmanifestのvoice_host/nameに記録する。
"""
import os
from pathlib import Path
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
UI_CREDIT = 'VoiSona Talk 雨衣 / ©Ui Shigure / ©INCOLORE'


def selected():
    value = os.getenv('COLLESPO_SOLO_HOST', 'metan') or 'metan'
    if value not in ('metan', 'ui'):
        raise ValueError('COLLESPO_SOLO_HOST は metan または ui です')
    return value


def for_segments(segments, default_speaker=3):
    solo = bool(segments) and all(str(s.get('speaker', default_speaker)) == '2'
                                 and not (s.get('meta') or {}).get('duo') for s in segments)
    return selected() if solo else 'metan'


def presentation(speaker, cast):
    if selected() == 'ui' and speaker == 'metan' and tuple(cast) == ('metan',):
        return 'ui', ('ui',)
    return speaker, cast


def validate_audio(segments):
    expected = for_segments(segments)
    for seg in segments:
        actual = seg.get('voice_host', 'metan')
        if actual != expected:
            raise ValueError('ソロ話者と保存音声が一致しません。選択した話者で全音声を作り直してください')


def credit(description, segments):
    if for_segments(segments) != 'ui':
        return description
    lines = description.splitlines()
    for i, line in enumerate(lines):
        if 'VOICEVOX:' in line and (line.startswith('音声:') or line.startswith('VOICEVOX:')):
            lines[i] = UI_CREDIT
    if not any(UI_CREDIT in line for line in lines):
        lines.append(UI_CREDIT)
    return '\n'.join(lines)


def portrait(face, height):
    """既存の部品を重ねるだけ。COLLESPO_UI_PORTRAIT_DIRは非公開の素材置き場。"""
    import ui_puppet
    return ui_puppet.portrait(face, height)


def synthesize(text, destination):
    """このPCのVoiSona Talk RESTのみ。認証・声が無ければ中止し、代役の声を使わない。"""
    import requests
    user, password = os.getenv('VOISONA_API_USERNAME'), os.getenv('VOISONA_API_PASSWORD')
    if not user or not password:
        raise ValueError('雨衣の声には、この実行環境のVoiSona Talk API認証が必要です（値をログに書かないでください）')
    destination = Path(destination).resolve()
    if not destination.is_relative_to(ROOT/'build'):
        raise ValueError('雨衣の音声出力先は作業コピーの build/ 内にしてください')
    session = requests.Session(); session.trust_env = False; session.auth = (user, password)
    base = 'http://127.0.0.1:32766/api/talk/v1'

    def call(method, path, payload=None):
        try:
            response = session.request(method, base+path, json=payload, timeout=30, allow_redirects=False)
        except requests.RequestException:
            raise ValueError('このPCのVoiSona Talk RESTに接続できません') from None
        if response.status_code not in (200, 201, 202, 204):
            raise ValueError('VoiSona Talkの認証・ライセンス・API設定を確認してください')
        return response.json() if response.content else {}

    voice = next((v for v in call('GET', '/voices').get('items', []) if v.get('voice_name') == 'ui_ja_JP'), None)
    if not voice:
        raise ValueError('VoiSona Talkに雨衣の声がありません')
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.stem+'.'+uuid.uuid4().hex+'.pending.wav')
    from notability_engine import apply_readings
    request = call('POST', '/speech-syntheses', dict(language='ja_JP', voice_name='ui_ja_JP',
        voice_version=voice['voice_version'], text=apply_readings(text), destination='file',
        output_file_path=str(pending), can_overwrite_file=True, force_enqueue=True,
        global_parameters={'speed': 1.15, 'style_weights': [1, 0, 0, 0, 0]}))
    if not request.get('uuid'):
        raise ValueError('VoiSona Talkの受付番号がありません')
    deadline = time.monotonic()+180
    while time.monotonic() < deadline:
        state = call('GET', '/speech-syntheses/'+request['uuid']).get('state')
        if state == 'failed':
            raise ValueError('雨衣の音声生成に失敗しました')
        if state == 'succeeded':
            with wave.open(str(pending), 'rb') as wav:
                if not wav.getnframes() or wav.getsampwidth() != 2:
                    raise ValueError('雨衣のWAVが空または16-bit PCMではありません')
            pending.replace(destination)
            return True
        time.sleep(.25)
    raise ValueError('雨衣の音声生成が時間内に完了しませんでした')
