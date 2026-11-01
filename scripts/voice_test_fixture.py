"""声の出所を確かめる試験では、文字列の偽WAVでなく実PCMを再作成する。"""
import io
from pathlib import Path
import wave


def pcm_wav_bytes(frames=6000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x00\x01' * frames)
    return buffer.getvalue()


def wav_file(path, frames=6000):
    Path(path).write_bytes(pcm_wav_bytes(frames))
