#!/usr/bin/env python3
"""サッカーの順位争いを、動画1本ぶんの材料にする。

なぜこの枠を作るのか:
  実測（8/11〜9/8、194本）でいちばん強いのは数字が主役の枠。

    成績ランキング   平均411再生 / 登録0.72（千再生あたり）
    現地の報道       272 / 0.15
    明日の注目試合   241 / 0.58
    コメント欄       112 / 0.00
    長編（コメント欄）  2 / 0.00

  MLBには進出争いの枠（postseason）があるが、サッカーには無い。
  10月にMLBのポストシーズンが終わると3月まではサッカーが主になるのに、
  サッカーは「明日の注目試合」1本だけだった。

  そして**順位争いは期間がいちばん長い。**MLBの進出争いは9〜10月の
  2か月だが、サッカーの順位争いは9月から5月まで材料があり続ける。

何を出すか:
  順位表を丸ごと読み上げても、20クラブの羅列は誰も追えない。
  見るのは**線の前後だけ**にする。

    ・CL圏内（4位）の内と外
    ・EL圏内（5位、リーグによって6位）
    ・残留（17位、18クラブなら15位）
    ・昇格（2部）

  線の前後・線をまたぐ差・昨日またいだかは cutline.py が持つ。
  ここは「どの大会のどの線を見るか」と「日本人選手がどこにいるか」。

いつから出すか:
  開幕直後は順位に意味が無い。全クラブが数試合しかしておらず、
  1勝の差が5位ぶん動く。notability_engine が AIに順位を渡す境目と
  同じ SOCCER_TABLE_MIN_MATCHES（5節）で切る。

  **足りない大会は ready を False にして返す。**黙って省くと、
  呼ぶ側は「データが無い」のか「まだ早い」のか区別できない。
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import cutline  # noqa: E402

try:
    from notability_engine import (JP_PLAYERS_SOCCER, SOCCER_LEAGUE_NAME_JP,
                                   SOCCER_TABLE_MIN_MATCHES, club_name_jp)
except ImportError:                                     # pragma: no cover
    JP_PLAYERS_SOCCER, SOCCER_LEAGUE_NAME_JP = [], {}
    SOCCER_TABLE_MIN_MATCHES = 5

    def club_name_jp(name):
        return name


# 動画1本に入れる大会の数。
#
# 5大リーグ全部を入れると1本が長くなり、どのリーグの話をしているのか
# 分からなくなる。日本人選手がいるリーグを先に、多くても4つ。
MAX_COMPETITIONS = 4

# 線の上下に何クラブずつ見せるか。
SPAN = 2

# その線から順位が何つ離れるまで、話として扱うか。
#
# 残留の線を折り返しまで出さないようにしたところ、16位のクラブに
# 「CL圏内まで勝点6」と付いた。勝ち点の差は小さく見えても、
# 間に12クラブいる。**それは順位争いではない。**
# 線をまたぐ可能性が現実にある範囲だけを話にする。
MAX_LINE_GAP = 5

# 残留争いを出し始める節。
#
# 9月に「残留争い」と言っても、まだ38節のうち4節しか終わっていない。
# 数字としては最下位でも、それは順位争いではない。
# 折り返し（19節）を過ぎてから出す。
RELEGATION_FROM = 19


def _jp_by_league() -> dict:
    """リーグごとの、日本人選手と所属クラブ。"""
    out = {}
    for p in JP_PLAYERS_SOCCER:
        code = p.get("league")
        if not code:
            continue
        out.setdefault(code, []).append(
            {"name": p.get("name_jp") or p.get("name_en"),
             "club_jp": p.get("team_jp") or "",
             "match": (p.get("match") or "").lower()})
    return out


def _norm(name: str) -> str:
    """クラブ名の突き合わせ用。記号と空白を落として小文字に。

    名簿の match は "crystalpalace" のような詰めた形。
    APIは "Crystal Palace FC" を返す。
    """
    low = (name or "").lower()
    for word in (" fc", "fc ", " afc", "afc ", " cf", " ac ", " as ",
                 " ss ", " us ", " sc ", " club", " calcio"):
        low = low.replace(word, " ")
    return "".join(ch for ch in low if ch.isalnum())


def phrase(near: dict) -> str:
    """線までの差を、そのまま読める言い方にする。

    **画面と読み上げで別々に組み立てない。**呼び名と数字が
    食い違うと、どちらが本当なのか見ている側には確かめようがない。
    成績の回で同じことを一度やっている（順位を別々に並べ替えて
    「1位 34点、3位 44点」と表示した事故）。

    差0は「まで勝点0」と書くと意味が通らない。勝ち点では並んでいて
    得失点差で下、という状態なので、そう言う。
    """
    if not near or not near.get("label"):
        return ""
    label, diff = near["label"], near.get("diff")
    if diff is None:
        return ""
    if near.get("side") == "inside":
        if diff == 0:
            return f"{label}だが、すぐ下と勝点で並んでいる"
        return f"{label}。落ちるまで勝点{diff}"
    if diff == 0:
        return f"{label}と勝点で並んでいる"
    return f"{label}まで勝点{diff}"


def jp_in_table(rows: list, players: list, code: str = "",
                played: int = 99) -> list:
    """順位表のどこに日本人選手がいるか。

    **順位も一緒に返す。**「リバプールに遠藤航が所属」だけでは
    順位争いの話にならない。「6位のリバプールに遠藤航」と言えて
    はじめて、その日の順位表の話になる。

    さらに、そのクラブから各線までの勝ち点差も付ける。
    線の前後に日本人選手がいない日でも、「9位のレアル・ソシエダは
    CL圏内まで勝ち点5」と言えば順位争いの話のまま名前を出せる。
    """
    out = []
    for row in rows:
        key = _norm(row.get("team", ""))
        if not key:
            continue
        for p in players:
            m = p.get("match") or ""
            if not m or (m not in key and key not in m):
                continue
            near = []
            for at, label in cutline.lines_for(code):
                # 残留は折り返しを過ぎてから。build_lines と同じ境目。
                # 3節で「残留から落ちるまで勝点1」と言っても、
                # それはまだ順位争いではない。
                if label == "残留" and played < RELEGATION_FROM:
                    continue
                d = cutline.distance_to(rows, at, row.get("team", ""))
                if not d:
                    continue
                # 線から遠すぎるものは話にしない。
                if abs((d.get("position") or 0) - at) > MAX_LINE_GAP:
                    continue
                near.append({**d, "label": label})
            out.append({"name": p["name"],
                        "club_jp": p.get("club_jp") or club_name_jp(
                            row.get("team", "")),
                        "position": row.get("position"),
                        "points": row.get("points"),
                        # 近い線から順に。いちばん近い線がその選手の話になる。
                        "lines": [{**x, "text": phrase(x)}
                                  for x in sorted(near,
                                                  key=lambda y: y["diff"])]})
    return out


def _jp_names(rows: list, players: list) -> set:
    """その並びに含まれるクラブの、日本人選手の名前。"""
    names = set()
    for row in rows:
        key = _norm(row.get("team", ""))
        for p in players:
            m = p.get("match") or ""
            if m and (m in key or key in m):
                names.add(p["name"])
    return names


def _row_out(row: dict, players: list) -> dict:
    """画面に出す1クラブぶん。クラブ名は日本語表記にする。"""
    jp = sorted(_jp_names([row], players))
    return {"position": row.get("position"),
            "team": club_name_jp(row.get("team", "")),
            "team_en": row.get("team", ""),
            "played": row.get("played"),
            "points": row.get("points"),
            "gf": row.get("gf"),
            "ga": row.get("ga"),
            "jp": jp}


def build_lines(rows: list, code: str, played: int, players: list,
                before: list = None) -> list:
    """その大会の、見る価値がある線だけを返す。"""
    out = []
    for at, label in cutline.lines_for(code):
        if at >= len(rows):
            continue
        # 残留争いは折り返しを過ぎてから。
        if label == "残留" and played < RELEGATION_FROM:
            continue
        around = cutline.around(rows, at, span=SPAN)
        gap = cutline.gap(rows, at)
        if not gap:
            continue
        moved = cutline.moved(rows, before or [], at) if before else {}
        out.append({
            "at": at,
            "label": label,
            "inside": [_row_out(r, players) for r in around["inside"]],
            "outside": [_row_out(r, players) for r in around["outside"]],
            "diff": gap.get("diff"),
            "moved": moved,
            # その線のまわりに日本人選手がいるか。
            # **いる線を先に出す。**題にも名前を出したい。
            "jp": sorted(_jp_names(around["inside"] + around["outside"],
                                   players)),
        })
    return out


def build(preview: dict, before: dict = None) -> dict:
    """順位争いの材料。preview は data/soccer_preview.json の中身。

    before は前日の同じファイル。渡せば「昨日から線をまたいだクラブ」
    が入る。無い日は moved が空になる（「変化なし」ではなく
    「分からない」なので、cutline 側で空を返す）。
    """
    jp_map = _jp_by_league()
    prev_tables = {}
    for c in (before or {}).get("competitions") or []:
        if c.get("code"):
            prev_tables[c["code"]] = c.get("table") or []

    comps = []
    for c in preview.get("competitions") or []:
        code = c.get("code") or ""
        rows = c.get("table") or []
        players = jp_map.get(code, [])
        played = max((r.get("played") or 0) for r in rows) if rows else 0
        ready = bool(rows) and played >= SOCCER_TABLE_MIN_MATCHES
        entry = {
            "code": code,
            "name_jp": (c.get("name_jp")
                        or SOCCER_LEAGUE_NAME_JP.get(code) or code),
            "played": played,
            "clubs": len(rows),
            "ready": ready,
            "jp": (jp_in_table(rows, players, code, played)
                   if rows else []),
            "lines": [],
        }
        if ready:
            entry["lines"] = build_lines(rows, code, played, players,
                                         prev_tables.get(code))
        comps.append(entry)

    # 出す順。日本人選手がいる大会を先に、次に節が進んでいる大会。
    #
    # 実測では題に日本人選手の名前がある動画が平均395再生、
    # 無い動画が192再生。**先頭に来た大会が題になる**ので、
    # そこに名前があるかで倍ちがう。
    ready = [c for c in comps if c["ready"] and c["lines"]]
    ready.sort(key=lambda c: (-(1 if c["jp"] else 0), -c["played"]))

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_at": preview.get("generated_at"),
        "competitions": comps,
        # 動画に使うぶんだけを、使う順に。
        "picked": [c["code"] for c in ready[:MAX_COMPETITIONS]],
    }


def summary(data: dict) -> str:
    """実行ページに出す1本ぶんの中身。"""
    lines = []
    picked = data.get("picked") or []
    lines.append("## サッカーの順位争い")
    lines.append("")
    if not picked:
        lines.append("出せる大会がありません。"
                     f"（{SOCCER_TABLE_MIN_MATCHES}節未満の大会は出しません）")
    for c in data.get("competitions") or []:
        mark = "◯" if c["code"] in picked else "－"
        note = "" if c["ready"] else f"（{c['played']}節なのでまだ出しません）"
        lines.append(f"{mark} **{c['name_jp']}** {c['played']}節"
                     f" {c['clubs']}クラブ{note}")
        for ln in c.get("lines") or []:
            inside = c and ln["inside"][-1] if ln["inside"] else None
            outside = ln["outside"][0] if ln["outside"] else None
            if inside and outside:
                lines.append(
                    f"   - {ln['label']}（{ln['at']}位まで）: "
                    f"{inside['position']}位 {inside['team']} 勝点"
                    f"{inside['points']} ／ {outside['position']}位 "
                    f"{outside['team']} 勝点{outside['points']}"
                    f" → 差{ln['diff']}")
            mv = ln.get("moved") or {}
            if mv.get("in") or mv.get("out"):
                lines.append(f"     昨日から: 入 {'・'.join(mv.get('in') or [])}"
                             f" / 出 {'・'.join(mv.get('out') or [])}")
        for x in (c.get("jp") or [])[:6]:
            near = (x.get("lines") or [{}])[0]
            note = near.get("text") or ""
            lines.append(f"   - {x['position']}位 {x['club_jp']}"
                         f" {x['name']} 勝点{x['points']}"
                         + (f"（{note}）" if note else ""))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", default="data/soccer_preview.json")
    ap.add_argument("--before", default="",
                    help="前日の soccer_preview.json（昨日の動きを出す）")
    ap.add_argument("--out", default="data/soccer_race.json")
    args = ap.parse_args()

    preview = json.loads(pathlib.Path(args.preview).read_text(
        encoding="utf-8"))
    before = {}
    if args.before and pathlib.Path(args.before).exists():
        before = json.loads(pathlib.Path(args.before).read_text(
            encoding="utf-8"))

    data = build(preview, before)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(summary(data))
    print(f"\n[done] {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
