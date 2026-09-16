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
from datetime import date

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

# 主役からこれだけ離れた選手は出さない（主役の点数に対する割合）。
#
# **「4打数1安打」を「きょうの日本人選手」として並べない。**
# ユーザーの指摘:「山本だけでいいのに、4打数1安打の岡本を無理して
# 出す理由は何？」。材料に入れれば、モデルはそれについて何か言おうと
# する。言うことが無い選手は、最初から渡さない。
#
# 絶対値で切らないのは、主役が小さい日もあるため。7回無失点の145点が
# いる日の44点と、最高が50点の日の44点では、意味がまるで違う。
RELATIVE_FLOOR = 0.45
MAX_RARE = 2
MAX_TRENDS = 3      # 主役1人ぶんの切り口。多いと読み切れない
MAX_CHANGES = 4      # 進出争いで動いたこと
MAX_SOCCER = 1       # 1本1大会。長編でも大会は1つに絞る
MAX_ROWS = 4         # 1枚の札に並ぶ行数（描画側の上限）

# 材料が何日前までなら使うか。
#
# **シーズンが終わると、更新の止まった材料がそのまま残る。**
# morning_recap.json の中身は最後の試合日のままなので、日付を見ない限り
# 「きょうの成績」として11月も12月も同じ動画を作り続ける。
# 進出争いも同じで、ポストシーズンが終わったあとの `changes` が
# 毎日「レイズ 進出決定」と言い続ける。
#
# 2日にするのは、枠がGitHubのscheduleの遅れで日をまたぐことがあるため
# （9/13に19時の枠がJST 0時台に走った）。1日だと、その日の回が
# 「昨日の材料」として落ちる。
MAX_AGE_DAYS = 2


def _read(path) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _day(value) -> date | None:
    """"2026-09-15" や ISO時刻から、日付だけを取る。読めなければ None。"""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def fresh(data: dict, today: date = None, days: int = MAX_AGE_DAYS,
          *keys: str) -> bool:
    """その材料が新しいか。**日付が読めないものは古いものとして扱う。**

    シーズンが終われば材料の更新は止まる。止まったことに気づく手が
    日付しかないので、読めないなら使わない。
    """
    today = today or date.today()
    for key in (keys or ("date_jst", "date", "updated_at")):
        got = _day(data.get(key))
        if got is not None:
            return 0 <= (today - got).days <= days
    return False


def _fresh_read(path, today: date, *keys: str) -> dict:
    """新しければそのまま、古ければ空。何を落としたかは言う。"""
    data = _read(path)
    if not data:
        return {}
    if fresh(data, today, MAX_AGE_DAYS, *keys):
        return data
    print("[info] %s が古いので使いません（%s）"
          % (pathlib.Path(path).name,
             data.get("date_jst") or data.get("date")
             or data.get("updated_at") or "日付なし"))
    return {}


def _score(row: dict) -> int:
    try:
        return int(mr.score_label(row) or 0)
    except Exception:
        return 0


OUTS_PER_INNING = 3


def outs(ip) -> int:
    """投球回からアウトの数。"1.2" は1回と2アウトで5。

    **これが無いと「1回で3三振はほとんどを三振で終わらせた」になる。**
    1回は3アウトなので、3奪三振なら「ほとんど」ではなく全部。
    """
    try:
        whole, _, frac = str(ip or "").partition(".")
        return int(whole) * OUTS_PER_INNING + int(frac or 0)
    except ValueError:
        return 0


def role_of(row: dict) -> str:
    """その日の登板が先発か救援か。

    **これが無いと「1回だけなのだ？ 短いのだ」が出る。**
    救援の1回と先発の1回では、意味がまるで違う。
    `gs` はその日に先発したかどうか（松井裕樹のセーブの日は0）。
    """
    if row.get("gs"):
        return "先発"
    if row.get("saves") or row.get("holds") or row.get("blown"):
        return "救援"
    return "救援" if outs(row.get("ip")) <= 9 else "先発"


