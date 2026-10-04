"""公開前の編集検査。数字の照合とは分け、APIを追加しない。"""
import re

_PRODUCTION = re.compile(
    r"(?:材料|データ|情報).{0,12}(?:無い|ない|渡され|渡って|出ていない|出てない)|"
    r"(?:何とも|なんとも)言えない|分からない|わからない")
_RANK = re.compile(r"(?:[0-9０-９]+|[一二三四五六七八九十]+)位")
_QUALIFIED = re.compile(r"規定(?:打席|投球回)?(?:に)?(?:到達|達した|達して|を満た)")


def check(dialogue):
    if dialogue.get("mode") != "numbers":
        return []
    material = dialogue.get("material") or {}
    subjects = material.get("rare") or []
    panels = dialogue.get("panels") or {}
    bad, introduced = [], set()
    active = None
    for i, seg in enumerate(dialogue.get("segments") or [], 1):
        text = seg.get("text") or ""
        if _PRODUCTION.search(text):
            bad.append(f"{i}行目: 材料の不足・制作上の都合を台詞にしています")
        active = seg.get("panel") or active
        target = (panels.get(active) or {}).get("name") if str(active).startswith("rare") else None
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
            if (needed and any(r["name"] not in introduced for r in needed)) or (
                    not needed and not introduced):
                bad.append(f"{i}行目: 順位より先に対象選手の名前と数字を紹介していません")
    if material.get("daily_player_count") == 0 and "成績" in (dialogue.get("title") or ""):
        bad.append("出場者0名の日の題に、その日の成績を使っています")
    return bad
