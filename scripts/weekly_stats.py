"""
週次まとめが使うデータの読み込みと集計。

なぜ別モジュールなのか:
  generate_weekly.py(映像)と generate_weekly_narration.py(原稿)は、
  同じ週・同じ順序・同じセグメント構成を前提にしている。片方だけ条件が
  変わると、ナレーションと画面が1つずつずれて全く別の試合の音声が乗る。
  以前これを「同じ条件で読むこと」というコメントで担保しようとして
  実際にずれたので、計算そのものを1か所に集約した。

ここで出す数字は、すべてアーカイブに実際に記録されている値だけから
機械的に導く。推定・予測は一切しない。
"""

import json
import sys
import pathlib
import re

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# 関数の中で import していたので、使う場所を増やすたびに書き足しが要り、
# 実際に2か所で書き忘れて undefined name になった。ここに1つ置く。
from notability_engine import is_soccer_league  # noqa: E402

DATE_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.json$")

# 「アストロズは5連勝中」の形をほどく。notability_engine.py が
# streak タグの理由文をこの形で作っているため、それに合わせている。
STREAK_RE = re.compile(r"^(?P<team>.+?)は(?P<n>\d+)(?P<kind>連勝|連敗)中$")

# 1日あたり取り上げる試合数。動画の尺と情報量の兼ね合いで決めている。
GAMES_PER_DAY = 2


def load_week(archive_dir: pathlib.Path, days: int = 7,
              sport: str = "mlb") -> list:
    """
    直近days日分のアーカイブを、古い順に [(日付, 試合), ...] で返す。

    競技で絞る。アーカイブにはMLBと欧州サッカーが同居しているので、
    絞らないと1日2試合の枠を取り合い、週末はサッカーが混ざる。
    日次を競技ごとに分けたのと同じ理由で、週次も分ける。
    """
    entries = []
    for f in sorted(archive_dir.glob("*.json")):
        if DATE_FILE_RE.match(f.name):
            entries.append((f.name[:10], f))
    entries.sort(key=lambda x: x[0], reverse=True)

    def wanted(g: dict) -> bool:
        soccer = is_soccer_league(g.get("league"))
        return soccer if sport == "soccer" else not soccer

    out = []
    for date_str, path in entries[:days]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        picked = [x for x in data.get("games", [])
                  if x.get("is_notable") and wanted(x)][:GAMES_PER_DAY]
        for g in picked:
            out.append((date_str, g))
    out.reverse()
    return out


def load_day(archive_dir: pathlib.Path, date_str: str,
             sport: str = "mlb") -> list:
    """
    その日に「注目」として出した試合を、結果つきで返す。

    週次の答え合わせと同じことを1日ぶんでやる。日次の中で前日を
    回収するために使う。結果が入っていない試合は返さない
    (推測はしない。試合が終わっていなければ、そもそも言えることが無い)。
    """
    p = archive_dir / f"{date_str}.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    out = []
    for g in data.get("games", []):
        if not g.get("is_notable"):
            continue
        soccer = is_soccer_league(g.get("league"))
        if (soccer if sport == "soccer" else not soccer) is False:
            continue
        if not (g.get("final_score") or {}).get("winner"):
            continue
        out.append(g)
    return out


def day_lines(games: list) -> list:
    """
    答え合わせの1行ずつ。(対戦, スコア, 添える一言) を返す。

    添える一言は、こちらが書いた注目理由が実際どうだったかに限る。
    「熱戦だった」のような感想は入れない。書いたことの検算だけをする。
    """
    lines = []
    for g in games:
        fs = g["final_score"]
        h, a = fs.get("home"), fs.get("away")
        if h is None or a is None:
            continue
        note = ""
        for s in check_streaks([("", g)]):
            note = s["result"]
            break
        # 添える一言は競技で変える。「完封」は野球の言い方で、
        # サッカーでは使わない(あちらは無失点・クリーンシート)。
        # 1点差もサッカーではありふれているので、態々書かない。
        if not note and h is not None and a is not None:
            if is_soccer_league(g.get("league")):
                if h == a:
                    note = "引き分け"
                elif min(h, a) == 0:
                    note = "無失点"
                elif abs(h - a) >= 3:
                    note = "大差"
            elif abs(h - a) == 1:
                note = "1点差"
            elif min(h, a) == 0:
                note = "完封"
        lines.append((g.get("abbr_matchup") or g.get("matchup"),
                      f"{h} - {a}", note))
    return lines


def load_news_items(news_path: str, log_path: str, since: str, until: str) -> list:
    """
    「今週の動き」に載せるニュース文を集める。

    週次ワークフローには public/news.json が無い(あれは日次側がその日限りで
    作るもので、リポジトリにも残らない)。日次がコミットしている
    data/news_log.json から、その週の分だけを拾う。
    """
    p = pathlib.Path(log_path)
    if p.exists():
        try:
            entries = json.loads(p.read_text(encoding="utf-8")).get("entries") or []
            return [e["text"] for e in entries
                    if e.get("text") and since <= (e.get("date") or "") <= until]
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    p = pathlib.Path(news_path)
    if p.exists():
        try:
            return [n["text"] for n in
                    (json.loads(p.read_text(encoding="utf-8")).get("news") or [])]
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    return []


