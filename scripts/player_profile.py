#!/usr/bin/env python3
"""
毎日1人、日本人選手をまとめて紹介するための材料を集める。

なぜこの枠を作るのか:
  視聴継続の実測で、日本人選手の名前を先頭に置いた回とそうでない回に
  32ポイントの差があった。名前が最も強いフックだと分かっている。

  さらに、この枠は「明日の試合」と違って古くならない。試合の予告は
  翌日には価値が消えるが、選手の通算成績と経歴は、後から名前で
  検索した人にも同じだけ役に立つ。積み上がる資産になる。

何を載せ、何を載せないか:
  載せるのは、MLB公式APIから引ける数字と事実だけ。
    通算成績 / 今季 / 昨季 / 直近5試合 / 出身地 / デビュー日 / 受賞歴

  「人となり」はAPIに無い。ここをAIに書かせると必ず作り話になるので、
  こちらからは一切書かない。代わりに、既に集めてある現地の番記者の
  投稿とファンのコメントを、出典つきでそのまま引く。
  誰かがそう言った、という事実だけを扱う。

誰を取り上げるか:
  その日のMLB全体で、いちばん活躍した選手。

  最初は日本人選手の名簿から順番に選ぶ作りにしていたが、それは
  この枠の趣旨ではなかった。8/17は Pete Crow-Armstrong が
  先頭打者本塁打とサヨナラ本塁打で154点、大谷が140点。
  名簿で絞ると、その日の1位が出てこない。

  採点は best_of_day.py が全出場選手に対して行う。物差しは
  日本人選手の成績で使っているものと同じ(morning_recap.contribution)。

  直近 COOLDOWN_DAYS 日に取り上げた人は外す。同じ選手が
  連日続くと、毎日見ている人には同じ動画に見える。

出力: data/player_profile.json

使い方:
  python3 scripts/player_profile.py --out data/player_profile.json
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import JP_PLAYERS_MLB, MLB_TEAM_NAME_JP  # noqa: E402

MLB_API = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))

# 同じ選手を続けて出さないための間隔。
# 日本人選手は10人強なので、14日あれば一巡してもまだ余裕がある。
COOLDOWN_DAYS = 14

# 直近何試合を「いまの状態」として見せるか。
RECENT_GAMES = 5

# 受賞歴のうち、画面に出す上限。73件あるので全部は出せない。
MAX_AWARDS = 5

# 出すに値する受賞かどうか。マイナー時代の週間賞まで並べると、
# MVPと同じ重さに見えてしまう。
MAJOR_AWARDS = ("MVP", "Cy Young", "Rookie of the Year", "All-Star",
                "Silver Slugger", "Gold Glove", "Hank Aaron",
                "World Series", "Player of the Month", "Pitcher of the Month",
                "Rookie of the Month", "Player of the Week")


def resolve_id(name_en: str) -> str:
    """
    名前から選手IDを引く。

    名簿(JP_PLAYERS_MLB)は name_en / name_jp / type しか持っていない。
    IDを名簿に書き込む手もあるが、移籍や登録の変更で古くなるので、
    毎回APIに聞く方が確実。1日1回しか呼ばない。
    """
    for person in _get("people/search", names=name_en).get("people", []):
        return str(person.get("id") or "")
    return ""


def _get(path: str, **params):
    try:
        r = requests.get(f"{MLB_API}/{path}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {path} を取得できませんでした: {e}", file=sys.stderr)
        return {}


def team_now(pid: str) -> str:
    """
    いまの所属。日本語名が引ければそちらを使う。

    hydrate=currentTeam を付けないと currentTeam は返ってこない
    (付けずに読んで空になっていた)。
    """
    for person in _get(f"people/{pid}", hydrate="currentTeam").get("people", []):
        t = person.get("currentTeam") or {}
        return MLB_TEAM_NAME_JP.get(str(t.get("id")), t.get("name") or "")
    return ""


def load_history(path: str) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def mention_counts(reporters_path: str, voices_path: str) -> dict:
    """
    いま現地で名前が挙がっている選手を数える。

    番記者の投稿とファンのコメントは毎朝集めてある。そこに名前が
    出ている選手は、その日いちばん話題になっている人にあたる。
    こちらで「話題だ」と決めるのではなく、数えるだけ。
    """
    texts = []
    for path, keys in ((reporters_path, ("posts", "headlines")),
                       (voices_path, ("voices",))):
        try:
            d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for key in keys:
            for item in (d.get(key) or []):
                for f in ("jp", "text", "title", "ja"):
                    if item.get(f):
                        texts.append(item[f])
    blob = " ".join(texts)
    counts = {}
    for p in JP_PLAYERS_MLB:
        n = blob.count(p["name_jp"]) + blob.count(p.get("name_en", "\0"))
        if n:
            counts[p["name_jp"]] = n
    return counts


def pick_from_best(best_path: str, history: dict) -> dict:
    """
    その日いちばん活躍した選手。直近に出した人は飛ばす。

    best_of_day.py が全MLBを採点した結果を読む。ここで選び直さない。
    採点をもう一度書くと、2つの物差しができる。
    """
    from datetime import datetime as _dt
    try:
        d = json.loads(pathlib.Path(best_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    players = d.get("players") or []
    if not players:
        return {}

    today = datetime.now(JST).date()
    for x in players:
        last = (history.get("featured") or {}).get(x["name"])
        if last:
            try:
                days = (today - _dt.strptime(last, "%Y-%m-%d").date()).days
                if days < COOLDOWN_DAYS:
                    continue
            except ValueError:
                pass
        why = f"{d.get('date_jst') or d.get('date')}のMLBで最も活躍"
        if x.get("is_japanese"):
            why += "(日本人選手)"
        return {"name_en": x["name"], "name_jp": x["name"],
                "why": why, "score": x.get("score"),
                "headline": x.get("headline"), "team": x.get("team")}
    return {}


def pick_player(history: dict, mentions: dict) -> dict:
    """名簿から選ぶ(その日の採点が取れなかったときの控え)。"""
    today = datetime.now(JST).date()
    fresh = []
    for p in JP_PLAYERS_MLB:
        last = (history.get("featured") or {}).get(p["name_jp"])
        days = 999
        if last:
            try:
                days = (today - datetime.strptime(last, "%Y-%m-%d").date()).days
            except ValueError:
                pass
        if days >= COOLDOWN_DAYS:
            fresh.append((p, days))

    # 全員が最近出ていれば、いちばん久しぶりの人に回す
    if not fresh:
        fresh = [(p, 0) for p in JP_PLAYERS_MLB]
        fresh.sort(key=lambda x: (history.get("featured") or {})
                   .get(x[0]["name_jp"], ""))
        return {"player": fresh[0][0], "why": "順番"}

    fresh.sort(key=lambda x: (-mentions.get(x[0]["name_jp"], 0), -x[1]))
    top, _ = fresh[0]
    why = "現地で名前が挙がっている" if mentions.get(top["name_jp"]) else "順番"
    return {"player": top, "why": why}


def season_line(pid: str, group: str, season: str = None) -> dict:
    """通算 or 指定シーズンの成績。取れなければ空。"""
    params = ({"stats": "career", "group": group} if season is None
              else {"stats": "season", "group": group, "season": season})
    for st in _get(f"people/{pid}/stats", **params).get("stats", []):
        for sp in st.get("splits", []):
            s = sp.get("stat") or {}
            if not s:
                continue
            if group == "hitting":
                if not s.get("gamesPlayed"):
                    continue
                return {"games": s.get("gamesPlayed"), "avg": s.get("avg"),
                        "hr": s.get("homeRuns"), "rbi": s.get("rbi"),
                        "ops": s.get("ops"), "sb": s.get("stolenBases"),
                        "hits": s.get("hits")}
            if not s.get("inningsPitched"):
                continue
            return {"games": s.get("gamesPlayed"), "wins": s.get("wins"),
                    "losses": s.get("losses"), "era": s.get("era"),
                    "so": s.get("strikeOuts"), "ip": s.get("inningsPitched"),
                    "whip": s.get("whip")}
    return {}


def recent_games(pid: str, group: str, season: str) -> list:
    """直近の出場。日付の新しい順に RECENT_GAMES 件。"""
    splits = []
    for st in _get(f"people/{pid}/stats", stats="gameLog", group=group,
                   season=season).get("stats", []):
        splits += st.get("splits", [])
    splits.sort(key=lambda s: s.get("date") or "")
    out = []
    for sp in reversed(splits):
        s = sp.get("stat") or {}
        if group == "hitting":
            if not s.get("plateAppearances"):
                continue
            line = (f"{s.get('atBats')}打数{s.get('hits')}安打")
            if s.get("homeRuns"):
                line += f" {s['homeRuns']}本塁打"
            if s.get("rbi"):
                line += f" {s['rbi']}打点"
        else:
            if not s.get("inningsPitched") or float(
                    s.get("inningsPitched") or 0) <= 0:
                continue
            line = (f"{s.get('inningsPitched')}回 "
                    f"自責{s.get('earnedRuns')} {s.get('strikeOuts')}奪三振")
        out.append({"date": sp.get("date"), "line": line,
                    "opponent": ((sp.get("opponent") or {}).get("name") or "")})
        if len(out) >= RECENT_GAMES:
            break
    return out


def awards(pid: str) -> list:
    """主要な受賞歴を新しい順に。マイナーの細かい賞は落とす。"""
    out = []
    for a in reversed(_get(f"people/{pid}/awards").get("awards") or []):
        name = a.get("name") or ""
        if not any(k in name for k in MAJOR_AWARDS):
            continue
        row = {"season": a.get("season"), "name": name}
        if row not in out:
            out.append(row)
        if len(out) >= MAX_AWARDS:
            break
    return out


def quotes(name_jp: str, name_en: str, reporters_path: str,
           voices_path: str) -> list:
    """
    その選手について、現地で誰が何と言ったか。

    「人となり」や「評判」はAPIに無い。こちらで書けば作り話になる。
    既に集めてある投稿から、その選手に触れているものを引いて、
    誰の言葉かを添えて出す。扱うのは「そう言った人がいる」という事実だけ。
    """
    out = []
    try:
        rep = json.loads(pathlib.Path(reporters_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        rep = {}
    try:
        voi = json.loads(pathlib.Path(voices_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        voi = {}

    for item in (rep.get("posts") or []):
        body = item.get("jp") or item.get("text") or ""
        if name_jp in body or (name_en and name_en in body):
            out.append({"who": f"{item.get('outlet', '現地メディア')}の記者",
                        "text": body, "kind": "reporter"})
    for item in (rep.get("headlines") or []):
        body = item.get("jp") or item.get("title") or ""
        if name_jp in body or (name_en and name_en in body):
            out.append({"who": item.get("source", "現地メディア"),
                        "text": body, "kind": "headline"})
    for item in (voi.get("voices") or []):
        body = item.get("ja") or ""
        if name_jp in body or (name_en and name_en in body):
            out.append({"who": "現地のファン", "text": body,
                        "kind": "fan", "likes": item.get("likes")})
    return out[:4]


def build(args) -> dict:
    history = load_history(args.history)
    mentions = mention_counts(args.reporters, args.voices)
    # まず、その日いちばん活躍した選手。取れなければ名簿から回す。
    best = pick_from_best(args.best, history)
    if best:
        p = {"name_en": best["name_en"], "name_jp": best["name_jp"],
             "type": "batter"}
        chosen = {"player": p, "why": best["why"]}
        print(f"[info] その日の1位: {best['name_jp']} "
              f"({best.get('score')}点 / {best.get('headline')})")
    else:
        chosen = pick_player(history, mentions)
        print("[info] その日の採点が取れないため、名簿から選びます")
    p = chosen["player"]
    pid = resolve_id(p.get("name_en", ""))
    if not pid:
        print(f"[warn] {p['name_jp']} のIDを引けませんでした")
        return {"name": p["name_jp"], "career": {}, "this_season": {}}
    season = str(datetime.now(JST).year)

    bio = {}
    for person in _get(f"people/{pid}").get("people", []):
        bio = {
            "name_en": person.get("fullName"),
            "age": person.get("currentAge"),
            "birth_city": person.get("birthCity"),
            "birth_date": person.get("birthDate"),
            "debut": person.get("mlbDebutDate"),
            "number": person.get("primaryNumber"),
            "position": (person.get("primaryPosition") or {}).get("name"),
            "nickname": person.get("nickName"),
            "height": person.get("height"),
            "weight": person.get("weight"),
        }
        break

    # 名簿の type が "pitcher" / "batter"。二刀流は打者として扱い、
    # 投球成績は別途足す(大谷は打者としての数字の方が主になる)。
    group = "pitching" if p.get("type") == "pitcher" else "hitting"
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date_jst": datetime.now(JST).strftime("%Y-%m-%d"),
        "name": p["name_jp"],
        "player_id": pid,
        "team": team_now(pid),
        "group": group,
        "why": chosen["why"],
        "bio": bio,
        "career": season_line(pid, group),
        "this_season": season_line(pid, group, season),
        "last_season": season_line(pid, group, str(int(season) - 1)),
        "recent": recent_games(pid, group, season),
        "awards": awards(pid),
        "quotes": quotes(p["name_jp"], bio.get("name_en", ""),
                         args.reporters, args.voices),
    }
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/player_profile.json")
    ap.add_argument("--best", default="data/best_of_day.json",
                    help="その日いちばん活躍した選手(best_of_day.py の出力)")
    ap.add_argument("--history", default="data/featured_players.json")
    ap.add_argument("--reporters", default="data/local_reporters.json")
    ap.add_argument("--voices", default="data/local_voices.json")
    args = ap.parse_args()

    data = build(args)
    if not data.get("career") and not data.get("this_season"):
        print(f"[warn] {data['name']} の成績が1つも取れませんでした")
        return 1

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")

    # 誰を出したかを残す。次に選ぶとき、この記録で順番を回す。
    hist = load_history(args.history)
    hist.setdefault("featured", {})[data["name"]] = data["date_jst"]
    hp = pathlib.Path(args.history)
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(json.dumps(hist, ensure_ascii=False, indent=2),
                  encoding="utf-8")

    print(f"[info] {data['name']}({data['team']}) を選びました "
          f"— 理由: {data['why']}")
    print(f"       通算 {data['career']}")
    print(f"       直近 {len(data['recent'])}試合 / 受賞 {len(data['awards'])}件 "
          f"/ 現地の言葉 {len(data['quotes'])}件")
    print(f"[info] 書き出しました -> {p}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
