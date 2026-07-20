"""
VAPID鍵ペアを生成するスクリプト。

Web Pushの送信元を証明するために必要な鍵ペアを生成する。
このスクリプトは標準的な cryptography ライブラリのみを使い、
ネットワークアクセス無しで実行できる(実際に動作確認済み)。

出力される値の使い道:
  VAPID_PUBLIC_KEY  -> web/index.html の VAPID_PUBLIC_KEY 定数に貼り付ける
  VAPID_PRIVATE_KEY -> GitHub Secrets に登録する(絶対に公開しないこと)
  VAPID_SUBJECT     -> 自分の連絡先(mailto:か、GitHub Pagesのhttps URLでも可)

使い方:
  python3 generate_vapid_keys.py
"""

import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_vapid_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_value = private_key.private_numbers().private_value.to_bytes(32, "big")

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    return b64url(public_bytes), b64url(private_value)


if __name__ == "__main__":
    public_key, private_key = generate_vapid_keypair()

    print("=" * 60)
    print("VAPID_PUBLIC_KEY  =", public_key)
    print("VAPID_PRIVATE_KEY =", private_key)
    print("=" * 60)
    print()
    print("次にやること:")
    print("1. VAPID_PUBLIC_KEY を web/index.html 内の同名の定数に貼り付ける")
    print("2. VAPID_PRIVATE_KEY と VAPID_PUBLIC_KEY を GitHub Secrets に登録する")
    print("   (リポジトリの Settings > Secrets and variables > Actions)")
    print("3. VAPID_SUBJECT には mailto:自分のメールアドレス を登録する")
    print()
    print("注意: この鍵は一度発行したら使い回す。毎回生成し直すとブラウザ側の")
    print("購読情報と食い違って通知が届かなくなるので、生成は最初の1回だけでよい。")