def _side_of(game: dict, team_name: str):
    if team_name == game.get("home_team_name"):
        return "home"
    if team_name == game.get("away_team_name"):
        return "away"
    return None


def check_streaks(week: list) -> list:
    """
    「◯連勝中だから注目」として取り上げた試合が、実際どうなったかを照合する。

    コレスポが注目理由として書いたことの答え合わせであり、
    元の理由文と最終スコアの両方が記録されているからこそ言える。
    どちらかが欠けている試合は黙って飛ばす(推測はしない)。
    """
    out = []
    for date_str, g in week:
        fs = g.get("final_score")
        if not fs or not fs.get("winner"):
            continue
        for r in g.get("reasons") or []:
            if r.get("tag") != "streak":
                continue
            m = STREAK_RE.match((r.get("text") or "").strip())
            if not m:
                continue
            team = m.group("team")
            side = _side_of(g, team)
            if side is None:
                continue

            n = int(m.group("n"))
            is_win_streak = m.group("kind") == "連勝"
            won = fs["winner"] == side

            # 画面用は短く、読み上げ用は敬体。番組のナレーションとして
            # 読ませるので、画面の文言をそのまま喋らせると口調が崩れる。
            if is_win_streak:
                held = won
                result = f"{n + 1}連勝に伸ばした" if won else "連勝が止まった"
                spoken = (f"{n + 1}連勝に伸ばしました" if won
                          else "そこで連勝が止まりました")
            else:
                held = not won
                result = "連敗を止めた" if won else f"{n + 1}連敗になった"
                spoken = ("ようやく連敗を止めました" if won
                          else f"{n + 1}連敗まで伸びてしまいました")

            out.append({
                "date": date_str,
                "team": team,
                "n": n,
                "kind": "連勝" if is_win_streak else "連敗",
                "held": held,
                "won": won,
                "result": result,
                "spoken": spoken,
                "matchup": g.get("abbr_matchup") or g.get("matchup"),
                "score": f"{fs.get('home')}-{fs.get('away')}",
            })
    return out


def dedupe_streaks(streaks: list) -> list:
    """
    同じチームが週内で何度も条件に当てはまることがある
    (5連勝中→6連勝中と、連日取り上げられる場合)。
    並べても冗長なので、チームごとに最後の1件だけ残す。
    最後の1件は、その週の最終的な結末にあたる。
    """
    latest = {}
    for s in streaks:          # check_streaks は古い順に返すので後勝ちが最新
        latest[s["team"]] = s
    return sorted(latest.values(), key=lambda s: s["date"])


def compute_verdict(week: list) -> dict:
    """
    その週の注目試合を、記録されている最終スコアだけから集計する。

    どれも数え上げただけの値なので、言い切っても誤りようがない。
    「今週はこうだった」と語れる、コレスポにしか出せない数字になる。
    """
    decided = [(d, g) for d, g in week if (g.get("final_score") or {}).get("winner")]

    home_wins = sum(1 for _, g in decided if g["final_score"]["winner"] == "home")
    # 引き分けを引かずに away_wins = decided - home_wins としていた。
    # 野球には引き分けが無いので気付かなかったが、サッカーでは3割前後あり、
    # そのぶんアウェイの勝ち数が水増しされる。
    draws = sum(1 for _, g in decided if g["final_score"]["winner"] == "draw")
    one_run = 0
    shutouts = 0
    top = None
    for d, g in decided:
        fs = g["final_score"]
        h, a = fs.get("home"), fs.get("away")
        if h is None or a is None:
            continue
        if abs(h - a) == 1:
            one_run += 1
        if min(h, a) == 0:
            shutouts += 1
        if top is None or (h + a) > top["total"]:
            top = {
                "total": h + a,
                "date": d,
                "matchup": g.get("matchup"),
                "abbr": g.get("abbr_matchup"),
                "home": h,
                "away": a,
                "home_name": g.get("home_team_name"),
                "away_name": g.get("away_team_name"),
            }

    return {
        "picked": len(week),
        "decided": len(decided),
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": len(decided) - home_wins - draws,
        "one_run": one_run,
        "shutouts": shutouts,
        "top_game": top,
        "streaks": dedupe_streaks(check_streaks(week)),
        # 語彙を競技で変えるため。週の全試合が同じ競技である前提で見る
        # (load_week が sport で絞ってから渡している)。
        "soccer": bool(week) and is_soccer_league(week[0][1].get("league")),
    }


def verdict_lines(v: dict) -> list:
    """答え合わせ画面に出す行。数字が入るものだけを返す。"""
    soccer = v.get("soccer")
    lines = []
    if v["decided"]:
        lines.append((f"{v['decided']}試合", "結果が出た注目試合"))
        record = f"{v['home_wins']}勝 {v['away_wins']}敗"
        if v.get("draws"):
            record += f" {v['draws']}分"
        lines.append((record, "ホームチームの成績"))
    if v["one_run"] and not soccer:
        lines.append((f"{v['one_run']}試合", "1点差の接戦"))
    if v["shutouts"]:
        lines.append((f"{v['shutouts']}試合",
                      "無失点で終えた試合" if soccer else "完封試合"))
    if v["top_game"]:
        t = v["top_game"]
        lines.append((f"{t['home']} - {t['away']}", f"最も点が入った {t['abbr']}"))
    return lines
