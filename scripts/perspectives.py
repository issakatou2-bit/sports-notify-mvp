#!/usr/bin/env python3
"""
1つの試合を、いくつかの角度から読む。

なぜ要るのか:
  これまで注目理由は、規則に重みを付けて足した点数と、その根拠の文
  だった。正しいが、出てくるのは「◯◯が所属」「連勝中」のような
  1行の事実で、なぜ今日その試合なのかまでは届いていない。

  同じ材料でも、問いを変えれば別のことが見える。
    順位で見れば     首位攻防なのか、消化試合なのか
    勢いで見れば     直近10試合でどちらが上向きか
    投手で見れば     どういう質の投げ合いになるか
    球場で見れば     点の入りやすい場所か
  これを並べると「文脈で語る」に近づく。

  肝心なのは、**視点どうしが食い違うとき**。
    「順位では首位攻防。ただし直近10試合ではドジャースが3勝7敗」
  この食い違いこそ、その日その試合を見る理由になる。解説者が
  やっているのもこれで、こちらは持っている数字から出せる。

やらないこと:
  人格を名乗らせない。「解説員はこう見る」とは書かない。
  ここに出るのは全部、取得済みの数字を言い換えたものだけで、
  評価も予想もしない。視点とは問いの立て方であって、意見ではない。

  数字が無い視点は、黙って出さない。埋めるために推測しない。
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# 直近10試合を「上向き/下向き」と見なす境目。
# 7勝3敗以上を上向き、3勝7敗以下を下向きとする。5割前後は触れない。
HOT_WINS = 7
COLD_WINS = 3

# 首位攻防と見なすゲーム差。ここを広げると毎日どこかが該当してしまう。
CLOSE_GB = 3.0


def _ten(s):
    """直近10試合の "7-3" を (勝, 負) にする。読めなければ None。"""
    raw = (s or {}).get("last_ten")
    if not raw or "-" not in str(raw):
        return None
    try:
        w, l = str(raw).split("-")[:2]
        return int(w), int(l)
    except ValueError:
        return None


def _is_soccer(g: dict) -> bool:
    try:
        from notability_engine import is_soccer_league
        return bool(is_soccer_league(g.get("league")))
    except Exception:                            # noqa: BLE001
        return False


def _gap(g: dict, s: dict) -> tuple:
    """首位との差を、その競技の言い方で。(数, 単位) を返す。

    サッカーの Standing には points_back(勝ち点差)が入っていて、
    games_back はそれを3で割った互換用の数字でしかない。
    エンジン側にも「『ゲーム差』は野球の概念で、サッカーの画面に
    そのまま出すと嘘になる」と書いてある。

    実際そう出た。「シュツットガルトが地区4位、バイエルンが1位。
    その差2.0ゲームです」——サッカーに地区もゲーム差も無い。
    書いた時点で、その注意書きは読まれていなかった。
    """
    if _is_soccer(g) and s.get("points_back") is not None:
        return s["points_back"], "勝ち点"
    return s.get("games_back"), "ゲーム"


def _place(g: dict) -> str:
    """順位の呼び方。野球は地区、サッカーはリーグ。"""
    return "リーグ" if _is_soccer(g) else "地区"


def _diff_words(diff: float, unit: str) -> str:
    """差の言い方。単位を後ろに付けるだけだと日本語が崩れる。

    「その差6勝ち点です」は言わない。勝ち点差は「勝ち点差6」、
    ゲーム差は「1.5ゲーム差」と、順番が逆になる。
    """
    if unit == "勝ち点":
        return f"勝ち点差{diff:.0f}"
    return f"{diff:.1f}ゲーム差"


def lens_standings(g: dict) -> str:
    """順位の目。いまどこにいるか。"""
    h, a = g.get("home_standing") or {}, g.get("away_standing") or {}
    hn, an = g.get("home_team_name", ""), g.get("away_team_name", "")
    if not (h.get("rank") and a.get("rank")):
        return ""
    (hg, unit), (ag, _) = _gap(g, h), _gap(g, a)
    if hg is None or ag is None:
        return ""
    where = _place(g)
    near = CLOSE_GB * (3 if unit == "勝ち点" else 1)
    if g.get("same_division") and max(hg, ag) <= near:
        return (f"{an}が{where}{a['rank']}位、{hn}が{h['rank']}位。"
                f"{_diff_words(abs(hg - ag), unit)}です。")
    lead = (an, a, ag) if ag < hg else (hn, h, hg)
    trail = (hn, h, hg) if ag < hg else (an, a, ag)
    diff = trail[2] - lead[2]
    if diff >= (24 if unit == "勝ち点" else 8):
        return (f"{lead[0]}が{where}{lead[1]['rank']}位、"
                f"{trail[0]}は{_diff_words(diff, unit)}の"
                f"{trail[1]['rank']}位。順位は離れています。")
    return (f"{lead[0]}が{where}{lead[1]['rank']}位、"
            f"{trail[0]}が{trail[1]['rank']}位。"
            f"{_diff_words(diff, unit)}です。")


def lens_form(g: dict) -> str:
    """勢いの目。順位ではなく、直近どうか。"""
    out = []
    for side in ("away", "home"):
        s = g.get(f"{side}_standing") or {}
        name = g.get(f"{side}_team_name", "")
        t = _ten(s)
        if t:
            w, l = t
            if w >= HOT_WINS:
                out.append(f"{name}は直近10試合で{w}勝{l}敗と上向き")
            elif w <= COLD_WINS:
                out.append(f"{name}は直近10試合で{w}勝{l}敗と苦しい")
            continue
        st = s.get("streak")
        if isinstance(st, int) and abs(st) >= 3:
            out.append(f"{name}は{abs(st)}{'連勝' if st > 0 else '連敗'}中")
    return "、".join(out) + "。" if out else ""


def lens_pitching(g: dict) -> str:
    """投手の目。どういう投げ合いになるか。"""
    hp, ap = g.get("home_probable") or {}, g.get("away_probable") or {}
    pair = [(p.get("name"), p.get("era")) for p in (ap, hp)
            if p.get("name") and p.get("era") is not None]
    if len(pair) < 2:
        return ""
    (an, ae), (hn, he) = pair
    # 防御率は必ず小数2桁。3.8 と 3.80 では、野球の数字として読めない。
    a2, h2 = f"{float(ae):.2f}", f"{float(he):.2f}"
    if min(ae, he) < 3.00 and max(ae, he) < 4.00:
        return f"先発は{an}が防御率{a2}、{hn}が{h2}。投手戦になりそうな数字です。"
    return f"先発は{an}が防御率{a2}、{hn}が{h2}です。"


def lens_venue(g: dict) -> str:
    """球場の目。点が入りやすい場所か。"""
    note = g.get("venue_runs_note") or ""
    return note + "。" if note else ""


def lens_series(g: dict) -> str:
    """連戦の目。このカードの何試合目か。"""
    s = g.get("series_context") or {}
    n, total = s.get("series_game_number"), s.get("games_in_series")
    if not (n and total):
        return ""
    hw, aw = s.get("home_wins_in_stretch"), s.get("away_wins_in_stretch")
    base = f"{total}連戦の{n}試合目"
    if n > 1 and hw is not None and aw is not None and (hw or aw):
        lead = (g.get("home_team_name") if hw > aw
                else g.get("away_team_name") if aw > hw else "")
        if lead:
            return f"{base}。ここまで{lead}が{max(hw, aw)}勝。"
        return f"{base}。ここまで{hw}勝{aw}敗の五分。"
    return base + "。"


LENSES = (
    ("順位", lens_standings),
    ("勢い", lens_form),
    ("先発", lens_pitching),
    ("連戦", lens_series),
    ("球場", lens_venue),
)


def read(g: dict, limit: int = 3) -> list:
    """その試合を、数字が取れた角度からだけ読む。

    返すのは [(見出し, 文), ...]。数字が無い角度は入らない。
    多くても3つに絞る。全部並べると読み上げが長くなり、
    「注目理由」ではなく資料の朗読になる。
    """
    out = []
    for label, fn in LENSES:
        try:
            text = fn(g)
        except Exception:                        # noqa: BLE001
            text = ""
        if text:
            out.append((label, text))
    return out[:limit]


def tension(g: dict) -> str:
    """視点どうしが食い違っているとき、それを一言で。

    順位が上のチームが直近で負け越している、という形。
    ここがいちばん「見る理由」になる。無ければ空を返す。
    """
    h, a = g.get("home_standing") or {}, g.get("away_standing") or {}
    if not (h.get("games_back") is not None and a.get("games_back") is not None):
        return ""
    if h["games_back"] == a["games_back"]:
        return ""
    up = (g.get("away_team_name"), a) if a["games_back"] < h["games_back"] \
        else (g.get("home_team_name"), h)
    down = (g.get("home_team_name"), h) if a["games_back"] < h["games_back"] \
        else (g.get("away_team_name"), a)
    ut, dt = _ten(up[1]), _ten(down[1])
    # 順位が上なのに直近が負け越し、かつ下のチームが勝ち越している
    if ut and dt and ut[0] <= COLD_WINS and dt[0] >= HOT_WINS:
        return (f"順位では{up[0]}が上ですが、直近10試合は"
                f"{up[0]}が{ut[0]}勝{ut[1]}敗、"
                f"{down[0]}が{dt[0]}勝{dt[1]}敗です。")
    return ""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="notable_games.json")
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()
    try:
        data = json.loads(pathlib.Path(args.games).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] {args.games} を読めません: {e}")
        return 1
    for g in [x for x in data.get("games", []) if x.get("is_notable")][:3]:
        print(f"\n■ {g.get('away_team_name')} vs {g.get('home_team_name')}")
        for label, text in read(g, args.limit):
            print(f"   [{label}] {text}")
        t = tension(g)
        if t:
            print(f"   [食い違い] {t}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
