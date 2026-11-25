"""説明欄にチャンネル登録の導線を1行足す（11/25 点検：全部の型で登録のリンクが無く、
いちばん伸びる日本代表の回は説明欄が名簿と出典だけだった）。

最初の段落（内容の要約）のすぐ後に置く。内容が先、導線は1行だけ。二重には足さない。
"""

CHANNEL_URL = "https://www.youtube.com/@collespo_jp"
SUBSCRIBE_LINE = f"チャンネル登録: {CHANNEL_URL}?sub_confirmation=1"


def with_subscribe(text: str, limit: int = 5000) -> str:
    if not text or "sub_confirmation=1" in text:
        return text
    if len(text) + len(SUBSCRIBE_LINE) + 2 > limit:
        return text
    lines = text.split("\n")
    # 最初の空行（＝最初の段落の終わり）の前に入れる。空行が無ければ最後へ。
    for i, line in enumerate(lines):
        if i and not line.strip():
            return "\n".join(lines[:i] + ["", SUBSCRIBE_LINE] + lines[i:])
    return text.rstrip("\n") + "\n\n" + SUBSCRIBE_LINE
