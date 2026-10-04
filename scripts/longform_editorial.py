"""公開前の編集検査。数字の照合とは分け、APIを追加しない。"""
import re
from decimal import Decimal, InvalidOperation


def _distance_issues(text, row):
    """明記した順位間の近さだけを、同じ指標の表示値で照合する。"""
    if text.rstrip().endswith(("？", "?")):
        return []
    rank = re.search(r"中([0-9]+)位", row.get("rank", ""))
    leader, below = row.get("leader") or {}, row.get("below") or {}
    if not rank or not leader.get("shown") or not below.get("shown"):
        return []
    values = [row.get("value", ""), leader["shown"], below["shown"]]
    if any(not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%?", str(v)) for v in values):
        return []
    if len({str(v).endswith("%") for v in values}) != 1:
        return []
    try:
        own, first, lower = [Decimal(str(v).rstrip("%")) for v in values]
    except InvalidOperation:
        return []
    distances = {1: abs(own-first), int(rank[1])+1: abs(own-lower)}
    if int(rank[1]) == 1:
        return []  # 首位本人と2位だけでは、二つの比較先を定義できない。
    errors = []
    for match in re.finditer(r"([0-9]+)位(?:寄り|に近い)", text):
        at = int(match[1])
        if at in distances and distances[at] >= max(distances.values()):
            errors.append("比較先への近さが材料の差と一致しません")
    for match in re.finditer(r"([0-9]+)位との差より[、\s]*([0-9]+)位との差(?:の方)?が(?:小さい|大きい)", text):
        a, b = int(match[1]), int(match[2])
        if a in distances and b in distances:
            correct = distances[b] < distances[a] if match[0].endswith("小さい") else distances[b] > distances[a]
            if not correct:
                errors.append("順位間の差の大小が材料と一致しません")
    return errors

_PRODUCTION = re.compile(
    r"(?:材料|データ|情報).{0,12}(?:無い|ない|渡され|渡って|出ていない|出てない)|"
    r"(?:何とも|なんとも)言えない|分からない|わからない")
_RANK = re.compile(r"(?:[0-9０-９]+|[一二三四五六七八九十]+)位")
_QUALIFIED = re.compile(r"規定(?:打席|投球回)?(?:に)?(?:到達|達した|達して|を満た)")
_FEW_K = re.compile(r"少ない|少なかった|低い|低かった|多く(?:は)?ない|多い(?:方)?ではない")
_MANY_K = re.compile(r"多い(?!方ではない)|多かった|高い|高かった|少なく(?:は)?ない")
_GOOD = re.compile(r"(?:両方|三振の方でも).{0,18}(?:いい|良い|良好)")
_NO_RUNNERS = re.compile(r"(?:出した)?走者(?:も|が|は|を)?(?:四球も)?(?:一人も|1人も)?(?:無し|なし|無い|ない|ゼロ|0|出していない|出さなかった)")


def _k_claims(text):
    # 「評価が低い」と「三振率が低い」は別。評価の語だけを除く。
    text = re.sub(r"(?:Savant(?:の)?)?評価(?:は|が|だと|では)?(?:低い|高い|下位|上位)", "", text)
    # 二重否定を先に拾い、反対の表現への部分一致を避ける。
    fewer = bool(_FEW_K.search(text))
    more = bool(_MANY_K.search(_FEW_K.sub("", text)))
    return fewer, more


def _k_directions(text):
    few, many = False, False
    for clause in re.split(r"[。、]", text):
        for match in re.finditer(r"(?:奪)?三振(?:率)?", clause):
            # 他指標の「低い打率」などへ意味を流さない。
            claim = clause[match.end():match.end()+18]
            claim = re.split(r"打率|四球率|バレル率|OPS|WHIP|防御率", claim)[0]
            lo, hi = _k_claims(claim)
            few, many = few or lo, many or hi
    return few, many


def material(m):
    """生成と再検査へ渡す根拠。モデルが書いた説明から根拠を逆算しない。"""
    players = m.get("players") or []
    return {"players": [{"name": p["name"], "type": p["type"]} for p in players],
            "daily_player_count": len(players), "rare": m.get("rare") or [],
            "percentiles": [{"name": players[0]["name"], "metric_key": t["metric_key"],
                             "kind": t["statcast_kind"], "percentile": t["percentile"]}
                            for t in m.get("trends", []) if players and "percentile" in t
                            and "metric_key" in t and "statcast_kind" in t]}


def check(dialogue):
    if dialogue.get("mode") != "numbers":
        return []
    material = dialogue.get("material") or {}
    subjects = material.get("rare") or []
    panels = dialogue.get("panels") or {}
    bad, introduced = [], set()
    known_names = {r.get("name") for r in material.get("players", []) + subjects if r.get("name")}
    active, recent_k = None, None
    for i, seg in enumerate(dialogue.get("segments") or [], 1):
        text = seg.get("text") or ""
        if _PRODUCTION.search(text):
            bad.append(f"{i}行目: 材料の不足・制作上の都合を台詞にしています")
        if seg.get("panel") and seg["panel"] != active:
            recent_k = None
        active = seg.get("panel") or active
        owner = (panels.get(active) or {}).get("name")
        other_subject = any(name in text and name != owner for name in known_names)
        if other_subject or "別の選手" in text:
            recent_k = None
        k_sources = [r for r in material.get("percentiles", [])
                     if r.get("metric_key") == "k_percent"
                     and r.get("kind") in ("batter", "pitcher")
                     and type(r.get("percentile")) in (int, float)
                     and r.get("name")
                     and (r["name"] in text or (r.get("name") == owner and not other_subject))]
        for row in k_sources:
            label = "奪三振率" if row["kind"] == "pitcher" else "三振率"
            if label in text and not (row["kind"] == "batter" and "奪三振率" in text):
                recent_k = row
        daily = bool(re.search(r"今日|きょう|この日|当日", text)) and "今季" not in text
        if recent_k and not daily and not text.rstrip().endswith(("？", "?")) and ("三振" in text or _GOOD.search(text)):
            # 指標以外の打球などの評価を、三振の主張と混ぜない。
            few, many = _k_directions(text)
            pct, kind = recent_k["percentile"], recent_k["kind"]
            if pct <= 10 or pct >= 90:
                expected_many = (pct >= 90) if kind == "pitcher" else (pct <= 10)
                if (few if expected_many else many) or (pct <= 10 and _GOOD.search(text)):
                    bad.append(f"{i}行目: Savantの三振指標の評価と値の向きが逆です")
        if str(active).startswith("jp") and any(
                p.get("name") == owner and str(p.get("type", "")).startswith("p")
                and p.get("no_baserunners") is not True for p in material.get("players", [])):
            if _NO_RUNNERS.search(text):
                bad.append(f"{i}行目: 被安打・四球だけで走者なしと断定しています")
        target = (panels.get(active) or {}).get("name") if str(active).startswith("rare") else None
        for row in subjects:
            if row.get("name") == target and not other_subject:
                bad.extend(f"{i}行目: {issue}" for issue in _distance_issues(text, row))
        match = _RANK.search(text)
        before = text[:match.start()] if match else text
        if subjects and _QUALIFIED.search(text) and (
                str(active).startswith("rare") or match):
            bad.append(f"{i}行目: 指標ランキングの独自対象条件を規定到達者と呼んでいます")
        # 名前と値の両方を先に示す。数字だけ・比較相手だけの導入は不可。
        for row in subjects:
            if row.get("name") and row.get("value") and row["name"] in before and row["value"] in before:
                introduced.add(row["name"])
        if match and subjects:
            needed = [r for r in subjects if r.get("name") == target or r.get("name") in text]
            orphan = re.match(r"^(?:そうね[、。]?|でも[、。]?)?\s*(?:[0-9０-９]+|[一二三四五六七八九十]+)位", text)
            if (needed and any(r["name"] not in introduced for r in needed)) or (
                    not needed and orphan and not introduced):
                bad.append(f"{i}行目: 順位より先に対象選手の名前と数字を紹介していません")
    if material.get("daily_player_count") == 0 and "成績" in (dialogue.get("title") or ""):
        bad.append("出場者0名の日の題に、その日の成績を使っています")
    return bad
