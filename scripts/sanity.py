#!/usr/bin/env python3
"""
出す前に、常識で読み直す。

事実の照合(APIの値と一致するか)とは別の目が要る。
照合は「取ってきた値と同じか」しか見ないので、取ってきた値自体が
おかしい日、組み立ての途中で壊れた日は、そのまま通る。

ここでは二段見る。

  一段目　ありえない数字            (機械。API不要)
      打数2で3安打、防御率150、9回で25奪三振。
      野球の規則の上で起こりえない値と、起こりうるが桁が違う値。
      いちばん静かに壊れるのは内部矛盾のほう。
      「安打 > 打数」は範囲をいくら見ても分からない。

  二段目　競技を知っている人の目    (Claude)
      規則には反しないが、読むと引っかかるところ。
      「今季初登板の投手が今季15勝」のような、個々の値は正しくても
      並べると噛み合わない文。ここは機械では書ききれない。

  二段目は投稿を止めない。止めるのは一段目だけ。
  言語模型の違和感は当たることもあれば外れることもあるので、
  それで止めると、正しい日に出せなくなる。
  代わりに実行ページに出して、人が見る。

使い方:
  python3 scripts/sanity.py                     # 一段目だけ
  python3 scripts/sanity.py --general           # 二段目も(要 ANTHROPIC_API_KEY)
  python3 scripts/sanity.py --strict            # ありえない数字があれば異常終了
"""

import argparse
import json
import os
import pathlib
import re
import sys

MODEL = "claude-haiku-4-5-20251001"

NUM = "([0-9]+(?:[.][0-9]+)?)"

# 一試合で起こりうる幅。上限は実際の記録より少し広く取る。
# 狭すぎると、珍しいが本当にあった日を誤って止めてしまう。
GAME_BOUNDS = {
    "打数": (0, 12),
    "安打": (0, 9),
    "本塁打": (0, 4),      # 一試合4本が最多記録
    "打点": (0, 12),       # 一試合12打点が最多記録
    "盗塁": (0, 6),
    "四球": (0, 6),
    "三振": (0, 6),
    "回": (0, 15),         # 延長を含む
    "奪三振": (0, 21),     # 9回20が最多。延長で21
    "失点": (0, 20),
}

# 通算で起こりうる幅。
#
# これが抜けていて、8/21の「今日の1人」が出なかった。
# Zach Netoの通算は443安打・79本塁打・234打点。これを今季の幅
# (270安打・75本塁打・200打点)で見ると3か所で引っかかる。
# この枠は通算成績そのものが主題なので、毎回引っかかっていた。
#
# 上限は歴代記録の少し上に置く。安打4256、本塁打762、打点2297、
# 盗塁1406、勝511、奪三振5714。記録を追い抜く選手が現れる日は、
# その日に上げればよい。
CAREER_BOUNDS = {
    "勝": (0, 600),
    "敗": (0, 400),
    "セーブ": (0, 750),
    "ホールド": (0, 400),
    "防御率": (0, 15),
    "奪三振": (0, 6500),
    "本塁打": (0, 900),
    "打点": (0, 2600),
    "安打": (0, 5000),
    "盗塁": (0, 1600),
    "打率": (0, 0.400),
}

# 一シーズンで起こりうる幅。
SEASON_BOUNDS = {
    "勝": (0, 30),
    "敗": (0, 30),
    "セーブ": (0, 60),
    "ホールド": (0, 50),
    "防御率": (0, 15),
    "奪三振": (0, 400),
    "本塁打": (0, 75),     # 73本が最多記録
    "打点": (0, 200),
    "安打": (0, 270),
    "盗塁": (0, 140),
    "打率": (0, 0.500),
}


