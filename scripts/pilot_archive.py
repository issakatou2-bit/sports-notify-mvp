"""完成素材をAES-256-GCMで暗号化。公開artifactに平文の動画を置かない。"""
import argparse
import base64
import io
import os
import pathlib
import zipfile

MAGIC = b"COLLESPO-PILOT-ARCHIVE-1\x00"
MAX_BYTES = 500_000_000
SUFFIXES = {".mp4", ".wav", ".png", ".jpg", ".srt", ".vtt", ".json", ".html", ".txt", ".log"}


def read_key():
    try:
        key = base64.b64decode(os.environ["PILOT_ARCHIVE_KEY"], altchars=b"-_", validate=True)
    except (KeyError, ValueError) as error:
        raise ValueError("完成素材の保存キーが未設定です") from error
    if len(key) != 32:
        raise ValueError("完成素材の保存キーの形式が不正です")
    return key


def pack(folder):
    folder = pathlib.Path(folder).resolve()
    buffer = io.BytesIO()
    total, count = 0, 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise ValueError("リンク先のファイルは保存しません")
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            total += path.stat().st_size
            count += 1
            if total > MAX_BYTES or count > 500:
                raise ValueError("完成素材が保管上限を超えています")
            archive.write(path, path.relative_to(folder).as_posix())
    if not count:
        raise ValueError("保管する完成素材がありません")
    return buffer.getvalue()


def seal(raw, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(raw) + len(MAGIC) + 28 > MAX_BYTES:
        raise ValueError("完成素材が暗号化の保管上限を超えています")
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, raw, MAGIC)


def unseal(raw, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not raw.startswith(MAGIC) or len(raw) > MAX_BYTES or len(raw) <= len(MAGIC) + 28:
        raise ValueError("暗号化した完成素材の形式が不正です")
    at = len(MAGIC)
    return AESGCM(key).decrypt(raw[at:at + 12], raw[at + 12:], MAGIC)


def unpack(raw, folder):
    folder = pathlib.Path(folder).resolve()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 500 or sum(x.file_size for x in entries) > MAX_BYTES:
            raise ValueError("完成素材が展開上限を超えています")
        targets = []
        for entry in entries:
            name = pathlib.PurePosixPath(entry.filename)
            if entry.is_dir() or name.is_absolute() or ".." in name.parts or ":" in entry.orig_filename or "\\" in entry.orig_filename:
                raise ValueError("保管ファイルのパスが不正です")
            target = (folder / entry.filename).resolve()
            if not target.is_relative_to(folder) or target.exists() or target in targets:
                raise ValueError("完成素材の展開先を確認してください")
            targets.append(target)
        for entry, target in zip(entries, targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["encrypt", "decrypt"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    key = read_key()
    target = pathlib.Path(args.out)
    if args.command == "encrypt":
        encrypted = seal(pack(args.source), key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encrypted)
        print(f"完成素材を暗号化しました: {len(encrypted)} bytes")
    else:
        unpack(unseal(pathlib.Path(args.source).read_bytes(), key), target)
        print("完成素材を新しいフォルダへ復元しました")


if __name__ == "__main__":
    main()
