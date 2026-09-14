#!/usr/bin/env python3
"""長編を数字で組み立てる材料。

なぜ主題を変えるのか:
  長編はMLB公式ハイライトの**コメント欄**を見て話す番組だった。
  コメントは検算できない。9/10の「Bassoは5日ぶりの復帰」は
  数字の誤りではなく解釈の誤りで、「5日空いた」は事実、
  「復帰明け」が解釈だった。`verify_numbers` は台詞の数字と材料を
  突き合わせる仕組みなので、この形の間違いはそのまま通る。

  数字を主題にすれば、三段目の照合が台本の全文に効く。
  同じ形の事故が構造的に起きなくなる。

  そして**材料はもう全部ある。**その日のショート7本ぶんの、
  すでに検算を通った数字を読み直すだけ。追加のAPI代はほぼ0。

読むもの（どれも欠けてよい。取れない節は黙って飛ばす）:
  data/morning_recap.json  日本人選手のその日の成績と点数
  data/statcast.json       本塁打の飛距離と打球速度
  data/rarity.json         名前のある指標（アダム・ダン率など）
  data/postseason.json     進出争いの動き
  data/soccer_race.json    欧州サッカーの順位争い
"""

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import morning_recap as mr  # noqa: E402
import race_words as rw  # noqa: E402

try:
    import statcast as sc
except Exception:  # noqa: BLE001  取れない日でも材料は作る
    sc = None

# 話す順。上から、取れたものだけを使う。
MAX_PLAYERS = 4      # 全員並べると点呼になる。上位だけ
MAX_RARE = 2
MAX_CHANGES = 4      # 進出争いで動いたこと
MAX_SOCCER = 1       # 1本1大会。長編でも大会は1つに絞る
MAX_ROWS = 4         # 1枚の札に並ぶ行数（描画側の上限）


def _read(path) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _score(row: dict) -> int:
    try:
        return int(mr.score_label(row) or 0)
    except Exception:
        return 0


def is_pitcher(row: dict) -> bool:
    """投手か。**`type` は "pitcher" であって "P" ではない。**

    ここを外すと打者の書式で投手の行を作ることになり、被安打が安打に
    化ける。同じ名前が投手と打者で反対の意味を持つ項目があるので、
    判定を1か所に置く。
    """
    return (row.get("type") or "").lower().startswith("p")


def _line(row: dict) -> str:
    """その日の成績を1行で。投手と打者で項目が違う。

    **投手の hits は被安打。**打者と同じ名前で反対の意味を持つので、
    ここで混ぜない。
    """
    if not is_pitcher(row):
        return row.get("headline") or ""
    bits = []
    if row.get("ip"):
        bits.append("%s回" % row["ip"])
    for key, unit in (("hits", "被安打"), ("er", "自責"),
                      ("so", "奪三振"), ("bb", "四球")):
        if row.get(key) is not None:
            bits.append("%s%s" % (unit, row[key]))
    for key, unit in (("saves", "セーブ"), ("holds", "ホールド")):
        if row.get(key):
            bits.append(unit)
    return "・".join(bits)


HEADLINE_UNITS = ("打数", "安打", "本塁打", "打点", "四球", "盗塁", "三振")
_HEAD = re.compile(r"([0-9]+)(%s)" % "|".join(HEADLINE_UNITS))


def _numbers(row: dict) -> dict:
    """台詞と突き合わせる数字。**投手と打者で項目の意味が違う。**

    投手の `hits` は被安打、打者の `hits` は安打。同じ鍵なので、
    ここで別の名前に分けておかないと、照合する側が区別できない。
    """
    out = {}
    if is_pitcher(row):
        for key, unit in (("ip", "回"), ("hits", "被安打"), ("er", "自責"),
                          ("so", "奪三振"), ("bb", "四球"),
                          ("saves", "セーブ"), ("holds", "ホールド")):
            if row.get(key) is not None:
                out[unit] = row[key]
        return out
    # 打者は本塁打と打点が個別の項目に無く、見出しの中にしかない。
    for value, unit in _HEAD.findall(row.get("headline") or ""):
        out[unit] = int(value)
    if row.get("hits") is not None:
        out.setdefault("安打", row["hits"])
    return out


