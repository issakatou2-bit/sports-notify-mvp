#!/usr/bin/env python3
"""進出争いの位置を日本語にする。**言い方を1か所で決める。**

なぜ分けるか:
  「ワイルドカードまで0.5ゲーム差」とだけ書くと、中にいるのか外にいるのかが
  読み取れない。**同じ0.5でも圏内と圏外で意味が逆になる。**
  MLB APIは圏内の球団に「+5.0」と符号を付けて返し、圏外には付けない。

  この読み替えが台本・ショート・長編に散ると、どれか1つを直したときに
  他が古いまま残る。実際に長編の材料を書いたとき「圏内まで+1.5」という、
  圏内なのか圏内を目指しているのか分からない文になった。ここに集める。
"""

ELIMINATED = "E"
NO_DIFF = (None, "-", "")


def _gb(row: dict):
    """差の文字列。無いとき None。敗退は ELIMINATED のまま返す。"""
    value = row.get("wc_gb")
    if value in NO_DIFF:
        return None
    return str(value)


def settled(row: dict) -> bool:
    """その球団の行き先が決まっているか（進出も敗退も含む）。"""
    return bool(row.get("clinched") or row.get("div_champ")
                or row.get("eliminated")
                or str(row.get("wc_gb") or "") == ELIMINATED)


def ps_label(data: dict) -> str:
    """20:00の回の呼び名。**1か所で決める。**

    題・説明・画面・サムネイル・掛け合いの5か所に「ポストシーズン進出争い」
    と書いてあった。短期決戦に入ったら、もう進出を争ってはいない。
    """
    if (data or {}).get("phase") == "postseason":
        return "ポストシーズン"
    return "ポストシーズン進出争い"


def race_is_over(data: dict) -> bool:
    """進出争いそのものが終わっているか。

    **ポストシーズンが終わっても、順位表は決着した形のまま残る。**
    昨日からの動きが無く、全球団の行き先が決まっている状態が
    11月から3月まで続く。それを見ずに画面を組むと、
    「レイズ 進出決定」と言うだけの動画が毎日出る（実際に作れた）。

    材料そのものが無い日も、話すことが無いという意味で終わり扱い。

    **ポストシーズンに入ったら、順位表ではなくシリーズで決める。**
    順位表は全球団が決着した形で止まるので、上の見方だと
    短期決戦のあいだずっと「終わった」ことになる。昨日から動いた
    シリーズがあれば話し、試合の無い日（回戦の合間）は出さない。
    """
    if data.get("phase") == "postseason":
        return not data.get("changes")
    rows = data.get("teams")
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not rows:
        rows = data.get("japanese") or []
    if not rows:
        return True
    if data.get("changes"):
        return False          # 昨日から動いた。まだ争っている
    return all(settled(r) for r in rows)


def _by_division(row: dict) -> bool:
    """地区首位で進出しようとしているか。

    **差が無いことの意味が、ここで変わる。**地区首位の球団には
    ワイルドカードの差が返らない。それを「最後の枠」と読むと、
    90勝59敗で地区を走っているドジャースが最後の枠にいることになる
    （実際そう書いた）。
    """
    return str(row.get("route") or "").startswith("地区")


def phrase(row: dict) -> str:
    """台詞と事実に渡す言い方。圏内か圏外かを必ず書く。"""
    if row.get("clinched") or row.get("div_champ"):
        return "進出決定"
    gb = _gb(row)
    if gb == ELIMINATED:
        return "進出の可能性は消滅"
    bits = []
    if _by_division(row):
        bits.append("地区首位")
    elif gb is None:
        # ワイルドカードの最後の枠にいる球団には差が返らない（自分が基準）。
        bits.append("ワイルドカード最後の枠")
    elif gb.startswith("+"):
        # **「圏内で6位に6.5ゲーム差」は誤読された。**台本が「圏外側」と
        # 書いた。数字と語が続くと、どちらに付く差なのか読み取れない。
        # 「つけている」まで書いて、向きを言い切る。
        bits.append("ワイルドカード圏内（6位に%sゲーム差をつけている）"
                    % gb.lstrip("+"))
    else:
        bits.append("ワイルドカード圏外（進出圏内まであと%sゲーム）" % gb)
    if isinstance(row.get("magic"), int):
        bits.append("地区優勝マジック%d" % row["magic"])
    return "・".join(bits)


def short(row: dict) -> str:
    """札に入れる短い形。**圏内・圏外の語は落とさない。**

    数字だけにすると、画面を見た人が中にいるのか外にいるのか分からない。
    ここを削ると、口で補うしかなくなる。
    """
    if row.get("clinched") or row.get("div_champ"):
        return "進出決定"
    gb = _gb(row)
    if gb == ELIMINATED:
        return "敗退"
    if isinstance(row.get("magic"), int):
        return "M%d" % row["magic"]
    if _by_division(row):
        return "地区首位"
    if gb is None:
        return "圏内"
    if gb.startswith("+"):
        return "圏内 %s" % gb.lstrip("+")
    return "圏外 %s" % gb
