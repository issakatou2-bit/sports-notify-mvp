"""題の選手名と球団名を、新聞・大手メディアの書き方にそろえる（題だけ。読み上げには使わない）。

10/10 本人「大谷翔平のドジャースっていうか、大谷ドジャースとかでよくない？」
「村上ホワイトソックス、松井パドレス、全然自然ですよ」「新聞とか大手メディアの呼び方含めて参考にしよう」。
新聞の見出しの決まり（共同通信・デイリーなど、10/10 に元の記事を開いて確認）:
  - チームが主語: 「村上のWソックス、来季好転予想」  → ここでは本人の言い方で「村上ホワイトソックス」
  - 選手が主語:   「Wソックス村上『全力で戦う』」「ドジャース大谷」
  - 長い球団名は略す: ホワイトソックス→Wソックス、レッドソックス→Rソックス、ダイヤモンドバックス→Dバックス
    （YouTube の題は100字まであり、「ホワイトソックス」で検索する人もいるので、略すのは題が長すぎるときだけ）
読み上げ（VOICEVOX）は「ダブリュソックス」と読むので、ここは通さない。
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import notability_engine as ne  # noqa: E402

# 名字（新聞の呼び方）。名簿の名前と1対1。ここに無い選手はフルネームのまま。
SURNAME = {
    "大谷翔平": "大谷", "ダルビッシュ有": "ダルビッシュ", "佐々木朗希": "佐々木", "山本由伸": "山本",
    "菅野智之": "菅野", "菊池雄星": "菊池", "今永昇太": "今永", "鈴木誠也": "鈴木", "千賀滉大": "千賀",
    "松井裕樹": "松井", "吉田正尚": "吉田", "岡本和真": "岡本", "村上宗隆": "村上",
    "小笠原慎之介": "小笠原", "今井達也": "今井", "ヌートバー": "ヌートバー", "西田陸浮": "西田",
}
SHORT_TEAM = {"ホワイトソックス": "Wソックス", "レッドソックス": "Rソックス", "ダイヤモンドバックス": "Dバックス"}
TITLE_MAX = 100


def _teams():
    return sorted(set(ne.MLB_TEAM_NAME_JP.values()) | set(SHORT_TEAM.values()), key=len, reverse=True)


def press_title(title: str, limit: int = TITLE_MAX) -> str:
    """「村上宗隆のホワイトソックス」→「村上ホワイトソックス」、「ホワイトソックス 村上宗隆、」→「ホワイトソックス村上、」。"""
    out = str(title or "")
    teams = "|".join(map(re.escape, _teams()))
    names = "|".join(map(re.escape, sorted(SURNAME, key=len, reverse=True)))

    def team_subject(match):
        full, team = match.group("names", "team")
        # 空白を含む列挙も、途中の1人だけ省略しない。
        if (full not in SURNAME or
                out[:match.start()].rstrip().endswith(("・", "、", "と", "＆", "&", "/", "／"))):
            return match.group(0)
        sur = SURNAME[full]
        join = "の" if re.fullmatch(r"[ァ-ヶー・]+", sur) else ""
        return f"{sur}{join}{team}"

    out = re.sub(rf"(?P<names>(?:{names})(?:[・、と＆&/／\s]+(?:{names}))*)"
                 rf"(?:が所属する|の)(?P<team>{teams})", team_subject, out)
    for full, sur in sorted(SURNAME.items(), key=lambda kv: -len(kv[0])):
        f = re.escape(full)
        kana = bool(re.fullmatch(r"[ァ-ヶー・]+", sur))
        if kana:
            # 以前の変換で連結済みの題も、付け直すときに修復する。
            out = re.sub(rf"(?<![・、と＆&/／]){re.escape(sur)}({teams})",
                         rf"{sur}の\1", out)
        # 選手が主語（球団＋選手）
        gap = " " if kana else ""
        ending = r"(?=[、｜ 　の]|$)" if kana else r"(?=[、｜ 　の])"
        out = re.sub(rf"({teams})(?:\s|　|の)?{f}{ending}",
                     rf"\1{gap}{sur}", out)
    if len(out) > limit:
        for long, short in SHORT_TEAM.items():
            out = out.replace(long, short)
    return out
