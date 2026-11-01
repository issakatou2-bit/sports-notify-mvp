"""CI の既存描画処理が探す Noto CJK を、キャッシュ優先で用意する。"""
import shutil
import subprocess
import time
from pathlib import Path

from check_diagram_font import check

FONT_DIR = Path('/usr/share/fonts/opentype/noto')
CACHE_DIR = Path.home() / '.cache/collespo-noto-cjk'
NAMES = ('NotoSansCJK-Regular.ttc', 'NotoSansCJK-Bold.ttc')


def readable(directory):
    try:
        for name in NAMES:
            check(directory / name)
    except (OSError, RuntimeError):
        return False
    return True


def install(font_dir=FONT_DIR, cache_dir=CACHE_DIR):
    if not readable(font_dir) and readable(cache_dir):
        subprocess.run(['sudo', 'install', '-d', str(font_dir)], check=True)
        for name in NAMES:
            subprocess.run(['sudo', 'install', '-m', '644',
                            str(cache_dir / name), str(font_dir / name)], check=True)

    for attempt in range(3):
        if readable(font_dir):
            break
        try:
            subprocess.run(['sudo', 'apt-get', 'update', '-qq',
                            '-o', 'Acquire::Retries=3',
                            '-o', 'Acquire::http::Timeout=30',
                            '-o', 'Acquire::https::Timeout=30'], check=True, timeout=150)
            subprocess.run(['sudo', 'apt-get', 'install', '-y', '-qq',
                            '-o', 'Acquire::Retries=3', 'fonts-noto-cjk'],
                           check=True, timeout=240)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print(f'[warn] Noto CJK 導入 {attempt + 1}/3: {type(exc).__name__}', flush=True)
        if not readable(font_dir) and attempt < 2:
            time.sleep(5)

    # apt の終了コードやファイルの存在だけでは成功扱いしない。
    for name in NAMES:
        check(font_dir / name)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        shutil.copyfile(font_dir / name, cache_dir / name)
    print('ok Noto CJK Regular / Bold（日本語描画確認済み）')


if __name__ == '__main__':
    install()