def parse_line(line):
    """日本語の成績行から数字を拾う。「2打数2安打　2本塁打」-> {打数:2, 安打:2, 本塁打:2}"""
    out = {}
    # 「N単位」の形。長い単位から先に見る(本塁打を打より先に、奪三振を三振より先に)
    units = sorted(set(GAME_BOUNDS) | set(SEASON_BOUNDS), key=len, reverse=True)
    for unit in units:
        for m in re.finditer(NUM + re.escape(unit), line):
            out.setdefault(unit, float(m.group(1)))
    # 読み上げ原稿では打率を「2割9分1厘」と書く。数字だけ拾うと
    # 打率2.0になり、ありえない値として正常な原稿を止めてしまう。
    # 実際それで大谷の行が引っかかった。先に読み解く。
    m = re.search("打率[ 　]*([0-9]+)割(?:([0-9]+)分)?(?:([0-9]+)厘)?", line)
    if m:
        wari, bu, rin = (int(x or 0) for x in m.groups())
        out["打率"] = wari / 10 + bu / 100 + rin / 1000
        line = line[:m.start()] + line[m.end():]

    # 「防御率2.15」「打率.312」は数字が後ろに来る
    for unit in ("防御率", "打率"):
        if unit in out:
            continue
        m = re.search(re.escape(unit) + "[ 　]*([0-9]*[.][0-9]+|[0-9]+)", line)
        if m:
            out[unit] = float(m.group(1))
    return out


def check_line(name, line):
    """一行ぶんの成績を常識で見る。"""
    bad = []
    if "通算" in line:
        bounds, where = CAREER_BOUNDS, "通算"
    elif "今季" in line or "昨季" in line:
        bounds, where = SEASON_BOUNDS, "今季"
    else:
        bounds, where = GAME_BOUNDS, "一試合"
    season = where != "一試合"
    got = parse_line(line)

    for unit, val in got.items():
        lo, hi = bounds.get(unit, (None, None))
        if lo is None:
            continue
        if not (lo <= val <= hi):
            bad.append("%s: 「%s」の%s%g は%sとしてありえない(%g〜%g)"
                       % (name, line, unit, val, where, lo, hi))

    # 範囲では捕まらない、内部の矛盾。ここが本命。
    if not season:
        ab, h, hr = got.get("打数"), got.get("安打"), got.get("本塁打")
        if ab is not None and h is not None and h > ab:
            bad.append("%s: 「%s」打数%gより安打%gが多い" % (name, line, ab, h))
        if h is not None and hr is not None and hr > h:
            bad.append("%s: 「%s」安打%gより本塁打%gが多い" % (name, line, h, hr))
        ip, k = got.get("回"), got.get("奪三振")
        if ip is not None and k is not None and k > ip * 3 + 2:
            bad.append("%s: 「%s」%g回で%g奪三振は多すぎる" % (name, line, ip, k))

    return bad


def check_stat_files():
    """出す前の成績データを一通り見る。"""
    bad = []
    for path, groups, field in (
        ("data/best_of_day.json", ("players", "pitchers", "everyone"), "headline"),
        ("data/roster_stats.json", ("players",), "line"),
    ):
        try:
            d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        seen = set()
        for grp in groups:
            for r in (d.get(grp) or []):
                line = r.get(field) or ""
                sig = (r.get("name"), line)
                if not line or sig in seen:
                    continue
                seen.add(sig)
                bad += check_line(r.get("name", "?"), line)
    return bad


def check_narration(paths):
    """原稿そのものを見る。

    成績データが正しくても、組み立てで壊れることはある。
    ただし原稿は地の文なので、一試合の話か今季の話かが
    行からは決まらない。「45本塁打」は今季なら普通、
    一試合ならありえない。

    なので原稿には広いほうの幅だけを当てる。
    矛盾の検査(安打>打数)も原稿では見ない——1つの文に
    2人の成績が並ぶことがあり、別人の数字を突き合わせて
    しまう。狭く見て誤って止めるより、確実な分だけ止める。
    """
    loose = {}
    for unit in set(GAME_BOUNDS) | set(SEASON_BOUNDS) | set(CAREER_BOUNDS):
        lo, hi = 0, 0
        for table in (GAME_BOUNDS, SEASON_BOUNDS, CAREER_BOUNDS):
            b = table.get(unit)
            if b:
                lo, hi = min(lo, b[0]), max(hi, b[1])
        loose[unit] = (lo, hi)

    bad = []
    for p in paths:
        try:
            d = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for i, s in enumerate(d.get("segments") or []):
            text = (s.get("text") or "").strip()
            if not text:
                continue
            for unit, val in parse_line(text).items():
                lo, hi = loose.get(unit, (None, None))
                if lo is None or lo <= val <= hi:
                    continue
                bad.append("%s の%d番目: 「%s」の%s%g はありえない(%g〜%g)"
                           % (pathlib.Path(p).name, i + 1,
                              text[:40], unit, val, lo, hi))
    return bad


