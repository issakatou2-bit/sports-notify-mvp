"""四国めたんの台詞の語尾。散歩 sanpo/gobi.py の BAD / FIX 方式を参照。"""
import os
import re


GUIDANCE = (
    "四国めたんは柔らかい口調で、語尾は「のよ」「よ」「わ」「わね」「かしら」「しましょう」。"
    "「です」「ます」「でした」「ました」「でしょう」「ください」「だよ」「だね」「しよう」は使わない。"
    "ずんだもんは「のだ」口調で、視聴者がその場で感じる疑問・驚き・突っ込みを先に言う。"
    "めたんは確認済みの数字で答え、ずんだもんは数字を聞いて自分の予想を問いとして返せる。"
    "話をつなぐだけの「見えてきたのだ」や答えの言い直しは使わない。"
    "意外な表情を指定するときは、次か次の次の台詞で理由を分かるようにする。"
)
SHORT_OUTRO = '高評価と登録、よろしくね。'
POLITE_SHORT_OUTRO = '高評価と登録、お願いします。'
END = r"(?=[ \t]*(?:[。！？!?…\n]|$))"
BAD = re.compile(
    r"(?:です(?:ね|よ|か)?|ます(?:ね|よ|か)?|でした(?:ね|よ|か)?|ました(?:ね|よ|か)?"
    r"|(?<!ま)でしょう(?:か|ね)?|ください(?:ね|よ)?|だよね?|だね|しよう(?:か|ね)?)" + END
)
FIX = tuple((re.compile(pattern + END), replacement) for pattern, replacement in (
    (r"どうでしょうか?", "どうかしら"),
    (r"でしょう(?:か|ね)?", "かしら"),
    (r"ていました", "ていたわ"),
    (r"ています", "ているわ"),
    (r"ていましたね", "ていたわね"),
    (r"てください(?:ね)?", "てね"),
    (r"上回ります", "上回るわ"),
    (r"上回りました", "上回ったわ"),
    (r"勝ちました", "勝ったわ"),
    (r"敗れました", "敗れたわ"),
    (r"引き分けました", "引き分けたわ"),
    (r"話しました", "話したわ"),
    (r"決めました", "決めたわ"),
    (r"認められました", "認められたわ"),
    (r"しました", "したわ"),
    (r"紹介します", "紹介するわ"),
    (r"お伝えします", "お伝えするわ"),
    (r"対戦します", "対戦するわ"),
    (r"見ていきます", "見ていくわ"),
    (r"毎日追います", "毎日追っていくわ"),
    (r"振り返ります", "振り返るわ"),
    (r"並べます", "並べるわ"),
    (r"見ます", "見るわ"),
    (r"決まります", "決まるわ"),
    (r"勝ち上がります", "勝ち上がるわ"),
    (r"数えません", "数えないわ"),
    (r"出しません", "出さないわ"),
    (r"はしません", "はしないわ"),
    (r"追いつきました", "追いついたわ"),
    (r"勝ち越しました", "勝ち越したわ"),
    (r"守り切りました", "守り切ったわ"),
    (r"返しました", "返したわ"),
    (r"加えました", "加えたわ"),
    (r"終えました", "終えたわ"),
    (r"挙げました", "挙げたわ"),
    (r"始まります", "始まるわ"),
    (r"並びます", "並ぶわ"),
    (r"立ちます", "立つわ"),
    (r"がいます", "がいるわ"),
    # 置き換え後の文に別の規則が掛からないよう、「だよ」系を「です」系より前に置く（まだです→まだよ→まよ を防ぐ）。
    (r"なんだよ", "なのよ"),
    (r"んだよ", "のよ"),
    (r"ん(?:だよね|だね)", "のね"),
    (r"だよね|だね", "ね"),
    (r"だよ", "よ"),
    (r"なんです(?:ね|よ)?", "なのよ"),
    (r"残留争いです", "残留争いなのよ"),
    (r"なのです(?:ね|よ)?", "なのよ"),
    (r"のです(?:ね|よ)?", "のよ"),
    (r"でした(?:ね|よ)?", "だったわ"),
    (r"ですね", "ね"),
    (r"ですか", "かしら"),
    (r"です(?:よ)?", "よ"),
    (r"しよう(か?)", r"しましょう\1"),
))


def _parts(text):
    """引用を保持し、引用の外だけを検査・修正する。入れ子も扱う。"""
    depth = start = 0
    for i, char in enumerate(text):
        if char == "「":
            if depth == 0:
                yield False, text[start:i]
                start = i
            depth += 1
        elif char == "」" and depth:
            depth -= 1
            if depth == 0:
                yield True, text[start:i + 1]
                start = i + 1
    yield bool(depth), text[start:]


def problems(text):
    chunks = list(_parts(text))
    return [
        match.group()
        for index, (quoted, chunk) in enumerate(chunks)
        if not quoted
        for match in BAD.finditer(chunk)
        if index == len(chunks) - 1 or chunk[match.end():].strip()
    ]


def fix(text):
    chunks = list(_parts(text))
    out = []
    for index, (quoted, chunk) in enumerate(chunks):
        if quoted:
            out.append(chunk)
            continue
        # 引用直前を文末として扱わない。
        suffix = "" if index == len(chunks) - 1 else "「"
        chunk += suffix
        for pattern, replacement in FIX:
            chunk = pattern.sub(replacement, chunk)
        out.append(chunk[:-1] if suffix else chunk)
    return "".join(out)


def _literal_quote(segment):
    """括弧を外して読む形式でも、材料と同一の発言を保つ。"""
    marks = "。！!、."
    body = (segment.get("text") or "").strip().rstrip(marks)
    return any(row.get("read") and not row.get("fact")
               and body == (row.get("said") or "").strip().rstrip(marks)
               for row in (segment.get("meta") or {}).get("quote_rows", []))


def metan_enabled(segments):
    """ソロの雨衣では進行役キーの2を使うため、口調を変えない。"""
    return os.getenv('COLLESPO_SOLO_HOST') != 'ui' or any(
        s.get('speaker') not in (2, '2') or (s.get('meta') or {}).get('duo') for s in segments)


def check(segments):
    for i, segment in enumerate(segments, 1):
        if segment.get("speaker") not in (2, "2") or segment.get("voice_host") == "ui" or _literal_quote(segment):
            continue
        for ending in problems(segment.get("text") or ""):
            yield i, ending


def revise(segments):
    for segment in segments:
        if segment.get("speaker") in (2, "2") and segment.get("text") and not _literal_quote(segment):
            revised = fix(segment["text"])
            units = segment.get("caption_units")
            if units and revised != segment["text"]:
                new_units = [fix(unit) for unit in units]
                if "".join(new_units) != revised:
                    continue
                segment["caption_units"] = new_units
            segment["text"] = revised