def load(root: str = "data") -> dict:
    """その日の数字をまとめる。"""
    base = pathlib.Path(root)
    recap = _read(base / "morning_recap.json")
    rows = [r for r in (recap.get("players") or []) if r.get("name")]
    rows.sort(key=_score, reverse=True)
    players = []
    for row in rows[:MAX_PLAYERS]:
        players.append({
            "name": row.get("name"),
            "team": row.get("team_jp") or "",
            "line": _line(row),
            "score": _score(row),
            "badges": mr.badge_labels(row, limit=3),
            "type": row.get("type") or "",
            "player_id": str(row.get("player_id") or ""),
            "numbers": _numbers(row),
        })

    # 打球は {名前: [本塁打, ...]}。言い方は statcast.phrase に任せる。
    shots = []
    for name, hits in (_read(base / "statcast.json").get("japanese")
                       or {}).items():
        text = sc.phrase(hits) if sc else ""
        if text:
            shots.append({"name": name, "text": text})

    # 指標は {名前: {items: [...]}}。**同率は出さない。**
    # 全員が同じ値の指標で「1位」と言うことになる（ties で外す）。
    rare = []
    for name, row in (_read(base / "rarity.json").get("players")
                      or {}).items():
        for item in (row.get("items") or []):
            if (item.get("ties") or 1) > 1 or not item.get("label"):
                continue
            rare.append({"name": name, "stat": item["label"],
                         "value": item.get("shown") or "",
                         "rank": "%s人中%s位" % (item.get("of"),
                                                item.get("at")),
                         "note": item.get("note") or "",
                         "namesake": item.get("namesake") or ""})
            break
    rare = rare[:MAX_RARE]

    post = _read(base / "postseason.json")
    race = {"headline": post.get("headline") or "",
            "changes": (post.get("changes") or [])[:MAX_CHANGES],
            "japanese": post.get("japanese") or []}

    soccer = {}
    for comp in (_read(base / "soccer_race.json").get("competitions") or []):
        if comp.get("ready") and comp.get("round_complete"):
            soccer = comp
            break

    return {"date": recap.get("date_jst") or recap.get("date") or "",
            "players": players, "shots": shots, "rare": rare,
            "race": race, "soccer": soccer}


def has_enough(m: dict) -> bool:
    """話せるだけの数字があるか。**無い日に組み立てない。**"""
    return bool(m.get("players")) or bool(m.get("race", {}).get("changes"))


def facts(m: dict) -> str:
    """モデルに渡す事実。ここに無いことは書かせない。"""
    out = ["## きょうの日本人選手（点数の高い順）",
           "※ 点数はコレスポの独自指標。活躍の大きさを並べるためのもので、",
           "  公式の記録ではない。**点数そのものを主題にしない。**"]
    if not m["players"]:
        out.append("（出場した選手がいない）")
    for p in m["players"]:
        row = "- %s（%s）%s" % (p["name"], p["team"], p["line"] or "出場")
        if p["badges"]:
            row += " ／ " + "・".join(p["badges"])
        out.append(row)

    if m["shots"]:
        out.append("")
        out.append("## 本塁打の打球（Statcastの計測値）")
        for s in m["shots"]:
            out.append("- %s: %s" % (s["name"], s["text"]))

    if m["rare"]:
        out.append("")
        out.append("## 名前のある指標での位置")
        out.append("※ 公式記録ではないが、今季の規定到達者の中での実際の順位。")
        for r in m["rare"]:
            out.append("- %s の%s %s（%s）"
                       % (r["name"], r["stat"], r["value"], r["rank"]))
            if r.get("note"):
                out.append("  %s とは: %s" % (r["stat"], r["note"]))
            if r.get("namesake"):
                out.append("  %s" % r["namesake"])

    race = m["race"]
    if race.get("headline") or race.get("changes"):
        out.append("")
        out.append("## 進出争い")
        if race.get("headline"):
            out.append("見出し: %s" % race["headline"])
        for c in race["changes"]:
            out.append("- %s" % (c.get("text") or ""))
        inside = [j for j in race.get("japanese") or [] if j.get("route")]
        if inside:
            out.append("日本人選手のいる球団のいま:")
            for j in inside[:6]:
                bits = [j.get("team") or ""]
                if j.get("w") is not None:
                    bits.append("%s勝%s敗" % (j.get("w"), j.get("l")))
                bits.append(rw.phrase(j))
                if j.get("players"):
                    bits.append("／".join(j["players"]))
                out.append("- " + "・".join(str(b) for b in bits if b))

    if m["soccer"]:
        c = m["soccer"]
        out.append("")
        out.append("## 欧州サッカー（%s 第%s節が終わった）"
                   % (c.get("name_jp") or c.get("jp") or "", c.get("round")))
        for line in (c.get("lines") or [])[:3]:
            out.append("- %s" % (line.get("text") or line))

    return "\n".join(out)