def readings(row: dict) -> list:
    """その数字をどう読むか。**当たり前のことを珍しがらせない。**

    材料に数字だけを並べると、何が普通で何が珍しいかが分からないまま
    台本が書かれる。9/15の回は3つとも外した——3ランの3打点を「多い」、
    救援の1回を「短い」、1回3奪三振を「ほとんど」と言った。
    """
    out = []
    if is_pitcher(row):
        got, so = outs(row.get("ip")), row.get("so") or 0
        role = role_of(row)
        out.append("この日は%s" % role)
        if role == "救援" and got <= 4:
            out.append("救援で1回前後を投げるのは、その役割では普通のこと"
                       "（短い登板として珍しがらない）")
        if got and so >= got:
            out.append("取ったアウト%d個すべてが三振" % got)
        elif got and so:
            out.append("アウト%d個のうち%d個が三振" % (got, so))
        if row.get("saves"):
            out.append("セーブがついた")
        if row.get("holds"):
            out.append("ホールドがついた")
        return out

    nums = _numbers(row)
    hits, hr = nums.get("安打", 0), nums.get("本塁打", 0)
    rbi, ab = nums.get("打点", 0), nums.get("打数", 0)
    if hr == 1 and hits == 1 and rbi >= 2:
        # 安打が本塁打1本だけなら、その打点は全部その1本のもの。
        out.append("安打はその本塁打1本だけなので、%d打点は%dランによるもの"
                   "（本塁打が複数点を生むのは当たり前なので驚かない）"
                   % (rbi, rbi))
    if hits and hr == hits and hits > 1:
        out.append("安打%d本がすべて本塁打" % hits)
    if ab and not hits and (nums.get("四球") or nums.get("死球")):
        out.append("安打は無いが出塁はしている")
    return out


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


# 見出しに出る単位。**ここに無い単位は照合されない。**
# 9/15の回で「四球1、死球1」と言っていたが、死球がここに無かったので
# 台詞の数字と材料を突き合わせる対象から外れていた。
HEADLINE_UNITS = ("打数", "安打", "本塁打", "打点", "四球", "死球",
                  "盗塁", "三振", "犠飛", "犠打")
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


