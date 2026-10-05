"""同日の長編へ案内する、自動追記ブロックを1つだけ保つ。"""
import re


HEADING = "▼ 同日のMLB成績とポストシーズンを長編で紹介しています"
LEGACY_HEADING = "▼ この試合のコメント欄を、もっと詳しく読んでいます（3分）"
_PREFIX = re.compile(
    r"\A(?:" + "|".join(re.escape(x) for x in (HEADING, LEGACY_HEADING))
    + r")\r?\nhttps://youtu\.be/[A-Za-z0-9_-]{11}(?:\r?\n\r?\n|\Z)"
)


def replace_longform_link(description: str, long_id: str) -> str:
    """既知の先頭案内だけ置換し、本文・他のURL・クレジットは保つ。

    長編を作り直して旧候補を保留するときも、新しい案内の追記で
    旧候補の導線を積み重ねない。動画の公開設定自体は変更しない。
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", long_id):
        raise ValueError("長編の動画IDが不正です")
    body = description or ""
    while match := _PREFIX.match(body):
        body = body[match.end():]
    link = f"{HEADING}\nhttps://youtu.be/{long_id}"
    result = link + ("\n\n" + body if body else "")
    if len(result) > 5000:
        raise ValueError("説明欄の上限を超えるため本文を切らずに停止します")
    return result