def panels(m: dict) -> dict:
    """画面の札。**中身はここで決める。**モデルには鍵だけ選ばせる。

    型は長編の描画がすでに持っているものを使う（star / stat / group）。
    新しい型を足すと、描画と札の2か所で同じことを決めることになる。
    """
    out = {}
    for i, p in enumerate(m["players"], 1):
        line = p["line"] or ""
        if p["badges"]:
            line = (line + " " + "・".join(p["badges"])).strip()
        out["jp%d" % i] = {"type": "star", "name": p["name"],
                           "team": p["team"], "line": line,
                           "menu": "%sのきょうの成績" % p["name"]}
    for i, s in enumerate(m["shots"][:2], 1):
        out["shot%d" % i] = {"type": "star", "name": s["name"],
                             "team": "本塁打の打球", "line": s["text"],
                             "menu": "%sの本塁打の飛距離と打球速度" % s["name"]}
    for i, r in enumerate(m["rare"], 1):
        out["rare%d" % i] = {"type": "stat", "name": r["name"],
                             "stat": r["stat"], "value": r["value"],
                             "rank": r["rank"],
                             "menu": "%sの%s" % (r["name"], r["stat"])}

    rows = [{"name": j["team"], "value": rw.short(j)}
            for j in (m["race"].get("japanese") or []) if j.get("team")]
    if rows:
        out["race"] = {"type": "group", "head": "進出争い",
                       "rows": rows[:MAX_ROWS], "menu": "進出争いの現在地"}

    if m["soccer"]:
        c = m["soccer"]
        srows = []
        for club in (c.get("clubs") or [])[:MAX_ROWS]:
            if club.get("name_jp") or club.get("name"):
                srows.append({"name": club.get("name_jp") or club.get("name"),
                              "value": "%s位" % club.get("position", "")})
        if srows:
            out["soccer"] = {"type": "group",
                             "head": "%s 第%s節"
                                     % (c.get("name_jp") or c.get("jp") or "",
                                        c.get("round")),
                             "rows": srows,
                             "menu": "欧州サッカーの順位"}

    out["topic"] = {"type": "topic", "topic": "きょうのMLB、数字で",
                    "menu": "きょうの話（締めに使う）"}
    return out


def checkable(m: dict) -> dict:
    """台詞の数字と突き合わせる材料。`{名前: {単位: 値}}`。

    ここに無い数字を台詞が言っていたら、`verify_numbers` が止める。
    計算はしない（計算するなら材料側の仕事で、間違いも一緒に写る）。
    """
    out = {p["name"]: dict(p["numbers"]) for p in m["players"]
           if p["numbers"]}
    for j in (m["race"].get("japanese") or []):
        if j.get("team") and j.get("w") is not None:
            row = {"勝": j["w"], "敗": j["l"]}
            if isinstance(j.get("magic"), int):
                row["マジック"] = j["magic"]
            out[j["team"]] = row
    return out


def meta(m: dict) -> dict:
    """台本に添える、題とサムネイルの材料。

    **長編の弱さは題だった**（8本で平均11再生、名前のある回だけが伸びた）。
    数字の回は出場した選手を必ず拾えるので、題に名前が入る。
    """
    names = [p["name"] for p in m["players"]]
    best = m["players"][0] if m["players"] else {}
    return {"mode": "numbers",
            "top": "きょうのMLB、数字で",
            "title": "",
            "jp": names,
            "jp_team": [],
            "jp_team_name": best.get("team", ""),
            "pick": (("%s %s" % (best.get("name", ""), best.get("line", "")))
                     .strip()[:60]),
            "source": "その日の成績・進出争い・指標"}


def outline(m: dict) -> str:
    """サマリに出す一行。何が入って何が入らなかったか。"""
    bits = ["選手%d人" % len(m["players"])]
    if m["shots"]:
        bits.append("打球%d" % len(m["shots"]))
    if m["rare"]:
        bits.append("指標%d" % len(m["rare"]))
    if m["race"].get("changes"):
        bits.append("進出争い%d件" % len(m["race"]["changes"]))
    if m["soccer"]:
        bits.append("サッカー%s" % (m["soccer"].get("name_jp") or ""))
    return "・".join(bits)


if __name__ == "__main__":
    material = load(sys.argv[1] if len(sys.argv) > 1 else "data")
    print(outline(material))
    print()
    print(facts(material))
    print()
    print("札:", ", ".join(panels(material)))