def load(root: str = "data", today: date = None) -> dict:
    """その日の数字をまとめる。**古い材料は使わない。**

    シーズンが終われば材料の更新は止まる。日付を見ないと、
    止まった材料で毎日同じ動画を作り続けることになる。
    """
    base = pathlib.Path(root)
    today = today or date.today()
    recap = _fresh_read(base / "morning_recap.json", today)
    # **その日「何かした」選手だけを渡す。**
    #
    # 出場した順に上から4人を渡していたので、4打数1安打の選手が
    # 「きょうの日本人選手」として並んだ。ユーザーの指摘:
    # 「山本だけでいいのに、4打数1安打の岡本を無理して出す理由は何？」
    #
    # 材料に入っていれば、モデルはそれについて何か言おうとする。
    # 言うことが無い選手は、最初から渡さない。
    rows = [r for r in (recap.get("players") or [])
            if r.get("name") and mr.did_something(r)]
    rows.sort(key=_score, reverse=True)
    if rows:
        floor = _score(rows[0]) * RELATIVE_FLOOR
        # 名前のある記録（完封・HQS・猛打賞など）がある選手は、
        # 点数が低くても残す。**記録そのものが話すことなので。**
        rows = [r for r in rows
                if _score(r) >= floor or mr.badge_labels(r, limit=1)]
    players = []
    for row in rows[:MAX_PLAYERS]:
        players.append({
            "name": row.get("name"),
            "team": row.get("team_jp") or "",
            "line": _line(row),
            "score": _score(row),
            "badges": mr.badge_labels(row, limit=3),
            # **読み上げには開いた表記を渡す。**
            # 「HQS」をそのまま渡したら「ヒットクオリティスタート」と
            # 読まれた（正しくはハイクオリティスタート）。長編は声が主
            # なので、略記のままにしておくとモデルが勝手に開く。
            "badges_speech": mr.badge_speech(row, limit=3),
            # **はっきり称賛してよい内容か。**
            # ユーザーの判断:「日本人選手が素晴らしい内容だったら、
            # 今日の山本くらいの内容だったら、もう少し称賛を入れてもいい」。
            # 良し悪しをモデルに決めさせると、4打数1安打も褒めることに
            # なる。材料の側で線を引く（morning_recap.STANDOUT=130）。
            "standout": _score(row) >= mr.STANDOUT,
            "type": row.get("type") or "",
            "player_id": str(row.get("player_id") or ""),
            "numbers": _numbers(row),
            "readings": readings(row),
        })

    # 打球は {名前: [本塁打, ...]}。言い方は statcast.phrase に任せる。
    shots = []
    for name, hits in (_fresh_read(base / "statcast.json", today)
                       .get("japanese") or {}).items():
        text = sc.phrase(hits) if sc else ""
        if text:
            shots.append({"name": name, "text": text})

    # 指標は {名前: {items: [...]}}。**同率は出さない。**
    # 全員が同じ値の指標で「1位」と言うことになる（ties で外す）。
    #
    # 指標はシーズン通算なので、最終戦の翌日でも中身は正しい。
    # ただし更新が止まったまま年を越すと去年の数字になるので、
    # 他と同じ幅で切る（`updated_at` を見る）。
    rare = []
    for name, row in (_fresh_read(base / "rarity.json", today)
                      .get("players") or {}).items():
        for item in (row.get("items") or []):
            if (item.get("ties") or 1) > 1 or not item.get("label"):
                continue
            above = item.get("above") or {}
            rare.append({"name": name, "stat": item["label"],
                         "value": item.get("shown") or "",
                         "rank": "%s人中%s位" % (item.get("of"),
                                                item.get("at")),
                         "note": item.get("note") or "",
                         "namesake": item.get("namesake") or "",
                         # 「1位は誰か」を聞かれたときに答えられるように。
                         # 渡していなかったので「材料に出てないから
                         # 分からない」と言う回になった（9/15）。
                         "above": ("%s %s" % (above.get("name") or "",
                                              above.get("shown") or "")
                                   ).strip()})
            break
    rare = rare[:MAX_RARE]

    # 主役の1人だけ、切り口ごとの成績を足す。
    #
    # **MLBを見ている人が見るに耐える回にする**ための材料。
    # 成績を並べるだけだと、その日の表を読み上げたのと変わらない。
    # 「夜の試合ではOPS.921」「得点圏では今季全体を下回っている」まで
    # 入って、はじめて解説になる。
    #
    # 1人だけにするのはAPIの回数（1人4回）と、尺の都合。
    # 3分で全員ぶん入れても読み切れない。
    trends = []
    if players and players[0].get("player_id"):
        try:
            import insight
            trends = insight.player(
                players[0]["player_id"], players[0]["name"],
                season=(recap.get("date_jst") or "")[:4] or "2026",
                group="pitching" if players[0]["type"].startswith("p")
                else "hitting")[:MAX_TRENDS]
        except Exception as e:                       # noqa: BLE001
            print("[info] 切り口ごとの成績を取れません(%s)" % e)

    post = _fresh_read(base / "postseason.json", today)
    race = {"headline": post.get("headline") or "",
            "changes": (post.get("changes") or [])[:MAX_CHANGES],
            "japanese": post.get("japanese") or []}

    soccer = {}
    for comp in (_fresh_read(base / "soccer_race.json", today)
                 .get("competitions") or []):
        if comp.get("ready") and comp.get("round_complete"):
            soccer = comp
            break

    return {"date": recap.get("date_jst") or recap.get("date") or "",
            "players": players, "trends": trends, "shots": shots, "rare": rare,
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
        if p.get("badges_speech"):
            # **声に出す表記で渡す。**略記だと読み方を作られる。
            row += " ／ " + "・".join(p["badges_speech"])
        out.append(row)
        if p.get("standout"):
            out.append("  ★きょうの主役。**はっきり称賛してよい内容。**"
                       "「素晴らしい投球だった」と書いてよい")
        # **その数字が普通か珍しいかを、ここで渡す。**
        # 渡さないと、当たり前のことを珍しがる台詞になる。
        for note in p.get("readings") or []:
            out.append("  ・%s" % note)

    if m["shots"]:
        out.append("")
        out.append("## 本塁打の打球（Statcastの計測値）")
        for s in m["shots"]:
            out.append("- %s: %s" % (s["name"], s["text"]))

    if m.get("trends"):
        out.append("")
        out.append("## %s の、切り口ごとの成績" % m["players"][0]["name"])
        out.append("※ ここは**その日の成績ではなく今季の傾向。**")
        out.append("  「きょう」と混ぜない。確からしさが low のものは")
        out.append("  傾向として語らず、起きたことをそのまま置く。")
        for t in m["trends"]:
            out.append("- %s（確からしさ %s）" % (t["text"], t["sure"]))
            if t.get("detail"):
                out.append("  %s" % t["detail"])
            if t.get("why"):
                out.append("  なぜ見るか: %s" % t["why"])

    if m["rare"]:
        out.append("")
        out.append("## 名前のある指標での位置")
        out.append("※ 公式記録ではないが、今季の規定到達者の中での実際の順位。")
        out.append("※ **「とは」の行は画面に出る。声では説明しない。**")
        out.append("  用語の意味を読み上げると、そこで話が止まる。")
        out.append("  気になる人は画面を止めて読める。声で話すのは")
        out.append("  **どれくらい珍しいか**のほう。")
        for r in m["rare"]:
            out.append("- %s の%s %s（%s）"
                       % (r["name"], r["stat"], r["value"], r["rank"]))
            if r.get("above"):
                out.append("  1つ上にいるのは %s" % r["above"])
            if r.get("note"):
                out.append("  %s とは（画面に出る・読まない）: %s"
                           % (r["stat"], r["note"]))
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
                             # 用語の意味は**画面にだけ**出す。声で
                             # 説明すると、そこで話が止まる。
                             "note": r.get("note") or "",
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