def check_scores():
    """スコアの桁。20点差の試合はあるにはあるが、まず組み立てを疑う。"""
    bad = []
    recent = sorted(str(p) for p in pathlib.Path("archive").glob("*.json"))[-3:]
    for path in ("notable_games.json",) + tuple(recent):
        try:
            games = json.loads(
                pathlib.Path(path).read_text(encoding="utf-8")).get("games") or []
        except (OSError, json.JSONDecodeError):
            continue
        for g in games:
            s = str(g.get("final_score") or g.get("score") or "")
            m = re.search("([0-9]+)[^0-9]{1,3}([0-9]+)", s)
            if not m:
                continue
            a, b = int(m.group(1)), int(m.group(2))
            soccer = g.get("league") != "MLB"
            hi = 10 if soccer else 30
            if max(a, b) > hi:
                bad.append("%s: %s は%sの得点として大きすぎる"
                           % (g.get("matchup", "?"), s,
                              "サッカー" if soccer else "野球"))
    return bad


PROMPT = """以下は、今日公開する野球/サッカーのショート動画の読み上げ原稿です。
あなたはその競技をよく知っている視聴者です。読んでみて、事実として間違っていそうなところ、噛み合っていないところ、競技を知っている人が聞いて引っかかるところがあれば挙げてください。

・数字が規則の上でありえない
・前後の文が矛盾している(今季初登板なのに今季15勝、など)
・選手と所属球団の対応がおかしい
・言い回しがその競技の言い方と違う

文体の好みや構成の提案は要りません。事実の齟齬だけ。
問題がなければ空の配列を返してください。
JSONだけを返してください。形式:
[{"severity":"high|low","where":"該当箇所の引用","why":"何がおかしいか"}]

--- 原稿 ---
"""


def general(paths, api_key):
    """競技を知っている人が読んで引っかかるところを挙げてもらう。"""
    chunks = []
    for p in paths:
        try:
            d = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for s in (d.get("segments") or []):
            t = (s.get("text") or "").strip()
            if t:
                chunks.append(t)
    if not chunks:
        return []

    try:
        import anthropic
        resp = anthropic.Anthropic(api_key=api_key).messages.create(
            model=MODEL, max_tokens=900,
            messages=[{"role": "user",
                       "content": PROMPT + "\n".join(chunks)[:6000]}])
        txt = "".join(b.text for b in resp.content if b.type == "text").strip()
        m = re.search(r"\[.*\]", txt, re.S)
        return json.loads(m.group(0)) if m else []
    except Exception as e:      # 見えなかっただけ。出すのは止めない
        return [{"severity": "low", "where": "(確認できず)", "why": str(e)[:200]}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--general", action="store_true",
                    help="原稿を通しで読んでもらう(要 ANTHROPIC_API_KEY)")
    ap.add_argument("--narration", nargs="*",
                    default=["public/narration.json",
                             "public/soccer_narration.json"])
    ap.add_argument("--strict", action="store_true",
                    help="ありえない数字があれば異常終了する")
    ap.add_argument("--out", default="data/sanity.json")
    args = ap.parse_args()

    impossible = (check_stat_files() + check_scores()
                  + check_narration(args.narration))
    print("--- ありえない数字 ---")
    for b in impossible:
        print("  NG", b)
    if not impossible:
        print("  なし")

    odd = []
    if args.general:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            odd = general(args.narration, key)
            print("\n--- 読んで引っかかるところ ---")
            for o in odd:
                print("  [%s] %s — %s" % (o.get("severity", "?"),
                                          o.get("where", "")[:60],
                                          o.get("why", "")[:120]))
            if not odd:
                print("  なし")
        else:
            print("\n(ANTHROPIC_API_KEY がないので二段目は飛ばした)")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"impossible": impossible, "odd": odd},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and (impossible or odd):
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## 常識の確認\n\n")
            for b in impossible:
                f.write("- **ありえない数字** %s\n" % b)
            for o in odd:
                f.write("- %s 「%s」 — %s\n"
                        % ("**要確認**" if o.get("severity") == "high" else "参考",
                           o.get("where", ""), o.get("why", "")))

    return 1 if (impossible and args.strict) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
