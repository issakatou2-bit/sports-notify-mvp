"""既存の報道原稿と同じ見出し・記者の言葉を、出典つきの引用札へ。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import comment_render as cr
import review_render_v3 as r3


def selected(seg, reporters):
    import generate_morning_short as g
    import local_reporters as lr
    kind, meta = seg["kind"], seg.get("meta") or {}
    if kind in {"intro", "headlines"}:
        rows = reporters.get("headlines") or []
        picked = ([meta["used_headline"]] if meta.get("used_headline") is not None else []) if kind == "intro" else meta.get("picked", [])
        if any(type(i) is not int or not 0 <= i < len(rows) for i in picked):
            raise ValueError("報道の見出し番号が材料と合いません")
        return [(rows[i], rows[i].get("jp") or rows[i].get("title", "")) for i in picked]
    if kind == "reporters":
        out = []
        for row in reporters.get("posts") or []:
            body = g.clip_sentences(lr.baseball_jp(row.get("jp") or "") or row.get("text", ""))
            if body:
                out.append((row, body))
            if len(out) >= g.REPORTERS_SHOWN:
                break
        return out
    return []


def bubbles(seg, reporters):
    if 'quote_rows' in (seg.get('meta') or {}):
        rows=seg['meta']['quote_rows']
        allowed={body for _,body in selected({'kind':'reporters'},reporters)}
        allowed.update(h.get('jp') or h.get('title','') for h in reporters.get('headlines',[]))
        if any(not v.get('fact') and v['said'] not in allowed for v in rows):
            raise ValueError('引用区間の報道が原材料にありません')
        return rows
    result = []
    for row, body in selected(seg, reporters):
        if body not in seg["text"]:
            raise ValueError("引用札の本文が報道の読み上げと合いません")
        who = (" / ".join(x for x in [row.get("outlet"), row.get("author")] if x)
               if seg["kind"] == "reporters" else row.get("source")) or "現地メディア"
        result.append({"said": body, "who": who, "mark": cr.pick_mark(body)})
    if not result:
        result = [{"said": seg["text"], "who": "コレスポ" if seg["kind"] == "outro" else "概要", "fact": True}]
    return result


def team_id(seg, reporters):
    import notability_engine as ne
    rows = selected(seg, reporters)
    found = set()
    for row, body in rows:
        for tid, name in ne.MLB_TEAM_NAME_JP.items():
            if name in body or row.get("team") == ne.MLB_TEAM_NAME_EN.get(tid):
                found.add(int(tid))
    # 複数球団が同じ画面にあれば中立色。選手の名前だけで所属を推測しない。
    return next(iter(found)) if len(found) == 1 else None


def frame(t, seg, reporters, duration):
    rows = cr.reading_times(bubbles(seg, reporters), seg["text"], duration)
    end = seg["kind"] == "outro"
    return cr.unified_comments(t, rows, None, "", title="コレスポ" if end else "現地の報道",
                       live="" if end else "報道からの引用", backdrop=r3.background,
                       source_lines=("音声：VOICEVOX:四国めたん",) if end else ("引用：各札の報道元（訳：コレスポ）","コレスポの見解ではありません"))


def cues(seg, reporters, duration):
    if seg["kind"] == "intro":
        return r3.cues("intro", {"v3": {"big": str(len(reporters.get("headlines") or [])), "tag": seg["text"]}})
    return cr.unified_cues(cr.reading_times(bubbles(seg, reporters), seg["text"], duration))
